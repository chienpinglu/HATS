#!/usr/bin/env python3
"""Full tool matrix on generated APE RTL using complete streaming state hashes.

All events are included. This avoids materializing hundreds of GB of text; the
small SpinalSim gate remains the independent transport regression anchor.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "execute"))
import run as target
from toolchain import java_path


def digest_text(path):
    digest = hashlib.sha256(); registers = [0]*32; registers[10] = target.image.ARGUMENT
    count = retired = memory = 0
    for line in path.read_text().splitlines():
        event = json.loads(line)
        if event["kind"] == "retire":
            if event["writes"]: registers[event["rd"]] = int(event["value"])
            record = [1, int(event["pc"]), event["instruction"], int(event["next"]), *registers]; retired += 1
        elif event["kind"] == "memory":
            record = [2, int(event["address"]), event["bytes"], int(event["write"]), int(event["data"]), int(event["error"])]; memory += 1
        elif event["kind"] == "trap": record = [3, int(event["pc"]), event["cause"], int(event["value"])]
        else: raise ValueError("Unknown architectural record")
        digest.update(struct.pack("<" + "Q"*len(record), *record)); count += 1
    return {"schema": 1, "encoding": "hats-architectural-state-le64-v1", "events": count,
            "retirements": retired, "memory_events": memory, "sha256": digest.hexdigest()}


def cases(selected=None, kinds=None):
    image = target.image
    vectors = target.vectors()
    result = [("helpers", "integer-vectors", (image.MAGIC, 0, len(vectors), 0, 0, 0, 0, 0),
               b"".join(struct.pack("<4Q", *v) for v in vectors), b"", None),
              ("runtime", "runtime-tests", (image.MAGIC, 0, 0, 0, 65536, 0, 0, 0), b"", b"", None)]
    for name, old, new in target.native.cases():
        if selected and name not in selected: continue
        for kind in kinds or ["cold_old", "cold_new", "incremental"]:
            first, second = (new, b"") if kind == "cold_new" else (old, new if kind == "incremental" else b"")
            args = (image.MAGIC, int(kind == "incremental"), len(first), len(second), image.HEAP_BYTES, image.OUTPUT_BYTES, 0, 0)
            result.append(("parser", name + "-" + kind, args, first, second, 0))
    for name, updates, status in [("bad_magic", {0: 0}, 1), ("bad_mode", {1: 2}, 1),
                                  ("input_bound", {2: image.INPUT_MAX+1}, 1), ("invalid_heap_bound", {4: image.HEAP_BYTES+1}, 1),
                                  ("heap_zero", {4: 0}, 2), ("heap_small", {4: 128}, 2), ("output_full", {5: 64}, 3),
                                  ("output_short", {5: 63}, 1), ("output_bound", {5: image.OUTPUT_BYTES+1}, 1), ("reserved", {6: 1}, 1)]:
        args = [image.MAGIC, 0, 2, 0, image.HEAP_BYTES, image.OUTPUT_BYTES, 0, 0]
        for index, value in updates.items(): args[index] = value
        result.append(("parser", name, args, b"{}", b"", status))
    return result


def check_result(mode, args, old, new, status, output, result):
    if mode == "helpers":
        if result or struct.unpack_from("<4Q", output) != (target.image.MAGIC, 0, 0, 177): raise ValueError("Helper execution failed")
        for i, v in enumerate(target.vectors()):
            if struct.unpack_from("<6Q", output, 64+i*48) != target.expected_helpers(v): raise ValueError("Helper arithmetic differs")
    elif mode == "runtime":
        header = struct.unpack_from("<8Q", output)
        if result or header[:3] != (target.image.MAGIC, 0, 0) or header[3] != 160 or header[4]: raise ValueError("Runtime self checks failed")
    else:
        parsed = target.decode_result(output)
        if parsed["status"] != status or result != status: raise ValueError("Wrong parser status")
        if status == 0: target.native.check_output(new if args[1] else old, parsed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=[c[0] for c in target.native.cases()])
    parser.add_argument("--kind", action="append", choices=["cold_old", "cold_new", "incremental"])
    parser.add_argument("--rob", type=int, choices=[4, 8, 16], default=8)
    parser.add_argument("--prediction", choices=["off", "bimodal"], default="bimodal")
    parser.add_argument("--jobs", type=int, choices=[1, 2, 3], default=2)
    parser.add_argument("--repeat", type=int, choices=[1, 2], default=1)
    args = parser.parse_args()
    if args.case and len(set(args.case)) != len(args.case) or args.kind and len(set(args.kind)) != len(args.kind): parser.error("Duplicate selection")
    e = target.Execution()
    out = e.out / "bulk"; out.mkdir()
    sources = list(ROOT.glob("*.py")) + list(ROOT.glob("*.cc")) + list(ROOT.glob("*.h"))
    sources += list((target.REPO / "hardware/spinal/src").rglob("Ape*.scala"))
    sources += [target.REPO / "hardware/spinal" / p for p in ("build.sbt", "project/build.properties", "project/repositories", "tools/sbtw", "tools/toolchain.py")]
    hashes = {str(p.relative_to(target.REPO)): target.newlib.sha(p) for p in sources}
    report = {"schema": 1, "status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
              "claim_class": "actual_APE_RTL_complete_streaming_architectural_state_comparison", "source_sha256": hashes,
              "rob_entries": args.rob, "prediction": args.prediction, "repetitions": args.repeat,
              "limits": ["SHA-256 covers every memory event and every retired PC/instruction/next-PC/register state, not sampled traces",
                         "RTL register states reconstructed from architectural retirement ports; Spike states read from its actual registers",
                         "Independent semantic output check in addition to full stream and output-image equality",
                         "No CP/OS, cache/coherence, hardware speedup or PPA claim"]}
    print(f"Bulk RTL report: {out / 'validation.json'}", flush=True)
    try:
        reference = e.adapter()
        folders = {mode: e.build(mode) for mode in ("helpers", "runtime", "parser")}
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        report["toolchain"] = {
            "verilator": subprocess.check_output(["verilator", "--version"], env=env, text=True).strip(),
            "java": subprocess.check_output([java_path(), "-version"], stderr=subprocess.STDOUT, text=True).splitlines()[0],
            "crypto": subprocess.check_output(["/opt/homebrew/opt/openssl@3/bin/openssl", "version"], text=True).strip()}
        command = ["bash", "tools/sbtw", "compile", f"runMain hats.ApeToolGenerate {out / 'rtl'} {args.rob} {args.prediction}"]
        with (out / "build.log").open("w") as log:
            subprocess.run(command, cwd=target.REPO / "hardware/spinal", env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
            command = ["verilator", "--cc", str(out / "rtl/ApeCore.v"), "--exe", str(ROOT / "rtl_runner.cc"), "--build", "-j", "4",
                       "--Mdir", str(out / "obj"), "--top-module", "ApeCore", "--assert", "-Wno-fatal", "-O3",
                       "-CFLAGS", "-O3 -std=c++20 -I/opt/homebrew/opt/openssl@3/include",
                       "-LDFLAGS", "-L/opt/homebrew/opt/openssl@3/lib -lcrypto"]
            subprocess.run(command, cwd=target.REPO, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
        executable = out / "obj/VApeCore"
        report["generated_rtl_sha256"] = {p.name: target.newlib.sha(p) for p in (out / "rtl").glob("*.v")}
        report["rtl_executable_sha256"] = target.newlib.sha(executable)
        todo = cases(args.case, args.kind)
        def execute(case):
            mode, name, arguments, old, new, status = case
            folder = folders[mode]
            output, stats = e.invoke(reference, folder, name, arguments, old, new, 500000000,
                                     trace=(name == "empty-cold_old"), digest=True)
            golden = json.loads((folder / name / "digest.json").read_text())
            if name == "empty-cold_old" and digest_text(folder / name / "trace.jsonl") != golden:
                raise ValueError("Canonical binary stream differs from independently encoded text events")
            check_result(mode, arguments, old, new, status, output, stats["result"])
            prefix = folder / name / "rtl"
            command = [str(executable), str(folder), str(folder / name), str(prefix), str(args.repeat), "4000000000"]
            e.command(command, timeout=7200)
            runs = []
            for invocation in range(args.repeat):
                base = str(prefix) + f"-{invocation}"
                actual = json.loads(Path(base + ".digest.json").read_text())
                rtl_stats = json.loads(Path(base + ".execution.json").read_text())
                rtl_output = Path(base + ".result.bin").read_bytes()
                if actual != golden: raise ValueError(f"Complete architectural stream differs: {name}/{invocation}: {actual} != {golden}")
                if rtl_output != output: raise ValueError("Complete output image differs: " + name)
                check_result(mode, arguments, old, new, status, rtl_output, rtl_stats["result"])
                runs.append({"invocation": invocation, "digest": actual, "diagnostics": rtl_stats,
                             "output_sha256": target.newlib.sha(Path(base + ".result.bin"))})
            print(f"RTL PASS {mode}/{name}: {golden['retirements']} retirements, {golden['memory_events']} memory events", flush=True)
            return {"mode": mode, "case": name, "expected_status": status, "reference": stats, "runs": runs}
        results = []
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            futures = [pool.submit(execute, case) for case in todo]
            for future in as_completed(futures): results.append(future.result())
        report["results"] = sorted(results, key=lambda r: (r["mode"], r["case"]))
        if len(results) != len(todo): raise ValueError("Incomplete matrix")
        report["full_fixture_matrix"] = len([r for r in results if r["mode"] == "parser" and r["expected_status"] == 0]) == 30
        for p in sources:
            if target.newlib.sha(p) != hashes[str(p.relative_to(target.REPO))]: raise ValueError("Bulk source changed")
        if target.newlib.sha(executable) != report["rtl_executable_sha256"]: raise ValueError("RTL executable changed")
        e.check_artifacts(); report["target_build"] = e.report
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"APE full-stream gate PASS: {len(todo)*args.repeat} RTL invocations; complete fixture matrix={report['full_fixture_matrix']}")


if __name__ == "__main__": main()
