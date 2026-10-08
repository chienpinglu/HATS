import copy
import unittest
import run


class BaselineTests(unittest.TestCase):
    def test_known_structure(self):
        self.assertEqual(run.expected_nodes(b'{"a":[1,true]}'), [
            ["object", 0, 14, 0], ["string", 1, 4, 1], ["array", 5, 13, 1],
            ["number", 6, 7, 2], ["true", 8, 12, 2]])

    def test_unicode_offsets(self):
        self.assertEqual(run.expected_nodes('["\u03b1",2]'.encode()),
                         [["array", 0, 8, 0], ["string", 1, 5, 1], ["number", 6, 7, 1]])

    def test_syntax_rejections(self):
        for raw in (b'{}{}', b'[1,]', b'{"x":}', b'[NaN]', b''):
            with self.assertRaises(ValueError): run.expected_nodes(raw)

    def test_corrupt_outputs_rejected(self):
        raw = b'{"a":1}'
        good = {"nodes": run.expected_nodes(raw), "has_error": False, "live_after_cleanup": 0}
        run.check_output(raw, good)
        for change in ("span", "kind", "depth", "missing", "error", "leak"):
            bad = copy.deepcopy(good)
            if change == "span": bad["nodes"][-1][2] -= 1
            elif change == "kind": bad["nodes"][-1][0] = "null"
            elif change == "depth": bad["nodes"][-1][3] = 7
            elif change == "missing": bad["nodes"].pop()
            elif change == "error": bad["has_error"] = True
            else: bad["live_after_cleanup"] = 1
            with self.assertRaises(ValueError): run.check_output(raw, bad)

    def test_invalid_input_must_report_error(self):
        run.check_output(b'[1,]', {"has_error": True, "live_after_cleanup": 0})
        with self.assertRaises(ValueError): run.check_output(b'[1,]', {"has_error": False, "live_after_cleanup": 0})

    def test_fixture_identity(self):
        data = run.fixture_manifest()
        self.assertEqual(len(data["cases"]), 10)
        self.assertEqual(data, run.fixture_manifest())
        self.assertEqual(len({c["id"] for c in data["cases"]}), 10)


if __name__ == "__main__": unittest.main()
