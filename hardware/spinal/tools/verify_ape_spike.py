#!/usr/bin/env python3
"""Fresh RTL versus pinned external Spike; known profile gaps remain visible."""
from datetime import datetime, timezone
import copy
import json
from pathlib import Path
import re
import subprocess
import sys

import bootstrap_spike as spike
from compare_ape_spike import Divergence, compare, read_trace
from verify_ape import CONFIGS, hashes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/ape/spike"
PLATFORM_CASES = {"load_bounds", "store_bounds", "store_readonly", "load_bus_fault",
                  "store_bus_fault", "fetch_bounds", "zero_load_fault", "load_upper_bound", "entry_bounds"}


def case_profile(case):
    identity = (case["name"], case["image"], case["entry"], case["writable"], case["bus_error"])
    if identity == ("unsupported_fence_i", "p20", "0", True, False):
        return "fence_i_gap"
    if identity == ("entry_alignment", "p0", "2", True, False):
        return "launch_alignment_gap"
    return "shared"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "validation.json"
    inputs = list((ROOT / "tools").glob("*spike*"))
    inputs += list((ROOT / "src").rglob("Ape*.scala"))
    inputs += list((ROOT / "examples/ape").glob("*"))
    inputs += [ROOT / "tools/verify_ape.py", ROOT / "tools/assemble_ape.py"]
    initial = hashes(inputs)
    report = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
              "claim": "Independent upstream Spike comparison of APE RTL architectural events",
              "source_sha256": initial,
              "limits": ["Not full RV64I/privileged/OS or architectural-test certification",
                         "APE launch policy and instruction profile differ in two explicitly checked cases",
                         "Original adapter supplies APE bounds, permission and bus-error environment",
                         "No performance, coherence or physical memory-system validation"]}

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        report["reference_build"] = spike.check()
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_ape_spike.py", "-v"],
                       cwd=ROOT, check=True, timeout=60)
        # Always execute current RTL. Historical traces are never silently reused.
        subprocess.run([sys.executable, "tools/verify_ape.py"], cwd=ROOT, check=True, timeout=1200)
        rtl_report_path = ROOT / "build/ape/validation.json"
        rtl_report = json.loads(rtl_report_path.read_text())
        if rtl_report["status"] != "passed" or rtl_report["runs_passed"] != 600:
            raise RuntimeError("Current APE RTL matrix did not pass")
        for name, sha in {**rtl_report["source_sha256"], **rtl_report["artifact_sha256"]}.items():
            if spike.digest(ROOT / name) != sha:
                raise RuntimeError(f"RTL input/artifact changed: {name}")
        report["rtl_report_sha256"] = spike.digest(rtl_report_path)
        report["rtl_claim"] = rtl_report["claim"]
        golden = {}
        definitions = {}
        results = []
        evidence = {str(rtl_report_path.relative_to(ROOT)): spike.digest(rtl_report_path)}
        expected_keys = None
        observed_profiles = {}
        for n, mode in CONFIGS:
            folder = ROOT / f"build/ape/r{n}-{mode}"
            suite_path = folder / "validation.json"
            suite = json.loads(suite_path.read_text())
            evidence[str(suite_path.relative_to(ROOT))] = spike.digest(suite_path)
            keys = [(r["name"], r["invocation"]) for r in suite["results"]]
            if len(keys) != 100 or len(set(keys)) != 100 or any(i not in (0, 1) for _, i in keys):
                raise RuntimeError("Invalid case multiplicity")
            if expected_keys is None:
                expected_keys = keys
            elif keys != expected_keys:
                raise RuntimeError("Different scenario sets across configurations")
            for name, invocation in keys:
                if not re.fullmatch(r"[a-z0-9_]+", name):
                    raise RuntimeError("Invalid scenario name")
                prefix = folder / f"{name}-{invocation}"
                metadata = Path(str(prefix) + ".case.json")
                actual_path = Path(str(prefix) + ".arch.jsonl")
                case = json.loads(metadata.read_text())
                if (case["schema"], case["name"], case["invocation"]) != (1, name, invocation):
                    raise RuntimeError("Case identity mismatch")
                if not re.fullmatch(r"p\d+|random\d+|control\d+", case["image"]):
                    raise RuntimeError("Invalid image identity")
                if type(case["writable"]) is not bool or type(case["bus_error"]) is not bool:
                    raise RuntimeError("Invalid environment flags")
                definition = {k: v for k, v in case.items() if k != "invocation"}
                if name in definitions and definition != definitions[name]:
                    raise RuntimeError("Scenario inputs differ between invocations")
                definitions[name] = definition
                profile = case_profile(case)
                observed_profiles[name] = profile
                for p in (metadata, actual_path):
                    evidence[str(p.relative_to(ROOT))] = spike.digest(p)
                if name not in golden:
                    image = ROOT / f"build/ape/programs/{case['image']}.hex"
                    expected_path = OUT / f"{name}.spike.jsonl"
                    raw_log = OUT / f"{name}.spike.log"
                    command = [str(spike.BINARY), str(image), case["entry"], str(int(case["writable"])),
                               str(int(case["bus_error"])), str(raw_log)]
                    with expected_path.open("w") as stdout, (OUT / f"{name}.stderr").open("w") as stderr:
                        subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, check=True, timeout=30)
                    golden[name] = read_trace(expected_path)
                    for p in (image, expected_path, raw_log):
                        evidence[str(p.relative_to(ROOT))] = spike.digest(p)
                actual = read_trace(actual_path)
                result = compare(actual, golden[name], profile)
                result.update({"name": name, "invocation": invocation, "rob_entries": n, "prediction": mode,
                               "profile": profile, "environment_fault_case": name in PLATFORM_CASES})
                results.append(result)
        if len(golden) != 50 or len(results) != 600:
            raise RuntimeError("Incomplete independent comparison matrix")
        if {k for k, v in observed_profiles.items() if v != "shared"} != {"entry_alignment", "unsupported_fence_i"}:
            raise RuntimeError("Unexpected profile exclusions")
        report["results"] = results
        report["reference_program_runs"] = len(golden)
        report["fully_matched_invocations"] = sum(r["status"] == "matched" for r in results)
        report["expected_profile_differences"] = sum(r["status"] == "expected_profile_difference" for r in results)
        report["matched_retirements"] = sum(r.get("retirements", 0) for r in results)
        report["matched_memory_events"] = sum(r.get("memory_events", 0) for r in results)
        if (report["fully_matched_invocations"], report["expected_profile_differences"]) != (576, 24):
            raise RuntimeError("Differential coverage changed unexpectedly")
        # Mutate actual current-run DUT data to prove the checker rejects it.
        current = read_trace(ROOT / "build/ape/r8-bimodal/rename_raw_waw_war-0.arch.jsonl")
        rejected = 0
        mutations = [(0, "value", "1"), (0, "next", "8"), (0, "instruction", 0),
                     (1, "data", "8"), (1, "address", "65544"), (-1, "cause", 2)]
        for index, key, value in mutations:
            bad = copy.deepcopy(current)
            bad[index][key] = value
            try:
                compare(bad, golden["rename_raw_waw_war"])
            except Divergence:
                rejected += 1
            else:
                raise RuntimeError("Checker accepted a mutated current RTL trace")
        report["current_trace_mutations_rejected"] = rejected
        report["evidence_sha256"] = evidence
        for name, sha in evidence.items():
            if spike.digest(ROOT / name) != sha:
                raise RuntimeError(f"Evidence changed during comparison: {name}")
        if hashes(inputs) != initial:
            raise RuntimeError("Differential verifier sources changed during run")
        if spike.check() != report["reference_build"]:
            raise RuntimeError("Reference build changed during run")
        report["status"] = "passed_with_profile_differences"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        report["source_sha256_after"] = hashes(inputs)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(f"APE/Spike: {report['fully_matched_invocations']} fully matched invocations; "
          f"{report['expected_profile_differences']} explicitly checked profile differences; no unexpected divergence")


if __name__ == "__main__":
    main()
