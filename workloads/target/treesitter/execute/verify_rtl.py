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
    args = parser.parse_args()
    selected = args.case or ["empty", "scalars", "unicode"]
    kinds = args.kind or ["cold_old", "cold_new", "incremental"]
    if len(set(selected)) != len(selected) or len(set(kinds)) != len(kinds): parser.error("Duplicate selection")
    e = target.Execution()
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
        command = ["bash", "tools/sbtw", "Test / compile", f"Test / runMain hats.ApeToolSim {app} {args.rob} {args.prediction}"]
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        report["toolchain"] = {
            "verilator": subprocess.check_output(["verilator", "--version"], env=env, text=True).strip(),
            "java": subprocess.check_output([java_path(), "-version"], stderr=subprocess.STDOUT, text=True).splitlines()[0],
            "host_cxx": subprocess.check_output(["clang++", "--version"], env=env, text=True).splitlines()[0]}
        print(f"Running actual RTL; log: {e.out / 'rtl.log'}", flush=True)
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
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        (e.out / "rtl-validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"RTL PASS: {len(report['comparisons'])} actual APE invocations. Report: {e.out / 'rtl-validation.json'}")


if __name__ == "__main__": main()
