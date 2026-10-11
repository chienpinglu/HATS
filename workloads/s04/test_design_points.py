import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PpeDesignPointReportTests(unittest.TestCase):
    def test_matched_workload_matrix_and_claim_limits(self):
        report = json.loads((ROOT / "workloads/s04/PPE-DESIGN-POINTS.json").read_text())
        self.assertEqual(report["status"], "matched_workload_rtl_design_point_comparison")
        self.assertFalse(report["S04_complete"])
        points = report["design_points"]
        self.assertEqual([(p["configuration"]["instruction_cache"], p["configuration"]["sets"],
                           p["configuration"]["mshrs"]) for p in points],
                         [(False, 8, 2), (False, 16, 4), (False, 32, 8),
                          (True, 8, 2), (True, 16, 4), (True, 32, 8)])
        for point in points:
            metrics = point["metrics"]
            self.assertEqual(metrics["exact_architectural_comparisons"], 316)
            self.assertEqual(metrics["ai_vector_epilogue_groups"], 32)
            self.assertEqual(metrics["total_accepted_lines"], metrics["total_completed_lines"])
            self.assertEqual(metrics["max_mshrs"], point["configuration"]["mshrs"])
            self.assertEqual(metrics["hits"] + metrics["misses"], metrics["global_words"])
        for mode in (False, True):
            selected = [p["metrics"] for p in points if p["configuration"]["instruction_cache"] == mode]
            self.assertEqual(len({m["global_words"] for m in selected}), 1)
            self.assertEqual(len({m["misses"] for m in selected}), 1)
        self.assertTrue(all(p["metrics"]["instruction_misses"] > 0 for p in points[3:]))
        app_points = [p["metrics"]["delimiter_application"] for p in points[3:]]
        self.assertEqual([p["groups_completed"] for p in app_points], [32, 32, 32])
        self.assertEqual(len({p["input_sha256"] for p in app_points}), 1)
        self.assertEqual(len({p["output_sha256"] for p in app_points}), 1)
        self.assertTrue(all(p["accepted_lines"] == p["completed_lines"] for p in app_points))
        vector_points = [p["metrics"]["ai_vector_application"] for p in points[3:]]
        self.assertEqual([p["groups_completed"] for p in vector_points], [32, 32, 32])
        self.assertEqual(len({p["input_sha256"] for p in vector_points}), 1)
        self.assertEqual(len({p["output_sha256"] for p in vector_points}), 1)
        self.assertTrue(all(p["accepted_lines"] == p["completed_lines"] for p in vector_points))
        self.assertTrue(any("not measured" in limit for limit in report["limits"]))


if __name__ == "__main__":
    unittest.main()
