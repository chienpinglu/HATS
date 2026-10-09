import copy
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import image
import run as execution


class ImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Original minimal ELF fixture generated through the actual linker script.
        with tempfile.TemporaryDirectory(prefix="hats-tool-elf-") as directory:
            root = Path(directory)
            source = ".option norvc\n.section .text.start,\"ax\"\n.globl _start,ape_exit\n_start:\n nop\nape_exit:\n ebreak\n.section .rodata\n.byte 1\n.section .data\n.word 1\n.section .bss\n.zero 16\n"
            subprocess.run([execution.newlib.tool("clang"), "--target=riscv64-unknown-elf", "-march=rv64i", "-mabi=lp64",
                            "-x", "assembler", "-c", "-", "-o", str(root / "fixture.o")], input=source, text=True, check=True, capture_output=True)
            subprocess.run([execution.newlib.tool("ld.lld"), "--no-relax", "--no-undefined", "-T", str(execution.ROOT / "link.ld"),
                            str(root / "fixture.o"), "-o", str(root / "fixture.elf")], check=True, capture_output=True)
            cls.raw = (root / "fixture.elf").read_bytes()

    def test_valid_image_and_poisoned_bss(self):
        code, data, profile = image.decode(self.raw)
        self.assertEqual((len(code), len(data)), (image.CODE_BYTES, image.DATA_BYTES))
        a, b = profile["bss_start"] - image.DATA_BASE, profile["bss_end"] - image.DATA_BASE
        self.assertEqual(data[a:b], b"\xa5" * (b-a))
        self.assertEqual(profile["exit_pc"], 4)

    def test_bad_headers(self):
        for fmt, offset, value in [("H", 16, 1), ("H", 18, 183), ("Q", 24, 4), ("I", 48, 1),
                                   ("H", 54, 55), ("H", 56, 0), ("H", 60, 129), ("Q", 40, 1 << 63)]:
            raw = bytearray(self.raw); struct.pack_into("<" + fmt, raw, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError): image.decode(raw)
        for size in (0, 63, 100, len(self.raw)-1):
            with self.assertRaises(ValueError): image.decode(self.raw[:size])

    def test_bad_segments_and_exit(self):
        phoff = struct.unpack_from("<Q", self.raw, 32)[0]
        for fmt, offset, value in [("I", 0, 2), ("I", 4, 7), ("Q", 8, 1 << 63),
                                   ("Q", 16, 4), ("Q", 32, 1 << 32), ("Q", 40, 0), ("Q", 48, 3)]:
            raw = bytearray(self.raw); struct.pack_into("<" + fmt, raw, phoff+offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError): image.decode(raw)
        raw = bytearray(self.raw)
        text = struct.unpack_from("<Q", raw, phoff+8)[0]
        struct.pack_into("<I", raw, text+4, 0x00000013)
        with self.assertRaises(ValueError): image.decode(raw)


class ResultTests(unittest.TestCase):
    def test_imported_checker_and_dependency_sources_are_bound(self):
        hashes = execution.own_hashes()
        for name in ("workloads/native/treesitter/run.py", "workloads/native/treesitter/cases.lock.json",
                     "workloads/target/treesitter/audit.py", "workloads/target/treesitter/newlib.py",
                     "hardware/spinal/tools/bootstrap_spike.py", "hardware/spinal/tools/spike.lock.json"):
            self.assertEqual(hashes[name], execution.newlib.sha(execution.REPO / name))

    def output(self):
        raw = bytearray(image.OUTPUT_BYTES)
        struct.pack_into("<8Q", raw, 0, image.MAGIC, 0, 0, 1, 0, 100, 1, 4096)
        struct.pack_into("<4I", raw, 64, 2, 0, 2, 0)
        return raw

    def test_valid_output_and_independent_oracle(self):
        result = execution.decode_result(self.output())
        self.assertEqual(result["nodes"], [["object", 0, 2, 0]])
        self.assertTrue(execution.native.check_output(b"{}", result)["valid_json"])

    def test_invalid_result_headers_and_nodes(self):
        for fmt, offset, value in [("Q", 0, 0), ("Q", 8, 6), ("Q", 16, 2), ("Q", 24, 1 << 32),
                                   ("I", 64, 0), ("I", 64, 8), ("I", 68, 3), ("I", 76, 1025)]:
            raw = self.output(); struct.pack_into("<" + fmt, raw, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError): execution.decode_result(raw)
        with self.assertRaises(ValueError): execution.decode_result(self.output()[:-1])

    def test_semantic_mutations_do_not_pass(self):
        for offset, value in ((32, 1), (64, 1), (72, 1), (76, 1)):
            raw = self.output(); struct.pack_into("<I", raw, offset, value)
            with self.assertRaises(ValueError): execution.native.check_output(b"{}", execution.decode_result(raw))

    def test_helper_edge_oracle(self):
        mask = (1 << 64)-1
        self.assertEqual(execution.expected_helpers((mask, 0, 2, 0)), (mask-1, mask//2, 1, mask, mask-1, 1))
        self.assertEqual(execution.expected_helpers((1 << 63, 0, mask, 0))[3], 0)
        self.assertEqual(execution.expected_helpers((7, 0, 0, 0)), (0, mask, 7, 7, 0, 0))
        self.assertEqual(len(execution.vectors()), 177)


if __name__ == "__main__": unittest.main()
