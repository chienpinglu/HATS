#!/usr/bin/env python3
"""Fresh physical-rename RTL and register-pressure Spike gate; not S03 closure."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import bootstrap_spike as spike
from compare_ape_spike import compare, read_trace
from verify_ape import hashes
from verify_ape_spike import case_profile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/ape_rename"
CONFIGS = [(16, mode, 36) for mode in ("off", "bimodal")]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "gate.json"
    inputs = list((ROOT / "src").rglob("Ape*.scala"))
    inputs += list((ROOT / "examples/ape").glob("*"))
    inputs += [ROOT / p for p in (
        "build.sbt", "project/build.properties", "project/repositories",
        "tools/sbtw", "tools/toolchain.py", "tools/assemble_ape.py", "tools/assemble_hse.py",
        "tools/verify_ape.py", "tools/verify_ape_rename.py", "tools/verify_ape_spike.py",
        "tools/bootstrap_spike.py", "tools/compare_ape_spike.py", "tools/spike.lock.json",
        "tools/spike_adapter.cc")]
    initial = hashes(inputs)
    report = {"schema": 1, "status": "running", "issue": 4, "S03_complete": False,
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "claim_class": "actual_physical_rename_RTL_and_pressure_Spike_comparison",
              "source_sha256": initial,
              "limits": ["Simulation assertions and port scoreboard, not formal proof",
                         "Head-only memory; checkpoint correctness requires the separate early-recovery gate",
                         "Not a multi-issue, synthesis, timing, energy or speedup result",
                         "Two existing RISC-V profile differences remain explicitly checked"]}

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        report["reference_build"] = spike.check()
        env = dict(os.environ)
        env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        subprocess.run([sys.executable, "tools/assemble_ape.py"], cwd=ROOT, env=env, check=True, timeout=180)
        command = ["bash", "tools/sbtw", "Test / compile", "Test / runMain hats.ApeRenameSim"]
        command += [f"Test / runMain hats.ApeCoreSim {n} {mode} {physical}" for n, mode, physical in CONFIGS]
        report["command"] = command
        # Old evidence cannot survive a failed or incomplete current invocation.
        report_paths = [OUT / "validation.json"] + [
            ROOT / f"build/ape_pressure/r{n}-{mode}-p{physical}/validation.json" for n, mode, physical in CONFIGS]
        for p in report_paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{"status":"not_run"}\n')
        save()
        print("Running physical-rename RTL gate; log: build/ape_rename/gate.log", flush=True)
        with (OUT / "gate.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
        unit = json.loads(report_paths[0].read_text())
        if unit["status"] != "passed" or [r["physical_registers"] for r in unit["runs"]] != [33, 36, 64]:
            raise RuntimeError("Incomplete rename unit matrix")
        for r in unit["runs"]:
            if not (r["cycles"] == 6000 and r["allocations"] > 1000 and r["resource_stalls"] > 0
                    and r["recoveries"] > 100 and r["retirements"] > 500 and r["relaunches"] == 7
                    and r["commit_and_recovery"] > 0
                    and (r["physical_registers"] == 33 or r["out_of_order_writebacks"] > 100)):
                raise RuntimeError("Missing physical-register hazard coverage")
        report["rename_unit"] = unit
        evidence = {str(p.relative_to(ROOT)): spike.digest(p) for p in report_paths}
        definitions, golden, comparisons, stalls = {}, {}, [], []
        expected_keys = None
        for (n, mode, physical), suite_path in zip(CONFIGS, report_paths[1:]):
            suite = json.loads(suite_path.read_text())
            if (suite["status"], suite["rob_entries"], suite["prediction"], suite["physical_registers"],
                suite["scenarios"], suite["runs"]) != ("passed", n, mode, physical, 50, 100):
                raise RuntimeError("Incomplete register-pressure RTL matrix")
            keys = [(r["name"], r["invocation"]) for r in suite["results"]]
            if len(keys) != 100 or len(set(keys)) != 100 or any(i not in (0, 1) for _, i in keys):
                raise RuntimeError("Invalid pressure case multiplicity")
            if expected_keys is not None and keys != expected_keys:
                raise RuntimeError("Pressure configuration scenario sets differ")
            expected_keys = keys
            if not all(r["passed"] for r in suite["results"]):
                raise RuntimeError("Failed pressure scenario")
            stalled = sum(r["rename_stall_cycles"] for r in suite["results"])
            if stalled <= 0:
                raise RuntimeError("Register exhaustion was not exercised in the integrated core")
            stalls.append({"rob_entries": n, "prediction": mode, "physical_registers": physical,
                           "rename_stall_cycles": stalled})
            for name, invocation in keys:
                if not re.fullmatch(r"[a-z0-9_]+", name):
                    raise RuntimeError("Invalid case name")
                prefix = suite_path.parent / f"{name}-{invocation}"
                metadata, actual = Path(str(prefix) + ".case.json"), Path(str(prefix) + ".arch.jsonl")
                case = json.loads(metadata.read_text())
                if (case["schema"], case["name"], case["invocation"]) != (1, name, invocation):
                    raise RuntimeError("Case identity mismatch")
                if not re.fullmatch(r"p\d+|random\d+|control\d+", case["image"]):
                    raise RuntimeError("Invalid image identity")
                if type(case["writable"]) is not bool or type(case["bus_error"]) is not bool:
                    raise RuntimeError("Invalid environment flags")
                definition = {k: v for k, v in case.items() if k != "invocation"}
                if name in definitions and definitions[name] != definition:
                    raise RuntimeError("Pressure scenario definitions differ")
                definitions[name] = definition
                if name not in golden:
                    image = ROOT / f"build/ape/programs/{case['image']}.hex"
                    expected, raw = OUT / f"{name}.spike.jsonl", OUT / f"{name}.spike.log"
                    with expected.open("w") as stdout, (OUT / f"{name}.stderr").open("w") as stderr:
                        subprocess.run([str(spike.BINARY), str(image), case["entry"], str(int(case["writable"])),
                                        str(int(case["bus_error"])), str(raw)], cwd=ROOT,
                                       stdout=stdout, stderr=stderr, check=True, timeout=30)
                    golden[name] = read_trace(expected)
                    for p in (image, expected, raw):
                        evidence[str(p.relative_to(ROOT))] = spike.digest(p)
                result = compare(read_trace(actual), golden[name], case_profile(case))
                result.update({"name": name, "invocation": invocation, "rob_entries": n,
                               "prediction": mode, "physical_registers": physical, "profile": case_profile(case)})
                comparisons.append(result)
                for p in (metadata, actual):
                    evidence[str(p.relative_to(ROOT))] = spike.digest(p)
        if len(golden) != 50 or len(comparisons) != 200:
            raise RuntimeError("Incomplete independent pressure comparison")
        matched = sum(r["status"] == "matched" for r in comparisons)
        gaps = sum(r["status"] == "expected_profile_difference" for r in comparisons)
        if (matched, gaps) != (192, 8):
            raise RuntimeError("Unexpected pressure differential result")
        report.update({"pressure_comparisons": comparisons, "pressure_counters": stalls,
                       "fully_matched_invocations": matched, "expected_profile_differences": gaps})
        generated = list(OUT.glob("p*/**/*.v")) + list((ROOT / "build/ape_pressure").glob("r16-*-p36/sim/**/*.v"))
        if not generated:
            raise RuntimeError("No generated RTL evidence")
        evidence.update(hashes(generated))
        for name, digest in evidence.items():
            if spike.digest(ROOT / name) != digest:
                raise RuntimeError("Evidence changed: " + name)
        if hashes(inputs) != initial or spike.check() != report["reference_build"]:
            raise RuntimeError("Sources/reference changed during verification")
        report["evidence_sha256"] = evidence
        report["status"] = "passed_with_profile_differences"
    except Exception as error:
        report.update({"status": "failed", "error": str(error)})
        raise
    finally:
        report["source_sha256_after"] = hashes(inputs)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print("Physical rename PASS: 18000 RTL cycles; pressure Spike comparisons: 192 matches, 8 checked profile differences")


if __name__ == "__main__":
    main()
