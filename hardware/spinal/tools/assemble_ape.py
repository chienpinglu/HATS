#!/usr/bin/env python3
"""Compile/link real RV64I inputs and extract checked ELF code images for APE RTL."""
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/ape/programs"


def find_tool(variable, candidates):
    supplied = os.environ.get(variable)
    for name in ([supplied] if supplied else candidates):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError(f"Missing tool; set {variable}. Candidates: {candidates}")


def extract(path):
    raw = path.read_bytes()
    if raw[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Expected little-endian ELF64")
    typ, machine = struct.unpack_from("<HH", raw, 16)
    entry = struct.unpack_from("<Q", raw, 24)[0]
    flags = struct.unpack_from("<I", raw, 48)[0]
    if (typ, machine, entry, flags) != (2, 243, 0, 0):
        raise ValueError(f"Expected linked RV64 soft-float/non-RVC executable: {typ, machine, entry, flags}")
    offset = struct.unpack_from("<Q", raw, 40)[0]
    size, count, strings = struct.unpack_from("<HHH", raw, 58)
    headers = [struct.unpack_from("<IIQQQQIIQQ", raw, offset + i * size) for i in range(count)]
    names_h = headers[strings]
    names = raw[names_h[4]:names_h[4] + names_h[5]]
    code = None
    for h in headers:
        name = names[h[0]:].split(b"\0")[0].decode()
        if h[1] in (4, 9) and h[5]:
            raise ValueError("Unresolved relocations")
        if h[2] & 2 and h[5] and name != ".text":
            raise ValueError(f"Unexpected allocated section {name}; data loading not implemented")
        if name == ".text":
            if h[3] != 0:
                raise ValueError("Text not linked at PC zero")
            code = raw[h[4]:h[4] + h[5]]
    if not code or len(code) % 4 or len(code) > 4096:
        raise ValueError("Invalid code size")
    return struct.unpack("<" + "I" * (len(code) // 4), code)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    clang = find_tool("HATS_RV_CLANG", ["/opt/homebrew/opt/llvm/bin/clang", "clang"])
    linker = find_tool("HATS_RV_LD", ["/opt/homebrew/opt/llvm/bin/ld.lld", "/opt/homebrew/opt/lld/bin/ld.lld", "ld.lld"])
    common = [clang, "--target=riscv64-unknown-elf", "-march=rv64i", "-mabi=lp64", "-mno-relax"]
    manifest = {"clang": subprocess.check_output([clang, "--version"], text=True).splitlines()[0],
                "linker": subprocess.check_output([linker, "--version"], text=True).strip(),
                "programs": {}}
    cobj = OUT / "kernel.o"
    subprocess.run(common + ["-O2", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-pic",
                            "-c", str(ROOT / "examples/ape/kernel.c"), "-o", str(cobj)], check=True)

    def build(name, source, defines=(), extra=()):
        obj, elf = OUT / f"{name}.o", OUT / f"{name}.elf"
        subprocess.run(common + list(defines) + ["-c", str(source), "-o", str(obj)], check=True)
        subprocess.run([linker, "--no-relax", "-T", str(ROOT / "examples/ape/link.ld"), str(obj)] +
                       list(extra) + ["-o", str(elf)], check=True)
        words = extract(elf)
        image = OUT / f"{name}.hex"
        image.write_text("".join(f"{w:08x}\n" for w in words))
        manifest["programs"][name] = {"words": len(words), "elf_sha256": hashlib.sha256(elf.read_bytes()).hexdigest(),
            "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}

    for i in range(32):
        build(f"p{i}", ROOT / "examples/ape/programs.S", [f"-DAPE_TEST={i}"], [str(cobj)] if i == 18 else [])
    # Deterministic instruction streams stress renaming and ring wrap. They are
    # assembler inputs, not synthetic substitutes for the RTL execution engine.
    for seed in range(8):
        rng = random.Random(seed)
        lines = [".option norvc", ".option norelax", '.section .text.start,"ax",@progbits',
                 ".globl _start", "_start:", "li x31, 0x10000", "ld x1, 0(x31)"]
        for _ in range(160):
            dst, lhs, rhs = [rng.randrange(0, 16) for _ in range(3)]
            kind = rng.randrange(4)
            if kind == 0:
                ins = rng.choice(["addi", "xori", "ori", "andi", "slti", "sltiu", "addiw"])
                lines.append(f"{ins} x{dst}, x{lhs}, {rng.randrange(-2048, 2048)}")
            elif kind == 1:
                ins = rng.choice(["slli", "srli", "srai", "slliw", "srliw", "sraiw"])
                lines.append(f"{ins} x{dst}, x{lhs}, {rng.randrange(32 if ins.endswith('w') else 64)}")
            else:
                ins = rng.choice(["add", "sub", "xor", "or", "and", "slt", "sltu", "sll", "srl", "sra",
                                  "addw", "subw", "sllw", "srlw", "sraw"])
                lines.append(f"{ins} x{dst}, x{lhs}, x{rhs}")
        lines.append("ebreak")
        source = OUT / f"random{seed}.S"
        source.write_text("\n".join(lines) + "\n")
        build(f"random{seed}", source)
    # Bounded backward loop around seeded forward diamonds and real memory work.
    # Branch outcomes, register dependencies and aliased predictor entries vary.
    for seed in range(8):
        rng = random.Random(100 + seed)
        lines = [".option norvc", ".option norelax", '.section .text.start,"ax",@progbits',
                 ".globl _start", "_start:", "li s0, 0x10000", "li s1, 4",
                 f"li t0, {seed + 1}", "li a0, 0", "outer:"]
        for i in range(24):
            reg = rng.choice(["t0", "t1", "t2"])
            branch = rng.choice(["beq", "bne", "blt", "bge", "bltu", "bgeu"])
            lines += [f"ld t1, {rng.randrange(8) * 8}(s0)",
                      f"addi t2, t0, {rng.randrange(-20, 21)}",
                      f"{branch} {reg}, t1, taken{i}", f"addi a0, a0, {rng.randrange(-9, 10)}",
                      f"jal zero, join{i}", f"taken{i}:", "xor a0, a0, t2", f"join{i}:",
                      "add t0, t0, a0", f"sd t0, {64 + (i % 8) * 8}(s0)"]
        lines += ["addi s1, s1, -1", "bne s1, zero, outer", "ebreak"]
        source = OUT / f"control{seed}.S"
        source.write_text("\n".join(lines) + "\n")
        build(f"control{seed}", source)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {len(manifest['programs'])} linked RV64I test images")


if __name__ == "__main__":
    main()
