#!/usr/bin/env python3
"""S01 native demand measurements, never an APE execution or speedup claim."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
WORKLOADS = ROOT.parent
REPO = WORKLOADS.parent
spec = importlib.util.spec_from_file_location("s01_native_baseline", WORKLOADS / "native/treesitter/run.py")
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


def source_hashes():
    return {str(p.relative_to(WORKLOADS)): native.sha(p)
            for p in sorted(ROOT.iterdir()) if p.suffix in (".py", ".c", ".h")}


def branches(export):
    """Function records include expanded macros; file summaries can duplicate them.

    Each LLVM branch region is [line,col,endline,endcol,true,false,file,
    expanded_file,kind]. Count region outcomes, not hardware instructions.
    """
    if export.get("type") != "llvm.coverage.json.export":
        raise ValueError("Unexpected LLVM coverage schema")
    regions = [b for d in export["data"] for f in d["functions"] for b in f.get("branches", [])]
    if not regions or any(len(b) != 9 or min(b[4], b[5]) < 0 for b in regions):
        raise ValueError("Missing/malformed branch regions")
    return {"regions": len(regions), "visited_regions": sum(b[4] + b[5] > 0 for b in regions),
            "both_outcomes_regions": sum(b[4] > 0 and b[5] > 0 for b in regions),
            "true_outcomes": sum(b[4] for b in regions), "false_outcomes": sum(b[5] for b in regions)}


def validate_memory(rows, incremental):
    names = ["setup", "full_parse"] + (["incremental_parse"] if incremental else []) + ["cleanup"]
    if [r["phase"] for r in rows] != list(range(len(names))):
        raise ValueError("Missing or misordered instrumentation phases")
    for row in rows:
        if row["line_touches"] != row["unique_64b_lines"] + row["reused_line_touches"]:
            raise ValueError("Memory accounting mismatch")
        if row["consecutive_same_line"] + row["consecutive_adjacent_line"] > max(0, row["line_touches"] - 1):
            raise ValueError("Transition accounting mismatch")
    if not rows[1]["loads"] or not rows[1]["stores"]:
        raise ValueError("Memory probes did not execute")
    return dict(zip(names, rows))


class Experiment:
    def __init__(self):
        self.runtime, self.grammar = native.sources()
        if native.fixture_manifest() != json.loads((native.ROOT / "cases.lock.json").read_text()):
            raise ValueError("Fixtures drifted")
        self.out = WORKLOADS / "results" / f"s01-profile-{time.time_ns()}"
        self.out.mkdir(parents=True)
        self.cc = native.tool("clang")
        self.common = [self.cc, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-D_DARWIN_C_SOURCE",
                       "-O2", "-g", "-fno-omit-frame-pointer",
                       "-I" + str(self.runtime / "lib/include"), "-I" + str(self.runtime / "lib/src"),
                       "-I" + str(self.grammar / "src"), "-I" + str(native.ROOT), "-I" + str(ROOT)]
        self.report = {"schema": 1, "status": "running", "claim_class": "host_native_demand_profile",
                       "hats_execution": False, "full_agent_experiment": False,
                       "machine": platform.machine(), "system": platform.system(),
                       "python": platform.python_version(),
                       "compiler": subprocess.check_output([self.cc, "--version"], text=True).splitlines()[0],
                       "compiler_sha256": native.sha(Path(self.cc).resolve()),
                       "source_sha256": source_hashes(), "fixtures": native.fixture_manifest(),
                       "upstream_sources": json.loads(native.LOCK.read_text()),
                       "native_harness_sha256": {p.name: native.sha(p) for p in native.ROOT.iterdir() if p.is_file()},
                       "commands": [], "runs": [], "workflow": {}, "limits": [
                           "Native compiler probes perturb code and time; never use their latency for speedup.",
                           "Memory probes cover instrumented runtime/grammar loads and stores, not libc, OS, atomics or bulk intrinsics; unique lines are not cache misses.",
                           "Branch regions cover the complete invocation including result traversal and cleanup; not per-phase hardware branch or mispredict counts.",
                           "Stack watermark observes written bytes including pthread/libc/adapter; not reserved/unwritten space, worst-case depth or an RV64 bound.",
                           "Atomics retain original orders; single-thread tests do not measure contention or prove inter-thread ordering.",
                           "Workflow uses deterministic original edits with real host tools; not a model-driven agent experiment. Inference and network are unexercised."]}
        self.inputs = self.out / "inputs"; self.inputs.mkdir()
        for name, old, new in native.cases():
            (self.inputs / f"{name}.old").write_bytes(old)
            (self.inputs / f"{name}.new").write_bytes(new)

    def command(self, cmd, **kwargs):
        self.report["commands"].append([str(c).replace(str(REPO), "${HATS_ROOT}") for c in cmd])
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=180, **kwargs)
        if p.returncode:
            raise RuntimeError(f"Command failed: {cmd}\n{p.stderr[-8000:]}")
        return p

    def build(self, mode):
        build = self.out / mode; build.mkdir()
        objects = []
        for name, src, upstream in [("runtime", self.runtime / "lib/src/lib.c", True),
                                    ("grammar", self.grammar / "src/parser.c", True),
                                    ("baseline", native.ROOT / "baseline.c", False),
                                    ("profile", native.ROOT / "profile.c", False)]:
            flags = []
            if mode == "memory":
                if upstream:
                    flags += ["-fsanitize-coverage=trace-pc-guard,trace-loads,trace-stores", "-include", str(ROOT / "atomic_profile.h"),
                              "-D__atomic_add_fetch=hats_atomic_add_fetch", "-D__atomic_sub_fetch=hats_atomic_sub_fetch",
                              "-D__atomic_load_n=hats_atomic_load_n"]
                if name == "profile":
                    flags += ["-Dhats_profile_begin=hats_base_profile_begin", "-Dhats_profile_end=hats_base_profile_end"]
            if mode == "branches" and upstream:
                flags += ["-fprofile-instr-generate", "-fcoverage-mapping"]
            if mode == "stack" and name == "baseline": flags += ["-Dmain=hats_baseline_main"]
            obj = build / f"{name}.o"; objects.append(str(obj))
            self.command(self.common + flags + ["-c", str(src), "-o", str(obj)])
        extra = {"memory": "memory_profile.c", "stack": "stack_probe.c"}.get(mode)
        if extra:
            obj = build / "extra.o"; objects.append(str(obj))
            self.command(self.common + ["-c", str(ROOT / extra), "-o", str(obj)])
        binary = build / "ts-profile"
        self.command([self.cc] + objects + (["-fprofile-instr-generate"] if mode == "branches" else []) + ["-pthread", "-o", str(binary)])
        return binary

    def measure(self):
        for mode in ("memory", "branches", "stack"):
            binary = self.build(mode)
            for name, old, new in native.cases():
                for kind, args, raw in [("cold_old", [self.inputs / f"{name}.old"], old),
                                        ("cold_new", [self.inputs / f"{name}.new"], new),
                                        ("incremental", [self.inputs / f"{name}.old", self.inputs / f"{name}.new"], new)]:
                    stem = binary.parent / f"{name}-{kind}"
                    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
                    if mode == "branches": env["LLVM_PROFILE_FILE"] = str(stem.with_suffix(".profraw"))
                    proc = self.command([str(binary)] + [str(p) for p in args], env=env)
                    result = json.loads(proc.stdout)
                    check = native.check_output(raw, result)
                    stem.with_suffix(".json").write_text(proc.stdout)
                    if mode == "memory":
                        metrics = validate_memory([json.loads(s) for s in proc.stderr.splitlines()], kind == "incremental")
                    elif mode == "stack":
                        metrics = json.loads(proc.stderr)
                        if not 0 < metrics["observed_touched_extent_bytes"] < metrics["stack_capacity_bytes"]:
                            raise ValueError("Bad stack watermark")
                    else:
                        self.command([native.tool("llvm-profdata"), "merge", "-sparse", str(stem.with_suffix(".profraw")), "-o", str(stem.with_suffix(".profdata"))])
                        export = self.command([native.tool("llvm-cov"), "export", str(binary), "-instr-profile=" + str(stem.with_suffix(".profdata"))])
                        metrics = branches(json.loads(export.stdout))
                        stem.with_suffix(".coverage.json").write_text(export.stdout)
                    self.report["runs"].append({"mode": mode, "case": name, "kind": kind, "check": check,
                                                "metrics": metrics, "output_sha256": native.sha(stem.with_suffix(".json"))})
                print(f"PASS {mode}: {name}", flush=True)

    def finish(self):
        if len(self.report["runs"]) != 90: raise ValueError("Incomplete measurement matrix")
        if source_hashes() != self.report["source_sha256"]: raise ValueError("Harness changed during run")
        if {p.name: native.sha(p) for p in native.ROOT.iterdir() if p.is_file()} != self.report["native_harness_sha256"]:
            raise ValueError("Native adapter changed during run")
        native.sources()  # Upstream stays pristine.
        self.report["status"] = "passed"
        path = self.out / "profile.json"
        path.write_text(json.dumps(self.report, indent=2) + "\n")
        print(f"Report: {path}", flush=True)
        return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, help="Write a public-safe summary after all gates pass")
    args = parser.parse_args()
    e = Experiment()
    print(f"Output: {e.out}", flush=True)
    try:
        e.measure()
        from workflow import run_workflow
        e.report["workflow"] = run_workflow(e, native)
        report_path = e.finish()
        if args.summary:
            summary = dict(e.report)
            summary.pop("commands")
            summary["full_report_sha256"] = native.sha(report_path)
            summary["reproduction"] = "python3 workloads/profile/run.py --summary workloads/evidence/S01-DEMAND-PROFILE.json"
            args.summary.write_text(json.dumps(summary, indent=2) + "\n")
    except Exception as error:
        e.report["status"] = "failed"
        e.report["error"] = str(error)
        (e.out / "profile.json").write_text(json.dumps(e.report, indent=2) + "\n")
        raise


if __name__ == "__main__": main()
