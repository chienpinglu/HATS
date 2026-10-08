"""Malformed executable and workload-output rejection tests."""
import struct
import unittest
from pathlib import Path
from ape_app_image import decode_elf
from check_ape_diff import check_output, lines


class ImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (Path(__file__).resolve().parents[1] / "build/ape_app/diff.elf").read_bytes()

    def test_valid_segments(self):
        code, data, profile = decode_elf(self.raw)
        self.assertEqual((len(code), len(data)), (4096, 65536))
        a, b = [profile["symbols"][k]-0x10000 for k in ("__bss_start", "__bss_end")]
        self.assertEqual(data[a:b], bytes(b-a))
        self.assertEqual(struct.unpack_from("<Q", data, 16)[0], 0x48415453)
        self.assertEqual(data[:5], b"HATS\0")

    def test_truncated_files(self):
        for length in (0, 6, 63, 100, len(self.raw)-1):
            with self.subTest(length=length), self.assertRaises(ValueError):
                decode_elf(self.raw[:length])

    def test_invalid_headers(self):
        for fmt, offset, value in [("H", 16, 3), ("H", 18, 183), ("Q", 24, 4), ("I", 48, 1),
                                   ("H", 54, 55), ("H", 56, 65535), ("H", 60, 0), ("Q", 40, 2**63)]:
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                bad = bytearray(self.raw); struct.pack_into("<"+fmt, bad, offset, value); decode_elf(bad)

    def test_invalid_segments(self):
        phoff = struct.unpack_from("<Q", self.raw, 32)[0]
        for fmt, offset, value in [("I", 0, 2), ("I", 4, 7), ("Q", 8, 2**63),
                                   ("Q", 16, 4), ("Q", 32, 2**63), ("Q", 40, 0), ("Q", 48, 3)]:
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                bad = bytearray(self.raw); struct.pack_into("<"+fmt, bad, phoff+offset, value); decode_elf(bad)

    def test_relocations_rejected(self):
        bad = bytearray(self.raw)
        shoff = struct.unpack_from("<Q", bad, 40)[0]
        struct.pack_into("<I", bad, shoff+64+4, 4)
        with self.assertRaises(ValueError):
            decode_elf(bad)


class DiffTests(unittest.TestCase):
    def test_line_boundaries(self):
        for text in (b"", b"a\n", b"a", b"\n\n", b"a\r\nb", b"\0\xff\n"):
            self.assertEqual(b"".join(lines(text)), text)

    def image(self):
        result = bytearray(65536)
        struct.pack_into("<5I", result, 0x8000, 0, 2, 2, 1, 1)
        struct.pack_into("<6I", result, 0x8014, 1, 0, 0, 2, 1, 0)
        return result

    def test_valid_output(self):
        self.assertEqual(check_output(self.image(), b"old\n", b"new\n", 0)["cost"], 2)

    def test_corrupt_output(self):
        for offset, value in ((0, 1), (4, 65), (8, 1), (12, 2), (20, 0), (24, 1), (28, 1)):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                bad = self.image(); struct.pack_into("<I", bad, 0x8000+offset, value)
                check_output(bad, b"old\n", b"new\n", 0)

    def test_nonminimal_script(self):
        with self.assertRaises(ValueError):
            check_output(self.image(), b"same\n", b"same\n", 0)

    def test_rejection_output(self):
        image = bytearray(65536)
        struct.pack_into("<I", image, 0x8000, 1)
        self.assertEqual(check_output(image, b"a"*513, b"", 1)["status"], 1)
        struct.pack_into("<I", image, 0x8004, 1)
        with self.assertRaises(ValueError):
            check_output(image, b"a"*513, b"", 1)


if __name__ == "__main__":
    unittest.main()
