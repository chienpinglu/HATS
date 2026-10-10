#!/usr/bin/env python3
"""Fail-closed shape/arithmetic checks for the full S03 design-point evidence.

These checks do not execute RTL or manufacture a performance result. File/source
revalidation belongs to the final collector in addition to these shape checks.
"""
import math
import re

from compare import POINTS, SERVICE_BASES, SERVICE_SEED
from multi_evidence import matrix, require

CASES = [("helpers", "integer-vectors"), ("runtime", "runtime-tests"),
         ("parser", "empty-incremental"), ("parser", "unicode-incremental"),
         ("parser", "repository_lock-incremental"), ("parser", "records_256-incremental")]
FIXED = {"program_words": 65536, "checkpoints": 4, "dispatch_width": 1, "retire_width": 1,
         "writeback_width": 1, "execution_stages": 2, "generation_bits": 2, "outstanding_memory": 1}


def validate_study(study):
    require(study["status"] == "passed" and study["full_design_matrix"] is True
            and study["claim_class"] == "actual_APE_RTL_matched_work_controlled_abstract_service",
            "A complete actual-RTL controlled design study is required")
    require(study["points"] == [list(p) for p in POINTS] and study["fixed"] == FIXED, "Wrong design configurations")
    require(study["service"]["response_bases"] == list(SERVICE_BASES) and study["service"]["seed"] == SERVICE_SEED
            and study["service"]["acceptance_jitter"] == [0, 3] and study["service"]["response_jitter"] == [0, 7],
            "Wrong realized-memory-service contract")
    rows = study["results"]
    matrix(rows, ("point", "response_base", "workload", "case"),
           [(p[0], b, w, c) for p in POINTS for b in SERVICE_BASES for w, c in CASES])
    baseline = {(r["response_base"], r["workload"], r["case"]): r for r in rows if r["point"] == "narrow"}
    grouped = {p[0]: [] for p in POINTS}
    for row in rows:
        ref = baseline[row["response_base"], row["workload"], row["case"]]
        m, b, digest = row["metrics"], ref["metrics"], row["digest"]
        require(digest == ref["digest"], "Designs did not execute the same architectural work")
        require(digest["encoding"] == "hats-architectural-state-le64-v1" and digest["schema"] == 1
                and digest["events"] == digest["retirements"] + digest["memory_events"] + 1
                and re.fullmatch(r"[0-9a-f]{64}", digest["sha256"]),
                "Incomplete architectural digest")
        for field in ("retired", "requests", "service_seed", "response_base", "acceptance_wait_sum", "response_wait_sum"):
            require(m[field] == b[field], "Different realized work/service: " + field)
        require(m["retired"] == digest["retirements"] > 0 and m["requests"] == digest["memory_events"] > 0
                and m["cycles"] > 0, "Invalid execution counts")
        require(m["response_base"] == row["response_base"] and m["service_seed"] == SERVICE_SEED, "Counter service mismatch")
        require(0 <= m["acceptance_wait_sum"] <= 3 * m["requests"]
                and row["response_base"] * m["requests"] <= m["response_wait_sum"] <= (row["response_base"] + 7) * m["requests"],
                "Impossible realized service")
        require(row["simulated_ipc"] == m["retired"] / m["cycles"]
                and row["baseline_cycles_over_candidate_cycles"] == b["cycles"] / m["cycles"], "Derived metric changed")
        require(m["dual_issue_cycles"] > 0 if row["point"] == "dual" else m["dual_issue_cycles"] == 0,
                "Incorrect or unexercised issue width")
        point = next(p for p in POINTS if p[0] == row["point"])
        rob, prf, width = point[1:4]
        counters = ("cycles", "retired", "requests", "issued_operations", "dual_issue_cycles",
                    "execution_stall_cycles", "completion_stall_cycles", "rename_stall_cycles",
                    "checkpoint_stall_cycles", "rob_stall_cycles", "ready_sum", "occupancy_sum",
                    "peak_occupancy", "minimum_free_registers", "branches", "branch_misses",
                    "redirects", "late_rejected")
        require(all(type(m[k]) is int and m[k] >= 0 for k in counters), "Non-integral or negative RTL counter")
        require(m["retired"] <= m["cycles"] and m["retired"] <= m["issued_operations"] <= width * m["cycles"]
                and m["dual_issue_cycles"] <= m["cycles"], "Impossible issue/retirement count")
        require(all(m[k] <= m["cycles"] for k in counters if k.endswith("stall_cycles")), "Impossible stall count")
        require(0 < m["peak_occupancy"] <= rob and m["minimum_free_registers"] <= prf
                and m["ready_sum"] <= rob * m["cycles"] and m["occupancy_sum"] <= rob * m["cycles"],
                "Impossible resource utilization")
        require(m["branch_misses"] <= m["branches"] <= m["retired"], "Impossible retired-branch count")
        grouped[row["point"]].append(row)
    summaries = []
    for point in POINTS:
        measured = grouped[point[0]]
        ratios = [r["baseline_cycles_over_candidate_cycles"] for r in measured]
        summaries.append({"point": list(point), "runs": len(measured),
                          "baseline_over_candidate_cycles_range": [min(ratios), max(ratios)],
                          "equal_case_geometric_mean_cycle_ratio": math.exp(sum(math.log(v) for v in ratios) / len(ratios)),
                          "cycles": sum(r["metrics"]["cycles"] for r in measured),
                          "retired": sum(r["metrics"]["retired"] for r in measured),
                          "dual_issue_cycles": sum(r["metrics"]["dual_issue_cycles"] for r in measured)})
    return summaries


