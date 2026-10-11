#!/usr/bin/env python3
"""Run source-bound nonblocking L1 RTL tests; not the S04 integration gate."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from toolchain import java_path

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def hashes(paths):
    return {str(p.relative_to(ROOT)): sha(p) for p in paths}


def validate(result):
    require(result["status"] == "passed" and result["issue"] == 5 and result["S04_complete"] is False
            and result["claim_class"] == "actual_nonblocking_L1_component_RTL", "Wrong L1 execution scope")
    rows = result["configurations"]
    require(sorted((r["sets"], r["line_bytes"], r["mshrs"]) for r in rows)
            == [(4, 16, 2), (8, 32, 4), (16, 64, 8)], "Missing or duplicate L1 configuration")
    for row in rows:
        require(row["generation_bits"] == 2 and row["cycles"] > row["completed"] == 3118 + row["mshrs"]
                and row["accepted"] == row["completed"] == row["reads"] + row["writes"] + row["faulted_requests"],
                "Incomplete request accounting")
        require(row["max_client_outstanding"] == row["max_lower_outstanding"] == row["mshrs"], "No full/concurrent MSHR witness")
        require(all(row[k] > 0 for k in ("client_reorders", "lower_reorders", "stale_replies", "lower_stall_cycles",
                                        "response_stall_cycles", "flush_stall_cycles", "hits_under_miss", "drain_checks",
                                        "stale_generations", "stale_phases")), "Missing adversarial witness")
        require(row["atomic_adds"] == 4 and row["faulted_requests"] == 5
                and row["failed_flushes"] == row["quiescent_resets"] == 1
                and row["flushes"] >= 7, "Missing fault/maintenance lifecycle coverage")
        counters = row["counters"]
        require(counters["hits"] + counters["misses"] == row["accepted"] - 1
                and counters["writebacks"] == row["observed_lower_writes"] > 0
                and counters["refills"] == row["observed_lower_reads"] > 0
                and counters["rejected_replies"] == row["stale_replies"] == row["stale_generations"] + row["stale_phases"]
                and counters["set_stalls"] > 0 and counters["full_stalls"] > 0
                and row["observed_generations"] == 4, "Counters differ from observed protocol events")
        require(result["limits"] and any("64-bit atomic-add" in x for x in result["limits"]),
                "Undocumented atomic primitive/evidence boundary")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Fresh run directory under hardware/spinal/build")
    args = parser.parse_args()
    out = args.output.resolve() if args.output else ROOT / "build/s04" / f"l1-{time.time_ns()}"
    require(out.is_relative_to(ROOT / "build") and not out.exists(), "Use a fresh local build directory")
    out.mkdir(parents=True)
    sources = [ROOT / p for p in ("src/main/scala/hats/MemoryHierarchy.scala", "src/test/scala/hats/NonBlockingL1Sim.scala",
               "src/test/scala/hats/MemoryPoisonSim.scala",
               "tools/verify_memory_l1.py", "tools/toolchain.py", "tools/sbtw", "tools/bootstrap.py", "build.sbt",
               "project/build.properties", "project/repositories")]
    before = hashes(sources)
    env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    tools = {}
    for name, command in {"java": [java_path(), "-version"], "verilator": ["verilator", "--version"],
                          "cxx": ["c++", "--version"], "make": ["make", "--version"]}.items():
        binary = Path(shutil.which(command[0], path=env["PATH"]) or command[0]).resolve()
        result = subprocess.run(command, env=env, text=True, capture_output=True, check=True)
        tools[name] = {"path": str(binary), "sha256": sha(binary), "version": (result.stdout + result.stderr).strip()}
    command = ["bash", "tools/sbtw", "Test / compile", f"Test / runMain hats.NonBlockingL1Sim {out / 'rtl'}",
               f"Test / runMain hats.MemoryPoisonSim {out / 'poison'}"]
    report = {"schema": 1, "status": "running", "issue": 5, "S04_complete": False,
              "claim_class": "source_bound_nonblocking_L1_component_RTL", "source_sha256": before,
              "started_utc": datetime.now(timezone.utc).isoformat(), "command": command, "tools": tools}
    path = out / "gate.json"
    def save(): path.write_text(json.dumps(report, indent=2) + "\n")
    save(); print("L1 component gate: " + str(path), flush=True)
    try:
        log = out / "simulation.log"
        with log.open("w") as stream:
            subprocess.run(command, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=900)
        result_path = out / "rtl/validation.json"
        result = json.loads(result_path.read_text()); validate(result)
        poison_path = out / "poison/validation.json"
        poison = json.loads(poison_path.read_text())
        require(poison["status"] == "passed" and poison["requests"] == 12 and poison["faults"] == 6
                and poison["writes"] == 2 and poison["failed_writes"] == 1 and poison["flushes"] == 4,
                "Missing word-poison preservation/fault recovery witnesses")
        generated = list(out.rglob("*.v"))
        require(len(generated) >= 3, "Missing actual generated RTL")
        require(hashes(sources) == before, "Sources changed during cache verification")
        for tool in tools.values(): require(sha(Path(tool["path"])) == tool["sha256"], "Tool changed during verification")
        report.update(status="passed_component", result=result, poison_result=poison,
                      evidence_sha256=hashes([result_path, poison_path, log, *generated]))
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        report["source_sha256_after"] = hashes(sources)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print("Source-bound L1 component matrix passed; both-engine S04 integration remains open", flush=True)


if __name__ == "__main__":
    main()
