import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import newlib


class NewlibTests(unittest.TestCase):
    def fixture(self, root, extra=None):
        name = "newlib-4.5.0.20241231"
        archive = root / (name + ".tar.gz")
        with tarfile.open(archive, "w:gz") as tar:
            for path, data in (("COPYING.NEWLIB", b"test notice"), ("newlib/libc/include/stdio.h", b"test header")):
                entry = tarfile.TarInfo(name + "/" + path)
                entry.size = len(data)
                tar.addfile(entry, io.BytesIO(data))
            if extra: tar.addfile(extra, io.BytesIO(b""))
        lock = root / "lock.json"
        lock.write_text(json.dumps({"release": name, "url": "https://sourceware.org/pub/newlib/" + name + ".tar.gz",
            "archive_sha256": newlib.sha(archive), "license_sha256": hashlib.sha256(b"test notice").hexdigest()}))
        return lock

    def test_extract_and_verify_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); lock = self.fixture(root)
            with patch.object(newlib, "CACHE", root), patch.object(newlib, "LOCK", lock), patch.object(newlib.urllib.request, "urlopen") as network:
                src = newlib.source()
                self.assertEqual((src / "newlib/libc/include/stdio.h").read_bytes(), b"test header")
                self.assertEqual(newlib.source(), src)
                network.assert_not_called()

    def test_changes_are_rejected_not_overwritten(self):
        for change in ("modified", "unexpected", "archive"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); lock = self.fixture(root)
                with patch.object(newlib, "CACHE", root), patch.object(newlib, "LOCK", lock):
                    src = newlib.source()
                    p = src / ("newlib/libc/include/stdio.h" if change == "modified" else "extra.h")
                    if change == "archive": p = root / "newlib-4.5.0.20241231.tar.gz"
                    p.write_bytes(b"modified")
                    with self.assertRaises(ValueError): newlib.source()
                    self.assertEqual(p.read_bytes(), b"modified")

    def test_path_escape_rejected(self):
        for path in ("/escape", "../escape", "newlib-4.5.0.20241231/../../escape", "other/include.h"):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); entry = tarfile.TarInfo(path)
                lock = self.fixture(root, entry)
                with patch.object(newlib, "CACHE", root), patch.object(newlib, "LOCK", lock):
                    with self.assertRaises(ValueError): newlib.source()

    def test_archive_links_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            entry = tarfile.TarInfo("newlib-4.5.0.20241231/link")
            entry.type = tarfile.SYMTYPE; entry.linkname = "../outside"
            lock = self.fixture(root, entry)
            with patch.object(newlib, "CACHE", root), patch.object(newlib, "LOCK", lock):
                with self.assertRaises(ValueError): newlib.source()


if __name__ == "__main__": unittest.main()
