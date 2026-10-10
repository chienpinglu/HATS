"""Synthetic report-shape/rejection tests only; never RTL verification evidence."""
import copy
import unittest
from multi_evidence import CONFIGS, RECOVERY_NAMES, validate


def fixtures():
    names = [f"case{i}" for i in range(48)] + ["entry_alignment", "unsupported_fence_i"]
    comparisons = [{"configuration": list(c), "name": name, "invocation": i,
                    "status": "expected_profile_difference" if c[-1] == "standard" and name in names[-2:] else "matched"}
                   for c in CONFIGS for name in (RECOVERY_NAMES if c[-1] == "recovery" else names) for i in (0, 1)]
    counters = dict.fromkeys(("dual_issue_cycles", "completion_stall_cycles", "rename_stall_cycles", "rejected_after_slot_reuse",
                             "commit_and_redirect", "resolved_younger_squashes"), 1)
    multi = {"status": "passed_with_profile_differences", "S03_complete": False,
             "claim_class": "actual_multi_issue_RTL_and_independent_ISA_comparison",
             "source_sha256": {"source": "hash"}, "source_sha256_after": {"source": "hash"},
             "fully_matched_invocations": 456, "expected_profile_differences": 16, "comparisons": comparisons,
             "core_suites": [{"configuration": list(c), "counters": dict(counters)} for c in CONFIGS], "scheduler": {"status": "passed"}}
    rows = []
    for point in ("narrow", "dual"):
        for workload, name in (("helpers", "integer-vectors"), ("runtime", "runtime-tests"),
                               ("parser", "empty-incremental"), ("parser", "scalars-incremental")):
            metrics = dict.fromkeys(("retired", "requests", "acceptance_wait_sum", "response_wait_sum"), 10)
            metrics.update(cycles=100 if point == "narrow" else 125, response_base=2, service_seed=0x48415453,
                           dual_issue_cycles=int(point == "dual"))
            rows.append({"point": point, "workload": workload, "case": name, "response_base": 2,
                         "metrics": metrics, "digest": {"sha256": "same"}, "baseline_cycles_over_candidate_cycles": 1 if point == "narrow" else 0.8})
    study = {"status": "passed", "S03_complete": False, "claim_class": "actual_APE_RTL_matched_work_controlled_abstract_service",
             "full_design_matrix": False, "points": [["narrow", 8, 64, 1, "bimodal", 16], ["dual", 8, 64, 2, "bimodal", 16]],
             "service": {"response_bases": [2], "seed": 0x48415453}, "results": rows}
    return multi, study


class MultiEvidenceTests(unittest.TestCase):
    def test_complete_shape_and_slowdown(self):
        rows = validate(*fixtures())
        self.assertEqual(len(rows), 4)
        self.assertTrue(all(r["baseline_over_candidate_cycles"] == 0.8 for r in rows))

    def test_missing_duplicate_and_profile_mutation(self):
        for mode in ("missing", "duplicate", "profile", "stale", "pressure", "reuse", "recovery"):
            m, s = fixtures()
            if mode == "missing": m["comparisons"].pop()
            if mode == "duplicate": m["comparisons"][1] = copy.deepcopy(m["comparisons"][0])
            if mode == "profile": m["comparisons"][0]["status"] = "expected_profile_difference"
            if mode == "stale": m["source_sha256_after"]["source"] = "changed"
            if mode == "pressure": m["core_suites"][2]["counters"]["rename_stall_cycles"] = 0
            if mode == "reuse": m["core_suites"][3]["counters"]["rejected_after_slot_reuse"] = 0
            if mode == "recovery": m["core_suites"][5]["counters"]["commit_and_redirect"] = 0
            with self.subTest(mode=mode), self.assertRaises((RuntimeError, ValueError)):
                validate(m, s)

    def test_same_work_service_and_cycle_fidelity(self):
        for mode in ("work", "service", "ratio", "dual", "missing", "full", "closure"):
            m, s = fixtures()
            if mode == "work": s["results"][-1]["digest"]["sha256"] = "changed"
            if mode == "service": s["results"][-1]["metrics"]["response_wait_sum"] += 1
            if mode == "ratio": s["results"][-1]["baseline_cycles_over_candidate_cycles"] = 2
            if mode == "dual": s["results"][-1]["metrics"]["dual_issue_cycles"] = 0
            if mode == "missing": s["results"].pop()
            if mode == "full": s["full_design_matrix"] = True
            if mode == "closure": s["S03_complete"] = True
            with self.subTest(mode=mode), self.assertRaises((RuntimeError, ValueError)):
                validate(m, s)


if __name__ == "__main__":
    unittest.main()
