#!/usr/bin/env python3
"""Bounded proof of selected properties on source-bound generated checkpoint RTL.

Consumes (does not regenerate) the passing recovery gate's RTL. Not S03 closure,
an unbounded proof, or a proof of the full renamer/core. No downloads here.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HW = Path(__file__).resolve().parents[1]
ROOT = HW / "formal"
OUT = HW / "build/ape_formal"
ENVIRONMENT = HW / ".tools/ape-formal"
STEPS = 12  # Global transitions after clk2fflogic, not 12 executed instructions.


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--solver-timeout", type=int, default=90)
    parser.add_argument("--wall-timeout", type=int, default=180)
    args = parser.parse_args()
    require(args.solver_timeout >= 1 and args.wall_timeout >= args.solver_timeout,
            "Wall timeout must accommodate the solver budget")
    OUT.mkdir(parents=True, exist_ok=True)
    gate_path = HW / "build/ape_recovery/gate.json"
    gate = json.loads(gate_path.read_text())
    require(gate["status"] == "passed" and gate["source_sha256"] == gate["source_sha256_after"], "Run recovery gate first")
    sources = dict(gate["source_sha256"])
    sources.update({str(p.relative_to(HW)): sha(p) for p in ROOT.iterdir() if p.is_file()})
    def check_sources():
        for name, digest in sources.items():
            path = (HW / name).resolve()
            require(path.is_relative_to(HW.resolve()) and sha(path) == digest, "Stale source: " + name)
        require(sha(gate_path) == report["recovery_report_sha256"], "Recovery gate changed")
    env = dict(os.environ)
    env["YOWASP_CACHE_DIR"] = str(ENVIRONMENT / "cache")
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    yosys = str(ENVIRONMENT / "bin/yowasp-yosys")
    smtbmc = str(ENVIRONMENT / "bin/yowasp-yosys-smtbmc")
    solver = shutil.which("z3", path=env["PATH"])
    require(solver, "Missing z3 solver")
    report = {"schema": 1, "status": "running", "S03_complete": False,
              "claim_class": "bounded_selected_checkpoint_RTL_properties",
              "started_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": sources,
              "recovery_report_sha256": sha(gate_path), "runs": [],
              "budgets_seconds": {"safety_solver": args.solver_timeout, "command_wall": args.wall_timeout},
              "assumptions": ["Reset in the initial global state only; clear may occur later",
                              "Capture only a free slot below capacity; resolve only a live owner",
                              "No capture/allocation during redirect; no activity during reset/clear",
                              "Allocation tags 1..35; squash mask and snapshot values otherwise arbitrary",
                              "Single-clock sampled safety; no fairness or physical reset/metastability model"],
              "limits": ["Bounded global transitions only, not unbounded induction",
                         "P36/8 ROB slots, C1/C4, snapshot field x10; arbitrary watched slot and tag 1..35",
                         "Does not prove ROB age selection, committed/free exclusion, early timing or stale completion rejection",
                         "Negative control adds a false harness assertion; not a mutated-DUT coverage score",
                         "No full-core formal closure, synthesis timing, PPA or acceleration result"]}
    def save():
        (OUT / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    artifacts = {str(gate_path.relative_to(HW)): sha(gate_path)}
    def run(command, folder, label, expected=0, timeout=None):
        log = folder / (label + ".log")
        with log.open("w") as output:
            result = subprocess.run(command, cwd=HW, env=env, stdout=output,
                                    stderr=subprocess.STDOUT, timeout=args.wall_timeout if timeout is None else timeout)
        artifacts[str(log.relative_to(HW))] = sha(log)
        text = log.read_text()
        require(result.returncode == expected, f"Unexpected {label} status; inspect {log}")
        return text
    save()
    try:
        check_sources()
        expected = sorted(line for line in (ROOT / "requirements.txt").read_text().splitlines() if line and not line.startswith("#"))
        installed = subprocess.check_output([str(ENVIRONMENT / "bin/python"), "-m", "pip", "freeze"], text=True).splitlines()
        require(sorted(installed) == expected, "Formal package versions differ from requirements lock")
        wasm = next((ENVIRONMENT / "lib").glob("python*/site-packages/yowasp_yosys/yosys.wasm"))
        report["tools"] = {"packages": expected, "yosys_wasm_sha256": sha(wasm),
                           "yosys": subprocess.check_output([yosys, "-V"], env=env, text=True).strip(),
                           "z3": subprocess.check_output([solver, "--version"], text=True).strip(), "z3_sha256": sha(solver)}
        for capacity in (1, 4):
            folder = OUT / f"c{capacity}"
            folder.mkdir(exist_ok=True)
            rtl = f"build/ape_checkpoints/p36-c{capacity}/ApeRename/rtl/ApeRename.v"
            require(sha(HW / rtl) == gate["evidence_sha256"][rtl], "Generated RTL identity differs")
            artifacts[rtl] = sha(HW / rtl)
            prefix = f"read_verilog -formal -sv {rtl} formal/CheckpointFormal.sv; chparam -set CAPACITY {capacity} CheckpointFormal; prep -top CheckpointFormal -flatten; clk2fflogic; opt_clean; check -assert; "
            smt = folder / "model.smt2"
            run([yosys, "-Q", "-T", "-p", prefix + f"write_smt2 -wires {smt.relative_to(HW)}"], folder, "elaboration")
            model = smt.read_text()
            require(model.count("; yosys-smt2-assert ") == 8, "Expected four RTL and four harness assertions")
            cover_count = 4 if capacity == 1 else 5
            require(model.count("; yosys-smt2-cover ") == cover_count, "Missing reachability witness")
            proof = run([yosys, "-Q", "-T", "-p", prefix + f"chformal -cover -remove; sat -seq {STEPS} -prove-asserts -set-assumes -verify -timeout {args.solver_timeout}"], folder, "bounded")
            require("SAT proof finished - no model found: SUCCESS!" in proof, "Bounded proof was not conclusive")
            cover = run([smtbmc, "-s", "z3", "-c", "--noprogress", "--timeout", "60", "-t", "16",
                         "--dump-vcd", str((folder / "cover%.vcd").relative_to(HW)), str(smt.relative_to(HW))], folder, "covers")
            require("Status: PASSED" in cover and cover.count("Reached cover statement") == cover_count, "Unreachable activity / possible vacuity")
            mutation = prefix.replace("-sv ", "-sv -DMUTATION ") + "chformal -cover -remove; sat -seq 8 -prove-asserts -set-assumes -verify -timeout 30"
            negative = run([yosys, "-Q", "-T", "-p", mutation], folder, "negative-control", expected=1)
            require("proof did fail" in negative and "timeout" not in negative.split("ERROR:")[-1].lower(), "Negative control did not find a counterexample")
            report["runs"].append({"physical_registers": 36, "slots": 8, "capacity": capacity,
                                   "snapshot_field": 10, "bounded_global_steps": STEPS, "assertions": 8,
                                   "bounded_status": "passed", "cover_status": "passed", "covers_reached": cover_count,
                                   "negative_control": "counterexample_found", "rtl_sha256": sha(HW / rtl)})
            artifacts[str(smt.relative_to(HW))] = sha(smt)
            for p in folder.glob("cover*.vcd"): artifacts[str(p.relative_to(HW))] = sha(p)
            print(f"Checkpoint formal C{capacity}: bounded {STEPS} steps, {cover_count} covers, negative control passed", flush=True)
            save()
        check_sources()
        for name, digest in artifacts.items(): require(sha(HW / name) == digest, "Formal artifact changed")
        report.update(status="passed_bounded", evidence_sha256=artifacts)
    except Exception as error:
        report.update(status="failed_or_inconclusive", error=str(error))
        raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()


if __name__ == "__main__":
    main()
