import struct
import unittest
import audit


def object_fixture():
    strings = b"\0.shstrtab\0.text\0"
    header = struct.pack("<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + bytes(9),
                         1, 243, 1, 0, 0, 64, 0, 64, 0, 0, 64, 3, 1)
    empty = bytes(64)
    names = struct.pack("<IIQQQQIIQQ", 1, 3, 0, 0, 256, len(strings), 0, 0, 1, 0)
    text = struct.pack("<IIQQQQIIQQ", 11, 1, 6, 0, 256 + len(strings), 4, 0, 0, 4, 0)
    return bytearray(header + empty + names + text + strings + bytes.fromhex("13000000"))


class AuditTests(unittest.TestCase):
    def test_elf_sections(self):
        sections = audit.elf_sections(object_fixture())
        self.assertEqual(sections[2], {"name": ".text", "type": 1, "flags": 6, "size": 4})

    def test_elf_rejects_bad_profile(self):
        for offset, code, value in ((16, "H", 2), (18, "H", 62), (48, "I", 1),
                                    (48, "I", 4), (58, "H", 32), (60, "H", 0), (62, "H", 9)):
            raw = object_fixture()
            struct.pack_into("<" + code, raw, offset, value)
            with self.subTest(offset=offset, value=value), self.assertRaises(ValueError): audit.elf_sections(raw)

    def test_elf_bounds(self):
        for raw in (b"", object_fixture()[:63], object_fixture()[:-1]):
            with self.assertRaises(ValueError): audit.elf_sections(raw)
        raw = object_fixture()
        struct.pack_into("<Q", raw, 40, 1 << 63)
        with self.assertRaises(ValueError): audit.elf_sections(raw)

    def test_instruction_inventory(self):
        raw = "00000000 <foo>:\n  0: addi a0, zero, 1\n  4: amoadd.w.aqrl a0, a1, (a2)\n  8: jalr zero, 0(ra)\n"
        self.assertEqual(audit.instruction_inventory(raw), {"addi": 1, "amoadd.w.aqrl": 1, "jalr": 1})
        with self.assertRaises(ValueError): audit.instruction_inventory("  0: <unknown>\n")
        with self.assertRaises(ValueError): audit.instruction_inventory("no instructions")

    def test_unresolved_is_exact_and_deduplicated(self):
        log = "ld.lld: error: undefined symbol: _sbrk\nld.lld: error: undefined symbol: __muldi3\nld.lld: error: undefined symbol: _sbrk\n"
        self.assertEqual(audit.unresolved(log), ["__muldi3", "_sbrk"])

    def test_missing_capability_classes(self):
        for sym in ("__muldi3", "__multi3", "__udivdi3"): self.assertEqual(audit.classify(sym), "integer_compiler_runtime")
        self.assertEqual(audit.classify("__atomic_load_8"), "atomic_runtime")
        self.assertEqual(audit.classify("_sbrk"), "platform_or_posix_service")

    def test_instruction_profile_cannot_silently_expand(self):
        self.assertEqual(audit.verify_instructions("rv64i", {"ld": 1, "fence": 2}), [])
        self.assertEqual(audit.verify_instructions("rv64ima", {"mul": 1, "amoadd.w.aqrl": 2}), ["amoadd.w.aqrl", "mul"])
        for isa, op in (("rv64i", "mul"), ("rv64im", "amoadd.w"), ("rv64ima", "csrrw"), ("rv64ima", "fence.i"), ("rv64ima", "fadd.s"), ("rv64i", "ecall")):
            with self.subTest(isa=isa, op=op), self.assertRaises(ValueError): audit.verify_instructions(isa, {op: 1})


if __name__ == "__main__": unittest.main()
