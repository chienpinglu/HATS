#!/usr/bin/env python3
"""Run a bounded Tree-sitter heap-exhaustion case on actual cached APE RTL."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time

from toolchain import java_path

HW = Path(__file__).resolve().parents[1]
REPO = HW.parent.parent
EXECUTE = REPO / "workloads/target/treesitter/execute"
sys.path.insert(0, str(EXECUTE))
sys.path.insert(0, str(HW / "tools"))
import run as target
from compare_ape_spike import compare, read_trace
from verify_ape_tool_cached import final_memory, trace_snapshot as parser_entry_snapshot


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-dir", required=True, type=Path,
                        help="parser folder from a source-bound Tree-sitter direct APE run")
    parser.add_argument("--case", default="scalars-cold_old")
    parser.add_argument("--heap-limit", type=int, default=128)
    parser.add_argument("--sets", type=int, default=64)
    parser.add_argument("--mshrs", type=int, default=4)
    parser.add_argument("--evidence-output", type=Path,
                        default=REPO / "workloads/evidence/S04-APE-HEAP-EXHAUSTION.json")
    args = parser.parse_args()
    app = args.application_dir.resolve()
    require(app.is_relative_to(REPO) and app.is_dir(), "Application directory must be inside this repository")
    require(0 <= args.heap_limit <= 0xA00000 and args.sets > 0 and args.mshrs > 0,
            "Invalid heap/cache configuration")
    base = app / args.case
    require(base.is_dir(), "Selected Tree-sitter case is missing")
    result_gate, direct_gate = app.parent / "validation.json", app.parent / "rtl-validation.json"
    reference = json.loads(result_gate.read_text())
    direct = json.loads(direct_gate.read_text())
    require(reference.get("status") == "passed" and direct.get("status") == "passed"
            and direct.get("ape_rtl_execution") is True
            and direct.get("reference_report_sha256") == sha(result_gate),
            "Requires passing source-bound target and direct APE reference gates")
    require(any(row.get("case") == args.case and row.get("invocation") == 0
                for row in direct.get("comparisons", [])),
            "Direct APE reference does not contain the selected case")
    source_case_args = struct.unpack("<8Q", (base / "args.bin").read_bytes())
    require(source_case_args[4] > args.heap_limit, "Selected heap cap must be below the passing baseline")

    out = HW / "build/s04" / f"ape-heap-exhaustion-{time.time_ns()}"
    out.mkdir(parents=True)
    e = target.Execution(out / "spike")
    reference_app = e.out / "parser"
    reference_app.mkdir()
    for name in ("code.bin", "data.bin", "runtime.properties"):
        shutil.copy2(app / name, reference_app / name)
    old = (base / "old.bin").read_bytes()
    new = (base / "new.bin").read_bytes()
    heap_args = list(source_case_args)
    heap_args[4] = args.heap_limit
    result_bytes, spike_stats = e.invoke(
        app.parent / "spike-tool", reference_app, "heap_exhaustion",
        tuple(heap_args), old, new, 500_000_000, trace=True)
    result = target.decode_result(result_bytes)
    case_dir = reference_app / "heap_exhaustion"
    spike_trace = case_dir / "trace.jsonl"
    require(spike_stats.get("status") == "executed" and spike_stats.get("result") == 2
            and result.get("status") == 2 and result.get("live_after_cleanup") == 0
            and result.get("heap_granted", args.heap_limit + 1) <= args.heap_limit,
            f"Spike target reference did not produce clean ENOMEM: stats={spike_stats} result={result}")
    require(result_bytes[64:] == bytes([0xCC]) * (len(result_bytes) - 64),
            "Spike OOM result wrote a partial output payload")
    expected = final_memory(reference_app, "heap_exhaustion", spike_trace)
    expected_path = out / "expected-memory.bin"
    expected_path.write_bytes(expected)
    setup_trace = app / f"{args.case}-setup" / "trace.jsonl"
    require(setup_trace.is_file(), "Source-bound successful setup trace is missing")
    warm = bytearray(parser_entry_snapshot(app, args.case, setup_trace))
    warm[0x210000 - 0x100000:0x300000 - 0x100000] = b"\xcc" * 0xF0000
    warm_path = out / "warm-start-memory.bin"
    warm_path.write_bytes(warm)
    warm_code = bytearray((reference_app / "code.bin").read_bytes())
    require(int.from_bytes(warm_code[0x1C:0x20], "little") == 0x0062F863,
            "Tree-sitter startup BSS-loop instruction changed")
    warm_code[0x1C:0x20] = (0x0100006F).to_bytes(4, "little")
    warm_code_path = out / "warm-start-code.bin"
    warm_code_path.write_bytes(warm_code)

    rtl_input = out / "rtl-input"
    rtl_input.mkdir()
    for name in ("code.bin", "data.bin", "runtime.properties"):
        shutil.copy2(reference_app / name, rtl_input / name)
    rtl_case = rtl_input / "heap_exhaustion"
    shutil.copytree(case_dir, rtl_case)
    rtl_out = out / "rtl-run"
    rtl_out.mkdir()
    shutil.copy2(expected_path, rtl_out / "expected-memory.bin")
    classpath_export = HW / "target/streams/test/fullClasspath/_global/streams/export"
    sim_class = HW / "target/scala-2.13/test-classes/hats/ApeCachedToolSim$.class"
    sim_source = HW / "src/test/scala/hats/ApeCachedToolSim.scala"
    require(classpath_export.is_file() and sim_class.is_file()
            and sim_class.stat().st_mtime >= sim_source.stat().st_mtime,
            "Fresh compiled ApeCachedToolSim is required; compile with the pinned Spinal plugin first")
    classpath = classpath_export.read_text().strip()
    require(bool(classpath), "Exported sbt test classpath is empty")
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    command = [java_path(), "-cp", classpath, "hats.ApeCachedToolSim", str(rtl_input), str(rtl_out),
               str(args.sets), str(args.mshrs), "heap_exhaustion", str(warm_path), str(warm_code_path)]
    gate = out / "gate.json"
    hw_sources = sorted(set((HW / "src/main/scala/hats").glob("*.scala"))
                        | set((HW / "src/test/scala/hats").glob("*.scala"))
                        | {HW / name for name in ("tools/verify_ape_heap_exhaustion.py",
                            "tools/verify_ape_tool_cached.py", "tools/compare_ape_spike.py",
                            "tools/toolchain.py", "tools/sbtw", "build.sbt",
                            "project/build.properties", "project/repositories")})
    hw_hashes = {str(p.relative_to(HW)): sha(p) for p in hw_sources}
    target_hashes = target.own_hashes()
    report = {"schema": 1, "issue": 5, "status": "running", "S04_complete": False,
              "claim_class": "actual_Tree_sitter_heap_exhaustion_on_APE_LSQ_I_D_L1_RTL",
              "application_dir": str(app.relative_to(REPO)), "case": args.case,
              "heap_limit_bytes": args.heap_limit, "cache": {"sets": args.sets, "mshrs": args.mshrs},
              "source_sha256": hw_hashes, "target_source_sha256": target_hashes,
              "reference_input_sha256": {str(p.relative_to(REPO)): sha(p) for p in
                  (result_gate, direct_gate, app / "code.bin", app / "data.bin", app / "runtime.properties",
                   app.parent / "spike-tool", base / "args.bin", base / "old.bin", base / "new.bin")},
              "derived_input_sha256": {str(p.relative_to(REPO)): sha(p) for p in
                  (case_dir / "args.bin", case_dir / "old.bin", case_dir / "new.bin", case_dir / "result.bin",
                   spike_trace, expected_path, warm_path, warm_code_path)},
              "spike_reference": {"stats": spike_stats, "result": {k: v for k, v in result.items() if k != "nodes"},
                  "trace_sha256": sha(spike_trace), "result_sha256": sha(case_dir / "result.bin")},
              "command": [x if x != classpath else "<sbt-test-classpath>" for x in command],
              "started_utc": datetime.now(timezone.utc).isoformat()}
    gate.write_text(json.dumps(report, indent=2) + "\n")
    log = out / "rtl-run.log"
    try:
        with log.open("w") as stream:
            subprocess.run(command, cwd=HW, env=env, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=1800)
        rtl_result = json.loads((rtl_out / "validation.json").read_text())
        actual_final = rtl_out / "final-memory.bin"
        actual_trace = rtl_out / "cached.trace.jsonl"
        require(rtl_result.get("status") == "passed" and rtl_result.get("line_requests") == rtl_result.get("line_completions") > 0
                and actual_final.is_file() and sha(actual_final) == sha(expected_path),
                "Actual APE RTL did not drain or match the independent full-memory OOM state")
        actual_bytes = actual_final.read_bytes()[0x110000:0x200000]
        require(actual_bytes == result_bytes and actual_bytes[64:] == bytes([0xCC]) * (len(actual_bytes) - 64),
                "APE heap-exhaustion output status/payload differs or contains partial result mutation")
        expected_trace = read_trace(spike_trace)
        actual_trace_events = read_trace(actual_trace)
        spike_start = next((i for i, event in enumerate(expected_trace)
                            if event["kind"] == "retire" and event["pc"] == "52"), None)
        ape_start = next((i for i, event in enumerate(actual_trace_events)
                          if event["kind"] == "retire" and event["pc"] == "52"), None)
        require(spike_start is not None and ape_start is not None, "Parser-entry architectural marker is missing")
        comparison = compare(actual_trace_events[ape_start:], expected_trace[spike_start:])
        require(comparison.get("status") == "matched", "APE OOM architectural trace differs from Spike")
        require(hw_hashes == {str(p.relative_to(HW)): sha(p) for p in hw_sources},
                "Hardware/test sources changed during heap-exhaustion run")
        e.check_artifacts()
        generated = list(rtl_out.rglob("ApeCachedDataTile.v"))
        require(bool(generated), "Actual APE I/D-L1 generated RTL is missing")
        report.update(status="passed_actual_APE_heap_exhaustion", actual_result=rtl_result,
            full_final_memory_matches_spike=True, architectural_comparison=comparison,
            generated_rtl_sha256={str(p.relative_to(out)): sha(p) for p in generated},
            final_memory_sha256=sha(actual_final), cached_trace_sha256=sha(actual_trace),
            classpath_export_sha256=sha(classpath_export), simulator_class_sha256=sha(sim_class),
            toolchain={"java": subprocess.run([java_path(), "-version"], capture_output=True, text=True).stderr.strip(),
                "verilator": subprocess.check_output(["verilator", "--version"], env=env, text=True).strip(),
                "cxx": subprocess.check_output(["c++", "--version"], env=env, text=True).splitlines()[0]},
            simulation_log_sha256=sha(log),
            limits=["Heap limit is 128 bytes for one selected Tree-sitter fixture; not an application-wide exhaustion bound",
                    "External line service is behavioral, not calibrated HBM/LPDDR timing"])
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        report["source_sha256_after"] = {str(p.relative_to(HW)): sha(p) for p in hw_sources}
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        gate.write_text(json.dumps(report, indent=2) + "\n")
    report["gate_path"] = str(gate.relative_to(REPO))
    report["gate_sha256"] = sha(gate)
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Actual APE I/D-L1 heap-exhaustion gate passed: {gate}")


if __name__ == "__main__":
    main()
