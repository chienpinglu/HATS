"""Original PPE-ISA-0.1 codec, assembler and independent functional reference.

This executes an ISA model, not PPE RTL or a host-substitution execution backend.
The model is the specification-side oracle for the subsequent SpinalHDL core.
"""
from dataclasses import dataclass
import struct

MASK = (1 << 64) - 1
OPS = {name: value for value, name in enumerate((
    "MOVI", "MOV", "ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "SAR", "LT", "LTU",
    "VMOVI", "VMOV", "VADD", "VSUB", "VAND", "VOR", "VXOR", "VSHL", "VSHR", "VSAR",
    "VCMPEQ", "VCMPLT", "VCMPLTU", "SELECT", "JMP", "JNZ", "SPLIT", "JOIN",
    "LOAD", "STORE", "VLOAD", "VSTORE", "FENCE", "BARRIER", "RETURN"), 1)}
NAMES = {value: name for name, value in OPS.items()}
SCALAR_BINARY = {"ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "SAR", "LT", "LTU"}
VECTOR_BINARY = {"V" + n for n in ("ADD", "SUB", "AND", "OR", "XOR", "SHL", "SHR", "SAR")}
COMPARE = {"VCMPEQ", "VCMPLT", "VCMPLTU"}
MEMORY = {"LOAD", "STORE", "VLOAD", "VSTORE"}
HEADER = struct.Struct("<8sHHIHHIII")


def signed(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits-1) else value


@dataclass(frozen=True)
class Instruction:
    op: str
    d: int = 0
    a: int = 0
    b: int = 0
    p: int = 0
    width: int = 0
    flags: int = 0
    imm: int = 0

    def validate(self):
        if self.op not in OPS: raise ValueError("Unknown opcode")
        for name, limit in (("d", 32), ("a", 32), ("b", 32), ("p", 8), ("width", 4), ("flags", 4)):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value < limit: raise ValueError("Invalid operand " + name)
        if type(self.imm) is not int or not (0 <= self.imm < 1 << 32 if self.op == "SPLIT" else -(1 << 31) <= self.imm < 1 << 31):
            raise ValueError("Immediate outside encoding")
        used = set()
        if self.op in SCALAR_BINARY | VECTOR_BINARY | COMPARE | {"SELECT"}:
            used = {"d", "a", "b", "width", "flags"}
            if self.op == "SELECT": used.add("p")
            if self.width not in (2, 3): raise ValueError("Arithmetic width is 32 or 64")
            if self.op in SCALAR_BINARY and self.flags & 2: raise ValueError("Scalar instruction cannot broadcast")
            if self.op in COMPARE and (self.d >= 8 or self.flags & 1): raise ValueError("Invalid predicate result")
            if self.op not in COMPARE and self.flags & 1 and self.width != 2: raise ValueError("Sign extension only applies to 32-bit results")
            if self.op == "SELECT" and self.flags & 2: raise ValueError("Select uses two vector sources")
        elif self.op in {"MOVI", "VMOVI", "MOV", "VMOV"}:
            used = {"d", "width", "flags", "imm" if self.op.endswith("I") else "a"}
            if self.width not in (2, 3) or (self.flags & 1 and self.width != 2): raise ValueError("Invalid move width")
            if self.flags & 2 and self.op != "VMOV": raise ValueError("Broadcast only on VMOV register source")
        elif self.op in MEMORY:
            used = {"d", "a", "width", "flags", "imm"}
            if self.op.startswith("V"): used.add("b")
            if self.op.endswith("STORE") and self.flags & 1: raise ValueError("Store cannot sign-extend")
            if self.width == 3 and self.flags & 1: raise ValueError("64-bit load has no extension flag")
        elif self.op == "SPLIT": used = {"p", "imm"}
        elif self.op == "JMP": used = {"imm"}
        elif self.op == "JNZ": used = {"a", "imm"}
        elif self.op == "RETURN": used = {"a"}
        for field in ("d", "a", "b", "p", "width", "flags", "imm"):
            if field not in used and getattr(self, field): raise ValueError("Nonzero reserved operand " + field)
        return self

    def encode(self):
        self.validate()
        word = OPS[self.op] | self.d << 8 | self.a << 13 | self.b << 18 | self.p << 23 | self.width << 26 | self.flags << 28
        return struct.pack("<II", word, self.imm & 0xffffffff)

    @staticmethod
    def decode(raw):
        if len(raw) != 8: raise ValueError("Instruction is exactly eight bytes")
        low, imm = struct.unpack("<II", raw)
        if low >> 30 or low & 255 not in NAMES: raise ValueError("Reserved bits/unknown opcode")
        op = NAMES[low & 255]
        return Instruction(op, low >> 8 & 31, low >> 13 & 31, low >> 18 & 31, low >> 23 & 7,
                           low >> 26 & 3, low >> 28 & 3, imm if op == "SPLIT" else signed(imm, 32)).validate()


@dataclass(frozen=True)
class Code:
    instructions: tuple
    scratch_bytes: int = 0
    width: int = 8

    def validate(self):
        if self.width != 8 or type(self.scratch_bytes) is not int or not 0 <= self.scratch_bytes <= 4096 or self.scratch_bytes % 16:
            raise ValueError("Unsupported PPE-0.1 resource profile")
        if not 1 <= len(self.instructions) <= 65536: raise ValueError("Invalid code length")
        for instruction in self.instructions: instruction.validate()
        regions, joins = [], set()
        for i, instruction in enumerate(self.instructions):
            if instruction.op == "SPLIT":
                other, join = instruction.imm & 65535, instruction.imm >> 16
                if not i + 1 < other <= join < len(self.instructions) or self.instructions[join].op != "JOIN" or join in joins:
                    raise ValueError("Invalid structured split/join targets")
                if self.instructions[other-1].op != "JMP" or other-1 + self.instructions[other-1].imm != join:
                    raise ValueError("Then arm must end with explicit jump to its JOIN")
                regions.append((i, other, join)); joins.add(join)
        if joins != {i for i, instruction in enumerate(self.instructions) if instruction.op == "JOIN"}:
            raise ValueError("Unowned JOIN")
        for start, other, end in regions:
            for inner, inner_other, inner_end in regions:
                if start < inner < end and not (inner_end < other if inner < other else inner_end < end):
                    raise ValueError("Structured regions cross arms or share a JOIN")
        contexts = []
        for i in range(len(self.instructions)):
            contexts.append(tuple((start, 0 if i < other else 1, end) for start, other, end in regions if start < i < end))
        for i, instruction in enumerate(self.instructions):
            if instruction.op in ("JMP", "JNZ"):
                dest = i + instruction.imm
                if not 0 <= dest < len(self.instructions): raise ValueError("Branch out of code")
                if dest in joins and not (contexts[i] and dest == contexts[i][-1][2]):
                    raise ValueError("Branch enters unowned JOIN")
                if contexts[i] != contexts[dest] and not (contexts[i] and dest == contexts[i][-1][2]):
                    raise ValueError("Branch crosses structured region")
        return self

    def encode(self):
        self.validate()
        return HEADER.pack(b"HATSPPE\0", 0, 1, 0, self.width, 32, self.scratch_bytes, len(self.instructions), 0) + b"".join(i.encode() for i in self.instructions)

    @staticmethod
    def decode(raw):
        if len(raw) < HEADER.size: raise ValueError("Truncated code object")
        magic, major, minor, flags, width, registers, scratch, count, entry = HEADER.unpack_from(raw)
        if (magic, major, minor, flags, registers, entry) != (b"HATSPPE\0", 0, 1, 0, 32, 0) or len(raw) != HEADER.size + count * 8:
            raise ValueError("Code-object header/profile/length mismatch")
        return Code(tuple(Instruction.decode(raw[i:i+8]) for i in range(HEADER.size, len(raw), 8)), scratch, width).validate()


def assemble(items, scratch_bytes=0):
    """Two-pass Python API: labels end ':', instructions are (opcode, kwargs).
    JMP/JNZ 'target' is a label; SPLIT 'other'/'join' are labels. No eval().
    """
    labels, count = {}, 0
    for item in items:
        if isinstance(item, str):
            if not item.endswith(":") or not item[:-1] or item[:-1] in labels: raise ValueError("Invalid/duplicate label")
            labels[item[:-1]] = count
        else: count += 1
    result = []
    for item in items:
        if isinstance(item, str): continue
        name, operands = item; operands = dict(operands)
        if name in ("JMP", "JNZ") and "target" in operands: operands["imm"] = labels[operands.pop("target")] - len(result)
        if name == "SPLIT": operands["imm"] = labels[operands.pop("other")] | labels[operands.pop("join")] << 16
        if name in SCALAR_BINARY | VECTOR_BINARY | COMPARE | MEMORY | {"SELECT", "MOV", "MOVI", "VMOV", "VMOVI"}: operands.setdefault("width", 3)
        result.append(Instruction(name, **operands))
    return Code(tuple(result), scratch_bytes).encode()


def disassemble(raw):
    code = Code.decode(raw)
    return [f"{i*8:08x}: {v.op} d={v.d} a={v.a} b={v.b} p={v.p} width={v.width} flags={v.flags} imm={v.imm}"
            for i, v in enumerate(code.instructions)]


class Fault(Exception):
    def __init__(self, cause, address=0, lanes=0):
        self.cause, self.address, self.lanes = cause, address, lanes
        super().__init__(f"PPE fault {cause} at {address:#x} lanes={lanes:#x}")


class Memory:
    def __init__(self, data, base=0, writable=True, fail_addresses=()):
        self.data, self.base, self.writable = bytearray(data), base, writable
        if type(base) is not int or not 0 <= base <= MASK or base + len(self.data) > 1 << 64:
            raise ValueError("Memory span outside address space")
        self.fail_addresses, self.events = set(fail_addresses), []

    def access(self, address, size, store=False, value=0, lane=0):
        cause = (2 if address % size else 3 if not self.base <= address or address + size > self.base + len(self.data)
                 or address + size > 1 << 64 or (store and not self.writable) else 4 if address in self.fail_addresses else 0)
        if cause:
            self.events.append({"address": address, "size": size, "store": store, "lane": lane, "error": cause})
            raise Fault(cause, address, 1 << lane)
        offset = address - self.base
        if store: self.data[offset:offset+size] = (value & ((1 << (size*8))-1)).to_bytes(size, "little")
        else: value = int.from_bytes(self.data[offset:offset+size], "little")
        self.events.append({"address": address, "size": size, "store": store, "lane": lane, "value": value & ((1 << (size*8))-1), "error": 0})
        return value


class Wave:
    def __init__(self, code, memory, argument=0, argument_bytes=0, group=0, groups=1, task=1):
        self.code = Code.decode(code); self.memory = memory
        if not 0 <= argument <= MASK or not 0 <= argument_bytes <= MASK or argument + argument_bytes > 1 << 64:
            raise ValueError("Argument span overflow")
        if not 0 <= group < groups <= 0xffffffff or not 1 <= task <= MASK: raise ValueError("Invalid launch identity/geometry")
        self.scalar = [0]*32; self.scalar[:7] = [argument, argument_bytes, group, groups, 8, 0, task]
        self.vector = [[0]*8 for _ in range(32)]; self.vector[0] = list(range(8)); self.vector[1] = list(range(8))
        self.predicate = [0]*8; self.active = 255; self.stack = []; self.pc = 0
        self.scratch = Memory(bytes(self.code.scratch_bytes))
        self.trace = []; self.completion = None

    def uniform(self):
        if self.stack or self.active != 255: raise Fault(6)

    def step(self):
        if self.completion is not None: raise ValueError("Wave already completed")
        before_s = list(self.scalar); before_v = [list(v) for v in self.vector]; before_p = list(self.predicate)
        pc, mask = self.pc, self.active
        i = self.code.instructions[pc] if 0 <= pc < len(self.code.instructions) else None
        try:
            if i is None or not self.active: raise Fault(1)
            op = i.op; next_pc = pc + 1; bits = 32 if i.width == 2 else 64; word_mask = (1 << bits)-1
            def result(value):
                value &= word_mask
                return (signed(value, 32) & MASK) if i.flags & 1 else value
            def binary(name, a, b):
                a &= word_mask; b &= word_mask
                if name == "ADD": return a + b
                if name == "SUB": return a - b
                if name == "AND": return a & b
                if name == "OR": return a | b
                if name == "XOR": return a ^ b
                if name == "SHL": return a << (b & (bits-1))
                if name == "SHR": return a >> (b & (bits-1))
                if name == "SAR": return signed(a, bits) >> (b & (bits-1))
                if name == "LT": return int(signed(a,bits) < signed(b,bits))
                if name == "LTU": return int(a < b)
                raise Fault(1)
            lanes = [n for n in range(8) if self.active >> n & 1]
            if op in SCALAR_BINARY | {"MOVI", "MOV"}:
                self.uniform()
                value = i.imm if op == "MOVI" else self.scalar[i.a] if op == "MOV" else binary(op, self.scalar[i.a], self.scalar[i.b])
                self.scalar[i.d] = result(value)
            elif op in VECTOR_BINARY | {"VMOVI", "VMOV", "SELECT"}:
                values = []
                for lane in lanes:
                    if op == "VMOVI": value = i.imm
                    elif op == "VMOV": value = self.scalar[i.a] if i.flags & 2 else self.vector[i.a][lane]
                    elif op == "SELECT": value = self.vector[i.a if self.predicate[i.p] >> lane & 1 else i.b][lane]
                    else: value = binary(op[1:], self.vector[i.a][lane], self.scalar[i.b] if i.flags & 2 else self.vector[i.b][lane])
                    values.append(result(value))
                for lane, value in zip(lanes, values): self.vector[i.d][lane] = value
            elif op in COMPARE:
                value = self.predicate[i.d]
                for lane in lanes:
                    a = self.vector[i.a][lane] & word_mask
                    b = (self.scalar[i.b] if i.flags & 2 else self.vector[i.b][lane]) & word_mask
                    yes = a == b if op == "VCMPEQ" else signed(a,bits) < signed(b,bits) if op == "VCMPLT" else a < b
                    value = value | 1 << lane if yes else value & ~(1 << lane)
                self.predicate[i.d] = value
            elif op in ("JMP", "JNZ"):
                if op == "JMP" or self.scalar[i.a]: next_pc = pc + i.imm
            elif op == "SPLIT":
                if len(self.stack) >= 8: raise Fault(7)
                true = self.active & self.predicate[i.p]; false = self.active & ~self.predicate[i.p]
                other, join = i.imm & 65535, i.imm >> 16
                self.stack.append([self.active, false, other, join, bool(true)])
                self.active = true if true else false
                if not true: next_pc = other
            elif op == "JOIN":
                if not self.stack or self.stack[-1][3] != pc: raise Fault(6)
                frame = self.stack[-1]
                if frame[4] and frame[1]: frame[4] = False; self.active = frame[1]; next_pc = frame[2]
                else: self.active = frame[0]; self.stack.pop()
            elif op in MEMORY:
                vector = op.startswith("V"); store = op.endswith("STORE")
                if not vector: self.uniform()
                memory = self.scratch if i.flags & 2 else self.memory
                loaded = []
                for lane in lanes if vector else [0]:
                    address = self.scalar[i.a] + (self.vector[i.b][lane] if vector else 0) + i.imm
                    if not 0 <= address <= MASK: raise Fault(3, address & MASK, (1 << lane) if vector else 0)
                    data = self.vector[i.d][lane] if vector else self.scalar[i.d]
                    try: value = memory.access(address, 1 << i.width, store, data, lane)
                    except Fault as fault:
                        if not vector: fault.lanes = 0
                        raise
                    if not store: loaded.append((lane, signed(value, 8 << i.width) & MASK if i.flags & 1 else value))
                # All-lane register publication is delayed until every read succeeds.
                for lane, value in loaded:
                    if vector: self.vector[i.d][lane] = value
                    else: self.scalar[i.d] = value
            elif op in ("FENCE", "BARRIER"):
                self.uniform()  # Synchronous functional memory is already drained.
            elif op == "RETURN":
                self.uniform(); self.completion = {"status": "success", "value": self.scalar[i.a], "pc": pc*8}
            else: raise Fault(1)
            self.pc = next_pc
            self.trace.append({"pc": pc*8, "opcode": op, "mask": mask, "next_pc": next_pc*8,
                               "scalar": [(n,v) for n,v in enumerate(self.scalar) if v != before_s[n]],
                               "vector": [(n,lane,v) for n,row in enumerate(self.vector) for lane,v in enumerate(row) if v != before_v[n][lane]],
                               "predicate": [(n,v) for n,v in enumerate(self.predicate) if v != before_p[n]]})
        except Fault as fault:
            self.completion = {"status": "fault", "cause": fault.cause, "pc": pc*8,
                               "address": fault.address, "lane_mask": fault.lanes}
        return self.completion

    def run(self, budget=10000):
        if type(budget) is not int or budget <= 0: raise ValueError("Invalid reference instruction budget")
        for _ in range(budget):
            if self.step() is not None: return self.completion
        self.completion = {"status": "fault", "cause": 5, "pc": self.pc*8, "address": 0, "lane_mask": 0}
        return self.completion
