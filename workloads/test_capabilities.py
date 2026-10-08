"""Prevent S01's map from silently losing cases or claiming host runs as HATS."""
import hashlib
import json
from pathlib import Path
import unittest
import suite

ROOT = Path(__file__).resolve().parent


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "capabilities.json").read_text())

    def test_all_cases_and_sources(self):
        cases = self.data["cases"]
        self.assertEqual(len(cases), len(suite.cases()))
        self.assertEqual({c["id"] for c in cases}, set(suite.cases()))
        self.assertEqual({c["source"] for c in cases}, {s["id"] for s in suite.manifest()["sources"]})
        self.assertEqual(self.data["component_source_lock_sha256"], hashlib.sha256(suite.LOCK.read_bytes()).hexdigest())

    def test_engine_and_host_responsibilities(self):
        for case in self.data["cases"]:
            self.assertEqual(case["source"], suite.cases()[case["id"]]["source"])
            p = self.data["profiles"][case["profile"]]
            for key in ("ape", "ppe", "cp", "memory", "host_services"):
                self.assertTrue(p[key].strip(), (case["id"], key))
            self.assertEqual(case["measured_backend"], "host")
            self.assertFalse(case["hats_execution"])
            self.assertFalse(case["full_agent_experiment"])

    def test_native_tool_is_separate_and_pinned(self):
        native = self.data["native_tool"]
        lock = json.loads((ROOT / native["source_lock"]).read_text())
        cases = json.loads((ROOT / native["case_lock"]).read_text())
        self.assertEqual(len(lock["sources"]), 2)
        self.assertEqual(len(cases["cases"]), 10)
        self.assertFalse(native["hats_execution"])
        for c in cases["cases"]:
            for field in ("old_sha256", "new_sha256", "old_expected_sha256", "new_expected_sha256"):
                self.assertRegex(c[field], r"^[0-9a-f]{64}$")

    def test_phase_boundaries(self):
        p = self.data["phases"]
        self.assertEqual(set(p), {"inference", "tool", "compilation", "tests", "orchestration", "network_wait"})
        for key in ("inference", "network_wait"):
            self.assertIs(p[key]["measured"], False)
        self.assertTrue(p["orchestration"]["measured"])
        evidence = json.loads((ROOT / p["orchestration"]["evidence"]).read_text())
        self.assertEqual(evidence["workflow"]["status"], "passed")
        self.assertFalse(evidence["workflow"]["model_generated_candidates"])

    def test_riscv_audit_is_not_target_execution(self):
        reference = self.data["native_tool"]["static_target_audit"]
        evidence = json.loads((ROOT / reference["evidence"]).read_text())
        self.assertEqual(evidence["status"], "audit_complete")
        self.assertFalse(evidence["target_execution"])
        self.assertFalse(evidence["hats_execution"])
        self.assertEqual(set(evidence["profiles"]), set(reference["profiles"]))
        for p in evidence["profiles"].values():
            self.assertEqual(p["strict_link"]["status"], "blocked")
            self.assertNotEqual(p["strict_link"]["exit_code"], 0)
            self.assertEqual(set(p["strict_link"]["unresolved"]), set(p["closure"]["unresolved"]))
        for path, digest in evidence["own_source_sha256"].items():
            self.assertTrue((ROOT / path).resolve().is_relative_to(ROOT.resolve()))
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest, path)

    def test_saved_evidence_identifies_current_harness(self):
        evidence = json.loads((ROOT / "evidence/S01-HOST-BASELINE.json").read_text())
        self.assertEqual(evidence["native"]["status"], "passed")
        self.assertEqual(evidence["native"]["runs_passed"], 150)
        self.assertFalse(evidence["native"]["hats_execution"])
        for path, digest in evidence["native"]["source_sha256"].items():
            self.assertTrue((ROOT / path).resolve().is_relative_to(ROOT.resolve()))
            self.assertEqual(hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), digest, path)
        self.assertEqual(evidence["components"]["runner_sha256"], hashlib.sha256((ROOT / "suite.py").read_bytes()).hexdigest())
        self.assertEqual(evidence["components"]["lock_sha256"], self.data["component_source_lock_sha256"])
        self.assertEqual({c["id"] for c in evidence["components"]["cases"]}, set(suite.cases()))
        self.assertTrue(all(c["status"] == "passed" and c["samples"] == 3 for c in evidence["components"]["cases"]))


if __name__ == "__main__": unittest.main()
