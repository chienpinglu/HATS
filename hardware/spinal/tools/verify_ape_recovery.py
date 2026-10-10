#!/usr/bin/env python3
"""Fresh checkpoint RTL, early timing witnesses and exact external ISA comparison.

Does not substitute for the standard matrix, real-tool regression or S03 closure.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import bootstrap_spike as spike
from compare_ape_spike import compare, read_trace
from verify_ape import hashes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/ape_recovery"
CONFIGS = [(mode, p, c, early) for mode in ("off", "bimodal")
           for p, c, early in ((64, 1, True), (64, 4, True), (36, 4, True), (64, 4, False))]
CONFIGS += [("off", 64, 2, True)]
NAMES = ("older_load", "nested_checkpoints", "jalr_link", "older_bus_fault", "faulting_link", "checkpoint_exhaustion")


def directory(mode, p, c, early):
    return OUT / f"r16-{mode}-p{p}-c{c}-{'early' if early else 'retire'}-witness"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "gate.json"
    inputs = list((ROOT / "src").rglob("Ape*.scala"))
    inputs += list((ROOT / "examples/ape_recovery").glob("*"))
    inputs += [ROOT / p for p in (
        "build.sbt", "project/build.properties", "project/repositories", "tools/sbtw", "tools/toolchain.py",
        "tools/assemble_ape.py", "tools/assemble_ape_recovery.py", "examples/ape/link.ld",
        "tools/verify_ape.py", "tools/verify_ape_recovery.py", "tools/compare_ape_spike.py",
        "tools/bootstrap_spike.py", "tools/spike.lock.json", "tools/spike_adapter.cc")]
    initial = hashes(inputs)
    report = {"schema": 1, "status": "running", "issue": 4, "S03_complete": False,
              "started_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": initial,
              "claim_class": "actual_checkpoint_RTL_early_recovery_and_Spike_comparison",
              "limits": ["Bounded RTL simulation, not formal proof or full ISA certification",
                         "Single issue, registered integer/branch completion and head-only memory",
                         "Completion identity/backpressure coverage is checked by the separate execution gate",
                         "Witness cycle comparisons use the same synthetic memory service; not silicon speedup/PPA"]}

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        report["reference_build"] = spike.check()
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        subprocess.run([sys.executable, "tools/assemble_ape_recovery.py"], cwd=ROOT, check=True, env=env, timeout=180)
        unit_path = ROOT / "build/ape_checkpoints/validation.json"
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        paths = [unit_path] + [directory(*cfg) / "validation.json" for cfg in CONFIGS]
        for p in paths:
            p.parent.mkdir(parents=True, exist_ok=True); p.write_text('{"status":"not_run"}\n')
        command = ["bash", "tools/sbtw", "Test / compile", "Test / runMain hats.ApeCheckpointSim"]
        command += [f"Test / runMain hats.ApeCoreSim 16 {mode} {p} {c} {'early' if early else 'retire'} recovery"
                    for mode, p, c, early in CONFIGS]
        report["command"] = command; save()
        print("Running early-recovery RTL gate; log: build/ape_recovery/gate.log", flush=True)
        with (OUT / "gate.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
        unit = json.loads(unit_path.read_text())
        if unit["status"] != "passed" or [(r["physical_registers"], r["capacity"], r["cycles"]) for r in unit["runs"]] != [
                (36, 1, 8000), (36, 4, 8000), (64, 2, 8000), (64, 4, 8000)]:
            raise RuntimeError("Incomplete checkpoint unit matrix")
        for r in unit["runs"]:
            if not (r["captures"] > 100 and r["redirects"] > 50 and r["commit_and_redirect"] > 10
                    and r["checkpoint_stalls"] > 0 and r["retirements"] > 500 and r["squashed_instructions"] > 100
                    and (r["capacity"] == 1 or r["nested_redirects"] > 20)
                    and (r["physical_registers"] != 36 or r["register_stalls"] > 0)):
                raise RuntimeError("Missing checkpoint hazard coverage")
        report["checkpoint_unit"] = unit
        evidence = hashes(paths)
        golden, comparisons, suites = {}, [], {}
        for mode, p, c, early in CONFIGS:
            folder = directory(mode, p, c, early)
            suite = json.loads((folder / "validation.json").read_text())
            if (suite["status"], suite["rob_entries"], suite["physical_registers"], suite["prediction"],
                suite["checkpoint_capacity"], suite["early_recovery"], suite["recovery_suite"], suite["runs"]) != (
                    "passed", 16, p, mode, c, early, True, 12):
                raise RuntimeError("Incomplete recovery core configuration")
            rows = suite["results"]
            if [(r["name"], r["invocation"]) for r in rows] != [(name, i) for name in NAMES for i in (0, 1)]:
                raise RuntimeError("Changed recovery scenario matrix")
            if not all(r["passed"] for r in rows): raise RuntimeError("Recovery scenario failed")
            for row in rows:
                name, invocation = row["name"], row["invocation"]
                if early:
                    if name == "older_load" and not (row["early_memory_redirects"] > 0 and row["target_issues_before_memory"] > 0):
                        raise RuntimeError("No early redirect and target execution witness")
                    if name == "nested_checkpoints" and c >= 2 and not (row["resolved_younger_squashes"] > 0 and row["commit_and_redirect"] > 0):
                        raise RuntimeError("No nested recovery / concurrent older commit")
                    if name == "older_bus_fault" and row["early_memory_redirects"] == 0:
                        raise RuntimeError("Older fault did not supersede early recovery")
                    if name == "checkpoint_exhaustion" and row["checkpoint_stall_cycles"] == 0:
                        raise RuntimeError("Checkpoint exhaustion not exercised")
                elif row["early_memory_redirects"] or row["target_issues_before_memory"]:
                    raise RuntimeError("Retirement baseline unexpectedly recovered early")
                prefix = folder / f"{name}-{invocation}"
                metadata, actual = Path(str(prefix) + ".case.json"), Path(str(prefix) + ".arch.jsonl")
                case = json.loads(metadata.read_text())
                expected = {"schema": 1, "name": name, "image": f"recovery{NAMES.index(name)}", "entry": "0",
                            "writable": True, "bus_error": name == "older_bus_fault", "invocation": invocation}
                if case != expected: raise RuntimeError("Recovery input/environment identity mismatch")
                if name not in golden:
                    image = OUT / f"programs/{case['image']}.hex"
                    trace, raw = OUT / f"{name}.spike.jsonl", OUT / f"{name}.spike.log"
                    with trace.open("w") as stdout, (OUT / f"{name}.stderr").open("w") as stderr:
                        subprocess.run([str(spike.BINARY), str(image), "0", "1", str(int(case["bus_error"])), str(raw)],
                                       cwd=ROOT, stdout=stdout, stderr=stderr, check=True, timeout=30)
                    golden[name] = read_trace(trace)
                    evidence.update(hashes([image, trace, raw]))
                result = compare(read_trace(actual), golden[name])
                if result["status"] != "matched": raise RuntimeError("Recovery witness differs from Spike")
                result.update({"name": name, "invocation": invocation, "prediction": mode, "physical_registers": p,
                               "checkpoint_capacity": c, "early_recovery": early})
                comparisons.append(result)
                evidence.update(hashes([metadata, actual, Path(str(prefix) + ".trace")]))
            suites[folder.name] = rows
        if len(comparisons) != 108: raise RuntimeError("Missing independent witness comparisons")
        cycles = []
        for mode in ("off", "bimodal"):
            a = suites[directory(mode, 64, 4, True).name]
            b = suites[directory(mode, 64, 4, False).name]
            for early, baseline in zip(a, b):
                if (early["name"], early["invocation"], early["retired"], early["memory_requests"], early["result"]) != (
                    baseline["name"], baseline["invocation"], baseline["retired"], baseline["memory_requests"], baseline["result"]):
                    raise RuntimeError("Unmatched baseline architectural work")
                cycles.append({"name": early["name"], "invocation": early["invocation"], "prediction": mode,
                               "early_cycles": early["cycles"], "retirement_cycles": baseline["cycles"]})
        generated = list((ROOT / "build/ape_checkpoints").glob("p*-c*/**/*.v"))
        for cfg in CONFIGS: generated += list(directory(*cfg).glob("sim/**/*.v"))
        if not generated: raise RuntimeError("No generated RTL")
        evidence.update(hashes(generated + [OUT / "programs/manifest.json"]))
        for p, digest in evidence.items():
            if spike.digest(ROOT / p) != digest: raise RuntimeError("Evidence changed: " + p)
        if hashes(inputs) != initial or spike.check() != report["reference_build"]:
            raise RuntimeError("Source/reference changed during recovery verification")
        report.update({"status": "passed", "fully_matched_invocations": 108, "comparisons": comparisons,
                       "witness_suites": suites, "same_work_cycle_diagnostics": cycles, "evidence_sha256": evidence})
    except Exception as error:
        report.update({"status": "failed", "error": str(error)}); raise
    finally:
        report["source_sha256_after"] = hashes(inputs)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print("Early recovery PASS: 32000 checkpoint RTL cycles, 108 exact Spike comparisons and explicit early timing witnesses")


if __name__ == "__main__":
    main()
