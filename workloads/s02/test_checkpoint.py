import copy
from pathlib import Path
import tempfile
import unittest
import checkpoint as c


class CheckpointTests(unittest.TestCase):
    def test_hashes_and_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "source"; file.write_bytes(b"original")
            c.check_hashes(root, {"source": c.sha(file)})
            for hashes in ({}, {"source": "0"*64}, {str(file): c.sha(file)}, {"../source": c.sha(file)}):
                with self.assertRaises(ValueError): c.check_hashes(root, hashes)

    def test_matrix_multiplicity(self):
        c.matrix([{"a": 1, "b": 2}], ("a", "b"), [(1, 2)])
        for rows in ([], [{"a": 1, "b": 3}], [{"a": 1, "b": 2}]*2):
            with self.assertRaises(ValueError): c.matrix(rows, ("a", "b"), [(1, 2)])

    def test_rtl_claim_and_coverage(self):
        rows = [{"case": case + "-" + kind, "invocation": i,
                 "trace": {"status": "matched", "retirements": 1}, "result": 0}
                for case in c.SMALL for kind in c.KINDS for i in range(2)]
        report = {"status": "passed", "claim_class": "upstream_tool_on_ape_rtl", "ape_rtl_execution": True,
                  "full_S02_gate": False, "rob_entries": 8, "prediction": "bimodal",
                  "selected_cases": list(c.SMALL), "selected_kinds": list(c.KINDS),
                  "comparisons": rows, "rtl_diagnostics": {"runs": rows}}
        c.validate_rtl(report)
        for field, value in (("ape_rtl_execution", False), ("full_S02_gate", True),
                             ("rob_entries", 16), ("comparisons", rows[:-1]), ("status", "failed")):
            bad = copy.deepcopy(report); bad[field] = value
            with self.assertRaises(ValueError): c.validate_rtl(bad)

    def test_reference_cannot_claim_rtl(self):
        with self.assertRaises(ValueError):
            c.validate_reference({"status": "passed", "claim_class": "rv64i_spike_tool_execution",
                                  "ape_rtl_execution": True}, [], False)


if __name__ == "__main__": unittest.main()