def validate_technology(reports):
    rows = []
    reference_constraints = None
    for report in reports:
        require(report["status"] == "passed_early_estimate"
                and report["claim_class"] == "early_Liberty_mapped_area_and_combinational_boundary_delay",
                "Missing mapped early-timing evidence")
        require(report["fixed"] == {"program_words": 1024, "checkpoints": 4, "execution_stages": 2,
                "generation_bits": 2, "dispatch_width": 1, "writeback_width": 1, "retire_width": 1}, "Inconsistent physical scope")
        c = report["constraints"]
        require(c["mapping_delay_target_ps"] == 1000 and c["boundary_driver"] == "BUF_X1"
                and c["boundary_load_fF"] == 5 and c["clock_constraints"] is None, "Physical constraints changed")
        if reference_constraints is None:
            reference_constraints = c
        require(c == reference_constraints, "Technology comparisons use different constraints")
        require(report["limits"] and report["tool_manifest"]["status"] == "built", "Physical scope/tool lock absent")
        require(report["proof_controls"]["positive"] == "equivalent" and report["proof_controls"]["negative"] == "not_equivalent",
                "Missing equivalence-path controls")
        require(report["points"] == [r["point"] for r in report["results"]], "Incomplete requested physical matrix")
        rows += report["results"]
    matrix([{"point": tuple(r["point"])} for r in rows], ("point",), [(p,) for p in POINTS])
    for row in rows:
        d = row["statistics"]["design"]
        require(row["comb_equivalence"] == "passed" and row["comb_boundary_delay_ps"] > 0, "Missing mapped logic proof/delay")
        i = row["comb_interface"]
        require(i["inputs"] > 0 and i["outputs"] > 0 and i["latches"] == 0
                and i["identical_ordered_names"] is True and i["abstracted_internal_logic"] is False,
                "Unaligned or abstracted equivalence interface")
        require(row["meets_comb_mapping_target"] == (row["comb_boundary_delay_ps"] <= 1000), "Misclassified mapping target")
        require(d["area"] == row["mapped_area_library_units"] > 0
                and d["sequential_area"] == row["sequential_area_library_units"] > 0
                and d["num_cells"] == row["mapped_cells"] > 0 and d["num_memories"] == 0,
                "Physical statistics missing or inconsistent")
        require(not any(n.startswith("$") and n != "$scopeinfo" for n in d["num_cells_by_type"]), "Unmapped cells")
    return [{k: row[k] for k in ("point", "mapped_area_library_units", "sequential_area_library_units", "mapped_cells",
                                 "comb_boundary_delay_ps", "meets_comb_mapping_target", "comb_equivalence")} for row in rows]
