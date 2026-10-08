"""Checker sensitivity tests, not RTL fault-injection or ISA conformance tests."""
import copy
import unittest
from compare_ape_spike import Divergence, compare, unique_object


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.good = [
            {"kind": "retire", "pc": "0", "instruction": 0x02a00513, "writes": True, "rd": 10, "value": "42", "next": "4"},
            {"kind": "memory", "address": "65536", "bytes": 8, "write": True, "data": "42", "error": False},
            {"kind": "trap", "pc": "4", "cause": 3, "value": "42"}]

    def test_matching(self):
        self.assertEqual(compare(self.good, copy.deepcopy(self.good))["status"], "matched")

    def test_mutations(self):
        changes = [(0, "pc", "8"), (0, "next", "12"), (0, "instruction", 0x02900513),
                   (0, "rd", 9), (0, "value", "41"), (0, "writes", False),
                   (1, "address", "65544"), (1, "bytes", 4), (1, "write", False),
                   (1, "data", "41"), (1, "error", True), (2, "pc", "8"),
                   (2, "cause", 2), (2, "value", "41")]
        for i, name, value in changes:
            with self.subTest(i=i, field=name):
                bad = copy.deepcopy(self.good)
                bad[i][name] = value
                with self.assertRaises(Divergence):
                    compare(bad, self.good)

    def test_missing_duplicate_reordered_events(self):
        variants = [self.good[1:], self.good[:-1], [], self.good[:1] + self.good,
                    [self.good[1], self.good[0], self.good[2]], self.good + self.good[-1:]]
        for bad in variants:
            with self.subTest(bad=bad):
                with self.assertRaises(Divergence):
                    compare(bad, self.good)

    def test_schema_rejection(self):
        for field, value in [("writes", 1), ("pc", 0), ("pc", "00"), ("pc", str(2**64)), ("unexpected", 0)]:
            bad = copy.deepcopy(self.good)
            bad[0][field] = value
            with self.assertRaises(Divergence):
                compare(bad, bad)
        with self.assertRaises(Divergence):
            unique_object([("kind", "retire"), ("kind", "trap")])

    def test_fence_boundary_is_exact(self):
        rtl = [self.good[0], {"kind": "trap", "pc": "4", "cause": 2, "value": "42"}]
        spike = [self.good[0], {"kind": "retire", "pc": "4", "instruction": 0x100f, "writes": False,
                               "rd": 0, "value": "0", "next": "8"},
                 {"kind": "trap", "pc": "8", "cause": 3, "value": "42"}]
        self.assertEqual(compare(rtl, spike, "fence_i_gap")["status"], "expected_profile_difference")
        with self.assertRaises(Divergence):
            compare(rtl, spike)
        for side in ("rtl", "spike"):
            a, b = copy.deepcopy(rtl), copy.deepcopy(spike)
            (a if side == "rtl" else b)[0]["value"] = "41"
            with self.assertRaises(Divergence):
                compare(a, b, "fence_i_gap")
        with self.assertRaises(Divergence):
            compare(self.good, self.good, "fence_i_gap")

    def test_launch_boundary_is_exact(self):
        a = [{"kind": "trap", "pc": "2", "cause": 0, "value": "0"}]
        b = [{"kind": "trap", "pc": "0", "cause": 2, "value": "0"}]
        self.assertEqual(compare(a, b, "launch_alignment_gap")["status"], "expected_profile_difference")
        a[0]["value"] = "1"
        with self.assertRaises(Divergence):
            compare(a, b, "launch_alignment_gap")

    def test_unknown_profile(self):
        with self.assertRaises(Divergence):
            compare(self.good, self.good, "ignore")


if __name__ == "__main__":
    unittest.main()
