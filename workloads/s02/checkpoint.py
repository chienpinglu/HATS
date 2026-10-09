#!/usr/bin/env python3
"""Summarize verified S02 evidence without claiming S02 or PPE RTL completion.

This checks existing local artifacts and runs fast model/loader tests. It does
not rerun hardware simulation; the execution drivers remain authoritative.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
HARDWARE = REPO / "hardware/spinal"
EXECUTE = REPO / "workloads/target/treesitter/execute"
KINDS = ("cold_old", "cold_new", "incremental")
SMALL = ("empty", "scalars", "unicode")
NEGATIVES = {"bad_magic": 1, "bad_mode": 1, "input_bound": 1, "invalid_heap_bound": 1,
             "heap_zero": 2, "heap_small": 2, "output_full": 3, "output_short": 1,
             "output_bound": 1, "reserved": 1}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition: raise ValueError(message)


def check_hashes(base, hashes):
    require(bool(hashes), "Empty evidence manifest")
    base = base.resolve()
    for name, digest in hashes.items():
        path = (base / name).resolve()
        require(not Path(name).is_absolute() and path.is_relative_to(base), "Evidence path escapes root")
        require(path.is_file() and sha(path) == digest, "Stale or missing evidence: " + name)


def matrix(rows, fields, expected):
    actual = [tuple(row[field] for field in fields) for row in rows]
    require(len(actual) == len(set(actual)) and set(actual) == set(expected), "Incomplete or duplicated matrix")


def validate_reference(report, cases, full):
    require(report["status"] == "passed" and report["claim_class"] == "rv64i_spike_tool_execution"
            and report["ape_rtl_execution"] is False, "Reference mislabeled as hardware")
    require(report["full_fixture_matrix"] is full, "Wrong reference coverage label")
    matrix(report["runs"], ("case", "kind"), [(c, k) for c in cases for k in KINDS])
    require(report["helpers"]["vectors_passed"] == 177 and report["helpers"]["operations_per_vector"] == 6
            and report["runtime_tests"]["checks_passed"] == 160, "Missing helper/runtime checks")
    for row in report["runs"]:
        require(row["result"]["status"] == 0 and row["result"]["live_after_cleanup"] == 0
                and row["execution"]["result"] == 0 and row["execution"]["retired"] > 0, "Failed parser execution")
    matrix(report["negative_cases"], ("case", "expected_status"), NEGATIVES.items())
    for row in report["negative_cases"]:
        require(row["result"]["status"] == row["expected_status"] == row["execution"]["result"], "Wrong rejection result")
    require(all(b["strict_link"] == "passed" for b in report["builds"].values())
            and set(report["builds"]) == {"helpers", "runtime", "parser"}, "Missing strict executable")


def validate_rtl(report):
    require(report["status"] == "passed" and report["claim_class"] == "upstream_tool_on_ape_rtl"
            and report["ape_rtl_execution"] is True and report["full_S02_gate"] is False, "Incorrect RTL claim")
    require(report["rob_entries"] == 8 and report["prediction"] == "bimodal"
            and report["selected_cases"] == list(SMALL) and report["selected_kinds"] == list(KINDS), "Wrong checkpoint profile")
    expected = [(c + "-" + k, i) for c in SMALL for k in KINDS for i in range(2)]
    matrix(report["comparisons"], ("case", "invocation"), expected)
    matrix(report["rtl_diagnostics"]["runs"], ("case", "invocation"), expected)
    require(all(r["trace"]["status"] == "matched" and r["trace"]["retirements"] > 0
                for r in report["comparisons"]), "Unmatched RTL trace")
    require(all(r["result"] == 0 for r in report["rtl_diagnostics"]["runs"]), "Failed RTL application")


def collect(reference_path, rtl_path):
    def read(path): return json.loads(path.read_text())
    reference, rtl = read(reference_path), read(rtl_path)
    small_path = rtl_path.parent / "validation.json"
    small = read(small_path)
    fixtures = read(REPO / "workloads/native/treesitter/cases.lock.json")
    lock = read(REPO / "workloads/native/treesitter/sources.lock.json")
    validate_reference(reference, [c["id"] for c in fixtures["cases"]], True)
    validate_reference(small, SMALL, False)
    validate_rtl(rtl)
    for report, path in ((reference, reference_path), (small, small_path)):
        require(report["fixtures"] == fixtures and report["source_lock"] == lock, "Upstream/fixture identity differs")
        check_hashes(REPO, report["source_sha256"])
        check_hashes(path.parent, report["artifacts_sha256"])
    require(reference["source_sha256"] == small["source_sha256"], "Reference and RTL use different target source")
    require(reference["builds"] == small["builds"], "Reference and RTL use different executables")
    require(sha(small_path) == rtl["reference_report_sha256"], "RTL reference report changed")
    check_hashes(REPO, rtl["source_sha256"])
    folder = rtl_path.parent / "parser/rtl-r8-bimodal"
    for row in rtl["comparisons"]:
        prefix = f"{row['case']}-{row['invocation']}"
        check_hashes(folder, {prefix + ".trace.jsonl": row["trace_sha256"], prefix + ".result.bin": row["output_sha256"]})
        require(sha(rtl_path.parent / "parser" / row["case"] / "result.bin") == row["output_sha256"], "RTL output differs from reference")
    generated = list((folder / "sim").rglob("ApeCore.v"))
    require(generated and sorted(sha(p) for p in generated) == sorted(rtl["generated_rtl_sha256"]), "Generated RTL changed")

    regressions = {}
    source_hashes = {**reference["source_sha256"], **rtl["source_sha256"]}
    for label, filename in (("ape", "ape/validation.json"), ("ape_spike", "ape/spike/validation.json"),
                            ("bounded_diff", "ape_app/validation.json"), ("legacy_task_tile", "validation.json")):
        path = HARDWARE / "build" / filename
        report = read(path)
        require(report["status"] == ("passed_with_profile_differences" if label == "ape_spike" else "passed"), "Regression failed: " + label)
        hashes = report.get("source_sha256", report.get("sha256"))
        check_hashes(HARDWARE, hashes)
        if "source_sha256_after" in report: require(hashes == report["source_sha256_after"], "Regression source changed")
        if label != "legacy_task_tile":
            source_hashes.update({"hardware/spinal/" + n: h for n, h in hashes.items()})
        else:
            # Preserve pre-existing, out-of-scope work. Do not silently include it
            # in this checkpoint's current-source/clean-checkout claim.
            changed = subprocess.check_output(["git", "diff", "--name-only", "HEAD", "--", "hardware/spinal/src/main/scala/hats/TaskTile.scala"], cwd=REPO, text=True).strip()
            regressions[label] = {"tests_passed": report["tests_passed"], "local_modified_source": bool(changed),
                                   "task_tile_sha256": hashes["src/main/scala/hats/TaskTile.scala"]}
        selected = {k: report[k] for k in ("runs_passed", "fully_matched_invocations", "expected_profile_differences") if k in report}
        regressions.setdefault(label, {}).update(selected, report_sha256=sha(path))
        if label == "ape":
            require(report["predictor"]["lookup_checks"] == 4096, "Missing predictor checks")
            regressions[label]["predictor_checks"] = 4096
    require(regressions["ape"]["runs_passed"] == 600 and regressions["bounded_diff"]["runs_passed"] == 144
            and regressions["ape_spike"]["fully_matched_invocations"] == 576
            and regressions["ape_spike"]["expected_profile_differences"] == 24
            and regressions["legacy_task_tile"]["tests_passed"] == 123, "Regression coverage differs")

    tests = []
    for directory, pattern in (("hardware/spinal/tools", "test_ppe_isa.py"),
                               ("workloads/target/treesitter/execute", "test_*.py"), ("workloads/s02", "test_*.py")):
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", pattern, "-v"]
        result = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, check=True, timeout=60)
        print(result.stderr, end="")
        tests.append({"directory": directory, "pattern": pattern, "status": "passed",
                      "output_sha256": hashlib.sha256((result.stdout + result.stderr).encode()).hexdigest()})
    for path in [HARDWARE / "tools/ppe_isa.py", HARDWARE / "tools/ppe_programs.py",
                 HARDWARE / "tools/test_ppe_isa.py", *Path(__file__).parent.glob("*.py")]:
        source_hashes[str(path.relative_to(REPO))] = sha(path)
    check_hashes(REPO, source_hashes)
    return {"schema": 1, "status": "checkpoint_verified", "created_utc": datetime.now(timezone.utc).isoformat(),
            "issue": 3, "stage": "S02", "S02_complete": False, "ppe_rtl_implemented": False,
            "claim_class": "real_upstream_tool_on_selected_ape_rtl_plus_ppe_reference_model",
            "source_sha256": source_hashes,
            "dependencies": {"sources": lock["sources"], "compiler": reference["compiler"],
                             "newlib_build_sha256": reference["newlib_build_sha256"], "spike_revision": reference["spike_revision"],
                             "spike_build_sha256": reference["spike_build_sha256"]},
            "reference": {"report_sha256": sha(reference_path), "cases_passed": 30, "helper_results": 1062,
                          "runtime_checks": 160, "negative_cases": 10, "code_bytes": reference["builds"]["parser"]["profile"]["code_bytes"],
                          "elf_sha256": reference["builds"]["parser"]["elf_sha256"], "runs": reference["runs"]},
            "ape_rtl": {"report_sha256": sha(rtl_path), "invocations": 18, "rob_entries": 8, "prediction": "bimodal",
                        "program_words": 65536, "selected_cases": list(SMALL), "kinds": list(KINDS),
                        "toolchain": rtl["toolchain"],
                        "matched_retirements": sum(r["trace"]["retirements"] for r in rtl["comparisons"]),
                        "matched_memory_events": sum(r["trace"]["memory_events"] for r in rtl["comparisons"]),
                        "generated_rtl_sha256": sorted(set(rtl["generated_rtl_sha256"]))},
            "regressions": regressions, "fast_tests": tests,
            "limits": ["Checkpoint validation checks prior local execution artifacts; it does not rerun RTL",
                       "Only nine tool inputs/modes on one APE configuration; helper/negative/large cases currently Spike-only",
                       "PPE has an independent functional model and codec, not an implemented RTL engine",
                       "Legacy regression includes a pre-existing local TaskTile change when flagged; not clean-checkout evidence",
                       "No CP, OS, caches/coherence, CPU-offload speedup, high-performance big core or PPA claim"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--rtl", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = collect(args.reference.resolve(), args.rtl.resolve())
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"S02 checkpoint verified (S02 incomplete): {args.output}")


if __name__ == "__main__": main()
