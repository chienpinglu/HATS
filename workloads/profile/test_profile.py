import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import run as profile
from workflow import account


class ProfileTests(unittest.TestCase):
    def test_branch_outcomes(self):
        report = {"type": "llvm.coverage.json.export", "data": [{"functions": [{"branches": [
            [1, 1, 1, 2, 2, 3, 0, 0, 4], [2, 1, 2, 2, 0, 7, 0, 0, 4],
            [3, 1, 3, 2, 0, 0, 0, 0, 4]]}]}]}
        self.assertEqual(profile.branches(report), {"regions": 3, "visited_regions": 2,
                         "both_outcomes_regions": 1, "true_outcomes": 2, "false_outcomes": 10})
        bad = copy.deepcopy(report); bad["data"][0]["functions"][0]["branches"][0][4] = -1
        with self.assertRaises(ValueError): profile.branches(bad)
        with self.assertRaises(ValueError): profile.branches({"type": "unknown"})

    def test_serial_accounting(self):
        events = [{"category": "compilation", "start_ns": 2, "end_ns": 12, "depends_on": []},
                  {"category": "tests", "start_ns": 15, "end_ns": 19, "depends_on": [0]}]
        a = account(events, 22)
        self.assertEqual(a["phase_ns"]["compilation"], 10)
        self.assertEqual(a["phase_ns"]["tests"], 4)
        self.assertEqual(a["phase_ns"]["orchestration"], 8)
        self.assertEqual(sum(a["phase_ns"].values()), a["critical_path_ns"])
        for changes in ({"start_ns": 11}, {"end_ns": 14}, {"depends_on": []}, {"category": "fake"}):
            bad = copy.deepcopy(events); bad[1].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError): account(bad, 22)
        with self.assertRaises(ValueError): account(events, 18)
        with self.assertRaises(ValueError): account([], 22)

    def test_memory_calibration_and_reset(self):
        cc = profile.native.tool("clang")
        with tempfile.TemporaryDirectory(prefix="hats-profile-test-") as tmp:
            root = Path(tmp)
            flags = [cc, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-O2", "-I" + str(profile.native.ROOT), "-I" + str(profile.ROOT)]
            subprocess.run(flags + ["-Dhats_profile_begin=hats_base_profile_begin", "-Dhats_profile_end=hats_base_profile_end",
                                   "-c", str(profile.native.ROOT / "profile.c"), "-o", str(root / "profile.o")], check=True, capture_output=True)
            subprocess.run(flags + [str(profile.ROOT / "memory_profile.c"), str(profile.ROOT / "probe_test.c"),
                                   str(root / "profile.o"), "-o", str(root / "test")], check=True, capture_output=True)
            p = subprocess.run([str(root / "test")], check=True, capture_output=True, text=True)
            a, b = [json.loads(line) for line in p.stderr.splitlines()]
            for key, value in {"loads": 2, "stores": 1, "access_bytes": 25, "line_touches": 4,
                               "unique_64b_lines": 2, "reused_line_touches": 2, "consecutive_same_line": 0,
                               "consecutive_adjacent_line": 3, "atomic_inc_seqcst": 1,
                               "atomic_dec_seqcst": 1, "atomic_load_relaxed": 1}.items():
                self.assertEqual(a[key], value, key)
                self.assertEqual(b[key], 0, key)


if __name__ == "__main__": unittest.main()
