import struct
import unittest
import ppe_isa as p
from ppe_programs import delimiter_candidates


def op(name, **fields): return name, fields


class EncodingTests(unittest.TestCase):
    def test_known_instruction_bytes(self):
        instruction = p.Instruction("ADD", d=1, a=2, b=3, width=3)
        self.assertEqual(instruction.encode(), struct.pack("<II", 0x0c0c4103, 0))
        self.assertEqual(p.Instruction.decode(instruction.encode()), instruction)
        self.assertEqual(p.Instruction.decode(p.Instruction("MOVI", d=9, width=3, imm=-1).encode()).imm, -1)

    def test_code_roundtrip(self):
        raw = p.assemble([op("MOVI", d=8, imm=42), op("RETURN", a=8)], scratch_bytes=16)
        self.assertEqual(len(raw), 48)
        self.assertEqual(p.Code.decode(raw).encode(), raw)
        self.assertIn("MOVI", p.disassemble(raw)[0])
        self.assertEqual(p.HEADER.size, 32)

    def test_illegal_encodings(self):
        for raw in (bytes(8), struct.pack("<II", 0xc0000001, 0), bytes(7), bytes(9)):
            with self.assertRaises(ValueError): p.Instruction.decode(raw)
        for instruction in (p.Instruction("ADD"), p.Instruction("MOVI", d=32, width=3),
                            p.Instruction("RETURN", d=1), p.Instruction("STORE", flags=1),
                            p.Instruction("VMOVI", width=3, flags=2), p.Instruction("VCMPEQ", d=8, width=3),
                            p.Instruction("MOVI", width=3, imm=1 << 31), p.Instruction("JOIN", imm=1)):
            with self.subTest(instruction=instruction), self.assertRaises(ValueError): instruction.encode()

    def test_invalid_code_headers(self):
        raw = p.assemble([op("RETURN")])
        for offset in (0, 8, 10, 12, 16, 18, 24, 28):
            bad = bytearray(raw); bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError): p.Code.decode(bad)
        with self.assertRaises(ValueError): p.Code.decode(raw[:-1])
        with self.assertRaises(ValueError): p.Code.decode(raw + bytes(8))
        with self.assertRaises(ValueError): p.assemble([op("RETURN")], scratch_bytes=4112)

    def test_structured_targets(self):
        for items in ([op("JOIN"), op("RETURN")], [op("JMP", imm=3), op("RETURN")],
                      [op("SPLIT", p=0, other="else", join="end"), op("VMOVI", d=2, imm=1),
                       "else:", op("VMOVI", d=2, imm=2), "end:", op("JOIN"), op("RETURN")]):
            with self.assertRaises(ValueError): p.assemble(items)
        items = [op("JMP", target="end"), op("SPLIT", p=0, other="else", join="end"),
                 op("JMP", target="end"), "else:", "end:", op("JOIN"), op("RETURN")]
        with self.assertRaises(ValueError): p.assemble(items)


