import copy
import json
from pathlib import Path
import unittest
import s01_gate as gate


class GateTests(unittest.TestCase):
    def setUp(self):
        self.p = json.loads((Path(__file__).resolve().parent / "evidence/S01-DEMAND-PROFILE.json").read_text())

    def test_profile_gate(self):
        self.assertEqual(gate.validate_demand(self.p)["native_demand_runs"], 90)

    def test_reject_incomplete_or_mislabeled_evidence(self):
        for modify in (lambda p: p["runs"].pop(), lambda p: p.update(hats_execution=True),
                       lambda p: p["runs"].__setitem__(0, p["runs"][1]),
                       lambda p: p["workflow"]["accounting"]["phase_ns"].update(inference=1),
                       lambda p: p["workflow"]["outcomes"][0]["checks"].pop(),
                       lambda p: p["workflow"]["outcomes"][-1].update(compile_exit=0)):
            p = copy.deepcopy(self.p); modify(p)
            with self.assertRaises(ValueError): gate.validate_demand(p)

    def test_reject_stale_or_escaping_source(self):
        with self.assertRaises(ValueError): gate.hashes_match({"suite.py": "0" * 64})
        with self.assertRaises(ValueError): gate.hashes_match({"../README.md": "0" * 64})


if __name__ == "__main__": unittest.main()
