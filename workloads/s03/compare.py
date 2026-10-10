#!/usr/bin/env python3
"""Matched real-tool design points on actual RTL, with transaction-indexed service.

No native parser supplies DUT results. Complete architectural digests, output
images, binaries and realized service are checked before calculating cycle ratios.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware/spinal"
BULK = REPO / "workloads/target/treesitter/bulk"
sys.path.insert(0, str(BULK))
import verify as bulk

# name, ROB/reservation rows, PRF, issue width, prediction, predictor entries.
POINTS = [("narrow", 8, 64, 1, "bimodal", 16), ("dual", 8, 64, 2, "bimodal", 16),
          ("rob4", 4, 64, 1, "bimodal", 16), ("rob16", 16, 64, 1, "bimodal", 16),
          ("prf36", 8, 36, 1, "bimodal", 16), ("prf48", 8, 48, 1, "bimodal", 16),
          ("predict_off", 8, 64, 1, "off", 16), ("predict4", 8, 64, 1, "bimodal", 4),
          ("predict64", 8, 64, 1, "bimodal", 64)]
SERVICE_BASES = (2, 16)
SERVICE_SEED = 0x48415453


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Two widths and small inputs only; not full design-point evidence")
    args = parser.parse_args()
    points = POINTS[:2] if args.smoke else POINTS
    bases = SERVICE_BASES[:1] if args.smoke else SERVICE_BASES
    selected = ["empty", "scalars"] if args.smoke else ["empty", "unicode", "repository_lock", "records_256"]
    todo = [c for c in bulk.cases(selected, ["incremental"]) if c[0] != "parser" or c[-1] == 0]
    e = bulk.target.Execution()
    out = e.out / "design-study"; out.mkdir()
    path = out / "validation.json"
    source_paths = list((HW / "src").rglob("Ape*.scala"))
    source_paths += list(BULK.glob("*.py")) + list(BULK.glob("*.cc")) + list(BULK.glob("*.h"))
    source_paths += [Path(__file__), Path(__file__).with_name("service_schedule.h")]
    source_paths += [HW / p for p in ("build.sbt", "project/build.properties", "project/repositories", "tools/sbtw", "tools/toolchain.py")]
    sha = bulk.target.newlib.sha
    hashes = {str(p.relative_to(REPO)): sha(p) for p in source_paths}
    report = {"schema": 1, "status": "running", "issue": 4, "S03_complete": False,
              "claim_class": "actual_APE_RTL_matched_work_controlled_abstract_service",
              "started_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": hashes,
              "full_design_matrix": not args.smoke, "points": points,
              "service": {"response_bases": bases, "seed": SERVICE_SEED, "acceptance_jitter": [0, 3], "response_jitter": [0, 7],
                          "identity": "transaction ordinal, relative to first request presentation and acceptance; not cycle RNG"},
              "fixed": {"program_words": 65536, "checkpoints": 4, "dispatch_width": 1, "retire_width": 1,
                        "writeback_width": 1, "execution_stages": 2, "generation_bits": 2, "outstanding_memory": 1},
              "limits": ["Abstract memory cycles, not HBM/LPDDR latency or a cache hierarchy",
                         "Simulated cycles/IPC are not clock frequency, wall-clock hardware speedup or physical energy",
                         "ROB capacity also sizes the fused reservation rows; not a separately sized issue-queue study",
                         "Small generic synthesis code memories must not be equated to this 65536-word tool image",
                         "Not a compiler or Python running on APE; actual tree-sitter parsing, integer helpers and runtime tests"]}

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    save(); print(f"Controlled design study: {path}", flush=True)
    try:
        adapter = e.adapter()
        folders = {mode: e.build(mode) for mode in ("helpers", "runtime", "parser")}
        references = {}
        for mode, name, arguments, old, new, status in todo:
            output, stats = e.invoke(adapter, folders[mode], name, arguments, old, new, 500000000, digest=True)
            bulk.check_result(mode, arguments, old, new, status, output, stats["result"])
            references[(mode, name)] = (output, json.loads((folders[mode] / name / "digest.json").read_text()))
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        report["tools"] = {"verilator": subprocess.check_output(["verilator", "--version"], env=env, text=True).strip(),
                           "java": subprocess.check_output([bulk.java_path(), "-version"], stderr=subprocess.STDOUT, text=True).splitlines()[0],
                           "openssl": subprocess.check_output(["/opt/homebrew/opt/openssl@3/bin/openssl", "version"], text=True).strip()}
        generated, results = {}, []
        for label, rob, prf, width, mode, predictor in points:
            dest = out / label; dest.mkdir()
            command = ["bash", "tools/sbtw", "compile",
                       f"runMain hats.ApeDesignPointGenerate {dest / 'rtl'} {rob} {prf} {width} {mode} {predictor} 65536 4"]
            with (dest / "build.log").open("w") as log:
                subprocess.run(command, cwd=HW, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
                command = ["verilator", "--cc", str(dest / "rtl/ApeCore.v"), "--exe", str(BULK / "rtl_runner.cc"), "--build", "-j", "4",
                           "--Mdir", str(dest / "obj"), "--top-module", "ApeCore", "--assert", "-Wno-fatal", "-O3",
                           "-CFLAGS", "-O3 -std=c++20 -DHATS_S03 -I/opt/homebrew/opt/openssl@3/include",
                           "-LDFLAGS", "-L/opt/homebrew/opt/openssl@3/lib -lcrypto"]
                subprocess.run(command, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
            executable = dest / "obj/VApeCore"
            generated[label] = {str(p.relative_to(REPO)): sha(p) for p in [executable, dest / "build.log", *(dest / "rtl").glob("*.v")]}

            def execute(item):
                base, case = item
                workload, name, arguments, old, new, status = case
                prefix = dest / f"{workload}-{name}-m{base}"
                e.command([str(executable), str(folders[workload]), str(folders[workload] / name), str(prefix), "1", "4000000000",
                           str(base), str(SERVICE_SEED)], timeout=7200)
                stem = str(prefix) + "-0"
                actual = json.loads(Path(stem + ".digest.json").read_text())
                stats = json.loads(Path(stem + ".execution.json").read_text())
                output = Path(stem + ".result.bin").read_bytes()
                golden_output, golden_digest = references[(workload, name)]
                require(actual == golden_digest and output == golden_output, "Architectural stream/output differs from Spike")
                bulk.check_result(workload, arguments, old, new, status, output, stats["result"])
                require(stats["cycles"] > 0 and stats["retired"] == actual["retirements"] and stats["requests"] == actual["memory_events"], "Inconsistent counters")
                require(stats["response_base"] == base and stats["service_seed"] == SERVICE_SEED, "Wrong service profile")
                require(width != 1 or stats["dual_issue_cycles"] == 0, "Narrow configuration reported dual issue")
                artifacts = {str(Path(stem + ext).relative_to(REPO)): sha(Path(stem + ext)) for ext in (".digest.json", ".execution.json", ".result.bin")}
                print(f"PASS {label}/m{base}/{workload}/{name}: {stats['cycles']} cycles, {stats['dual_issue_cycles']} dual issues", flush=True)
                return {"point": label, "response_base": base, "workload": workload, "case": name,
                        "digest": actual, "metrics": stats, "artifacts_sha256": artifacts}

            with ThreadPoolExecutor(max_workers=2) as pool:
                results += list(pool.map(execute, [(base, case) for base in bases for case in todo]))
            report.update(results=results, generated=generated); save()
        require(len(results) == len(points) * len(bases) * len(todo), "Incomplete design matrix")
        baseline = {(r["response_base"], r["workload"], r["case"]): r for r in results if r["point"] == "narrow"}
        for row in results:
            base = baseline[(row["response_base"], row["workload"], row["case"])]
            require(row["digest"] == base["digest"], "Changed architectural work")
            for field in ("requests", "retired", "service_seed", "response_base", "acceptance_wait_sum", "response_wait_sum"):
                require(row["metrics"][field] == base["metrics"][field], "Different realized work/service: " + field)
            row["simulated_ipc"] = row["metrics"]["retired"] / row["metrics"]["cycles"]
            row["baseline_cycles_over_candidate_cycles"] = base["metrics"]["cycles"] / row["metrics"]["cycles"]
        require(sum(r["metrics"]["dual_issue_cycles"] for r in results if r["point"] == "dual") > 0, "Real workload never exercised dual issue")
        require(all(sha(REPO / n) == h for n, h in hashes.items()), "Source changed during comparison")
        for bound in [*generated.values(), *(r["artifacts_sha256"] for r in results)]:
            require(all(sha(REPO / n) == h for n, h in bound.items()), "Generated evidence changed")
        e.check_artifacts()
        e.report["status"] = "passed_reference_preparation"
        report.update(status="passed", target_build=e.report, results=results, generated=generated)
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print(f"Controlled RTL comparison passed; full design matrix={not args.smoke}. No clock/energy/issue-closure claim.")


if __name__ == "__main__":
    main()
