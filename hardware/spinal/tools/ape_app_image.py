"""Checked ELF64 loader for the fixed APE application profile, not a general OS loader."""
import struct

CODE_SIZE, DATA_BASE, DATA_SIZE = 4096, 0x10000, 65536


def decode_elf(raw):
    def span(offset, size):
        if offset < 0 or size < 0 or offset > len(raw) or size > len(raw) - offset:
            raise ValueError("ELF range exceeds file")
        return raw[offset:offset + size]

    if len(raw) < 64 or raw[:7] != b"\x7fELF\x02\x01\x01":
        raise ValueError("Expected ELF64 little-endian version 1")
    header = struct.unpack("<16sHHIQQQIHHHHHH", span(0, 64))
    _, typ, machine, version, entry, phoff, shoff, flags, ehsize, phsize, phnum, shsize, shnum, shstr = header
    if (typ, machine, version, entry, flags, ehsize, phsize, shsize) != (2, 243, 1, 0, 0, 64, 56, 64):
        raise ValueError("Unsupported executable/ISA/ABI/header profile")
    if not 1 <= phnum <= 16 or not 1 <= shnum <= 128 or not 0 < shstr < shnum:
        raise ValueError("Invalid ELF table counts")
    span(phoff, phnum * phsize)
    span(shoff, shnum * shsize)
    code, data = bytearray(CODE_SIZE), bytearray(DATA_SIZE)
    segments, ranges = [], []
    for index in range(phnum):
        kind, perm, off, va, pa, filesz, memsz, align = struct.unpack("<IIQQQQQQ", span(phoff + index*56, 56))
        if kind != 1:
            raise ValueError("Only PT_LOAD headers are accepted")
        if filesz > memsz or not memsz or va != pa or perm not in (4, 5, 6):
            raise ValueError("Invalid segment size/address/permissions")
        if align < 1 or align & (align-1) or va % align != off % align:
            raise ValueError("Invalid segment alignment")
        payload = span(off, filesz)
        end = va + memsz
        if any(va < b and a < end for a, b in ranges):
            raise ValueError("Overlapping segments")
        ranges.append((va, end))
        if perm == 5:
            if va != 0 or end > CODE_SIZE or filesz != memsz or filesz % 4:
                raise ValueError("Invalid code segment")
            code[va:end] = payload
        else:
            if not DATA_BASE <= va < end <= 0x14000:
                raise ValueError("Static data outside reserved region")
            data[va-DATA_BASE:va-DATA_BASE+filesz] = payload
        segments.append(dict(address=va, file_bytes=filesz, memory_bytes=memsz, flags=perm))
    if sum(s["flags"] == 5 for s in segments) != 1:
        raise ValueError("Need exactly one executable segment")
    sections = [struct.unpack("<IIQQQQIIQQ", span(shoff + i*64, 64)) for i in range(shnum)]
    symbols = {}
    for section in sections:
        _, kind, attr, va, off, size, link, _, _, entsize = section
        if kind in (4, 9) and size:
            raise ValueError("Unresolved relocation section")
        if kind == 6 or attr & 0x400:
            raise ValueError("Dynamic linking and TLS are unsupported")
        if kind != 8:
            span(off, size)
        if attr & 2 and size:
            if not any(s["address"] <= va and va+size <= s["address"]+s["memory_bytes"] for s in segments):
                raise ValueError("Allocated section outside load segments")
        if kind == 2:
            if entsize != 24 or size % 24 or not 0 <= link < shnum or sections[link][1] != 3:
                raise ValueError("Invalid symbol table")
            strings = span(sections[link][4], sections[link][5])
            for pos in range(off, off + size, 24):
                name, info, _, _, value, _ = struct.unpack("<IBBHQQ", span(pos, 24))
                if name >= len(strings) or b"\0" not in strings[name:]:
                    raise ValueError("Invalid symbol name")
                key = strings[name:].split(b"\0", 1)[0].decode("ascii")
                # Mapping symbols and other local names may legally repeat.
                # Runtime entry symbols must be globally bound and unambiguous.
                if key and info >> 4 == 1:
                    if key in symbols and symbols[key] != value:
                        raise ValueError("Ambiguous symbol")
                    symbols[key] = value
    needed = ("_start", "ape_exit", "__bss_start", "__bss_end", "__stack_top")
    if any(k not in symbols for k in needed):
        raise ValueError("Missing runtime symbol")
    bss_start, bss_end = symbols["__bss_start"], symbols["__bss_end"]
    code_end = next(s["memory_bytes"] for s in segments if s["flags"] == 5)
    if (symbols["_start"] != 0 or not 0 <= symbols["ape_exit"] < code_end or
            symbols["ape_exit"] % 4 or symbols["__stack_top"] != 0x20000 or
            not DATA_BASE <= bss_start < bss_end <= 0x14000 or bss_start % 16 or bss_end % 16):
        raise ValueError("Invalid runtime placement")
    if not any(s["flags"] == 6 and s["address"] + s["file_bytes"] <= bss_start and
               bss_end <= s["address"] + s["memory_bytes"] for s in segments):
        raise ValueError("BSS is not a zero-fill writable segment tail")
    if struct.unpack_from("<I", code, symbols["ape_exit"])[0] != 0x00100073:
        raise ValueError("Runtime exit is not EBREAK")
    return code, data, {"entry": entry, "code_bytes": code_end, "segments": segments,
                        "symbols": {k: symbols[k] for k in needed},
                        "writable_start": min(s["address"] for s in segments if s["flags"] == 6)}
