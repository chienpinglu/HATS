"""Checked static RV64I/LP64 ELF loader for the isolated S02 tool profile."""
import struct

CODE_BYTES = 0x40000
DATA_BASE, DATA_BYTES = 0x100000, 0x1000000
ARGUMENT, OLD, NEW = 0x180000, 0x181000, 0x1c1000
INPUT_MAX, OUTPUT, OUTPUT_BYTES = 0x3f000, 0x210000, 0xf0000
HEAP, HEAP_BYTES, STACK_BASE, STACK_TOP = 0x400000, 0xa00000, 0xf00000, 0x1000000
MAGIC = 0x4841545354533031


def decode(raw):
    def span(start, length):
        if start < 0 or length < 0 or start > len(raw) or length > len(raw) - start:
            raise ValueError("ELF span outside file")
        return raw[start:start+length]
    if len(raw) < 64 or raw[:7] != b"\x7fELF\x02\x01\x01": raise ValueError("Expected ELF64 LE v1")
    _, kind, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = struct.unpack("<16sHHIQQQIHHHHHH", span(0, 64))
    if (kind, machine, version, entry, flags, ehsize, phsize, shsize) != (2, 243, 1, 0, 0, 64, 56, 64):
        raise ValueError("Not the static RV64I/LP64 entry-0 profile")
    if not 1 <= phnum <= 16 or not 1 <= shnum <= 128 or not 0 < shstr < shnum:
        raise ValueError("Invalid ELF table counts")
    span(phoff, phnum * phsize); span(shoff, shnum * shsize)
    code, data, segments = bytearray(CODE_BYTES), bytearray(DATA_BYTES), []
    for i in range(phnum):
        typ, perm, off, va, pa, size, memsz, align = struct.unpack("<IIQQQQQQ", span(phoff + i*56, 56))
        if typ != 1 or perm not in (4, 5, 6) or va != pa or not 0 < memsz or size > memsz:
            raise ValueError("Unsupported load segment")
        if not align or align & (align-1) or va % align != off % align: raise ValueError("Segment alignment")
        end = va + memsz
        if end > 1 << 64 or any(va < b["end"] and b["start"] < end for b in segments):
            raise ValueError("Segment overflow/overlap")
        payload = span(off, size)
        if perm == 5:
            if va or end > CODE_BYTES or size != memsz or size % 4: raise ValueError("Code outside instruction image")
            code[:size] = payload
        else:
            if not DATA_BASE <= va < end <= ARGUMENT: raise ValueError("Static state overlaps fixture regions")
            data[va-DATA_BASE:va-DATA_BASE+size] = payload
        segments.append({"start": va, "end": end, "file_bytes": size, "flags": perm})
    if sum(s["flags"] == 5 for s in segments) != 1: raise ValueError("Need one executable segment")
    sections = [struct.unpack("<IIQQQQIIQQ", span(shoff + i*64, 64)) for i in range(shnum)]
    symbols = {}
    for _, typ, attr, va, off, size, link, _, _, entsize in sections:
        if (typ in (4, 9) and size) or typ == 6 or attr & 0x400: raise ValueError("Unresolved relocation/dynamic/TLS")
        if typ != 8: span(off, size)
        if attr & 2 and size and not any(s["start"] <= va and va+size <= s["end"] for s in segments):
            raise ValueError("Allocated section outside segments")
        if typ == 2:
            if entsize != 24 or size % 24 or not 0 <= link < shnum or sections[link][1] != 3:
                raise ValueError("Invalid symbol table")
            strings = span(sections[link][4], sections[link][5])
            for pos in range(off, off+size, 24):
                name, info, _, index, value, _ = struct.unpack("<IBBHQQ", span(pos, 24))
                if name >= len(strings) or b"\0" not in strings[name:]: raise ValueError("Invalid symbol name")
                key = strings[name:].split(b"\0", 1)[0].decode("ascii")
                if key and info >> 4 in (1, 2) and index == 0: raise ValueError("Undefined linked symbol")
                if key and info >> 4 == 1:
                    if key in symbols and symbols[key] != value: raise ValueError("Ambiguous symbol")
                    symbols[key] = value
    required = ("_start", "ape_exit", "__bss_start", "__bss_end", "__stack_top")
    if any(n not in symbols for n in required): raise ValueError("Missing startup/runtime symbol")
    code_size = next(s["end"] for s in segments if s["flags"] == 5)
    start, end = symbols["__bss_start"], symbols["__bss_end"]
    if symbols["_start"] or symbols["__stack_top"] != STACK_TOP or not DATA_BASE <= start <= end <= ARGUMENT or start % 16 or end % 16:
        raise ValueError("Invalid runtime placement")
    if start != end and not any(s["flags"] == 6 and s["start"] + s["file_bytes"] <= start and end <= s["end"] for s in segments):
        raise ValueError("BSS is not a writable zero-fill tail")
    exit_pc = symbols["ape_exit"]
    if exit_pc % 4 or not 0 <= exit_pc < code_size or struct.unpack_from("<I", code, exit_pc)[0] != 0x00100073:
        raise ValueError("Exit is not the declared EBREAK sentinel")
    # Startup must clear BSS; a host zero-fill alone is not sufficient evidence.
    data[start-DATA_BASE:end-DATA_BASE] = b"\xa5" * (end-start)
    return code, data, {"code_bytes": code_size, "exit_pc": exit_pc, "bss_start": start, "bss_end": end,
                        "writable_start": min((s["start"] for s in segments if s["flags"] == 6), default=end),
                        "stack_top": STACK_TOP, "symbols": symbols, "segments": segments}
