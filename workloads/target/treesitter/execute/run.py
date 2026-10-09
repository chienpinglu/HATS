#!/usr/bin/env python3
"""Strict-linked upstream Tree-sitter execution on pinned Spike, before APE RTL."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
WORKLOADS, REPO = ROOT.parents[2], ROOT.parents[3]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(REPO / "hardware/spinal/tools"))
import audit
import newlib
import bootstrap_spike as spike
import image
native = audit.load_native()


def own_hashes():
    files = [p for p in ROOT.iterdir() if p.suffix in (".py", ".c", ".cc", ".h", ".S", ".ld")]
    files += [ROOT.parent / name for name in ("audit.py", "newlib.py", "newlib.lock.json")]
    files += [native.ROOT / name for name in ("run.py", "sources.lock.json", "cases.lock.json")]
    files += [WORKLOADS / "sources.lock.json"]
    files += [ROOT.parent / "bulk/digest.h"]
    files += [REPO / "hardware/spinal/tools" / name for name in ("bootstrap_spike.py", "spike.lock.json")]
    return {str(p.relative_to(REPO)): newlib.sha(p) for p in sorted(files)}


def decode_result(raw):
    if len(raw) != image.OUTPUT_BYTES: raise ValueError("Wrong output image size")
    magic, status, error, count, live, peak, allocations, granted = struct.unpack_from("<8Q", raw)
    if magic != image.MAGIC or error not in (0, 1) or status > 5 or count > (len(raw)-64)//16:
        raise ValueError("Invalid target result header")
    result = {"status": status, "has_error": bool(error), "live_after_cleanup": live,
              "peak_bytes": peak, "allocation_calls": allocations, "heap_granted": granted, "nodes": []}
    if status == 0:
        names = ("array", "object", "string", "number", "true", "false", "null")
        for i in range(count):
            kind, start, end, depth = struct.unpack_from("<4I", raw, 64+i*16)
            if not 1 <= kind <= 7 or start > end or depth > 1024: raise ValueError("Invalid typed node")
            result["nodes"].append([names[kind-1], start, end, depth])
    return result


def vectors():
    rng = random.Random(0x48415453)
    values = [0, 1, 2, 3, (1 << 63)-1, 1 << 63, (1 << 64)-1]
    return [(a, (1 << 64)-1, b, 1) for a in values for b in values] + [tuple(rng.getrandbits(64) for _ in range(4)) for _ in range(128)]


def expected_helpers(v):
    mask = (1 << 64)-1
    a, ah, b, bh = v
    x = a if a < 1 << 63 else a - (1 << 64)
    y = b if b < 1 << 63 else b - (1 << 64)
    rem = (abs(x) % abs(y)) * (-1 if x < 0 else 1) if y else x
    product = ((ah << 64) | a) * ((bh << 64) | b)
    return (a*b & mask, a//b if b else mask, a % b if b else a, rem & mask, product & mask, product >> 64 & mask)


class Execution:
    def __init__(self):
        self.libc = newlib.check(); self.reference = spike.check()
        self.runtime, self.grammar = native.sources()
        if native.fixture_manifest() != json.loads((native.ROOT / "cases.lock.json").read_text()):
            raise ValueError("Frozen fixtures changed")
        self.out = WORKLOADS / "results" / f"s02-treesitter-{time.time_ns()}"; self.out.mkdir(parents=True)
        self.cc = newlib.tool("clang")
        includes = [ROOT, newlib.BUILD / "riscv64-unknown-elf/newlib/targ-include", newlib.source() / "newlib/libc/include",
                    self.runtime / "lib/include", self.runtime / "lib/src", self.grammar / "src"]
        self.common = [self.cc, "--target=riscv64-unknown-elf", "-march=rv64i", "-mabi=lp64", "-mno-relax",
                       "-msmall-data-limit=0", "-std=c11", "-O2", "-ffreestanding", "-fno-builtin",
                       "-fno-stack-protector", "-fno-pic", "-ffunction-sections", "-fdata-sections", "-fstack-usage",
                       "-D_POSIX_C_SOURCE=200809L", "-DHAVE_SYS_ENDIAN_H=1", "-D_DEFAULT_SOURCE=1"] + ["-I" + str(p) for p in includes]
        self.report = {"schema": 1, "status": "running", "claim_class": "rv64i_spike_tool_execution", "ape_rtl_execution": False,
                       "source_sha256": own_hashes(), "source_lock": json.loads(native.LOCK.read_text()),
                       "fixtures": native.fixture_manifest(), "compiler": self.libc["compiler"],
                       "newlib_build_sha256": newlib.sha(newlib.BUILD / "hats-build.json"),
                       "spike_revision": self.reference["revision"], "spike_build_sha256": newlib.sha(spike.STAMP),
                       "commands": [], "builds": {}, "runs": [],
                       "limits": ["Independent ISA execution, not APE RTL execution or hardware performance",
                                  "Isolated one hart, no interrupts/other writers; serialized atomic helpers are not a concurrent A-extension runtime",
                                  "Host compiles, loads inputs, models memory and checks outputs; parser results come from target instructions",
                                  "Fixed memory/service profile, not Linux/POSIX, caches, coherence or protected multitasking",
                                  "Input-specific stack and heap observations are not worst-case bounds"]}
        self.artifacts = {}

    def command(self, cmd, timeout=180):
        self.report["commands"].append([str(p).replace(str(REPO), "${HATS_ROOT}") for p in cmd])
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "LC_ALL": "C"})
        if proc.returncode: raise RuntimeError(f"Command failed: {cmd}\n{proc.stderr[-8000:]}")
        return proc

    def build(self, mode="parser"):
        folder = self.out / mode; folder.mkdir()
        files = [("start", ROOT / "start.S"), ("compiler_rt", ROOT / "compiler_rt.c")]
        if mode == "helpers": files += [("application", ROOT / "helper_test.c")]
        elif mode == "runtime": files += [("runtime", ROOT / "runtime.c"), ("application", ROOT / "runtime_test.c")]
        else: files += [("runtime", ROOT / "runtime.c"), ("application", ROOT / "application.c"),
                        ("upstream", self.runtime / "lib/src/lib.c"), ("grammar", self.grammar / "src/parser.c")]
        for name, source in files:
            self.command(self.common + ["-c", str(source), "-o", str(folder / (name + ".o"))])
        elf = folder / "application.elf"
        self.command([newlib.tool("ld.lld"), "--no-relax", "--no-undefined", "--gc-sections", "-T", str(ROOT / "link.ld"),
                      *[str(folder / (n + ".o")) for n, _ in files], str(newlib.BUILD / "riscv64-unknown-elf/newlib/libc.a"), "-o", str(elf)])
        undefined = self.command([newlib.tool("llvm-nm"), "--undefined-only", str(elf)]).stdout
        if undefined.strip(): raise ValueError("Strict-linked executable retains undefined symbols")
        dis = self.command([newlib.tool("llvm-objdump"), "-d", "--no-show-raw-insn", "-M", "no-aliases", str(elf)]).stdout
        inventory = audit.instruction_inventory(dis)
        audit.verify_instructions("rv64i", {k: v for k, v in inventory.items() if k != "ebreak"})
        code, data, profile = image.decode(elf.read_bytes())
        (folder / "code.bin").write_bytes(code); (folder / "data.bin").write_bytes(data)
        (folder / "runtime.properties").write_text("".join(f"{key}={profile[key]}\n" for key in ("code_bytes", "writable_start", "bss_end", "exit_pc")))
        (folder / "disassembly.txt").write_text(dis)
        (folder / "image.json").write_text(json.dumps(profile, indent=2) + "\n")
        self.report["builds"][folder.name] = {"strict_link": "passed", "elf_sha256": newlib.sha(elf), "profile": profile,
                                              "instruction_sites": inventory, "image_sha256": {n: newlib.sha(folder / n) for n in ("code.bin", "data.bin", "runtime.properties")}}
        for p in folder.iterdir():
            if p.is_file(): self.artifacts[str(p.relative_to(self.out))] = newlib.sha(p)
        return folder

    def adapter(self):
        includes = [spike.BUILD, spike.SOURCE] + [spike.SOURCE / n for n in ("riscv", "disasm", "fesvr", "softfloat")]
        exe = self.out / "spike-tool"
        self.command(["clang++", "-std=c++20", "-O2", "-g0", "-I/opt/homebrew/opt/openssl@3/include"] + ["-I" + str(p) for p in includes] +
                     [str(ROOT / "spike_runner.cc")] + [str(spike.BUILD / n) for n in spike.LIBRARIES] +
                     ["-L/opt/homebrew/opt/openssl@3/lib", "-lcrypto", "-lpthread", "-o", str(exe)])
        self.report["adapter_sha256"] = newlib.sha(exe)
        self.artifacts[exe.name] = newlib.sha(exe)
        return exe

    def invoke(self, exe, folder, name, args, old, new, limit, trace=False, digest=False):
        case = folder / name; case.mkdir()
        for n, raw in (("args.bin", struct.pack("<8Q", *args)), ("old.bin", old), ("new.bin", new)):
            (case / n).write_bytes(raw)
        command = [str(exe), str(folder / "code.bin"), str(folder / "data.bin"), str(folder / "runtime.properties"),
                   str(case / "args.bin"), str(case / "old.bin"), str(case / "new.bin"), str(case / "result.bin"), str(case / "execution.json"), str(limit)]
        if trace: command.append(str(case / "trace.jsonl"))
        elif digest: command.append("-")
        if digest: command.append(str(case / "digest.json"))
        self.command(command, timeout=1200 if digest else 300)
        evidence = json.loads((case / "execution.json").read_text())
        evidence["output_sha256"] = newlib.sha(case / "result.bin")
        evidence["input_sha256"] = {n: newlib.sha(case / n) for n in ("args.bin", "old.bin", "new.bin")}
        for p in case.iterdir():
            if p.is_file(): self.artifacts[str(p.relative_to(self.out))] = newlib.sha(p)
        return (case / "result.bin").read_bytes(), evidence

    def check_artifacts(self):
        for name, digest in self.artifacts.items():
            if newlib.sha(self.out / name) != digest: raise ValueError(f"Execution artifact changed: {name}")
        if own_hashes() != self.report["source_sha256"]: raise ValueError("Target sources changed")
        if newlib.check() != self.libc or spike.check() != self.reference: raise ValueError("Dependency build identity changed")
        native.sources()
        self.report["artifacts_sha256"] = dict(self.artifacts)

    def run(self, selected, kinds, limit, trace):
        exe = self.adapter()
        helpers = self.build("helpers")
        vec = vectors(); raw = b"".join(struct.pack("<4Q", *v) for v in vec)
        output, stats = self.invoke(exe, helpers, "integer-vectors", (image.MAGIC, 0, len(vec), 0, 0, 0, 0, 0), raw, b"", limit)
        if stats["result"] != 0 or struct.unpack_from("<4Q", output) != (image.MAGIC, 0, 0, len(vec)):
            raise ValueError("Helper executable failed")
        for i, v in enumerate(vec):
            if struct.unpack_from("<6Q", output, 64 + i*48) != expected_helpers(v): raise ValueError(f"Compiler helper failed vector {i}")
        self.report["helpers"] = {"vectors_passed": len(vec), "operations_per_vector": 6, "execution": stats}
        print(f"PASS RV64 compiler helpers: {len(vec)} vectors / {len(vec)*6} results", flush=True)
        runtime = self.build("runtime")
        output, stats = self.invoke(exe, runtime, "runtime-tests", (image.MAGIC, 0, 0, 0, 65536, 0, 0, 0), b"", b"", limit)
        header = struct.unpack_from("<8Q", output)
        if stats["result"] or header[0:3] != (image.MAGIC, 0, 0) or header[3] != 160 or header[4]:
            raise ValueError(f"Target runtime self-test failed: {header}")
        self.report["runtime_tests"] = {"checks_passed": header[3], "execution": stats}
        print(f"PASS RV64 runtime services: {header[3]} checks", flush=True)
        parser = self.build()
        for name, old, new in native.cases():
            if selected and name not in selected: continue
            for kind in kinds:
                first, second = (new, b"") if kind == "cold_new" else (old, new if kind == "incremental" else b"")
                if trace and len(first) + len(second) > 4096: raise ValueError("Text traces limited to small fixtures; avoid accidental multi-GB output")
                args = (image.MAGIC, int(kind == "incremental"), len(first), len(second), image.HEAP_BYTES, image.OUTPUT_BYTES, 0, 0)
                output, stats = self.invoke(exe, parser, name + "-" + kind, args, first, second, limit, trace)
                result = decode_result(output)
                if stats["result"] or result["status"]: raise ValueError("Target program failed")
                checked = native.check_output(second if kind == "incremental" else first, result)
                result.pop("nodes")
                self.report["runs"].append({"case": name, "kind": kind, "check": checked, "result": result, "execution": stats})
                print(f"PASS RV64 {name}/{kind}: {stats['retired']} retired, {result['peak_bytes']} peak requested heap", flush=True)
        expected = (len(selected) if selected else len(native.cases())) * len(kinds)
        if len(self.report["runs"]) != expected: raise ValueError("Incomplete selected matrix")
        self.report["full_fixture_matrix"] = len(self.report["runs"]) == 30
        self.report["negative_cases"] = []
        for name, updates, status in [("bad_magic", {0: 0}, 1), ("bad_mode", {1: 2}, 1),
                                      ("input_bound", {2: image.INPUT_MAX + 1}, 1),
                                      ("invalid_heap_bound", {4: image.HEAP_BYTES + 1}, 1),
                                      ("heap_zero", {4: 0}, 2), ("heap_small", {4: 128}, 2),
                                      ("output_full", {5: 64}, 3), ("output_short", {5: 63}, 1),
                                      ("output_bound", {5: image.OUTPUT_BYTES + 1}, 1), ("reserved", {6: 1}, 1)]:
            args = [image.MAGIC, 0, 2, 0, image.HEAP_BYTES, image.OUTPUT_BYTES, 0, 0]
            for field, value in updates.items(): args[field] = value
            output, stats = self.invoke(exe, parser, name, args, b"{}", b"", limit)
            result = decode_result(output)
            if stats["result"] != status or result["status"] != status: raise ValueError("Expected explicit target rejection")
            self.report["negative_cases"].append({"case": name, "expected_status": status, "result": result, "execution": stats})
        print("PASS 10 target argument/resource rejection cases", flush=True)
        self.report["status"] = "passed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=[c[0] for c in native.cases()])
    parser.add_argument("--kind", action="append", choices=["cold_old", "cold_new", "incremental"])
    parser.add_argument("--limit", type=int, default=500000000)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args()
    if args.case and len(set(args.case)) != len(args.case) or args.kind and len(set(args.kind)) != len(args.kind):
        parser.error("Duplicate cases/kinds")
    e = Execution(); print(f"Report: {e.out / 'validation.json'}", flush=True)
    try:
        e.run(args.case, args.kind or ["cold_old", "cold_new", "incremental"], args.limit, args.trace)
        e.check_artifacts()
    except Exception as error:
        e.report.update(status="failed", error=str(error)); raise
    finally:
        (e.out / "validation.json").write_text(json.dumps(e.report, indent=2) + "\n")
    print("Selected RV64 reference gate passed; APE RTL gate remains open.")


if __name__ == "__main__": main()
