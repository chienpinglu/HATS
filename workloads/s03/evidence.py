#!/usr/bin/env python3
"""Collect a public-safe S03 increment record from source-bound completed gates.

This does not run simulations or close S03. The S02 driver performs full
compatibility artifact revalidation; this collector checks its source/document
identity and rechecks every focused physical-renaming and early-recovery artifact.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware/spinal"
sys.path.insert(0, str(REPO / "workloads/s02"))
from checkpoint import check_hashes, matrix, require, sha

RECOVERY_NAMES = ("older_load", "nested_checkpoints", "jalr_link", "older_bus_fault", "faulting_link", "checkpoint_exhaustion")
RECOVERY_CONFIGS = [(mode, p, c, early) for mode in ("off", "bimodal")
                    for p, c, early in ((64, 1, True), (64, 4, True), (36, 4, True), (64, 4, False))]
RECOVERY_CONFIGS += [("off", 64, 2, True)]


def validate_recovery(recovery):
    """Validate completeness and timing witnesses, independently of file hashing."""
    require(recovery["status"] == "passed" and recovery["S03_complete"] is False
            and recovery["claim_class"] == "actual_checkpoint_RTL_early_recovery_and_Spike_comparison",
            "Missing focused early-recovery gate")
    require(recovery["source_sha256"] == recovery["source_sha256_after"], "Recovery sources changed during execution")
    units = recovery["checkpoint_unit"]["runs"]
    require(recovery["checkpoint_unit"]["status"] == "passed", "Checkpoint unit did not pass")
    matrix(units, ("physical_registers", "capacity", "cycles"),
           [(36, 1, 8000), (36, 4, 8000), (64, 2, 8000), (64, 4, 8000)])
    for row in units:
        require(row["captures"] > 100 and row["redirects"] > 50 and row["commit_and_redirect"] > 10
                and row["checkpoint_stalls"] > 0 and row["retirements"] > 500 and row["squashed_instructions"] > 100
                and (row["capacity"] == 1 or row["nested_redirects"] > 20)
                and (row["physical_registers"] != 36 or row["register_stalls"] > 0), "Missing recovery ownership coverage")
    matrix(recovery["comparisons"], ("name", "invocation", "prediction", "physical_registers", "checkpoint_capacity", "early_recovery"),
           [(name, i, mode, p, c, early) for name in RECOVERY_NAMES for i in (0, 1)
            for mode, p, c, early in RECOVERY_CONFIGS])
    require(recovery["fully_matched_invocations"] == 108
            and all(r["status"] == "matched" for r in recovery["comparisons"]), "Recovery must match without exclusions")
    suites = recovery["witness_suites"]
    def key(mode, p, c, early):
        return f"r16-{mode}-p{p}-c{c}-{'early' if early else 'retire'}-witness"
    require(set(suites) == {key(*cfg) for cfg in RECOVERY_CONFIGS}, "Wrong recovery witness configurations")
    witnesses = {}
    for mode, p, c, early in RECOVERY_CONFIGS:
        name = key(mode, p, c, early)
        rows = suites[name]
        matrix(rows, ("name", "invocation"), [(n, i) for n in RECOVERY_NAMES for i in (0, 1)])
        for row in rows:
            require(row["passed"] is True and row["cycles"] > 0 and row["retired"] > 0, "Failed recovery witness")
            if early:
                if row["name"] == "older_load":
                    require(row["early_memory_redirects"] > 0 and row["target_issues_before_memory"] > 0, "Missing early target issue")
                if row["name"] == "nested_checkpoints" and c >= 2:
                    require(row["resolved_younger_squashes"] > 0 and row["commit_and_redirect"] > 0, "Missing nested/concurrent restore")
                if row["name"] == "older_bus_fault":
                    require(row["early_memory_redirects"] > 0, "Missing older fault after early redirect")
                if row["name"] == "checkpoint_exhaustion":
                    require(row["checkpoint_stall_cycles"] > 0, "Missing checkpoint backpressure")
            else:
                require(row["early_memory_redirects"] == row["target_issues_before_memory"] == 0, "Baseline is not retirement recovery")
        witnesses[name] = {field: sum(r[field] for r in rows) for field in (
            "early_memory_redirects", "target_issues_before_memory", "commit_and_redirect",
            "resolved_younger_squashes", "checkpoint_stall_cycles")}
    cycles = recovery["same_work_cycle_diagnostics"]
    matrix(cycles, ("name", "invocation", "prediction"),
           [(n, i, mode) for n in RECOVERY_NAMES for i in (0, 1) for mode in ("off", "bimodal")])
    for row in cycles:
        a, b = [next(r for r in suites[key(row["prediction"], 64, 4, early)]
                     if (r["name"], r["invocation"]) == (row["name"], row["invocation"])) for early in (True, False)]
        require(all(a[f] == b[f] for f in ("retired", "memory_requests", "result")), "Different architectural work")
        require(row["early_cycles"] == a["cycles"] and row["retirement_cycles"] == b["cycles"], "Stale cycle summary")
    return {"checkpoint_unit_runs": units, "spike_matches": 108, "timing_witnesses": witnesses,
            "cycle_diagnostics": cycles,
            "memory_comparison_scope": "same randomized service policy, not necessarily identical realized waits; not a controlled performance comparison"}


def validate_formal(formal):
    require(formal["status"] == "passed_bounded" and formal["S03_complete"] is False
            and formal["claim_class"] == "bounded_selected_checkpoint_RTL_properties", "Missing bounded formal gate")
    matrix(formal["runs"], ("physical_registers", "slots", "capacity", "snapshot_field", "bounded_global_steps"),
           [(36, 8, c, 10, 12) for c in (1, 4)])
    for row in formal["runs"]:
        require(row["assertions"] == 8 and row["bounded_status"] == row["cover_status"] == "passed"
                and row["covers_reached"] == (4 if row["capacity"] == 1 else 5)
                and row["negative_control"] == "counterexample_found", "Incomplete formal checks / possible vacuity")
    require(bool(formal["assumptions"]) and bool(formal["limits"]), "Undocumented formal assumptions/scope")
    return {key: formal[key] for key in ("claim_class", "runs", "assumptions", "limits", "tools")}


EXECUTION_CONFIGS = [(8, "off", 64, 2, 1), (8, "bimodal", 64, 8, 1), (16, "bimodal", 36, 2, 2)]


def validate_execution(report):
    require(report["status"] == "passed_with_profile_differences" and report["S03_complete"] is False
            and report["claim_class"] == "actual_registered_execution_and_qualified_completion_RTL",
            "Missing registered execution gate")
    require(report["source_sha256"] == report["source_sha256_after"], "Execution source changed during verification")
    transport, ownership = report["transport"], report["ownership"]
    require(transport["status"] == "passed" and transport["cycles"] == 16800, "Incomplete transport gate")
    matrix(transport["configurations"], ("depth", "generation_bits", "cycles"),
           [(d, g, 4200) for d, g in ((2, 1), (2, 2), (8, 1), (16, 2))])
    for row in transport["configurations"]:
        require(row["accepted"] == row["completed"] + row["canceled"] and row["completed"] > 500
                and row["canceled"] > 0 and row["input_stalls"] > 500 and row["full_cycles"] > 100
                and row["clear_events"] == 15, "Missing backpressure/clear/transport accounting")
    require(ownership["status"] == "passed" and ownership["checks"] == 16000, "Incomplete ownership gate")
    matrix(ownership["configurations"], ("generation_bits", "checks"), [(g, 8000) for g in (1, 2)])
    for row in ownership["configurations"]:
        require(row["qualified"] + row["rejected"] == 8000 and row["qualified"] > 2000
                and row["rejected"] > 2000 and row["wrap_conflicts"] > 500, "Missing identity/wrap exclusions")
    suites = [{**r, "configuration": tuple(r["configuration"])} for r in report["core_suites"]]
    matrix(suites, ("configuration",), [(c,) for c in EXECUTION_CONFIGS])
    for row in suites:
        n, mode, p, depth, bits = row["configuration"]
        counters = row["counters"]
        require(counters["late_rejected"] > 0 and counters["physical_reuse_while_pending"] > 0
                and counters["max_execution_tokens"] >= 2 and counters["canceled_at_stop"] > 0,
                "Missing integrated completion/cancellation evidence")
        require(depth <= 2 or counters["rejected_after_slot_reuse"] > 0, "Missing late result after prior-edge slot reuse")
        require(p != 36 or counters["rename_stall_cycles"] > 0, "Missing execution register-pressure witness")
    comparisons = [{**r, "configuration": tuple(r["configuration"])} for r in report["comparisons"]]
    names = {r["name"] for r in comparisons}
    require(len(names) == 50, "Wrong execution scenario count")
    matrix(comparisons, ("name", "invocation", "configuration"),
           [(name, i, c) for name in names for i in (0, 1) for c in EXECUTION_CONFIGS])
    require(report["fully_matched_invocations"] == sum(r["status"] == "matched" for r in comparisons) == 288
            and report["expected_profile_differences"] == sum(r["status"] == "expected_profile_difference" for r in comparisons) == 12,
            "Incomplete pipeline Spike comparison")
    require({r["name"] for r in comparisons if r["status"] != "matched"} == {"unsupported_fence_i", "entry_alignment"},
            "New pipeline profile exclusion")
    return {"transport": transport, "ownership": ownership, "core_suites": report["core_suites"],
            "spike_matches": 288, "explicit_profile_differences": 12,
            "limits": report["limits"]}


def validate_lifecycle(report):
    require(report["status"] == "passed_bounded" and report["S03_complete"] is False
            and report["claim_class"] == "bounded_restricted_rename_lifecycle_RTL_properties",
            "Missing selected rename lifecycle proof")
    require(report["bounded_global_steps"] == 16 and report["assertions"] == 24
            and report["bounded_status"] == "passed" and report["covers_reached"] == 6
            and report["negative_control"] == "counterexample_found", "Incomplete restricted lifecycle proof")
    require(report["assumptions"] and report["limits"] and report["tools"], "Undocumented lifecycle scope/tool identity")
    return {k: report[k] for k in ("claim_class", "bounded_global_steps", "assertions", "covers_reached",
                                  "negative_control", "assumptions", "limits", "tools")}


def collect_probes(sources):
    """Bind structural diagnostics without promoting them to physical closure."""
    results = []
    for n in (4, 8, 16):
        path = HW / f"build/ape_synthesis/r{n}-bimodal/validation.json"
        report = json.loads(path.read_text())
        require(report["status"] == "passed_diagnostic" and report["S03_complete"] is False
                and report["claim_class"] == "technology_independent_synthesis_diagnostic", "Missing generic synthesis diagnostic")
        require(report["configuration"] == {"rob_entries": n, "prediction": "bimodal", "program_words": 1024,
                "physical_registers": 64, "issue_width": 1, "execution_stages": 2, "generation_bits": 2}, "Wrong synthesis diagnostic configuration")
        check_hashes(HW, report["source_sha256"])
        check_hashes(HW, report["evidence_sha256"])
        snapshot = path.parent / "ape-gate.json"
        require(sha(snapshot) == report["ape_gate_sha256"], "Synthesis lost its verified input-gate snapshot")
        original = json.loads(snapshot.read_text())
        require(original["status"] == "passed" and original["source_sha256"] == original["source_sha256_after"], "Unverified synthesis input")
        check_hashes(HW, original["source_sha256"])
        rtl = f"build/ape/rtl/r{n}-bimodal/ApeCore.v"
        require(report["generated_rtl_sha256"] == original["artifact_sha256"][rtl] == sha(HW / rtl), "Synthesis used different RTL")
        for name, digest in report["source_sha256"].items():
            key = "hardware/spinal/" + name
            require(key not in sources or sources[key] == digest, "Mixed synthesis source revision")
            sources[key] = digest
        stats = report["statistics"]["design"]
        require(stats["num_memories"] == stats["num_processes"] == 0 and stats["num_cells"] > 0
                and report["longest_path_generic_cells"] > 0, "Incomplete structural diagnostic")
        results.append({"report_sha256": sha(path), "configuration": report["configuration"],
                        "generated_rtl_sha256": report["generated_rtl_sha256"],
                        "generic_cells_including_metadata": stats["num_cells"],
                        "longest_path_generic_cells": report["longest_path_generic_cells"],
                        "constraints": report["constraints"], "limits": report["limits"]})
    return results


def collect(rename_path, compatibility_path, recovery_path, formal_path, execution_path, lifecycle_path):
    rename = json.loads(rename_path.read_text())
    compatibility = json.loads(compatibility_path.read_text())
    recovery = json.loads(recovery_path.read_text())
    recovery_summary = validate_recovery(recovery)
    formal = json.loads(formal_path.read_text())
    formal_summary = validate_formal(formal)
    execution = json.loads(execution_path.read_text())
    execution_summary = validate_execution(execution)
    lifecycle = json.loads(lifecycle_path.read_text())
    lifecycle_summary = validate_lifecycle(lifecycle)
    require(formal["recovery_report_sha256"] == sha(recovery_path), "Formal gate used different recovery RTL")
    require(lifecycle["recovery_report_sha256"] == sha(recovery_path), "Lifecycle gate used different recovery RTL")
    require(rename["status"] == "passed_with_profile_differences" and rename["S03_complete"] is False
            and rename["claim_class"] == "actual_physical_rename_RTL_and_pressure_Spike_comparison",
            "Missing focused physical-renaming gate")
    require(rename["source_sha256"] == rename["source_sha256_after"], "Rename sources changed during execution")
    require(compatibility["status"] == "passed" and compatibility["S02_complete"] is True
            and compatibility["claim_class"] == "actual_APE_tool_and_first_PPE_RTL", "Missing compatibility gate")
    sources = dict(compatibility["source_sha256"])
    check_hashes(REPO, sources)
    check_hashes(REPO, compatibility["documentation_sha256"])
    check_hashes(HW, rename["source_sha256"])
    check_hashes(HW, rename["evidence_sha256"])
    check_hashes(HW, recovery["source_sha256"])
    check_hashes(HW, recovery["evidence_sha256"])
    check_hashes(HW, formal["source_sha256"])
    check_hashes(HW, formal["evidence_sha256"])
    check_hashes(HW, execution["source_sha256"])
    check_hashes(HW, execution["evidence_sha256"])
    check_hashes(HW, lifecycle["source_sha256"])
    check_hashes(HW, lifecycle["evidence_sha256"])
    for report in (rename, recovery, formal, execution, lifecycle):
        for name, digest in report["source_sha256"].items():
            key = "hardware/spinal/" + name
            require(key not in sources or sources[key] == digest, "Mixed RTL source revisions: " + key)
            sources[key] = digest
    for name in ("ApeCore", "ApeDecode", "ApeRename", "ApeCheckpoints", "ApeExecute", "ApeCompletionGuard"):
        require("hardware/spinal/src/main/scala/hats/" + name + ".scala" in compatibility["source_sha256"],
                "Compatibility evidence predates qualified pipelined execution")
    synthesis_diagnostics = collect_probes(sources)
    units = rename["rename_unit"]["runs"]
    matrix(units, ("physical_registers", "cycles"), [(p, 6000) for p in (33, 36, 64)])
    require(all(r["resource_stalls"] > 0 and r["commit_and_recovery"] > 0 for r in units), "Missing hazard coverage")
    comparisons = rename["pressure_comparisons"]
    names = {r["name"] for r in comparisons}
    require(len(names) == 50, "Wrong pressure scenario count")
    matrix(comparisons, ("name", "invocation", "rob_entries", "prediction", "physical_registers"),
           [(name, i, 16, mode, 36) for name in names for i in (0, 1) for mode in ("off", "bimodal")])
    require(sum(r["status"] == "matched" for r in comparisons) == rename["fully_matched_invocations"] == 192
            and sum(r["status"] == "expected_profile_difference" for r in comparisons)
            == rename["expected_profile_differences"] == 8, "Wrong pressure comparison results")
    require({r["name"] for r in comparisons if r["status"] != "matched"}
            == {"unsupported_fence_i", "entry_alignment"}, "New pressure profile exclusion")
    matrix(rename["pressure_counters"], ("rob_entries", "prediction", "physical_registers"),
           [(16, mode, 36) for mode in ("off", "bimodal")])
    require(all(r["rename_stall_cycles"] > 0 for r in rename["pressure_counters"]), "No integrated exhaustion")
    r = compatibility["regressions"]
    require([r[k] for k in ("ape_rtl_invocations", "predictor_checks", "spike_matches", "explicit_profile_differences",
                           "bounded_application_invocations", "committed_legacy_invocations")]
            == [600, 4096, 576, 24, 144, 123], "Incomplete regression anchor")
    require(compatibility["ape"]["bulk_invocations"] == 42 and compatibility["ape"]["spinal_invocations"] == 18
            and compatibility["native"]["runs"] == 90 and compatibility["ppe"]["isa_oracle_invocations"] == 180
            and compatibility["ppe"]["protocol_decode_invocations"] == 44, "Incomplete real-tool/PPE anchor")
    for path in Path(__file__).parent.glob("*.py"):
        sources[str(path.relative_to(REPO))] = sha(path)
    test_command = [sys.executable, "-m", "unittest", "discover", "-s", "workloads/s03", "-p", "test_*.py", "-v"]
    tested = subprocess.run(test_command, cwd=REPO, capture_output=True, text=True, check=True, timeout=60)
    print(tested.stderr, end="")
    check_hashes(REPO, sources)
    docs = {p: sha(REPO / p) for p in (
        "hardware/spinal/spec/APE-0.3.md", "hardware/spinal/spec/APE-0.4.md", "hardware/spinal/spec/S03-PROGRESS.md",
        "hardware/spinal/spec/APE-CHECKPOINT-FORMAL.md",
        "hardware/spinal/spec/APE-0.5.md", "hardware/spinal/spec/S03-CLOSURE-PLAN.md",
        "hardware/spinal/spec/APE-RENAME-FORMAL.md", "hardware/spinal/spec/APE-SYNTHESIS-PROBE.md",
        "hardware/spinal/spec/APE-SHARED-SUBSTRATE.md", "hardware/spinal/spec/APE-EARLY-RECOVERY-PLAN.md", "hardware/spinal/APE.md",
        "hardware/spinal/spec/APE-VERIFICATION.md", "hardware/spinal/spec/APE-0.2.md",
        "hardware/spinal/spec/APE-ROADMAP.md", "hardware/spinal/README.md")}
    recovery_summary["generated_rtl_sha256"] = {k: v for k, v in recovery["evidence_sha256"].items() if k.endswith(".v")}
    return {"schema": 2, "status": "verified_increment", "issue": 4, "stage": "S03", "S03_complete": False,
            "spec_revision": "APE-0.5",
            "created_utc": datetime.now(timezone.utc).isoformat(), "claim_class": "source_bound_gate_summary",
            "source_sha256": sources, "documentation_sha256": {**compatibility["documentation_sha256"], **docs},
            "reports_sha256": {"rename": sha(rename_path), "compatibility": sha(compatibility_path), "recovery": sha(recovery_path), "formal": sha(formal_path), "execution": sha(execution_path), "lifecycle_formal": sha(lifecycle_path)},
            "collector_tests": {"status": "passed", "scope": "report shape and rejection behavior, not RTL verification",
                                "output_sha256": hashlib.sha256((tested.stdout + tested.stderr).encode()).hexdigest()},
            "early_recovery": recovery_summary,
            "registered_execution": execution_summary,
            "bounded_checkpoint_formal": formal_summary,
            "bounded_restricted_rename_formal": lifecycle_summary,
            "generic_synthesis_diagnostics": synthesis_diagnostics,
            "physical_rename": {"unit_runs": units, "pressure_counters": rename["pressure_counters"],
                                "spike_matches": 192, "explicit_profile_differences": 8,
                                "generated_rtl_sha256": {k: v for k, v in rename["evidence_sha256"].items() if k.endswith(".v")}},
            "compatibility": {"native_runs": 90, "bulk_tool_invocations": 42, "spinal_tool_invocations": 18,
                              "matched_retirements": compatibility["ape"]["matched_retirements"],
                              "matched_memory_events": compatibility["ape"]["matched_memory_events"],
                              "bulk_generated_rtl_sha256": compatibility["ape"]["generated_rtl_sha256"],
                              "ppe_invocations": 224, "regressions": r},
            "limits": ["Completed-gate summary, not a new simulation run or formal proof",
                       "Qualified registered execution with single issue/retire; no multi-issue candidate yet",
                       "A separate generic synthesis probe is diagnostic only; no technology-based clock, energy or end-to-end agent acceleration result",
                       "Issue #4 remains open against its original acceptance criteria"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rename", type=Path, default=HW / "build/ape_rename/gate.json")
    parser.add_argument("--recovery", type=Path, default=HW / "build/ape_recovery/gate.json")
    parser.add_argument("--formal", type=Path, default=HW / "build/ape_formal/validation.json")
    parser.add_argument("--execution", type=Path, default=HW / "build/ape_execution/gate.json")
    parser.add_argument("--lifecycle", type=Path, default=HW / "build/ape_rename_formal/steps16/validation.json")
    parser.add_argument("--compatibility", type=Path, default=REPO / "workloads/results/s03-pipeline-compatibility.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Preserve existing checkpoint; use a new output path")
    result = collect(args.rename, args.compatibility, args.recovery, args.formal, args.execution, args.lifecycle)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("S03 registered-execution increment verified; issue #4 remains open: " + str(args.output))


if __name__ == "__main__":
    main()
