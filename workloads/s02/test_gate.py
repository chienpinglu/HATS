import copy
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import gate as g
import run_all


class GateTests(unittest.TestCase):
    def report(self):
        rows = []
        for mode, name, args, old, new, status in g.bulk.cases():
            rows.append({"mode": mode, "case": name, "expected_status": status,
                         "runs": [{"invocation": 0, "diagnostics": {"retired": 1},
                                   "digest": {"schema": 1, "encoding": "hats-architectural-state-le64-v1",
                                              "retirements": 1, "memory_events": 2, "events": 4}}]})
        return {"status": "passed", "full_fixture_matrix": True,
                "claim_class": "actual_APE_RTL_complete_streaming_architectural_state_comparison",
                "rob_entries": 8, "prediction": "bimodal", "repetitions": 1, "results": rows}

    def test_full_matrix(self):
        g.validate_bulk(self.report())

    def test_missing_duplicate_changed_and_mislabeled_matrix(self):
        good = self.report()
        mutations = [("results", good["results"][:-1]), ("results", good["results"] + good["results"][:1]),
                     ("status", "running"), ("full_fixture_matrix", False), ("claim_class", "reference_only"), ("repetitions", 2)]
        for key, value in mutations:
            with self.subTest(key=key), self.assertRaises(ValueError):
                bad = copy.deepcopy(good); bad[key] = value; g.validate_bulk(bad)
        for key, value in (("expected_status", 9), ("case", "invented")):
            bad = copy.deepcopy(good); bad["results"][0][key] = value
            with self.assertRaises(ValueError): g.validate_bulk(bad)

    def test_missing_event_and_retirement_count(self):
        for key in ("events", "retirements", "memory_events"):
            bad = self.report(); bad["results"][0]["runs"][0]["digest"][key] += 1
            with self.assertRaises(ValueError): g.validate_bulk(bad)

    def test_digest_uses_all_state_fields_and_order(self):
        events = [{"kind": "memory", "address": "65536", "bytes": 8, "write": False, "data": "5", "error": False},
                  {"kind": "retire", "pc": "0", "instruction": 123, "next": "4", "writes": True, "rd": 1, "value": "5"},
                  {"kind": "trap", "pc": "4", "cause": 3, "value": "0"}]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trace"
            def digest(rows):
                path.write_text("\n".join(json.dumps(r) for r in rows))
                return g.bulk.digest_text(path)
            baseline = digest(events)
            registers = [0]*32; registers[1] = 5; registers[10] = g.target.image.ARGUMENT
            words = [2, 65536, 8, 0, 5, 0, 1, 0, 123, 4, *registers, 3, 4, 3, 0]
            self.assertEqual(baseline["sha256"], hashlib.sha256(struct.pack("<" + "Q"*len(words), *words)).hexdigest())
            for index, field in ((0, "address"), (0, "data"), (0, "bytes"), (0, "write"), (0, "error"),
                                 (1, "pc"), (1, "instruction"), (1, "next"), (1, "rd"), (1, "value"),
                                 (2, "pc"), (2, "cause"), (2, "value")):
                bad = copy.deepcopy(events); bad[index][field] = int(bad[index][field])+1
                self.assertNotEqual(digest(bad)["sha256"], baseline["sha256"], (index, field))
            for bad in (events[:-1], events+events[-1:], list(reversed(events))): self.assertNotEqual(digest(bad), baseline)

    def test_ppe_cannot_be_a_model(self):
        with self.assertRaises(ValueError):
            g.validate_ppe({"status": "passed", "claim_class": "model_only"})


class PpeCheckerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name); self.actual = self.folder / "rtl-0"; self.actual.mkdir()
        state = {"scalar": [0]*32, "vector": [[0]*8 for _ in range(32)], "predicate": [0]*8, "active": 255, "depth": 0}
        self.reference = {**state, "trace": [{"pc": 0, **copy.deepcopy(state)}], "kind": 0,
                          "global": [{"address": 8, "data": 5, "size": 3, "lane": 0, "write": True, "error": 0}],
                          "scratch": [], "completion": {"status": "success"}}
        self.reference["ordered_access"] = [{**self.reference["global"][0], "scratch": False, "retirement_index": 0}]
        (self.folder / "reference.json").write_text(json.dumps(self.reference))
        self.write("trace.jsonl", self.reference["trace"][0]); self.write("access.jsonl", self.reference["ordered_access"][0])
        self.write("state.json", state); self.write("completion.json", self.reference["completion"])
        for space in ("memory", "scratch"):
            (self.folder / f"reference.{space}.bin").write_bytes(b"\0"*16)
            (self.actual / f"{space}.bin").write_bytes(b"\0"*16)

    def write(self, filename, value): (self.actual / filename).write_text(json.dumps(value)+"\n")
    def test_accept_exact(self): g.verify_ppe.compare(self.folder, 0)
    def test_missing_register_state_is_rejected(self):
        self.write("state.json", {})
        with self.assertRaises(ValueError): g.verify_ppe.compare(self.folder, 0)
    def test_retirement_state_is_checked(self):
        row = copy.deepcopy(self.reference["trace"][0]); row["vector"][31][7] = 1; self.write("trace.jsonl", row)
        with self.assertRaises(ValueError): g.verify_ppe.compare(self.folder, 0)
    def test_access_retirement_order_is_checked(self):
        row = copy.deepcopy(self.reference["ordered_access"][0]); row["retirement_index"] = 1; self.write("access.jsonl", row)
        with self.assertRaises(ValueError): g.verify_ppe.compare(self.folder, 0)
    def test_final_memory_checked(self):
        (self.actual / "scratch.bin").write_bytes(b"\1"*16)
        with self.assertRaises(ValueError): g.verify_ppe.compare(self.folder, 0)
    def test_completion_checked(self):
        self.write("completion.json", {"status": "fault"})
        with self.assertRaises(ValueError): g.verify_ppe.compare(self.folder, 0)


class FreshRunnerTests(unittest.TestCase):
    def test_never_reuses_old_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / "old.json").write_text('{"status":"passed"}')
            with patch.object(run_all, "REPO", root), patch.object(run_all.subprocess, "run"):
                with self.assertRaises(RuntimeError): run_all.fresh(["fake.py"], "*.json")

    def test_new_failed_or_duplicate_reports_are_rejected(self):
        for count, status in ((1, "failed"), (2, "passed"), (1, "passed")):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                def produce(*args, **kwargs):
                    for i in range(count): (root / f"new{i}.json").write_text(json.dumps({"status": status}))
                with patch.object(run_all, "REPO", root), patch.object(run_all.subprocess, "run", side_effect=produce):
                    if count == 1 and status == "passed": self.assertEqual(run_all.fresh(["fake.py"], "*.json"), root / "new0.json")
                    else:
                        with self.assertRaises(RuntimeError): run_all.fresh(["fake.py"], "*.json")


if __name__ == "__main__": unittest.main()
