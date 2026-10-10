"""Parser/interface-control tests, not synthesis or processor correctness."""
from pathlib import Path
import tempfile
import unittest

from probe_ape_technology import blif_interface, final_equivalence, parse_delay, validate_aiger_header


class TechnologyParserTests(unittest.TestCase):
    def test_final_outcome_including_fallback(self):
        self.assertTrue(final_equivalence("Networks are UNDECIDED.\nCalling old engine.\nNetworks are equivalent."))
        for text in ("Networks are UNDECIDED.", "Networks are NOT EQUIVALENT.", "parse failed",
                     "Networks are equivalent.\nNetworks are UNDECIDED."):
            self.assertFalse(final_equivalence(text))

    def test_timing_units_and_unique_result(self):
        self.assertEqual(parse_delay("Area = 123 Delay = 2869.98 ps"), 2869.98)
        for text in ("Delay = 3.2 ns", "Delay = 0 ps", "Delay = 1 ps Delay = 2 ps", "No timing"):
            with self.assertRaises(RuntimeError):
                parse_delay(text)

    def test_blif_and_aig_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "input.blif"
            p.write_text(".model x\n.inputs a \\\nb\n.outputs q\n.end\n")
            interface = blif_interface(p)
            self.assertEqual(interface, {".inputs": ["a", "b"], ".outputs": ["q"]})
            aig = Path(folder) / "a.aig"
            aig.write_bytes(b"aig 3 2 0 1 1\n")
            validate_aiger_header(aig, interface)
            for header in (b"aig 3 1 0 1 2\n", b"aig 3 2 1 1 0\n", b"aig 3 2 0 2 1\n"):
                aig.write_bytes(header)
                with self.assertRaises(RuntimeError):
                    validate_aiger_header(aig, interface)
            for bad in (".inputs a a\n.outputs q\n", ".inputs a\n.inputs b\n.outputs q\n",
                        ".inputs a\n.outputs q\n.latch a q\n"):
                p.write_text(bad)
                with self.assertRaises(RuntimeError):
                    blif_interface(p)


if __name__ == "__main__":
    unittest.main()
