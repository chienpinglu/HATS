#!/usr/bin/env python3
"""Fresh Spike/direct-APE oracle plus six actual APE cached RTL design points.

This compact S04 refresh complements, but does not replace, the 12-input
application suite. All generated inputs and RTL evidence use a fresh run root.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import bootstrap_spike as spike
from check_ape_diff import check_output
from compare_ape_spike import compare, read_trace
from toolchain import java_path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
POINTS = (("D_L1", 8, 2), ("D_L1", 16, 4), ("D_L1", 32, 8),
          ("I_D_L1", 8, 2), ("I_D_L1", 16, 4), ("I_D_L1", 32, 8))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hashes(paths):
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", default="repo_source_edit",
                        choices=("repo_source_edit", "empty", "insert", "delete", "replace",
                                 "duplicate_tie", "line_endings", "binary_bytes", "max_lines",
                                 "max_bytes", "too_many_lines", "too_many_bytes"))
    parser.add_argument("--evidence-output", type=Path,
                        default=REPO / "workloads/evidence/S04-APE-CACHED-FOCUSED-APPLICATION.json")
    args = parser.parse_args()
    out = ROOT / "build/s04" / f"ape-cached-focused-{time.time_ns()}"
    app = out / "app"
    out.mkdir(parents=True)
    sources = sorted((ROOT / "src/main/scala/hats").glob("*.scala")) + sorted(
        (ROOT / "src/test/scala/hats").glob("*.scala"))
    sources += [ROOT / p for p in ("tools/build_ape_app.py", "tools/ape_app_image.py",
        "tools/verify_ape_cached_focused_application.py", "tools/compare_ape_spike.py",
        "tools/check_ape_diff.py", "tools/bootstrap_spike.py", "tools/spike_adapter.cc",
        "tools/spike.lock.json", "tools/toolchain.py", "tools/sbtw", "build.sbt",
        "project/build.properties", "project/repositories", "examples/ape/kernel.c")]
    sources += sorted((ROOT / "examples/ape_app").glob("*"))
    sources = sorted(set(sources))
    before = hashes(sources)
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    java = java_path()
    tool_commands = {"java": [java, "-version"], "verilator": ["verilator", "--version"],
        "cxx": ["c++", "--version"], "make": ["make", "--version"],
        "clang": ["clang", "--version"], "linker": ["ld.lld", "--version"]}
    tool_info = {}
    for name, command in tool_commands.items():
        executable = Path(subprocess.check_output(["which", command[0]], env=env, text=True).strip()).resolve()
        version = subprocess.run(command, env=env, text=True, capture_output=True, check=True)
        tool_info[name] = {"path": str(executable), "sha256": sha(executable),
                           "version": (version.stdout + version.stderr).strip()}
    spike_build = spike.check()
    report = {"schema": 1, "issue": 5, "status": "running", "S04_complete": False,
        "claim_class": "one_real_APE_application_through_current_direct_and_cached_APE_I_D_L1_RTL",
        "application": args.application, "cache_points": [{"mode": m, "sets": s, "mshrs": n}
                                                            for m, s, n in POINTS],
        "source_sha256": before, "tools": tool_info, "spike_build_sha256": sha(spike.STAMP),
        "command": ["python3 tools/build_ape_app.py --output <run>/app",
          "<pinned-spike> <code.hex> 0 1 0 <spike.log> <application.bin> 90112",
          "bash tools/sbtw Test / compile",
          "direct Java hats.ApeApplicationSim 8 bimodal <run>/app <application>",
          "direct Java hats.CachedApplicationSim <run>/app <point-output> <sets> <mshrs> <mode> <application> 0"],
        "started_utc": datetime.now(timezone.utc).isoformat(), "runs": []}
    gate = out / "gate.json"
    log_path = out / "run.log"
    gate.write_text(json.dumps(report, indent=2) + "\n")
    try:
        with log_path.open("w") as log:
            subprocess.run(["python3", "tools/build_ape_app.py", "--output", str(app)], cwd=ROOT,
                           env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
            names = (app / "cases.txt").read_text().splitlines()
            require(args.application in names and len(names) == 12, "built application case manifest is incomplete")
            manifest = json.loads((app / "manifest.json").read_text())
            case = next(row for row in manifest["cases"] if row["name"] == args.application)
            spike_trace = app / "spike" / f"{args.application}.jsonl"
            spike_raw = app / "spike" / f"{args.application}.log"
            spike_trace.parent.mkdir(parents=True, exist_ok=True)
            with spike_trace.open("w") as stdout, spike_raw.open("w") as stderr:
                subprocess.run([str(spike.BINARY), str(app / "code.hex"), "0", "1", "0", str(spike_raw),
                    str(app / f"{args.application}.bin"), "90112"], cwd=ROOT, env=env,
                    stdout=stdout, stderr=stderr, check=True, timeout=60)
            spike_rows = read_trace(spike_trace)
            exit_pc = int(dict(line.split("=", 1) for line in
                (app / "runtime.properties").read_text().splitlines())["exit_pc"])
            require(spike_rows[-1] == {"kind": "trap", "pc": str(exit_pc), "cause": 3,
                "value": str(case["expected_status"])}, "Pinned Spike application run failed")
            reference_memory = bytearray((app / f"{args.application}.bin").read_bytes())
            for event in spike_rows:
                if event["kind"] == "memory" and event["write"]:
                    address, size = int(event["address"]), event["bytes"]
                    require(not event["error"] and 0x10000 <= address <= 0x20000 - size,
                            "Spike application emitted an invalid store")
                    offset = address - 0x10000
                    reference_memory[offset:offset+size] = int(event["data"]).to_bytes(size, "little")
            check_output(reference_memory, (app / f"{args.application}.old").read_bytes(),
                         (app / f"{args.application}.new").read_bytes(), case["expected_status"])

            subprocess.run(["bash", "tools/sbtw", "Test / compile"], cwd=ROOT, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
            classpath_export = ROOT / "target/streams/test/fullClasspath/_global/streams/export"
            require(classpath_export.is_file(), "compiled test classpath export is missing")
            classpath = classpath_export.read_text().strip()
            require(classpath and all(Path(item).exists() for item in classpath.split(":")),
                    "compiled test classpath contains missing entries")
            report["classpath_export_sha256"] = sha(classpath_export)

            def java_main(name, *arguments):
                command = [java, "-Xmx3G", "-XX:ActiveProcessorCount=4", "-cp", classpath,
                           "hats." + name, *map(str, arguments)]
                log.write("\nDirect Java main: " + " ".join(command) + "\n"); log.flush()
                subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=1800)

            java_main("ApeApplicationSim", 8, "bimodal", app, args.application)
            direct_folder = app / "r8-bimodal"
            direct_trace = direct_folder / f"{args.application}-0.arch.jsonl"
            direct_memory_path = direct_folder / f"{args.application}-0.memory.bin"
            direct_comparison = compare(read_trace(direct_trace), spike_rows)
            require(direct_comparison["status"] == "matched", "Current direct APE trace differs from Spike")
            require(direct_memory_path.read_bytes() == bytes(reference_memory),
                    "Current direct APE final memory differs from Spike oracle")

            inputs = [app / p for p in ("code.hex", "runtime.properties", f"{args.application}.bin",
                      f"{args.application}.old", f"{args.application}.new", "manifest.json")]
            inputs += [spike_trace, spike_raw, direct_trace, direct_memory_path,
                       app / "r8-bimodal/validation.json"]
            input_hashes = {str(path.relative_to(out)): sha(path) for path in inputs}
            for mode, sets, mshrs in POINTS:
                target = out / f"cached-{args.application}-{mode.lower()}-s{sets}-m{mshrs}"
                java_main("CachedApplicationSim", app, target, sets, mshrs,
                          "icache" if mode == "I_D_L1" else "dcache", args.application, 0)
                validation = target / "validation.json"
                rtl = target / "rtl/tmp/job_1/ApeCachedDataTile.v"
                result = json.loads(validation.read_text())
                require(result.get("status") == "passed" and result.get("line_requests") ==
                        result.get("line_completions") > 0, "Cached APE RTL run failed or did not drain")
                rtl_hash = sha(rtl)
                require(len(rtl_hash) == 64, "Generated RTL hash could not be read")
                report["runs"].append({**result, "validation_path": str(validation.relative_to(out)),
                    "validation_sha256": sha(validation), "generated_rtl": str(rtl.relative_to(out)),
                    "generated_rtl_sha256": rtl_hash,
                    "architectural_trace_matches_spike": direct_comparison["status"] == "matched",
                    "final_memory_matches_spike": (target / f"{args.application}-0.memory.bin").read_bytes()
                        == bytes(reference_memory)})
                require(report["runs"][-1]["final_memory_matches_spike"],
                        "Cached APE final memory differs from independent Spike oracle")
            report["application_manifest_sha256"] = sha(app / "manifest.json")
            require(input_hashes == {str(path.relative_to(out)): sha(path) for path in inputs},
                    "Application or oracle inputs changed during cached RTL runs")
            report["input_sha256"] = input_hashes
            report["spike_architectural_comparison"] = direct_comparison
            report["spike_final_memory_sha256"] = hashlib.sha256(reference_memory).hexdigest()
            report["status"] = "passed_focused_current_source_application_design_points"
            report["external_service_model"] = "Behavioral line service with randomized ready/response delay and ordering; not calibrated DRAM/HBM/LPDDR timing"
            report["limits"] = ["One of the 12 real diff workload inputs; broad 12-input cached matrix remains required",
                "Selected ROB8/P48/W1 direct APE profile and six cache points; no PPE integration claim in this run",
                "Behavioral lower-line service is not a physical controller or measured bandwidth"]
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        report["source_sha256_after"] = hashes(sources)
        report["run_log_sha256"] = sha(log_path) if log_path.is_file() else None
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        gate.write_text(json.dumps(report, indent=2) + "\n")
    require(report["source_sha256"] == report["source_sha256_after"], "Source changed during focused run")
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Focused current-source APE cache application passed: {gate}")


if __name__ == "__main__":
    main()
