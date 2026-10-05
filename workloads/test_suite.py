"""Harness regression tests; do not require downloads or execute agent code."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import suite


class SuiteTests(unittest.TestCase):
    def test_catalog_scope(self):
        data = suite.manifest()
        self.assertEqual(len(data["sources"]), 7)
        self.assertEqual(len(suite.cases()), 21)
        self.assertNotIn("hyperagents", {s["id"] for s in data["sources"]})

    def test_paths_cannot_escape(self):
        with self.assertRaises(ValueError):
            suite.source_path({"id": "test", "commit": "a" * 40}, {"path": "../../../../escape"})

    def test_checksum_mismatch_is_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(suite, "CACHE", Path(tmp)):
            source = {"id": "test", "commit": "a" * 40}
            entry = {"path": "file.py", "bytes": 4, "sha256": suite.digest(b"good")}
            path = suite.source_path(source, entry)
            path.parent.mkdir(parents=True)
            path.write_bytes(b"evil")
            with self.assertRaises(ValueError):
                suite.verified_bytes(source, entry)
            self.assertEqual(path.read_bytes(), b"evil")

    def test_rtl_unavailable_is_not_host_fallback(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(suite, "ROOT", Path(tmp)):
            with contextlib.redirect_stdout(io.StringIO()):
                status = suite.run(["gepa.pareto"], 1, 1, "hats-rtl")
            report = json.loads(next((Path(tmp) / "results").glob("*.json")).read_text())
            self.assertEqual(status, 1)
            self.assertEqual(report["status"], "blocked")
            self.assertFalse(report["hats_execution"])
            self.assertEqual(report["cases"], [])

    def test_failed_case_stays_failed(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(suite, "ROOT", Path(tmp)), \
             patch.object(suite, "fetch"), patch.object(suite, "isolated_worker", side_effect=RuntimeError("bad output")):
            with contextlib.redirect_stdout(io.StringIO()):
                status = suite.run(["gepa.pareto"], 1, 1, "host")
            report = json.loads(next((Path(tmp) / "results").glob("*.json")).read_text())
            self.assertEqual(status, 1)
            self.assertEqual(report["status"], "failed")

    def test_timeout_kills_worker_group(self):
        with patch.object(suite.subprocess, "Popen") as popen, patch.object(suite.os, "killpg") as kill:
            process = popen.return_value
            process.pid = 123
            process.communicate.side_effect = [subprocess.TimeoutExpired("worker", 1), (b"", b"")]
            with self.assertRaises(TimeoutError):
                suite.isolated_worker("gepa.pareto", 1)
            kill.assert_called_once_with(123, suite.signal.SIGKILL)

    def test_no_inherited_credentials(self):
        with patch.dict(suite.os.environ, {"OPENAI_API_KEY": "test-only", "AWS_SECRET_ACCESS_KEY": "test-only"}), \
             patch.object(suite.subprocess, "Popen") as popen:
            popen.return_value.communicate.return_value = (b"{}", b"")
            popen.return_value.returncode = 0
            suite.isolated_worker("gepa.pareto", 1)
            environment = popen.call_args.kwargs["env"]
            self.assertNotIn("OPENAI_API_KEY", environment)
            self.assertNotIn("AWS_SECRET_ACCESS_KEY", environment)


if __name__ == "__main__":
    unittest.main()
