#!/usr/bin/env python3
"""Selected bounded rename/commit/full-recovery properties on actual RTL.

The restricted single-architectural-register environment is explicit. This is
not a whole-core or selective-checkpoint proof, nor a substitute for regression.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

from verify_checkpoints import HW, ENVIRONMENT, sha, require


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, choices=(12, 16, 20), default=16)
    args = parser.parse_args()
    out = HW / "build/ape_rename_formal" / f"steps{args.steps}"
    out.mkdir(parents=True, exist_ok=True)
    gate_path = HW / "build/ape_recovery/gate.json"
    gate = json.loads(gate_path.read_text())
    require(gate["status"] == "passed" and gate["source_sha256"] == gate["source_sha256_after"], "Run recovery gate first")
    rtl = "build/ape_checkpoints/p36-c1/ApeRename/rtl/ApeRename.v"
    require(sha(HW / rtl) == gate["evidence_sha256"][rtl], "Unverified generated renamer")
    sources = {**gate["source_sha256"], **{f"formal/{p}": sha(HW / "formal" / p) for p in
               ("RenameLifecycleFormal.sv", "verify_rename_lifecycle.py", "verify_checkpoints.py", "requirements.txt")}}
    report = {"schema": 1, "status": "running", "S03_complete": False,
              "claim_class": "bounded_restricted_rename_lifecycle_RTL_properties",
              "started_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": sources,
              "generated_rtl_sha256": sha(HW / rtl), "recovery_report_sha256": sha(gate_path),
              "bounded_global_steps": args.steps,
              "assumptions": ["Reset only initially; relaunch clear may occur subsequently with no other activity",
                              "All allocations target architectural x10, with four outstanding writers maximum",
                              "Out-of-order writeback only to a live unwritten allocation; value is one arbitrary bit, other 63 bits zero",
                              "Retirement only at the oldest written allocation; may coincide with full recovery or new allocation",
                              "No writeback during full recovery; all checkpoint/resolve inputs disabled",
                              "No fairness or physical timing assumption; sampled single-clock safety"],
              "limits": ["Bounded proof under a restricted environment, not general multi-register rename or whole-core proof",
                         "Full recovery only; selective branch recovery and late-result qualification have separate gates",
                         "One-bit values validate selected data forwarding/commit cases, not all arithmetic values",
                         "False harness assertion control does not measure mutated-DUT coverage"]}
    env = dict(os.environ); env["YOWASP_CACHE_DIR"] = str(ENVIRONMENT / "cache")
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    yosys, smtbmc = [str(ENVIRONMENT / "bin" / name) for name in ("yowasp-yosys", "yowasp-yosys-smtbmc")]
    artifacts = {rtl: sha(HW / rtl)}

    def save():
        (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")

    def check():
        for name, digest in sources.items(): require(sha(HW / name) == digest, "Stale source: " + name)
        require(sha(gate_path) == report["recovery_report_sha256"], "Recovery gate changed")

    def run(command, label, expected=0, timeout=180):
        log = out / (label + ".log")
        with log.open("w") as stream:
            result = subprocess.run(command, cwd=HW, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        artifacts[str(log.relative_to(HW))] = sha(log)
        require(result.returncode == expected, f"Unexpected {label} status; inspect {log}")
        return log.read_text()

    save()
    try:
        check()
        expected = sorted(line for line in (HW / "formal/requirements.txt").read_text().splitlines() if line and not line.startswith("#"))
        installed = subprocess.check_output([str(ENVIRONMENT / "bin/python"), "-m", "pip", "freeze"], text=True).splitlines()
        require(sorted(installed) == expected, "Formal packages differ from the lock")
        solver = shutil.which("z3", path=env["PATH"])
        require(solver, "Missing z3 solver")
        wasm = next((ENVIRONMENT / "lib").glob("python*/site-packages/yowasp_yosys/yosys.wasm"))
        report["tools"] = {"packages": expected, "yosys_wasm_sha256": sha(wasm),
            "yosys": subprocess.check_output([yosys, "-V"], env=env, text=True).strip(),
            "z3": subprocess.check_output([solver, "--version"], env=env, text=True).strip(), "z3_sha256": sha(solver)}
        prefix = (f"read_verilog -formal -sv {rtl} formal/RenameLifecycleFormal.sv; "
                  "prep -top RenameLifecycleFormal -flatten; memory_map; opt -full; clk2fflogic; opt_clean; check -assert; ")
        smt = out / "model.smt2"
        run([yosys, "-Q", "-T", "-p", prefix + f"write_smt2 -wires {smt.relative_to(HW)}"], "elaboration")
        model = smt.read_text()
        report["assertions"] = model.count("; yosys-smt2-assert ")
        require(report["assertions"] == 24 and model.count("; yosys-smt2-cover ") == 6, "Missing safety/activity properties")
        save()
        proof = run([yosys, "-Q", "-T", "-p", prefix + f"chformal -cover -remove; sat -seq {args.steps} -prove-asserts -set-assumes -verify -timeout 90"], "bounded")
        require("SAT proof finished - no model found: SUCCESS!" in proof, "No conclusive bounded proof")
        report["bounded_status"] = "passed"; save()
        covers = run([smtbmc, "-s", "z3", "-c", "--noprogress", "--timeout", "90", "-t", "32",
                      "--dump-vcd", str((out / "cover%.vcd").relative_to(HW)), str(smt.relative_to(HW))], "covers")
        require("Status: PASSED" in covers and covers.count("Reached cover statement") == 6, "Missing lifecycle reachability")
        report["covers_reached"] = 6; save()
        negative = prefix.replace("-sv ", "-sv -DMUTATION ") + "chformal -cover -remove; sat -seq 8 -prove-asserts -set-assumes -verify -timeout 30"
        bad = run([yosys, "-Q", "-T", "-p", negative], "negative-control", expected=1)
        require("proof did fail" in bad and "timeout" not in bad.split("ERROR:")[-1].lower(), "Negative control did not find a counterexample")
        report["negative_control"] = "counterexample_found"
        artifacts[str(smt.relative_to(HW))] = sha(smt)
        for p in out.glob("cover*.vcd"): artifacts[str(p.relative_to(HW))] = sha(p)
        check()
        for name, digest in artifacts.items(): require(sha(HW / name) == digest, "Artifact changed: " + name)
        report.update(status="passed_bounded", evidence_sha256=artifacts)
    except Exception as error:
        report.update(status="failed_or_inconclusive", error=str(error)); raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print(f"Restricted rename lifecycle: {args.steps} global steps, six covers and false-assertion control passed")


if __name__ == "__main__":
    main()
