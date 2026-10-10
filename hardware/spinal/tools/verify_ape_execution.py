#!/usr/bin/env python3
"""Fresh execution/lease RTL gate and independent pipeline-profile comparison.

This is one source-bound S03 regression, not application/PPA or issue closure.
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
from verify_ape_spike import case_profile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/ape_execution"
CONFIGS = [(8, "off", 64, 2, 1), (8, "bimodal", 64, 8, 1), (16, "bimodal", 36, 2, 2)]


def directory(n, mode, p, depth, bits):
    return OUT / f"core/r{n}-{mode}-p{p}-c4-d{depth}-g{bits}-standard"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "gate.json"
    inputs = list((ROOT / "src").rglob("Ape*.scala")) + list((ROOT / "examples/ape").glob("*"))
    inputs += [ROOT / p for p in (
        "build.sbt", "project/build.properties", "project/repositories", "tools/sbtw", "tools/toolchain.py",
        "tools/assemble_ape.py", "tools/assemble_hse.py", "tools/verify_ape.py", "tools/verify_ape_execution.py",
        "tools/verify_ape_spike.py", "tools/compare_ape_spike.py", "tools/bootstrap_spike.py",
        "tools/spike.lock.json", "tools/spike_adapter.cc")]
    initial = hashes(inputs)
    report = {"schema": 1, "status": "running", "issue": 4, "S03_complete": False,
              "spec_revision": "APE-0.5", "started_utc": datetime.now(timezone.utc).isoformat(),
              "claim_class": "actual_registered_execution_and_qualified_completion_RTL",
              "source_sha256": initial,
              "limits": ["Not a whole-core formal proof; legal ownership state is supplied to guard unit tests",
                         "Core generation stalls and execution input stalls are reported, not assumed exercised",
                         "Extra result stages are delay stress, not arithmetic timing cuts",
                         "Real-tool, full standard, rename and checkpoint regressions are separate gates",
                         "Single issue/retire and head-only memory; no PPA or end-to-end speedup claim"]}

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        report["reference_build"] = spike.check()
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        subprocess.run([sys.executable, "tools/assemble_ape.py"], cwd=ROOT, env=env, check=True, timeout=180)
        unit_paths = [OUT / "validation.json", OUT / "ownership.json"]
        suite_paths = [directory(*cfg) / "validation.json" for cfg in CONFIGS]
        for p in unit_paths + suite_paths:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{"status":"not_run"}\n')
        command = ["bash", "tools/sbtw", "Test / compile", "Test / runMain hats.ApeExecuteSim",
                   "Test / runMain hats.ApeCompletionGuardSim"]
        command += [f"Test / runMain hats.ApeCoreSim {n} {mode} {p} 4 early standard {depth} {bits}"
                    for n, mode, p, depth, bits in CONFIGS]
        report["command"] = command; save()
        print("Execution RTL gate; log: build/ape_execution/gate.log", flush=True)
        with (OUT / "gate.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
        transport, ownership = [json.loads(p.read_text()) for p in unit_paths]
        if transport["status"] != "passed" or transport["cycles"] != 16800:
            raise RuntimeError("Incomplete elastic execution gate")
        if [(r["depth"], r["generation_bits"]) for r in transport["configurations"]] != [(2, 1), (2, 2), (8, 1), (16, 2)]:
            raise RuntimeError("Wrong pipeline stress configurations")
        for r in transport["configurations"]:
            if not (r["cycles"] == 4200 and r["accepted"] == r["completed"] + r["canceled"] and r["completed"] > 500
                    and r["canceled"] > 0 and r["input_stalls"] > 500 and r["full_cycles"] > 100 and r["clear_events"] == 15):
                raise RuntimeError("Missing transport/backpressure/clear coverage")
        if ownership["status"] != "passed" or ownership["checks"] != 16000:
            raise RuntimeError("Incomplete identity gate")
        if [r["generation_bits"] for r in ownership["configurations"]] != [1, 2]:
            raise RuntimeError("Missing small generation-width tests")
        for r in ownership["configurations"]:
            if not (r["checks"] == 8000 and r["qualified"] > 2000 and r["rejected"] > 2000 and r["wrap_conflicts"] > 500):
                raise RuntimeError("Missing stale/duplicate/wrap exclusions")
        evidence = hashes(unit_paths + suite_paths)
        golden, definitions, comparisons, suites = {}, {}, [], []
        expected_cases = None
        for cfg, suite_path in zip(CONFIGS, suite_paths):
            n, mode, p, depth, bits = cfg
            suite = json.loads(suite_path.read_text())
            if (suite["status"], suite["rob_entries"], suite["prediction"], suite["physical_registers"],
                suite["execution_stages"], suite["generation_bits"], suite["early_recovery"], suite["checkpoint_capacity"],
                suite["recovery_suite"], suite["scenarios"], suite["runs"]) != ("passed", n, mode, p, depth, bits, True, 4, False, 50, 100):
                raise RuntimeError("Wrong/incomplete core pipeline configuration")
            cases = [(r["name"], r["invocation"]) for r in suite["results"]]
            if len(cases) != len(set(cases)) or len(cases) != 100 or any(i not in (0, 1) for _, i in cases):
                raise RuntimeError("Wrong case multiplicity")
            if expected_cases is not None and cases != expected_cases:
                raise RuntimeError("Pipeline configurations did not run identical scenario sets")
            expected_cases = cases
            if not all(r["passed"] for r in suite["results"]):
                raise RuntimeError("Failed core scenario")
            counters = {k: sum(r[k] for r in suite["results"]) for k in (
                "late_rejected", "rejected_after_slot_reuse", "physical_reuse_while_pending", "canceled_at_stop",
                "execution_stall_cycles", "generation_stall_cycles", "rename_stall_cycles")}
            counters["max_execution_tokens"] = max(r["max_execution_tokens"] for r in suite["results"])
            if not (counters["late_rejected"] > 0 and counters["physical_reuse_while_pending"] > 0
                    and counters["max_execution_tokens"] >= 2 and counters["canceled_at_stop"] > 0):
                raise RuntimeError("Integrated late-result/physical-reuse/clear coverage missing")
            if p == 36 and counters["rename_stall_cycles"] <= 0:
                raise RuntimeError("Physical pressure not exercised")
            if depth > 2 and counters["rejected_after_slot_reuse"] <= 0:
                raise RuntimeError("Deep pipeline did not reject a late result after an earlier-edge ROB slot reuse")
            suites.append({"configuration": list(cfg), "counters": counters})
            for name, invocation in cases:
                prefix = suite_path.parent / f"{name}-{invocation}"
                metadata, actual, timing = [Path(str(prefix) + ext) for ext in (".case.json", ".arch.jsonl", ".trace")]
                case = json.loads(metadata.read_text())
                if (case["schema"], case["name"], case["invocation"]) != (1, name, invocation):
                    raise RuntimeError("Wrong input identity")
                definition = {k: v for k, v in case.items() if k != "invocation"}
                if name in definitions and definitions[name] != definition:
                    raise RuntimeError("Unequal input/environment definitions")
                definitions[name] = definition
                if name not in golden:
                    image = ROOT / f"build/ape/programs/{case['image']}.hex"
                    reference, raw = OUT / f"{name}.spike.jsonl", OUT / f"{name}.spike.log"
                    with reference.open("w") as stdout, (OUT / f"{name}.stderr").open("w") as stderr:
                        subprocess.run([str(spike.BINARY), str(image), case["entry"], str(int(case["writable"])),
                                        str(int(case["bus_error"])), str(raw)], cwd=ROOT, stdout=stdout, stderr=stderr,
                                       check=True, timeout=30)
                    golden[name] = read_trace(reference)
                    evidence.update(hashes([image, reference, raw]))
                result = compare(read_trace(actual), golden[name], case_profile(case))
                result.update({"name": name, "invocation": invocation, "configuration": list(cfg)})
                comparisons.append(result)
                evidence.update(hashes([metadata, actual, timing]))
        matched = sum(r["status"] == "matched" for r in comparisons)
        gaps = sum(r["status"] == "expected_profile_difference" for r in comparisons)
        if (len(golden), len(comparisons), matched, gaps) != (50, 300, 288, 12):
            raise RuntimeError("Unexpected independent comparison result")
        generated = list(OUT.glob("depth*/**/*.v")) + list(OUT.glob("ownership-*/**/*.v"))
        for cfg in CONFIGS: generated += list(directory(*cfg).glob("sim/**/*.v"))
        if not generated: raise RuntimeError("Missing actual generated RTL")
        evidence.update(hashes(generated + [ROOT / "build/ape/programs/manifest.json", OUT / "gate.log"]))
        for name, digest in evidence.items():
            if spike.digest(ROOT / name) != digest: raise RuntimeError("Evidence changed: " + name)
        if hashes(inputs) != initial or spike.check() != report["reference_build"]:
            raise RuntimeError("Source/reference changed during execution")
        report.update({"status": "passed_with_profile_differences", "transport": transport, "ownership": ownership,
                       "core_suites": suites, "comparisons": comparisons, "fully_matched_invocations": matched,
                       "expected_profile_differences": gaps, "evidence_sha256": evidence})
    except Exception as error:
        report.update({"status": "failed", "error": str(error)}); raise
    finally:
        report["source_sha256_after"] = hashes(inputs)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print("Execution PASS: 16800 pipeline cycles, 16000 identity checks, 288 Spike matches + 12 existing profile differences")


if __name__ == "__main__":
    main()
