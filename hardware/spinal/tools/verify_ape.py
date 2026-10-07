#!/usr/bin/env python3
"""Verify APE's RTL matrix, predictor and evidence identity. Not an ISA certificate."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from toolchain import java_path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build/ape"
CONFIGS = [(n, mode) for n in (4, 8, 16) for mode in ("off", "bimodal")]


def hashes(paths):
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    path = BUILD / "validation.json"
    inputs = [ROOT / "build.sbt", ROOT / "project/build.properties", ROOT / "project/repositories"]
    inputs += list((ROOT / "src").rglob("Ape*.scala")) + list((ROOT / "src").rglob("Hse*.scala"))
    inputs += list((ROOT / "examples/ape").glob("*"))
    inputs += [ROOT / "tools" / n for n in ("assemble_ape.py", "verify_ape.py", "assemble_hse.py",
                                              "verify_hse.py", "sbtw", "toolchain.py")]
    initial = hashes(inputs)
    report = {"status": "running", "spec_revision": "APE-0.2",
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "claim": "Speculative out-of-order RV64I-subset RTL mechanism verification",
              "path": "LLVM linked RV64 programs -> SpinalHDL -> Verilator/SpinalSim -> retirement scoreboard",
              "configurations": [{"rob_entries": n, "prediction": mode} for n, mode in CONFIGS],
              "source_sha256": initial,
              "limits": ["Not full RV64I/privileged conformance or a high-performance CPU",
                         "Local sequential oracle, not external Spike/Sail certification",
                         "Head-only external memory with synthetic service latency",
                         "Command sink is not a CP or integrated task runtime",
                         "No caches/MMU/coherence/vector/tensor hardware or PPA/speedup measurement"]}

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    save()
    for name in [f"r{n}-{mode}" for n, mode in CONFIGS] + ["predictor"]:
        directory = BUILD / name
        directory.mkdir(exist_ok=True)
        (directory / "validation.json").write_text('{"status":"not_run"}\n')
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    try:
        report["verilator"] = subprocess.check_output(["verilator", "--version"], env=env, text=True).strip()
        report["java"] = subprocess.check_output([java_path(), "-version"], stderr=subprocess.STDOUT, text=True).splitlines()[0]
        subprocess.run([sys.executable, "tools/assemble_ape.py"], cwd=ROOT, env=env, check=True, timeout=180)
        command = ["bash", "tools/sbtw", "compile", "Test / compile", "runMain hats.GenerateApe",
                   "runMain hats.GenerateHse", "Test / runMain hats.ApePredictorSim"]
        command += [f"Test / runMain hats.ApeCoreSim {n} {mode}" for n, mode in CONFIGS]
        report["command"] = command
        save()
        print("Running APE RTL validation; log: build/ape/verification.log", flush=True)
        with (BUILD / "verification.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                           check=True, timeout=900)
        predictor = json.loads((BUILD / "predictor/validation.json").read_text())
        if predictor.get("status") != "passed" or predictor.get("lookup_checks") != 4096:
            raise RuntimeError("Predictor gate incomplete")
        report["predictor"] = predictor
        suites = [json.loads((BUILD / f"r{n}-{mode}/validation.json").read_text()) for n, mode in CONFIGS]
        for (n, mode), suite in zip(CONFIGS, suites):
            if not (suite["status"] == "passed" and suite["rob_entries"] == n and suite["prediction"] == mode
                    and suite["runs"] == len(suite["results"]) == suite["scenarios"] * 2
                    and suite["scenarios"] == 50 and all(c["passed"] for c in suite["results"])):
                raise RuntimeError(f"Incomplete suite: {n}/{mode}")
        def signature(suite):
            return [(r["name"], r["invocation"], r["result"], r["retired"],
                     r["memory_requests"], r["command_writes"]) for r in suite["results"]]
        if any(signature(s) != signature(suites[0]) for s in suites[1:]):
            raise RuntimeError("Architectural outcomes differ across ROB/prediction configurations")
        report["architectural_matrix_equivalence"] = "passed"
        report["suites"] = [{k: s[k] for k in ("rob_entries", "prediction", "scenarios", "runs")} for s in suites]
        report["runs_passed"] = sum(s["runs"] for s in suites)
        report["loop_diagnostics"] = [{"rob_entries": s["rob_entries"], "prediction": s["prediction"],
            **{k: r[k] for k in ("cycles", "branches", "branch_misses", "redirects")}}
            for s in suites for r in s["results"] if r["name"] == "loop_rob_wrap" and r["invocation"] == 0]
        if hashes(inputs) != initial:
            raise RuntimeError("Sources changed during validation; rerun the gate")
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        report["source_sha256_after"] = hashes(inputs)
        artifacts = list(BUILD.glob("rtl/r*/ApeCore.v")) + list(BUILD.glob("programs/*.hex"))
        artifacts += [BUILD / "programs/manifest.json"]
        report["artifact_sha256"] = hashes(artifacts)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(f"APE PASS: {report['runs_passed']} RTL invocations, 4096 predictor checks, 6 configurations")


if __name__ == "__main__":
    main()
