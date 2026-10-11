"""Synthetic evidence-shape tests; these are not cache/processor simulations."""
import copy
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"hardware/spinal/tools"))
from verify_ape_memory_trace import validate_report


def fixture():
    rows=[]
    for sets,mshrs in ((8,2),(16,4),(32,8)):
        rows.append(dict(sets=sets,mshrs=mshrs,trace_sha256="a"*64,application_memory_events=100,
            accepted=100,completed=100,final_memory_matches_application=True,cycles=1000,
            lower_accepted=10,lower_completed=10,generated_rtl_sha256="b"*64,validation_sha256="c"*64))
    return dict(status="passed_trace_design_points",S04_complete=False,runs=rows,
        application_gate_sha256="d"*64,input_sha256={"trace":"a"*64},source_sha256={"sim":"e"*64},
        source_sha256_after={"sim":"e"*64},tools={"sim":"pinned"})


class ApeTraceDesignPointTests(unittest.TestCase):
    def test_valid_matched_points(self):
        self.assertEqual(validate_report(fixture()),fixture())

    def reject(self,mutate):
        report=fixture();mutate(report)
        with self.assertRaises(ValueError):validate_report(report)

    def test_rejects_mixed_trace(self):
        self.reject(lambda r:r["runs"][1].update(trace_sha256="f"*64))

    def test_rejects_missing_final_state(self):
        self.reject(lambda r:r["runs"][2].update(final_memory_matches_application=False))

    def test_rejects_unbalanced_memory_traffic(self):
        self.reject(lambda r:r["runs"][0].update(completed=99))

    def test_rejects_scope_promotion(self):
        self.reject(lambda r:r.update(S04_complete=True))


if __name__=="__main__":unittest.main()
