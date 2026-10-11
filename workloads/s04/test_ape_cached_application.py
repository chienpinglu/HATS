"""Evidence-shape checks; these are not processor or cache simulations."""
import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hardware/spinal/tools"))
from verify_ape_cached_application import APPLICATIONS, RUN_POINTS, validate_report


def fixture():
    rows = []
    for application, mode, sets, mshrs in RUN_POINTS:
        index = APPLICATIONS.index(application)
        rows.append(dict(application=application, mode=mode, sets=sets, mshrs=mshrs,
            application_trace_sha256=f"{index:064x}", application_memory_sha256=f"{index+32:064x}",
            architectural_trace_matches_direct_APE=True, final_memory_matches_direct_APE=True,
            line_requests=80, line_completions=80, cycles=1000, max_cache_outstanding=2,
            cache_hits=20, cache_misses=60, cache_refills=60, cache_writebacks=4,
            fetch_requests=10 if mode == "I_D_L1" else 0,
            max_fabric_outstanding=2 if mode == "I_D_L1" else 0,
            instruction_cache_misses=2 if mode == "I_D_L1" else 0,
            generated_rtl_sha256="c"*64, validation_sha256="d"*64))
    return dict(status="passed_integrated_application_design_points", S04_complete=False,
        runs=rows, input_sha256={"input": "e"*64}, source_sha256={"source": "f"*64},
        source_sha256_after={"source": "f"*64}, tools={"tool": "pinned"})


class ApeCachedApplicationEvidenceTests(unittest.TestCase):
    def test_valid_twelve_input_and_factorial_design_points(self):
        points = {(r["sets"], r["mshrs"]) for r in fixture()["runs"] if r["application"] == "repo_source_edit"}
        self.assertEqual(points, {(sets, mshrs) for sets in (8, 16, 32) for mshrs in (2, 4, 8)})
        self.assertEqual(validate_report(fixture()), fixture())

    def reject(self, mutate):
        report = fixture()
        mutate(report)
        with self.assertRaises(ValueError):
            validate_report(report)

    def test_rejects_missing_point(self):
        self.reject(lambda r: r["runs"].pop())

    def test_rejects_trace_mismatch(self):
        self.reject(lambda r: r["runs"][4].update(application_trace_sha256="1"*64))

    def test_rejects_missing_application_fixture(self):
        self.reject(lambda r: r["runs"].pop(6))

    def test_rejects_cross_point_input_mismatch(self):
        self.reject(lambda r: r["runs"][7].update(application_memory_sha256="0"*64))

    def test_rejects_final_memory_mismatch(self):
        self.reject(lambda r: r["runs"][5].update(final_memory_matches_direct_APE=False))

    def test_rejects_unbalanced_line_traffic(self):
        self.reject(lambda r: r["runs"][0].update(line_completions=79))

    def test_rejects_missing_cache_counters(self):
        self.reject(lambda r: r["runs"][0].pop("cache_misses"))

    def test_rejects_completion_promotion(self):
        self.reject(lambda r: r.update(S04_complete=True))


if __name__ == "__main__":
    unittest.main()
