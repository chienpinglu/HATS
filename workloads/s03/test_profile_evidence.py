"""Synthetic acceptance/rejection tests; no hardware execution claim."""
import copy
import unittest
from unittest.mock import patch
from pathlib import Path

from profile_evidence import validate_profile
from evidence import RECOVERY_NAMES
from verify_profile import verify_resume, bulk, POINT


def fixture():
    standard = ["unsupported_fence_i", "entry_alignment"] + [f"standard_{n}" for n in range(48)]
    recovery = list(RECOVERY_NAMES)
    cases = [{"mode": "parser", "case": f"input_{n}", "digest": {"retirements": 100, "memory_events": 20, "sha256": str(n)}} for n in range(42)]
    rows = [{**copy.deepcopy(row), "metrics": {"retired": 100, "requests": 20, "cycles": 200,
            "response_base": 2, "service_seed": 0x48415453, "dual_issue_cycles": 0}} for row in cases]
    suites, comparisons = {}, []
    for kind, names in (("standard", standard), ("recovery", recovery)):
        suites[kind] = {"status": "passed", "rob_entries": 8, "physical_registers": 48, "issue_width": 1,
                        "prediction": "bimodal", "checkpoint_capacity": 4, "execution_stages": 2, "generation_bits": 2,
                        "early_recovery": True, "recovery_suite": kind == "recovery", "runs": len(names) * 2,
                        "results": [{"name": n, "invocation": i, "passed": True,
                                     "early_memory_redirects": 1, "target_issues_before_memory": 1,
                                     "resolved_younger_squashes": 1, "commit_and_redirect": 1,
                                     "checkpoint_stall_cycles": 1} for n in names for i in (0, 1)]}
        comparisons += [{"suite": kind, "name": n, "invocation": i,
                         "status": "expected_profile_difference" if n in standard[:2] else "matched"} for n in names for i in (0, 1)]
    return {"status": "passed_with_profile_differences", "claim_class": "actual_selected_profile_full_tool_and_independent_ISA_RTL",
            "point": ["prf48", 8, 48, 1, "bimodal", 16],
            "service": {"response_base": 2, "seed": 0x48415453, "kind": "transaction_ordinal"},
            "tool_runs": rows, "isa_suites": suites, "comparisons": comparisons,
            "exact_isa_matches": 108, "unchanged_profile_differences": 4, "limits": ["synthetic shape test"]}, cases, standard, recovery


class ProfileEvidenceTests(unittest.TestCase):
    def test_complete_shape(self):
        self.assertEqual(validate_profile(*fixture())["full_tool_invocations"], 42)

    def reject(self, mutate):
        report, cases, standard, recovery = fixture()
        mutate(report)
        with self.assertRaises((RuntimeError, ValueError)):
            validate_profile(report, cases, standard, recovery)

    def test_partial_wrong_config_and_inputs(self):
        self.reject(lambda r: r.update(status="running"))
        self.reject(lambda r: r["point"].__setitem__(2, 64))
        self.reject(lambda r: r["tool_runs"].pop())
        self.reject(lambda r: r["tool_runs"][0]["digest"].update(sha256="different"))
        self.reject(lambda r: r["service"].update(kind="cycle_random"))

    def test_isa_gaps_and_multiplicity(self):
        self.reject(lambda r: r["isa_suites"]["standard"].update(physical_registers=64))
        self.reject(lambda r: r["isa_suites"]["recovery"]["results"].pop())
        self.reject(lambda r: r["comparisons"].append(copy.deepcopy(r["comparisons"][0])))
        self.reject(lambda r: r["comparisons"][-1].update(status="expected_profile_difference"))
        self.reject(lambda r: r.update(exact_isa_matches=107))

    def test_recovery_witnesses_remain_required(self):
        for name, counter in (("older_load", "target_issues_before_memory"),
                              ("nested_checkpoints", "resolved_younger_squashes"),
                              ("nested_checkpoints", "commit_and_redirect"),
                              ("older_bus_fault", "early_memory_redirects"),
                              ("checkpoint_exhaustion", "checkpoint_stall_cycles")):
            self.reject(lambda r: next(x for x in r["isa_suites"]["recovery"]["results"] if x["name"] == name).__setitem__(counter, 0))


class ResumeTests(unittest.TestCase):
    def test_only_driver_may_change_with_exact_snapshot(self):
        driver = "workloads/s03/verify_profile.py"
        sources = {driver: "new-driver", "rtl": "same-rtl"}
        previous = {"point": POINT, "status": "failed", "source_sha256": {driver: "old-driver", "rtl": "same-rtl"},
                    "inputs_sha256": {"reference": "same-input"}, "generated_sha256": {"executable": "same-executable"},
                    "tool_runs": [{"mode": c[0], "case": c[1]} for c in bulk.cases()]}
        def check(r=previous, s=sources):
            return verify_resume(r, s, {"reference": "same-input"}, {"executable": "same-executable"}, Path("snapshot"))
        with patch("verify_profile.sha", return_value="old-driver"), patch("verify_profile.check_hashes"):
            self.assertEqual(len(check()), 42)
            for mutate in (lambda r: r.update(status="running"), lambda r: r["tool_runs"].pop(),
                           lambda r: r["generated_sha256"].update(executable="different"),
                           lambda r: r["source_sha256"].update(rtl="different"),
                           lambda r: r["source_sha256"].update({driver: "different"})):
                r = copy.deepcopy(previous); mutate(r)
                with self.assertRaises((RuntimeError, ValueError)): check(r)
            with self.assertRaises((RuntimeError, ValueError)): check(s={driver: "new-driver"})


if __name__ == "__main__":
    unittest.main()
