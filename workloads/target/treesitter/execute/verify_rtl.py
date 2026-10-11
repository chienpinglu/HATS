#!/usr/bin/env python3
"""Fresh strict ELF -> Spike traces -> actual APE RTL -> independent output checks."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import run as target
from compare_ape_spike import compare, read_trace
from toolchain import java_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", choices=[c[0] for c in target.native.cases()])
    parser.add_argument("--kind", action="append", choices=["cold_old", "cold_new", "incremental"])
    parser.add_argument("--rob", type=int, choices=[4, 8, 16], default=8)
    parser.add_argument("--prediction", choices=["off", "bimodal"], default="bimodal")
    parser.add_argument("--output", type=Path, help="Use a fresh isolated output directory")
    args = parser.parse_args()
    selected = args.case or ["empty", "scalars", "unicode"]
    kinds = args.kind or ["cold_old", "cold_new", "incremental"]
    if len(set(selected)) != len(selected) or len(set(kinds)) != len(kinds): parser.error("Duplicate selection")
    e = target.Execution(args.output)
    print(f"Reference: {e.out / 'validation.json'}", flush=True)
    report = {"schema": 1, "status": "running", "claim_class": "upstream_tool_on_ape_rtl",
              "ape_rtl_execution": True, "rob_entries": args.rob, "prediction": args.prediction,
              "selected_cases": selected, "selected_kinds": kinds, "full_S02_gate": False,
              "limits": ["Selected small tool fixtures only; complete S02 APE/PPE/configuration gate remains open",
                         "Host compiles, loads and models memory; actual parser instructions execute on APE RTL",
                         "256 KiB asynchronous instruction store is a test profile, not an implemented cache or physical SRAM",
                         "No CP/OS integration, coherent hierarchy, performance/energy or large-core claim"]}
    rtl_sources = [p for p in (target.REPO / "hardware/spinal/src").rglob("Ape*.scala")]
    rtl_sources += [target.REPO / "hardware/spinal" / p for p in ("build.sbt", "project/build.properties",
                    "project/repositories", "tools/sbtw", "tools/toolchain.py", "tools/compare_ape_spike.py")]
    report["source_sha256"] = {str(p.relative_to(target.REPO)): target.newlib.sha(p) for p in rtl_sources}
    try:
        e.run(selected, kinds, 500000000, True)
        e.check_artifacts()
        unit = subprocess.run(["/opt/homebrew/bin/python3" if Path("/opt/homebrew/bin/python3").is_file() else "python3",
                               "-m", "unittest", "discover", "-s", str(target.ROOT), "-p", "test_*.py", "-v"],
                              check=True, capture_output=True, text=True, timeout=60)
        print(unit.stderr, flush=True)
        (e.out / "validation.json").write_text(json.dumps(e.report, indent=2) + "\n")
        app = e.out / "parser"
        names = [r["case"] + "-" + r["kind"] for r in e.report["runs"]]
        (app / "rtl-cases.txt").write_text("\n".join(names) + "\n")
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        env["TMPDIR"] = str(e.out / "tmp"); Path(env["TMPDIR"]).mkdir(exist_ok=True)
        classpath_export = target.REPO / "hardware/spinal/target/streams/test/fullClasspath/_global/streams/export"
        classes = target.REPO / "hardware/spinal/target/scala-2.13/test-classes/hats/ApeToolSim$.class"
        core_class = target.REPO / "hardware/spinal/target/scala-2.13/classes/hats/ApeCore.class"
        core_source = target.REPO / "hardware/spinal/src/main/scala/hats/ApeCore.scala"
        test_source = target.REPO / "hardware/spinal/src/test/scala/hats/ApeToolSim.scala"
        if not classpath_export.is_file() or not classes.is_file() or not core_class.is_file() or \
                classes.stat().st_mtime < test_source.stat().st_mtime or core_class.stat().st_mtime < core_source.stat().st_mtime:
            raise ValueError("Fresh compiled APE test classes are unavailable; run Test / compile outside the restricted sbt server")
        classpath = classpath_export.read_text().strip()
        if not classpath: raise ValueError("sbt Test classpath export is empty")
        report["toolchain"] = {
            "verilator": subprocess.check_output(["verilator", "--version"], env=env, text=True).strip(),
            "java": subprocess.check_output([java_path(), "-version"], stderr=subprocess.STDOUT, text=True).splitlines()[0],
            "host_cxx": subprocess.check_output(["clang++", "--version"], env=env, text=True).splitlines()[0]}
        print(f"Running actual RTL; log: {e.out / 'rtl.log'}", flush=True)
        command = [java_path(), "-cp", classpath, "hats.ApeToolSim", str(app), str(args.rob), args.prediction]
        with (e.out / "rtl.log").open("w") as log:
            subprocess.run(command, cwd=target.REPO / "hardware/spinal", env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        folder = app / f"rtl-r{args.rob}-{args.prediction}"
        suite = json.loads((folder / "validation.json").read_text())
        if suite["status"] != "passed" or [(r["case"], r["invocation"]) for r in suite["runs"]] != [(n, i) for n in names for i in range(2)]:
            raise ValueError("Incomplete RTL invocation matrix")
        fixtures = {name: (old, new) for name, old, new in target.native.cases()}
        report["comparisons"] = []
        for r in e.report["runs"]:
            name = r["case"] + "-" + r["kind"]
            golden = read_trace(app / name / "trace.jsonl")
            expected = fixtures[r["case"]][0 if r["kind"] == "cold_old" else 1]
            for i in range(2):
                path = folder / f"{name}-{i}.trace.jsonl"
                matched = compare(read_trace(path), golden)
                output = (folder / f"{name}-{i}.result.bin").read_bytes()
                if output != (app / name / "result.bin").read_bytes(): raise ValueError("RTL result image differs from Spike")
                parsed = target.decode_result(output)
                checked = target.native.check_output(expected, parsed)
                report["comparisons"].append({"case": name, "invocation": i, "trace": matched, "oracle": checked,
                                               "trace_sha256": target.newlib.sha(path), "output_sha256": target.newlib.sha(folder / f"{name}-{i}.result.bin")})
        for p in rtl_sources:
            if target.newlib.sha(p) != report["source_sha256"][str(p.relative_to(target.REPO))]: raise ValueError("RTL/test source changed")
        generated = list((folder / "sim").rglob("ApeCore.v"))
        if not generated: raise ValueError("Missing generated RTL")
        report["generated_rtl_sha256"] = [target.newlib.sha(p) for p in generated]
        report["reference_report_sha256"] = target.newlib.sha(e.out / "validation.json")
        report["rtl_diagnostics"] = suite
        e.check_artifacts()
        report["status"] = "passed"
        import bootstrap_spike as spike
        snapshots = {}
        for run in e.report["runs"]:
            name = run["case"] + "-" + run["kind"]
            setup_case = app / (name + "-setup")
            setup_case.mkdir()
            for filename in ("args.bin", "old.bin", "new.bin"):
                (setup_case / filename).write_bytes((app / name / filename).read_bytes())
            code=(app/"code.bin").read_bytes()
            (setup_case/"code.hex").write_text("".join(f"{int.from_bytes(code[i:i+4], 'little'):08x}\n" for i in range(0,len(code),4)))
            command=[str(spike.BINARY),str(setup_case/"code.hex"),"0","1","0",str(setup_case/"spike.log"),
              str(app/"data.bin"),"1572864","0x100000","1"]
            with (setup_case/"trace.jsonl").open("w") as output:
                subprocess.run(command,cwd=target.REPO/"hardware/spinal",stdout=output,check=True,timeout=600)
            setup_image=bytearray((app/"data.bin").read_bytes())
            for filename,address in (("args.bin",0x180000),("old.bin",0x181000),("new.bin",0x1c1000)):
                raw=(setup_case/filename).read_bytes();offset=address-0x100000;setup_image[offset:offset+len(raw)]=raw
            for event in map(json.loads,(setup_case/"trace.jsonl").read_text().splitlines()):
                if event.get("kind")=="parser_start": break
                if event.get("kind")=="memory" and event["write"]:
                    offset=int(event["address"])-0x100000;raw=int(event["data"]).to_bytes(event["bytes"],"little")
                    setup_image[offset:offset+len(raw)]=raw
            else: raise ValueError(f"Spike setup did not reach parser entry for {name}")
            warm_path=app/f"warm-start-memory-{name}.bin";warm_path.write_bytes(setup_image)
            snapshots[name]={"status":"passed", "claim_class":"Spike_derived_parser_entry_memory_snapshot",
              "setup_trace_sha256":target.newlib.sha(setup_case/"trace.jsonl"),
              "warm_start_sha256":target.newlib.sha(warm_path)}
        if "empty-cold_old" in snapshots:
            (app/"warm-start-memory.bin").write_bytes((app/"warm-start-memory-empty-cold_old.bin").read_bytes())
        if snapshots:
            (app/"setup-validation.json").write_text(json.dumps({"status":"passed","snapshots":snapshots},indent=2)+"\n")
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        (e.out / "rtl-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"RTL PASS: {len(report['comparisons'])} actual APE invocations. Report: {e.out / 'rtl-validation.json'}")


if __name__ == "__main__": main()