class WaveTests(unittest.TestCase):
    def run_code(self, items, memory=None, scratch=0, **launch):
        wave = p.Wave(p.assemble(items, scratch), memory if memory is not None else p.Memory(bytes(128)), **launch)
        wave.run(); return wave

    def test_scalar_arithmetic_and_width(self):
        expected = {"ADD": 5, "SUB": p.MASK-8, "AND": 6, "OR": p.MASK, "XOR": p.MASK-6,
                    "SHL": (-2 << 7) & p.MASK, "SHR": (p.MASK-1) >> 7, "SAR": p.MASK,
                    "LT": 1, "LTU": 0}
        for name, value in expected.items():
            w = self.run_code([op("MOVI", d=8, imm=-2), op("MOVI", d=9, imm=7), op(name, d=10, a=8, b=9), op("RETURN", a=10)])
            self.assertEqual(w.completion["value"], value, name)
        w = self.run_code([op("MOVI", d=8, imm=-1, width=2), op("MOV", d=9, a=8, width=2, flags=1), op("RETURN", a=9)])
        self.assertEqual(w.scalar[8], 0xffffffff); self.assertEqual(w.scalar[9], p.MASK)

    def test_vector_broadcast_select_and_signed_compare(self):
        w = self.run_code([op("MOVI", d=8, imm=3), op("VADD", d=2, a=0, b=8, flags=2),
                           op("VCMPLTU", d=0, a=0, b=8, flags=2), op("SELECT", d=3, a=0, b=2, p=0),
                           op("VMOVI", d=4, imm=-1), op("VCMPLT", d=1, a=4, b=0), op("RETURN")])
        self.assertEqual(w.vector[2], list(range(3, 11)))
        self.assertEqual(w.vector[3], [0, 1, 2, 6, 7, 8, 9, 10])
        self.assertEqual(w.predicate[:2], [7, 255])

    def split_program(self, cutoff, then_ops=None, else_ops=None):
        return [op("MOVI", d=8, imm=cutoff), op("VCMPLTU", d=0, a=0, b=8, flags=2),
                op("SPLIT", p=0, other="else", join="join"), *(then_ops or [op("VMOVI", d=2, imm=10)]),
                op("JMP", target="join"), "else:", *(else_ops or [op("VMOVI", d=2, imm=20)]),
                "join:", op("JOIN"), op("RETURN")]

    def test_reconvergence_all_true_false_and_mixed(self):
        for cutoff in (0, 4, 8):
            w = self.run_code(self.split_program(cutoff))
            self.assertEqual(w.completion["status"], "success")
            self.assertEqual(w.vector[2], [10]*cutoff + [20]*(8-cutoff))
            self.assertEqual((w.active, w.stack), (255, []))

    def test_scalar_write_barrier_return_forbidden_in_arm(self):
        for instruction in (op("MOVI", d=9, imm=1), op("BARRIER"), op("RETURN")):
            w = self.run_code(self.split_program(8, then_ops=[instruction]))
            self.assertEqual(w.completion["cause"], 6)
            self.assertEqual(w.scalar[9], 0)

    def test_masked_faults_are_suppressed(self):
        prefix = [op("MOVI", d=9, imm=3), op("VSHL", d=4, a=0, b=9, flags=2)]
        memory = p.Memory(struct.pack("<4Q", 11, 22, 33, 44), base=0x100)
        w = self.run_code(prefix + self.split_program(4, [op("VLOAD", d=2, a=0, b=4)]), memory, argument=0x100)
        self.assertEqual(w.completion["status"], "success")
        self.assertEqual(w.vector[2], [11, 22, 33, 44, 20, 20, 20, 20])
        self.assertEqual(len(memory.events), 4)

    def test_vector_load_has_no_partial_destination_commit(self):
        memory = p.Memory(bytes(64), base=0x100, fail_addresses=[0x108])
        w = self.run_code([op("VMOVI", d=2, imm=99), op("MOVI", d=8, imm=3), op("VSHL", d=3, a=0, b=8, flags=2),
                           op("VLOAD", d=2, a=0, b=3), op("RETURN")], memory, argument=0x100)
        self.assertEqual((w.completion["cause"], w.completion["lane_mask"]), (4, 2))
        self.assertEqual(w.vector[2], [99]*8)
        self.assertEqual(len(memory.events), 2)

    def test_partial_vector_stores_are_not_rollback(self):
        memory = p.Memory(bytes(64), base=0x100, fail_addresses=[0x110])
        w = self.run_code([op("MOVI", d=8, imm=100), op("VADD", d=2, a=0, b=8, flags=2),
                           op("MOVI", d=9, imm=3), op("VSHL", d=3, a=0, b=9, flags=2),
                           op("VSTORE", d=2, a=0, b=3), op("RETURN")], memory, argument=0x100)
        self.assertEqual((w.completion["cause"], w.completion["lane_mask"]), (4, 4))
        self.assertEqual(struct.unpack("<8Q", memory.data), (100, 101, 0, 0, 0, 0, 0, 0))

    def test_scratch_sign_extension_and_scalar_fault_mask(self):
        w = self.run_code([op("MOVI", d=8, imm=-1), op("STORE", d=8, a=9, imm=8, width=1, flags=2),
                           op("LOAD", d=10, a=9, imm=8, width=1, flags=3), op("FENCE"), op("BARRIER"), op("RETURN", a=10)], scratch=16)
        self.assertEqual(w.completion["value"], p.MASK)
        self.assertFalse(w.memory.events)
        w = self.run_code([op("LOAD", d=8, a=0, imm=1), op("RETURN")])
        self.assertEqual((w.completion["cause"], w.completion["lane_mask"]), (2, 0))

    def test_budget_and_launch_state(self):
        w = p.Wave(p.assemble([op("JMP", imm=0)]), p.Memory(bytes(64)), argument=16, argument_bytes=24, group=2, groups=3, task=7)
        self.assertEqual(w.scalar[:7], [16, 24, 2, 3, 8, 0, 7])
        self.assertEqual(w.run(17)["cause"], 5); self.assertEqual(len(w.trace), 17)
        with self.assertRaises(ValueError): w.step()
        with self.assertRaises(ValueError): p.Wave(p.assemble([op("RETURN")]), p.Memory(bytes(1)), group=1, groups=1)

    def test_nested_divergence_and_inactive_predicates(self):
        items = [op("MOVI", d=8, imm=4), op("MOVI", d=9, imm=2),
                 op("VCMPLTU", d=0, a=0, b=8, flags=2),
                 op("VCMPLTU", d=1, a=0, b=9, flags=2), op("VCMPEQ", d=2, a=0, b=0),
                 op("SPLIT", p=0, other="outer_else", join="outer_join"),
                 op("VCMPLTU", d=2, a=0, b=0),
                 op("SPLIT", p=1, other="inner_else", join="inner_join"),
                 op("VMOVI", d=3, imm=10), op("JMP", target="inner_join"),
                 "inner_else:", op("VMOVI", d=3, imm=20), "inner_join:", op("JOIN"),
                 op("JMP", target="outer_join"), "outer_else:", op("VMOVI", d=3, imm=30),
                 "outer_join:", op("JOIN"), op("RETURN")]
        w = self.run_code(items)
        self.assertEqual(w.completion["status"], "success")
        self.assertEqual(w.vector[3], [10, 10, 20, 20, 30, 30, 30, 30])
        self.assertEqual(w.predicate[2], 0xf0)
        self.assertEqual((w.active, w.stack), (255, []))

    def test_empty_else_and_depth_limit(self):
        w = self.run_code([op("MOVI", d=8, imm=4), op("VCMPLTU", d=0, a=0, b=8, flags=2),
                           op("SPLIT", p=0, other="end", join="end"), op("VMOVI", d=3, imm=7),
                           op("JMP", target="end"), "end:", op("JOIN"), op("RETURN")])
        self.assertEqual(w.vector[3], [7]*4 + [0]*4)
        self.assertEqual(w.completion["status"], "success")

        def nested(depth):
            if not depth: return [op("VMOVI", d=3, imm=1)]
            return [op("SPLIT", p=0, other=f"e{depth}", join=f"j{depth}"), *nested(depth-1),
                    op("JMP", target=f"j{depth}"), f"e{depth}:", f"j{depth}:", op("JOIN")]
        for depth in (8, 9):
            w = self.run_code([op("VCMPEQ", d=0, a=0, b=0), *nested(depth), op("RETURN")])
            if depth == 8:
                self.assertEqual(w.completion["status"], "success")
                self.assertEqual(w.vector[3], [1]*8)
            else:
                self.assertEqual(w.completion["cause"], 7)
                self.assertEqual((len(w.stack), w.vector[3]), (8, [0]*8))

    def test_address_overflow_has_correct_fault_mask_and_no_request(self):
        for vector in (False, True):
            for base, displacement in ((0, -1), (p.MASK, 1)):
                memory = p.Memory(bytes(16))
                w = self.run_code([op("VLOAD" if vector else "LOAD", d=8, a=0, b=2 if vector else 0,
                                      imm=displacement, width=0), op("RETURN")], memory, argument=base)
                self.assertEqual((w.completion["cause"], w.completion["lane_mask"]), (3, 1 if vector else 0))
                self.assertEqual(w.completion["address"], (base+displacement) & p.MASK)
                self.assertFalse(memory.events)

    def test_readonly_and_scratch_bounds(self):
        memory = p.Memory(bytes(16), writable=False)
        w = self.run_code([op("MOVI", d=8, imm=7), op("STORE", d=8), op("RETURN")], memory)
        self.assertEqual((w.completion["cause"], w.completion["lane_mask"]), (3, 0))
        self.assertEqual(memory.data, bytes(16))
        w = self.run_code([op("LOAD", d=8, imm=16, flags=2), op("RETURN")], scratch=16)
        self.assertEqual(w.completion["cause"], 3)
        self.assertFalse(w.memory.events)
        self.assertEqual(w.scalar[8], 0)

    def test_vector_arithmetic_matches_independent_values(self):
        expected = {"VADD": 5, "VSUB": p.MASK-8, "VAND": 6, "VOR": p.MASK, "VXOR": p.MASK-6,
                    "VSHL": (-2 << 7) & p.MASK, "VSHR": (p.MASK-1) >> 7, "VSAR": p.MASK}
        for name, value in expected.items():
            w = self.run_code([op("VMOVI", d=2, imm=-2), op("VMOVI", d=3, imm=7),
                               op(name, d=4, a=2, b=3), op("RETURN")])
            self.assertEqual(w.vector[4], [value]*8, name)
        w = self.run_code([op("MOVI", d=8, imm=-1), op("VMOV", d=2, a=8, width=2, flags=2),
                           op("VMOV", d=3, a=2, width=2, flags=1), op("RETURN")])
        self.assertEqual(w.vector[2], [0xffffffff]*8)
        self.assertEqual(w.vector[3], [p.MASK]*8)

    def test_conditional_loop_and_fallthrough_fault(self):
        w = self.run_code([op("MOVI", d=8, imm=3), op("MOVI", d=9, imm=1), "loop:",
                           op("SUB", d=8, a=8, b=9), op("JNZ", a=8, target="loop"), op("RETURN", a=8)])
        self.assertEqual(w.completion["value"], 0)
        self.assertEqual(len(w.trace), 9)
        w = self.run_code([op("VMOVI", d=2, imm=1)])
        self.assertEqual((w.completion["cause"], w.completion["pc"]), (1, 8))

    def test_delimiter_program_with_tail_groups_and_canaries(self):
        # Independent byte-class oracle includes punctuation inside strings;
        # classification is not a complete JSON tokenization/parsing claim.
        fixtures = [b"", b"{", b"{}[]:,ab", b"{}[]:,abc",
                    '{"text":"inside { and 中文","values":[1,2,3]}'.encode(), bytes(range(256))]
        code = delimiter_candidates()
        for raw in fixtures:
            base, source, output = 0x1000, 0x1100, 0x1300
            data = bytearray(b"\xa5" * 0x500)
            struct.pack_into("<3Q", data, 0, source, output, len(raw))
            data[source-base:source-base+len(raw)] = raw
            memory = p.Memory(data, base=base)
            groups = max(1, (len(raw)+7)//8)
            for group in range(groups):
                wave = p.Wave(code, memory, argument=base, argument_bytes=24, group=group, groups=groups)
                self.assertEqual(wave.run()["status"], "success")
                self.assertEqual((wave.active, wave.stack), (255, []))
            expected = bytearray(data)
            expected[output-base:output-base+len(raw)] = bytes(int(byte in b"{}[]:,") for byte in raw)
            self.assertEqual(memory.data, expected)
            writes = [e for e in memory.events if e["store"]]
            self.assertEqual([e["address"] for e in writes], list(range(output, output+len(raw))))


if __name__ == "__main__": unittest.main()
