"""Synthetic semantic gate rejection tests; no new hardware evidence."""
import unittest

from closure_evidence import validate_semantic, validate_review


def semantic_fixture():
    runs = []
    for entries, zero, argument, physical in ((16, 7, 3, 24), (32, 31, 2, 40)):
        runs.append({"architectural_registers": entries, "zero_slot": zero, "argument_slot": argument,
                     "physical_registers": physical, "cycles": 6000, "writable_zero_allocations": 1,
                     "resource_stalls": 1, "recoveries": 101, "retirements": 501, "relaunches": 7,
                     "out_of_order_writebacks": 101, "commit_and_recovery": 1})
    return {"status": "passed", "claim_class": "actual_shared_semantic_and_RV64_profile_RTL",
            "source_sha256": {"source": "synthetic"}, "source_sha256_after": {"source": "synthetic"},
            "execution": {"status": "passed", "semantic_vectors": 4953, "different_sign_zero_results": 101,
                          "alternate_target_vectors": 72, "fault_vectors": 101},
            "profile": {"status": "passed", "checks": 135},
            "layouts": {"status": "passed", "runs": runs},
            "predictor": {"status": "passed", "checks": 1024, "index_shifts": [1, 3]}, "limits": ["synthetic test only"]}


class SemanticEvidenceTests(unittest.TestCase):
    def test_complete_shape(self):
        self.assertEqual(validate_semantic(semantic_fixture())["execution"]["semantic_vectors"], 4953)

    def test_policy_and_ownership_gaps(self):
        changes = [lambda r: r["layouts"]["runs"][0].update(zero_slot=0),
                   lambda r: r["layouts"]["runs"][0].update(writable_zero_allocations=0),
                   lambda r: r["layouts"]["runs"][0].update(commit_and_recovery=0),
                   lambda r: r["layouts"]["runs"].pop(),
                   lambda r: r["execution"].update(different_sign_zero_results=0),
                   lambda r: r["profile"].update(checks=134),
                   lambda r: r["predictor"].update(index_shifts=[2, 2]),
                   lambda r: r["source_sha256_after"].update(source="changed")]
        for change in changes:
            report = semantic_fixture(); change(report)
            with self.assertRaises((ValueError, RuntimeError)):
                validate_semantic(report)


class ReviewTests(unittest.TestCase):
    def test_original_items_and_explicit_acceptance(self):
        text = "Status: accepted against the original S03 criteria.\n" + "\n".join(
            "| " + item + ": test | synthetic fixture |" for item in
            [*(f"WP{i}" for i in range(1, 7)), *(f"AC{i}" for i in range(1, 6))])
        validate_review(text)
        for changed in (text.replace("accepted against the original S03 criteria", "pending final acceptance"),
                        text.replace("| WP4:", "| Missing:"), text + "\n| AC3: duplicate |"):
            with self.assertRaises((RuntimeError, ValueError)):
                validate_review(changed)


if __name__ == "__main__":
    unittest.main()
