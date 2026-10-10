"""Synthetic report rendering tests; values here are not hardware measurements."""
import unittest

from report_designs import render_with_identity
from test_design_evidence import study_fixture, technology_fixture


class DesignReportTests(unittest.TestCase):
    def inputs(self):
        study = study_fixture()
        for row in study["results"]:
            row["metrics"].update(rename_stall_cycles=5, rob_stall_cycles=6, completion_stall_cycles=7,
                                  branch_misses=8, branches=9)
        return study, technology_fixture()

    def test_units_scope_and_honest_slowdown(self):
        study, technology = self.inputs()
        report = render_with_identity(study, technology, "study-digest", ["physical-digest"])
        self.assertIn("+10.000%", report)
        self.assertIn("2,500.00 ps | no", report)
        self.assertIn("30 / 0", report)
        self.assertIn("metadata entries", report)
        self.assertIn("Achievable processor clock frequency | Not measured", report)
        self.assertIn("Physical power / energy | Not measured", report)
        self.assertNotIn("GHz", report)
        self.assertIn("`study-digest`", report)
        self.assertIn("`physical-digest`", report)
        self.assertEqual(report.count("| helpers / integer-vectors |"), 2)
        self.assertEqual(report.count("| parser / records_256-incremental |"), 2)

    def test_incomplete_measurements_do_not_render(self):
        study, technology = self.inputs()
        study["status"] = "running"
        with self.assertRaises((RuntimeError, ValueError)):
            render_with_identity(study, technology, "a", ["b"])
        study, technology = self.inputs()
        technology[0]["results"].pop()
        with self.assertRaises((RuntimeError, ValueError)):
            render_with_identity(study, technology, "a", ["b"])


if __name__ == "__main__":
    unittest.main()
