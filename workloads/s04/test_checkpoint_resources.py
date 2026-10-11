import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

import checkpoint


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TargetResourceObservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.old_repo = checkpoint.REPO
        self.old_hw = checkpoint.HW
        checkpoint.REPO = self.root.resolve()
        checkpoint.HW = self.root.resolve() / "hardware/spinal"
        self.app = self.root / "workloads/results/run/parser"
        self.app.mkdir(parents=True)
        self.case = "empty-cold_old"
        self.trace = self.app / "rtl-r8-bimodal" / f"{self.case}-0.trace.jsonl"
        self.trace.parent.mkdir()
        self.trace.write_text("\n".join([
            json.dumps({"kind": "retire", "writes": True, "rd": 2, "value": str(0x1000000)}),
            json.dumps({"kind": "retire", "writes": True, "rd": 2, "value": str(0xFFF000)}),
        ]) + "\n")
        self.result_gate = self.app.parent / "validation.json"
        self.result_gate.write_text(json.dumps({"runs": [{
            "case": "empty", "kind": "cold_old",
            "execution": {"status": "executed", "observed_stack_pointer_bytes": 4096},
            "result": {"peak_bytes": 8192, "allocation_calls": 3, "heap_granted": 12288},
        }]}))
        self.direct_gate = self.app.parent / "rtl-validation.json"
        self.direct_gate.write_text(json.dumps({"comparisons": [{
            "case": self.case, "invocation": 0, "trace_sha256": digest(self.trace),
        }]}))
        self.build_gate = checkpoint.HW / "build/s04/test/gate.json"
        self.build_gate.parent.mkdir(parents=True)
        self.build_gate.write_text("{}\n")
        self.final_memory = self.build_gate.parent / "final-memory.bin"
        image = bytearray(0x1000000)
        struct.pack_into("<8Q", image, 0x110000, 0x4841545354533031, 0, 0, 5, 0, 8192, 3, 12288)
        self.final_memory.write_bytes(image)
        self.report = {
            "application_dir": str(self.app.relative_to(self.root)),
            "case": self.case,
            "gate_path": str(self.build_gate.relative_to(self.root)),
            "final_memory_sha256": digest(self.final_memory),
            "input_sha256": {
                str(self.result_gate.relative_to(self.root)): digest(self.result_gate),
                str(self.direct_gate.relative_to(self.root)): digest(self.direct_gate),
                str(self.trace.relative_to(self.root)): digest(self.trace),
            },
        }

    def tearDown(self):
        checkpoint.REPO = self.old_repo
        checkpoint.HW = self.old_hw
        self.temp.cleanup()

    def test_source_bound_ape_and_reference_resource_metrics(self):
        result = checkpoint.target_resource_observation(self.report)
        self.assertEqual(result["ape_observed_stack_bytes"], 4096)
        self.assertEqual(result["spike_observed_stack_bytes"], 4096)
        self.assertEqual(result["peak_requested_heap_bytes"], 8192)
        self.assertEqual(result["ape_peak_requested_heap_bytes"], 8192)
        self.assertEqual(result["heap_bytes_granted"], 12288)
        self.assertIn("not_worst_case", result["claim_class"])

    def test_rejects_trace_hash_or_stack_reservation_mismatch(self):
        self.report["input_sha256"][str(self.trace.relative_to(self.root))] = "0" * 64
        with self.assertRaises(ValueError):
            checkpoint.target_resource_observation(self.report)
        self.report["input_sha256"][str(self.trace.relative_to(self.root))] = digest(self.trace)
        self.trace.write_text(json.dumps({"kind": "retire", "writes": True, "rd": 2,
                                          "value": str(0xEFFFF0)}) + "\n")
        self.report["input_sha256"][str(self.trace.relative_to(self.root))] = digest(self.trace)
        self.direct_gate.write_text(json.dumps({"comparisons": [{
            "case": self.case, "invocation": 0, "trace_sha256": digest(self.trace),
        }]}))
        self.report["input_sha256"][str(self.direct_gate.relative_to(self.root))] = digest(self.direct_gate)
        with self.assertRaises(ValueError):
            checkpoint.target_resource_observation(self.report)

    def test_rejects_ape_heap_telemetry_that_differs_from_spike(self):
        image = bytearray(self.final_memory.read_bytes())
        struct.pack_into("<Q", image, 0x110000 + 5 * 8, 8193)
        self.final_memory.write_bytes(image)
        self.report["final_memory_sha256"] = digest(self.final_memory)
        with self.assertRaises(ValueError):
            checkpoint.target_resource_observation(self.report)


if __name__ == "__main__":
    unittest.main()
