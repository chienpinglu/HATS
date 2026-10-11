"""Synthetic report-shape negative controls, never hardware execution evidence."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hardware/spinal/tools"))
from verify_ape_memory import NAMES, validate, validate_publication, validate_device, validate_replay_pressure


def fixture():
    rows = [{"name": name, "cycles": 1000, "retired": 10, "max_outstanding": 6,
             "max_cache_outstanding": 4, "lower_reorders": 2, "word_requests": 8,
             "counters": {"forwarded": 1, "partial_forwarded": 1, "unknown_store_stalls": 0,
                          "speculative_loads": 1, "memory_replays": 1,
                          "fence_stalls": 1, "discarded": 2, "writebacks": 0,
                          "hits": 4, "misses": 4, "allocated": 9}} for name in sorted(NAMES)]
    for row in rows:
        if row["name"] == "queue_full": row["max_outstanding"] = 8
        if row["name"] == "wrong_path_read_drain": row["retired"] = 4
        if row["name"] == "older_fault_after_younger_read": row["retired"] = 1
    return {"status": "passed", "issue": 5, "S04_complete": False,
            "claim_class": "actual_APE_LSQ_data_L1_RTL", "profile": "ROB8/P48/W1/C4/D2/G2",
            "tests": rows, "limits": ["synthetic report test fixture"]}


class ApeMemoryEvidenceTests(unittest.TestCase):
    def reject(self, mutate):
        value = fixture(); mutate(value)
        with self.assertRaises(ValueError): validate(value)

    def test_complete_partial_scope(self):
        validate(fixture())

    def test_combined_replay_pressure_requires_all_resource_and_ordering_witnesses(self):
        value = {"status": "passed", "S04_complete": False,
                 "claim_class": "actual_APE_LSQ_data_L1_RTL", "profile": "ROB16/P48/W1/C4/D2/G2",
                 "tests": [{"name": "replay_under_queue_pressure", "max_outstanding": 8,
                            "max_cache_outstanding": 4, "lower_reorders": 4,
                            "counters": {"speculative_loads": 7, "memory_replays": 1, "refills": 8}}]}
        validate_replay_pressure(value)
        mutations = (("max_outstanding", 7), ("max_cache_outstanding", 3),
                     ("lower_reorders", 0), ("speculative_loads", 0),
                     ("memory_replays", 0), ("refills", 3))
        for key, invalid in mutations:
            changed = copy.deepcopy(value)
            field = key if key in ("max_outstanding", "max_cache_outstanding", "lower_reorders") else None
            if field: changed["tests"][0][field] = invalid
            else: changed["tests"][0]["counters"][key] = invalid
            with self.assertRaises(ValueError): validate_replay_pressure(changed)

    def test_scope_and_matrix(self):
        for key, value in (("status", "running"), ("S04_complete", True), ("profile", "ROB8/P64")):
            self.reject(lambda r: r.update({key: value}))
        self.reject(lambda r: r["tests"].pop())
        self.reject(lambda r: r["tests"].append(copy.deepcopy(r["tests"][0])))

    def test_required_mechanisms(self):
        for name, field in (("forward_bytes", "partial_forwarded"),
                            ("youngest_store_bytes", "forwarded"), ("unknown_store_address", "speculative_loads"),
                            ("unknown_store_address", "memory_replays"),
                            ("fence", "fence_stalls"), ("wrong_path_read_drain", "discarded")):
            self.reject(lambda r: next(x for x in r["tests"] if x["name"] == name)["counters"].update({field: 0}))
        for name, field, value in (("parallel_loads", "max_outstanding", 1), ("parallel_loads", "lower_reorders", 0),
                                   ("queue_full", "max_outstanding", 7), ("parallel_loads", "word_requests", 0),
                                   ("wrong_path_read_drain", "retired", 7), ("older_fault_after_younger_read", "retired", 5)):
            self.reject(lambda r: next(x for x in r["tests"] if x["name"] == name).update({field: value}))

    def test_instruction_path_identity_and_witnesses(self):
        value = fixture(); value["claim_class"] = "actual_APE_LSQ_instruction_data_L1_fabric_RTL"
        for row in value["tests"]:
            row.update(instruction_reads=0 if row["name"].startswith("entry_") else 1,
                       instruction_hits=2, fetch_requests=3, max_fabric_outstanding=2)
        validate(value, instructions=True)
        with self.assertRaises(ValueError): validate(value)
        value["tests"][0]["instruction_reads"] = 0
        with self.assertRaises(ValueError): validate(value, instructions=True)

    def test_publication_failure_retry_and_drain(self):
        value = {"status": "passed", "issue": 5, "S04_complete": False,
                 "claim_class": "actual_APE_instruction_publication_fault_RTL", "cycles": 1000,
                 "executions": 11, "publications": 5, "publication_stall_cycles": 25,
                 "cpu_code_stores": 1, "successful_code_writebacks": 1, "failed_code_writebacks": 1,
                 "fabric_accepted": 20, "fabric_completed": 20, "fabric_rejected": 2,
                 "fetch_failures": 3, "fetch_discarded": 2, "max_fabric_outstanding": 2,
                 "response_reorders": 2, "request_stall_cycles": 10, "limits": ["synthetic fixture"]}
        validate_publication(value)
        for field in ("executions", "publications", "publication_stall_cycles", "cpu_code_stores",
                      "failed_code_writebacks", "fetch_discarded", "fetch_failures", "fabric_rejected", "fabric_completed"):
            mutated = copy.deepcopy(value); mutated[field] = 0
            with self.assertRaises(ValueError): validate_publication(mutated)

    def test_device_path_scope_and_transaction_counts(self):
        value = {"status": "passed", "issue": 5, "S04_complete": False,
                 "claim_class": "actual_APE_D_L1_clean_then_uncached_device_RTL",
                 "instruction_cache_profiles": 2, "device_requests": 6, "device_reads": 4,
                 "device_writes": 2, "device_backpressure_cycles": 3,
                 "clean_before_every_device_request": True,
                 "malformed_response_id_rejected": True, "malformed_response_epoch_rejected": True,
                 "limits": ["No concurrent PPE device service or shared atomics claimed"]}
        validate_device(value)
        for key, invalid in (("device_requests", 5), ("clean_before_every_device_request", False),
                             ("S04_complete", True)):
            changed = copy.deepcopy(value); changed[key] = invalid
            with self.assertRaises(ValueError): validate_device(changed)


if __name__ == "__main__":
    unittest.main()
