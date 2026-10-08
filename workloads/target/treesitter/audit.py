#!/usr/bin/env python3
"""Static RV64 compile/link audit. Never executes or claims a target application."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

import newlib

ROOT = Path(__file__).resolve().parent
WORKLOADS = ROOT.parents[1]
NATIVE = WORKLOADS / "native/treesitter"
PROFILE = ("rv64i", "rv64im", "rv64ima")
INTEGER = set("lui auipc jal jalr beq bne blt bge bltu bgeu lb lh lw ld lbu lhu lwu sb sh sw sd addi slti sltiu xori ori andi slli srli srai add sub sll slt sltu xor srl sra or and addiw slliw srliw sraiw addw subw sllw srlw sraw fence".split())
MULTIPLY = set("mul mulh mulhsu mulhu div divu rem remu mulw divw divuw remw remuw".split())


def verify_instructions(isa, inventory):
    extra = []
    for name in inventory:
        if name in INTEGER: continue
        if name in MULTIPLY and isa in ("rv64im", "rv64ima"): extra.append(name); continue
        if isa == "rv64ima" and re.fullmatch(r"(?:amo(?:add|swap|xor|and|or|min|max|minu|maxu)|lr|sc)\.[wd](?:\.aq|\.rl|\.aqrl)?", name):
            extra.append(name); continue
        raise ValueError(f"Instruction {name} outside declared {isa} audit profile")
    return sorted(extra)


def load_native():
    spec = importlib.util.spec_from_file_location("hats_ts_native", NATIVE / "run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def elf_sections(raw):
    """Strict enough for our ET_REL audit inputs; not an executable loader."""
    if len(raw) < 64 or raw[:7] != b"\x7fELF\x02\x01\x01": raise ValueError("Expected ELF64 LE")
    header = struct.unpack_from("<16sHHIQQQIHHHHHH", raw)
    if header[1:4] != (1, 243, 1) or header[7] != 0 or header[8] != 64 or header[11] != 64:
        raise ValueError("Expected soft-float, non-compressed RISC-V ET_REL")
    offset, count, names = header[6], header[12], header[13]
    if count == 0 or count > 8192 or not 0 < names < count or offset + count * 64 > len(raw):
        raise ValueError("Invalid section table")
    sections = [struct.unpack_from("<IIQQQQIIQQ", raw, offset + i * 64) for i in range(count)]
    def data(s):
        if s[4] + s[5] > len(raw): raise ValueError("Section outside ELF")
        return raw[s[4]:s[4]+s[5]]
    strings = data(sections[names])
    result = []
    for s in sections:
        if s[0] >= len(strings) or b"\0" not in strings[s[0]:]: raise ValueError("Invalid section name")
        name = strings[s[0]:].split(b"\0", 1)[0].decode("ascii")
        if s[1] != 8: data(s)
        result.append({"name": name, "type": s[1], "flags": s[2], "size": s[5]})
    return result


def instruction_inventory(disassembly):
    inventory = Counter()
    for line in disassembly.splitlines():
        m = re.match(r"^\s*[0-9a-f]+:\s+([a-z][a-z0-9_.]*)\b", line)
        if m: inventory[m.group(1)] += 1
        elif re.match(r"^\s*[0-9a-f]+:", line): raise ValueError("Unparsed/unknown disassembly instruction")
    if not inventory: raise ValueError("No disassembled instructions")
    return dict(sorted(inventory.items()))


def unresolved(log):
    return sorted(set(re.findall(r"undefined symbol: ([^\s]+)", log)))


def classify(symbol):
    if symbol.startswith(("__atomic_", "__sync_")): return "atomic_runtime"
    if symbol in {"__muldi3", "__multi3", "__udivdi3", "__divdi3", "__umoddi3", "__moddi3", "__udivsi3", "__divsi3", "__umodsi3", "__modsi3"}: return "integer_compiler_runtime"
    if symbol.startswith("__"): return "other_compiler_or_runtime"
    return "platform_or_posix_service"


def run():
    libc = newlib.check()
    native = load_native()
    runtime, grammar = native.sources()
    if native.fixture_manifest() != json.loads((NATIVE / "cases.lock.json").read_text()):
        raise ValueError("Native fixture identity changed")
    out = WORKLOADS / "results" / f"treesitter-rv-audit-{time.time_ns()}"
    out.mkdir(parents=True)
    sources = [ROOT / n for n in ("newlib.py", "newlib.lock.json", "link_probe.c", "audit.py", "test_audit.py", "test_newlib.py")]
    sources += [NATIVE / n for n in ("run.py", "sources.lock.json", "cases.lock.json")]
    source_hashes = {str(p.relative_to(WORKLOADS)): newlib.sha(p) for p in sources}
    for base, folders in ((runtime, ["lib/src", "lib/include"]), (grammar, ["src"])):
        for folder in folders:
            for path in (base / folder).rglob("*"):
                if path.is_file(): source_hashes[str(path.relative_to(WORKLOADS))] = newlib.sha(path)
    report = {"schema": 1, "status": "running", "claim_class": "static_riscv_compile_link_audit",
              "target_execution": False, "hats_execution": False, "source_sha256": source_hashes,
              "native_fixture_lock_sha256": newlib.sha(NATIVE / "cases.lock.json"),
              "newlib_stamp_sha256": newlib.sha(newlib.BUILD / "hats-build.json"),
              "compiler": libc["compiler"], "profiles": {},
              "limits": ["Relocatable closure is not an executable; strict unresolved links stay blocked",
                         "API reachability probe is not the independently checked native application",
                         "All profiles use the same RV64I Newlib archive for controlled comparison",
                         "Static instruction sites and stack frames are not runtime counts, cache demand or a full stack bound"]}
    manifest = out / "audit.json"
    def save(): manifest.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Audit: {manifest}", flush=True)
    save()
    try:
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT), "-p", "test_*.py", "-v"], check=True, timeout=60)
        archive = newlib.BUILD / "riscv64-unknown-elf/newlib/libc.a"
        includes = [newlib.BUILD / "riscv64-unknown-elf/newlib/targ-include",
                    newlib.source() / "newlib/libc/include", runtime / "lib/include", runtime / "lib/src", grammar / "src"]
        for isa in PROFILE:
            work = out / isa; work.mkdir()
            record = {"isa": isa, "commands": [], "objects": {}}
            report["profiles"][isa] = record
            common = [newlib.tool("clang"), "--target=riscv64-unknown-elf", "-march=" + isa, "-mabi=lp64",
                      "-mno-relax", "-msmall-data-limit=0", "-std=c11", "-O2", "-ffreestanding", "-fno-builtin",
                      "-fno-stack-protector", "-fno-pic", "-ffunction-sections", "-fdata-sections", "-fstack-usage",
                      "-D_POSIX_C_SOURCE=200809L", "-DHAVE_SYS_ENDIAN_H=1", "-D_DEFAULT_SOURCE=1"] + ["-I" + str(p) for p in includes]
            objects = []
            with (work / "compile.log").open("w") as log:
                for name, src in (("runtime", runtime / "lib/src/lib.c"), ("grammar", grammar / "src/parser.c"), ("probe", ROOT / "link_probe.c")):
                    obj = work / (name + ".o"); objects.append(obj)
                    cmd = common + ["-c", str(src), "-o", str(obj)]
                    record["commands"].append(cmd)
                    subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120)
                    dis = subprocess.check_output([newlib.tool("llvm-objdump"), "-d", "--no-show-raw-insn", "-M", "no-aliases", str(obj)], text=True)
                    (work / (name + ".disasm")).write_text(dis)
                    sections = elf_sections(obj.read_bytes())
                    und = subprocess.check_output([newlib.tool("llvm-nm"), "--undefined-only", "--format=posix", str(obj)], text=True)
                    frames = []
                    for line in obj.with_suffix(".su").read_text().splitlines():
                        fn, size, kind = line.rsplit("\t", 2)
                        frames.append({"function": fn.split(":")[-1], "bytes": int(size), "kind": kind})
                    inventory = instruction_inventory(dis)
                    extra = verify_instructions(isa, inventory)
                    record["objects"][name] = {"sha256": newlib.sha(obj), "file_bytes": obj.stat().st_size,
                        "text_bytes": sum(s["size"] for s in sections if s["flags"] & 4),
                        "allocated_data_bytes": sum(s["size"] for s in sections if s["flags"] & 2 and not s["flags"] & 4),
                        "instruction_sites": inventory, "beyond_current_ape_isa": extra, "undefined_symbols": sorted(l.split()[0] for l in und.splitlines()),
                        "stack_frames": sorted(frames, key=lambda f: (-f["bytes"], f["function"]))}
            # Keep real relocations and missing symbols. No dummy providers or ignored unresolved symbols.
            closure = work / "reachable.o"
            base = [newlib.tool("ld.lld"), "--no-relax", "--gc-sections", "--entry=hats_tool_entry"]
            cmd = base + ["-r", *map(str, objects), str(archive), "-o", str(closure)]
            record["commands"].append(cmd)
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            sections = elf_sections(closure.read_bytes())
            und = subprocess.check_output([newlib.tool("llvm-nm"), "--undefined-only", "--format=posix", str(closure)], text=True)
            missing = sorted(l.split()[0] for l in und.splitlines())
            dis = subprocess.check_output([newlib.tool("llvm-objdump"), "-d", "--no-show-raw-insn", "-M", "no-aliases", str(closure)], text=True)
            (work / "reachable.disasm").write_text(dis)
            inventory = instruction_inventory(dis)
            record["closure"] = {"sha256": newlib.sha(closure), "text_bytes": sum(s["size"] for s in sections if s["flags"] & 4),
                                  "allocated_data_bytes": sum(s["size"] for s in sections if s["flags"] & 2 and not s["flags"] & 4),
                                  "instruction_sites": inventory, "beyond_current_ape_isa": verify_instructions(isa, inventory),
                                  "unresolved": {s: classify(s) for s in missing}}
            cmd = base + ["--no-undefined", "--error-limit=0", "-Ttext=0x10000", *map(str, objects), str(archive), "-o", str(work / "probe.elf")]
            record["commands"].append(cmd)
            linked = subprocess.run(cmd, text=True, capture_output=True, timeout=60)
            (work / "strict-link.log").write_text(linked.stdout + linked.stderr)
            if missing:
                if linked.returncode == 0 or unresolved(linked.stderr) != missing:
                    raise ValueError("Strict link failure does not match the relocatable unresolved inventory")
                if any("error:" in l and "undefined symbol:" not in l for l in linked.stderr.splitlines()):
                    raise ValueError("Additional unclassified linker failure")
                record["strict_link"] = {"status": "blocked", "unresolved": missing, "exit_code": linked.returncode}
            else:
                if linked.returncode: raise ValueError("Unexpected link failure: " + linked.stderr)
                record["strict_link"] = {"status": "linked_not_executed", "exit_code": 0}
            record["artifacts"] = {p.name: newlib.sha(p) for p in sorted(work.iterdir()) if p.is_file()}
            print(f"{isa}: compiled, reachable text {record['closure']['text_bytes']} bytes, {len(missing)} unresolved", flush=True)
            save()
        native.sources(); newlib.check()
        if any(newlib.sha(WORKLOADS / p) != h for p, h in source_hashes.items()): raise ValueError("Source changed during audit")
        for isa, record in report["profiles"].items():
            if any(newlib.sha(out / isa / p) != h for p, h in record["artifacts"].items()):
                raise ValueError("Audit output artifact changed during run")
        report["status"] = "audit_complete"
    except Exception as exc:
        report.update(status="failed", error=str(exc)); raise
    finally: save()
    print("Static audit complete; inspect strict_link statuses. No application execution or RTL claim.")
    return manifest


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
