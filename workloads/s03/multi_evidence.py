#!/usr/bin/env python3
"""Preserve the multi-issue correctness and controlled smoke evidence, not S03 closure."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware/spinal"
sys.path.insert(0, str(REPO / "workloads/s02"))
from checkpoint import check_hashes, matrix, require, sha

CONFIGS = [(8, "bimodal", 64, 4, 2, 2, w, "standard") for w in (1, 2)]
CONFIGS += [(16, "bimodal", 36, 4, 2, 1, 2, "standard"), (8, "bimodal", 64, 4, 8, 1, 2, "standard")]
CONFIGS += [(16, m, p, c, 2, 1, 2, "recovery") for m in ("off", "bimodal") for p, c in ((64, 1), (64, 4), (36, 4))]
RECOVERY_NAMES = ("older_load", "nested_checkpoints", "jalr_link", "older_bus_fault", "faulting_link", "checkpoint_exhaustion")


def validate_multi(multi):
    require(multi["status"] == "passed_with_profile_differences" and multi["S03_complete"] is False
            and multi["claim_class"] == "actual_multi_issue_RTL_and_independent_ISA_comparison", "Missing multi-issue RTL gate")
    require(multi["source_sha256"] == multi["source_sha256_after"], "Multi-issue sources changed")
    require(multi["fully_matched_invocations"] == 456 and multi["expected_profile_differences"] == 16,
            "Incomplete multi-issue independent comparison")
    require(len(multi["comparisons"]) == 472 and sum(r["status"] == "matched" for r in multi["comparisons"]) == 456,
            "Wrong comparison multiplicity")
    require({r["name"] for r in multi["comparisons"] if r["status"] != "matched"}
            == {"unsupported_fence_i", "entry_alignment"}, "New architectural exclusion")
    require(len(multi["core_suites"]) == 10 and multi["scheduler"]["status"] == "passed", "Incomplete scheduler/core evidence")
    suites = [{**r, "configuration": tuple(r["configuration"])} for r in multi["core_suites"]]
    matrix(suites, ("configuration",), [(cfg,) for cfg in CONFIGS])
    for row in suites:
        cfg, counters = row["configuration"], row["counters"]
        if cfg[6] == 2:
            require(counters["dual_issue_cycles"] > 0 and counters["completion_stall_cycles"] > 0, "Missing wider execution witness")
        if cfg[2] == 36:
            require(counters["rename_stall_cycles"] > 0, "Missing PRF pressure")
        if cfg[4] > 2:
            require(counters["rejected_after_slot_reuse"] > 0, "Missing generation/reuse witness")
        if cfg[7] == "recovery" and cfg[3] >= 2:
            require(counters["commit_and_redirect"] > 0 and counters["resolved_younger_squashes"] > 0, "Missing nested recovery timing")
    comparisons = [{**r, "configuration": tuple(r["configuration"])} for r in multi["comparisons"]]
    standard_names = {r["name"] for r in comparisons if r["configuration"][-1] == "standard"}
    require(len(standard_names) == 50, "Wrong standard scenario count")
    matrix(comparisons, ("configuration", "name", "invocation"),
           [(cfg, name, i) for cfg in CONFIGS for name in (RECOVERY_NAMES if cfg[-1] == "recovery" else standard_names) for i in (0, 1)])
    for row in comparisons:
        difference = row["configuration"][-1] == "standard" and row["name"] in ("entry_alignment", "unsupported_fence_i")
        require(row["status"] == ("expected_profile_difference" if difference else "matched"), "Unexpected profile classification")
    return {"scheduler": multi["scheduler"], "core_suites": multi["core_suites"],
            "spike_matches": 456, "unchanged_profile_differences": 16}


def validate(multi, study):
    validate_multi(multi)
    require(study["status"] == "passed" and study["S03_complete"] is False
            and study["claim_class"] == "actual_APE_RTL_matched_work_controlled_abstract_service",
            "Missing controlled RTL comparison")
    require(study["full_design_matrix"] is False, "This collector preserves the smoke checkpoint only")
    require(study["points"] == [["narrow", 8, 64, 1, "bimodal", 16], ["dual", 8, 64, 2, "bimodal", 16]], "Wrong width pair")
    require(study["service"]["response_bases"] == [2] and study["service"]["seed"] == 0x48415453,
            "Wrong controlled service")
    rows = study["results"]
    cases = [("helpers", "integer-vectors"), ("runtime", "runtime-tests"),
             ("parser", "empty-incremental"), ("parser", "scalars-incremental")]
    matrix(rows, ("point", "workload", "case", "response_base"),
           [(p, w, c, 2) for p in ("narrow", "dual") for w, c in cases])
    comparisons = []
    for workload, case in cases:
        a, b = [next(r for r in rows if (r["point"], r["workload"], r["case"]) == (p, workload, case))
                for p in ("narrow", "dual")]
        require(a["digest"] == b["digest"], "Different architectural work")
        for field in ("retired", "requests", "service_seed", "response_base", "acceptance_wait_sum", "response_wait_sum"):
            require(a["metrics"][field] == b["metrics"][field], "Different work/service: " + field)
        require(a["metrics"]["dual_issue_cycles"] == 0 and b["metrics"]["dual_issue_cycles"] > 0,
                "Missing baseline or actual simultaneous issue")
        require(a["metrics"]["cycles"] > 0 and b["metrics"]["cycles"] > 0, "Invalid cycle count")
        ratio = a["metrics"]["cycles"] / b["metrics"]["cycles"]
        require(b["baseline_cycles_over_candidate_cycles"] == ratio, "Stale cycle ratio")
        comparisons.append({"workload": workload, "case": case, "narrow_cycles": a["metrics"]["cycles"],
                            "dual_cycles": b["metrics"]["cycles"], "retired": a["metrics"]["retired"],
                            "dual_issue_cycles": b["metrics"]["dual_issue_cycles"], "baseline_over_candidate_cycles": ratio})
    return comparisons


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--multi", type=Path, default=HW / "build/ape_multi/gate.json")
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Preserve checkpoints; choose a new output")
    multi, study = [json.loads(p.read_text()) for p in (args.multi, args.study)]
    comparisons = validate(multi, study)
    check_hashes(HW, multi["source_sha256"]); check_hashes(HW, multi["evidence_sha256"])
    check_hashes(REPO, study["source_sha256"])
    for hashes in [*study["generated"].values(), *(r["artifacts_sha256"] for r in study["results"])]:
        check_hashes(REPO, hashes)
    # The target builder validates all program/reference artifacts at gate end.
    # Bind its existing source and artifact maps again without rerunning the tool.
    target = study["target_build"]
    check_hashes(REPO, target["source_sha256"])
    check_hashes(args.study.parent.parent, target["artifacts_sha256"])
    sources = dict(study["source_sha256"])
    for name, digest in multi["source_sha256"].items():
        key = "hardware/spinal/" + name
        require(key not in sources or sources[key] == digest, "Mixed core revisions")
        sources[key] = digest
    for name, digest in target["source_sha256"].items():
        require(name not in sources or sources[name] == digest, "Mixed workload revisions")
        sources[name] = digest
    for p in (Path(__file__), Path(__file__).with_name("test_multi_evidence.py")):
        sources[str(p.relative_to(REPO))] = sha(p)
    docs = ["hardware/spinal/spec/APE-0.6.md", "hardware/spinal/spec/S03-PROGRESS.md", "hardware/spinal/spec/S03-CLOSURE-PLAN.md"]
    summary = {"schema": 1, "status": "verified_increment", "issue": 4, "S03_complete": False,
               "spec_revision": "APE-0.6", "claim_class": "source_bound_multi_issue_and_controlled_smoke_summary",
               "created_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": sources,
               "documentation_sha256": {p: sha(REPO / p) for p in docs},
               "reports_sha256": {"multi": sha(args.multi), "controlled_smoke": sha(args.study)},
               "scheduler": multi["scheduler"], "core_suites": multi["core_suites"],
               "spike_matches": 456, "unchanged_profile_differences": 16, "controlled_smoke": comparisons,
               "limits": ["Focused correctness plus eight real-tool runs, not full current-source compatibility",
                          "Only a smoke comparison; full PRF/ROB/predictor/service design matrix remains required",
                          "Dual issue did not improve simulated cycles in this smoke; no clock or energy claim",
                          "Remaining semantic policy, synthesis/timing/design-point and final integration requirements keep #4 open"]}
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print("Preserved focused multi-issue/smoke evidence; issue #4 remains open: " + str(args.output))


if __name__ == "__main__":
    main()
