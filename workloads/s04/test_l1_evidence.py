"""Acceptance/rejection logic only; fixtures do not claim RTL execution."""
import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "hardware/spinal/tools"))
from verify_memory_l1 import validate


def fixture():
    return {"status": "passed", "issue": 5, "S04_complete": False,
            "claim_class": "actual_nonblocking_L1_component_RTL",
            "limits": ["synthetic test fixture includes a 64-bit atomic-add primitive"],
            "configurations": [{"sets": s, "line_bytes": b, "mshrs": m, "generation_bits": 2,
                "cycles": 10000, "accepted": 3118+m, "completed": 3118+m, "reads": 1609+m, "writes": 1504,
                "atomic_adds": 4, "faulted_requests": 5, "max_client_outstanding": m, "max_lower_outstanding": m,
                "client_reorders": 10, "lower_reorders": 10, "stale_replies": 10, "lower_stall_cycles": 10,
                "response_stall_cycles": 10, "flush_stall_cycles": 10, "hits_under_miss": 10, "drain_checks": 10,
                "stale_generations": 5, "stale_phases": 5, "observed_generations": 4,
                "observed_lower_reads": 100, "observed_lower_writes": 100,
                "counters": {"hits": 100, "misses": 3017+m, "refills": 100, "writebacks": 100,
                             "rejected_replies": 10, "set_stalls": 10, "full_stalls": 10},
                "flushes": 8, "failed_flushes": 1, "quiescent_resets": 1} for s, b, m in ((4,16,2),(8,32,4),(16,64,8))]}


class L1EvidenceTests(unittest.TestCase):
    def test_complete_component_scope(self):
        validate(fixture())

    def reject(self, mutation):
        r = fixture(); mutation(r)
        with self.assertRaises(ValueError): validate(r)

    def test_partial_duplicate_or_scope_promotion(self):
        self.reject(lambda r: r.update(status="running"))
        self.reject(lambda r: r.update(S04_complete=True))
        self.reject(lambda r: r["configurations"].pop())
        self.reject(lambda r: r["configurations"].append(copy.deepcopy(r["configurations"][0])))

    def test_counts_and_mechanism_witnesses(self):
        self.reject(lambda r: r["configurations"][0].update(completed=3099))
        self.reject(lambda r: r["configurations"][0].update(atomic_adds=0))
        for field in ("max_lower_outstanding", "hits_under_miss", "lower_reorders", "client_reorders",
                      "stale_replies", "failed_flushes", "quiescent_resets", "drain_checks", "stale_phases"):
            self.reject(lambda r: r["configurations"][0].__setitem__(field, 0))

    def test_counter_identity(self):
        for field in ("hits", "refills", "writebacks", "rejected_replies"):
            self.reject(lambda r: r["configurations"][0]["counters"].__setitem__(field, 0))


if __name__ == "__main__":
    unittest.main()
