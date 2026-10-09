#!/usr/bin/env python3
"""Run the committed legacy anchor without overwriting a user's dirty TaskTile.

The generated snapshot is an explicit, recorded build input. A temporary sbt
source override applies only to this invocation, never to repository sources.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from checkpoint import sha, require, check_hashes

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware/spinal"
TASK = "hardware/spinal/src/main/scala/hats/TaskTile.scala"


def main():
    out = HW / "build/s02-legacy" / str(time.time_ns()); out.mkdir(parents=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip()
    original = subprocess.check_output(["git", "show", revision + ":" + TASK], cwd=REPO)
    snapshot = out / "TaskTile.scala"
    snapshot.write_bytes(original)  # Generated build material, not an edit to the checkout.
    live_digest = sha(REPO / TASK)
    inputs = [HW / "src/test/scala/hats/TaskTileSim.scala"]
    inputs += list((HW / "examples").glob("*.s"))
    inputs += [HW / p for p in ("build.sbt", "project/build.properties", "project/repositories",
                                "tools/assemble.py", "tools/sbtw", "tools/toolchain.py")]
    inputs += [Path(__file__).resolve(), Path(__file__).with_name("checkpoint.py")]
    hashes = {str(p.relative_to(REPO)): sha(p) for p in inputs}
    report = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
              "claim_class": "committed_TaskTile_overlay", "source_sha256": hashes,
              "task_tile": {"repository_path": TASK, "commit": revision, "sha256": sha(snapshot)},
              "live_source_preserved": False}
    try:
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        report["verilator"] = subprocess.check_output(["verilator", "--version"], env=env, text=True).strip()
        subprocess.run([sys.executable, "tools/assemble.py"], cwd=HW, env=env, check=True)
        # file() is a Scala literal: JSON string quoting is compatible for this path.
        override = 'set Compile / unmanagedSources := (Compile / unmanagedSources).value.filterNot(_.getName == "TaskTile.scala") :+ file(' + json.dumps(str(snapshot)) + ')'
        command = ["bash", "tools/sbtw", override, "compile", "Test / compile", "runMain hats.Generate"]
        command += [f"Test / runMain hats.TaskTileSim {n}" for n in (2, 4, 8)]
        print(f"Committed legacy RTL report: {out / 'validation.json'}", flush=True)
        with (out / "rtl.log").open("w") as log:
            subprocess.run(command, cwd=HW, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        suites = [json.loads((HW / f"build/validation-c{n}.json").read_text()) for n in (2, 4, 8)]
        require(all(s["status"] == "passed" and s["tests"] == len(s["results"]) == 41
                    and all(r["passed"] for r in s["results"]) for s in suites), "Incomplete legacy matrix")
        report["suites"] = suites; report["tests_passed"] = 123
        artifacts = list((HW / "build/rtl").glob("c*/TaskTile.v"))
        artifacts += [HW / f"build/validation-c{n}.json" for n in (2, 4, 8)]
        artifacts += list((HW / "build/programs").glob("*")) + [snapshot]
        report["artifact_sha256"] = {str(p.relative_to(REPO)): sha(p) for p in artifacts if p.is_file()}
        check_hashes(REPO, hashes)
        require(sha(REPO / TASK) == live_digest and snapshot.read_bytes() == original, "TaskTile source changed")
        report["live_source_preserved"] = True; report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Committed legacy anchor PASS: 123 RTL tests; live source untouched")


if __name__ == "__main__": main()
