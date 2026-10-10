"""Collector rejection tests with synthetic reports, not DUT verification."""
from copy import deepcopy
import unittest

from evidence import (RECOVERY_CONFIGS, RECOVERY_NAMES, EXECUTION_CONFIGS,
                      validate_recovery, validate_formal, validate_execution, validate_lifecycle)


def fixture():
    units = [{"physical_registers": p, "capacity": c, "cycles": 8000,
              "captures": 101, "redirects": 51, "commit_and_redirect": 11,
              "checkpoint_stalls": 1, "retirements": 501, "squashed_instructions": 101,
              "nested_redirects": 21, "register_stalls": 1}
             for p, c in ((36, 1), (36, 4), (64, 2), (64, 4))]
    report = {"status": "passed", "S03_complete": False,
              "claim_class": "actual_checkpoint_RTL_early_recovery_and_Spike_comparison",
              "source_sha256": {"fixture": "synthetic"}, "source_sha256_after": {"fixture": "synthetic"},
              "checkpoint_unit": {"status": "passed", "runs": units},
              "fully_matched_invocations": 108, "comparisons": [], "witness_suites": {},
              "same_work_cycle_diagnostics": []}
    for mode, p, c, early in RECOVERY_CONFIGS:
        rows = []
        for name in RECOVERY_NAMES:
            for i in (0, 1):
                report["comparisons"].append({"status": "matched", "name": name, "invocation": i,
                    "prediction": mode, "physical_registers": p, "checkpoint_capacity": c, "early_recovery": early})
                rows.append({"name": name, "invocation": i, "passed": True, "cycles": 20, "retired": 5,
                    "memory_requests": 1, "result": "42", "early_memory_redirects": int(early),
                    "target_issues_before_memory": int(early), "resolved_younger_squashes": int(early),
                    "commit_and_redirect": int(early), "checkpoint_stall_cycles": int(early)})
        report["witness_suites"][f"r16-{mode}-p{p}-c{c}-{'early' if early else 'retire'}-witness"] = rows
    report["same_work_cycle_diagnostics"] = [{"name": n, "invocation": i, "prediction": mode,
        "early_cycles": 20, "retirement_cycles": 20} for n in RECOVERY_NAMES for i in (0, 1) for mode in ("off", "bimodal")]
    return report


class RecoveryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.report = fixture()

    def reject(self, mutate):
        changed = deepcopy(self.report)
        mutate(changed)
        with self.assertRaises(ValueError):
            validate_recovery(changed)

    def test_complete_shape(self):
        self.assertEqual(validate_recovery(self.report)["spike_matches"], 108)

    def test_no_completion_claim(self):
        self.reject(lambda r: r.update(S03_complete=True))

    def test_stale_sources(self):
        self.reject(lambda r: r["source_sha256_after"].update(fixture="changed"))

    def test_missing_and_duplicate_configuration(self):
        self.reject(lambda r: r["comparisons"].pop())
        self.reject(lambda r: r["comparisons"].append(r["comparisons"][0]))

    def test_no_new_profile_exception(self):
        self.reject(lambda r: r["comparisons"][0].update(status="expected_profile_difference"))

    def test_early_target_witness_required(self):
        self.reject(lambda r: r["witness_suites"]["r16-off-p64-c4-early-witness"][0].update(target_issues_before_memory=0))

    def test_nested_concurrent_commit_required(self):
        self.reject(lambda r: r["witness_suites"]["r16-off-p64-c4-early-witness"][2].update(commit_and_redirect=0))

    def test_baseline_cannot_redirect_early(self):
        self.reject(lambda r: r["witness_suites"]["r16-off-p64-c4-retire-witness"][0].update(early_memory_redirects=1))

    def test_pressure_required(self):
        self.reject(lambda r: r["checkpoint_unit"]["runs"][0].update(register_stalls=0))
        self.reject(lambda r: r["witness_suites"]["r16-off-p64-c4-early-witness"][-1].update(checkpoint_stall_cycles=0))

    def test_same_work_and_cycle_identity(self):
        self.reject(lambda r: r["witness_suites"]["r16-off-p64-c4-early-witness"][0].update(retired=6))
        self.reject(lambda r: r["same_work_cycle_diagnostics"][0].update(early_cycles=19))


class FormalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.report = {"status": "passed_bounded", "S03_complete": False,
            "claim_class": "bounded_selected_checkpoint_RTL_properties", "assumptions": ["synthetic"],
            "limits": ["synthetic"], "tools": {}, "runs": [{"physical_registers": 36, "slots": 8,
                "capacity": c, "snapshot_field": 10, "bounded_global_steps": 12, "assertions": 8,
                "bounded_status": "passed", "cover_status": "passed", "covers_reached": 4 if c == 1 else 5,
                "negative_control": "counterexample_found"} for c in (1, 4)]}

    def test_bounded_shape(self):
        self.assertEqual(len(validate_formal(self.report)["runs"]), 2)

    def test_inconclusive_and_missing_checks(self):
        mutations = [lambda r: r.update(status="failed_or_inconclusive"),
            lambda r: r.update(S03_complete=True), lambda r: r.update(assumptions=[]),
            lambda r: r["runs"].pop(), lambda r: r["runs"][0].update(bounded_global_steps=8),
            lambda r: r["runs"][0].update(assertions=4), lambda r: r["runs"][0].update(covers_reached=0),
            lambda r: r["runs"][0].update(negative_control="timeout")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                changed = deepcopy(self.report)
                mutate(changed)
                with self.assertRaises(ValueError):
                    validate_formal(changed)


class ExecutionEvidenceTests(unittest.TestCase):
    def setUp(self):
        names = ["unsupported_fence_i", "entry_alignment"] + [f"synthetic{i}" for i in range(48)]
        self.report = {"status": "passed_with_profile_differences", "S03_complete": False,
            "claim_class": "actual_registered_execution_and_qualified_completion_RTL",
            "source_sha256": {"fixture": "synthetic"}, "source_sha256_after": {"fixture": "synthetic"},
            "limits": ["synthetic report-shape fixture, not hardware"],
            "transport": {"status": "passed", "cycles": 16800, "configurations": [
                {"depth": d, "generation_bits": g, "cycles": 4200, "accepted": 602, "completed": 601,
                 "canceled": 1, "input_stalls": 501, "full_cycles": 101, "clear_events": 15}
                for d, g in ((2, 1), (2, 2), (8, 1), (16, 2))]},
            "ownership": {"status": "passed", "checks": 16000, "configurations": [
                {"generation_bits": g, "checks": 8000, "qualified": 4000, "rejected": 4000, "wrap_conflicts": 501}
                for g in (1, 2)]},
            "core_suites": [{"configuration": list(c), "counters": {"late_rejected": 1, "rejected_after_slot_reuse": 1,
                "physical_reuse_while_pending": 1, "max_execution_tokens": 2, "canceled_at_stop": 1, "rename_stall_cycles": 1}}
                for c in EXECUTION_CONFIGS],
            "comparisons": [{"name": n, "invocation": i, "configuration": list(c),
                "status": "expected_profile_difference" if n in names[:2] else "matched"}
                for n in names for i in (0, 1) for c in EXECUTION_CONFIGS],
            "fully_matched_invocations": 288, "expected_profile_differences": 12}

    def reject(self, mutate):
        changed = deepcopy(self.report)
        mutate(changed)
        with self.assertRaises(ValueError): validate_execution(changed)

    def test_complete_shape(self):
        self.assertEqual(validate_execution(self.report)["spike_matches"], 288)

    def test_incomplete_or_stale(self):
        self.reject(lambda r: r.update(status="running"))
        self.reject(lambda r: r.update(S03_complete=True))
        self.reject(lambda r: r["source_sha256_after"].update(fixture="changed"))

    def test_transport_and_wrap(self):
        self.reject(lambda r: r["transport"]["configurations"][0].update(accepted=603))
        self.reject(lambda r: r["transport"]["configurations"][0].update(input_stalls=0))
        self.reject(lambda r: r["transport"]["configurations"].pop())
        self.reject(lambda r: r["ownership"]["configurations"][0].update(wrap_conflicts=0))

    def test_integrated_reuse_and_pressure(self):
        self.reject(lambda r: r["core_suites"][0]["counters"].update(late_rejected=0))
        self.reject(lambda r: r["core_suites"][1]["counters"].update(rejected_after_slot_reuse=0))
        self.reject(lambda r: r["core_suites"][2]["counters"].update(rename_stall_cycles=0))
        self.reject(lambda r: r["core_suites"].append(r["core_suites"][0]))

    def test_independent_comparisons(self):
        self.reject(lambda r: r["comparisons"].pop())
        self.reject(lambda r: r["comparisons"].append(r["comparisons"][0]))
        self.reject(lambda r: r["comparisons"][0].update(name="invented_profile_exception"))
        self.reject(lambda r: r["comparisons"][0].update(status="matched"))


class LifecycleEvidenceTests(unittest.TestCase):
    def test_scope_and_required_checks(self):
        report = {"status": "passed_bounded", "S03_complete": False,
            "claim_class": "bounded_restricted_rename_lifecycle_RTL_properties",
            "bounded_global_steps": 16, "assertions": 24, "bounded_status": "passed", "covers_reached": 6,
            "negative_control": "counterexample_found", "assumptions": ["synthetic"], "limits": ["synthetic"],
            "tools": {"fixture": "synthetic"}}
        self.assertEqual(validate_lifecycle(report)["covers_reached"], 6)
        for key, value in (("status", "running"), ("S03_complete", True), ("bounded_global_steps", 12),
                           ("assertions", 23), ("bounded_status", "timeout"), ("covers_reached", 5),
                           ("negative_control", "timeout"), ("assumptions", []), ("tools", {})):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_lifecycle({**report, key: value})


if __name__ == "__main__":
    unittest.main()
