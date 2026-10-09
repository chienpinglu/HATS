#!/usr/bin/env python3
"""Fresh end-to-end S02 build/simulation gate; never silently reuses old reports.

Run from any directory with the documented local toolchain and pinned caches.
No Git/GitHub changes, paid infrastructure, downloads or source rewrites here.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

REPO = Path(__file__).resolve().parents[2]


def fresh(command, pattern):
    before = set(REPO.glob(pattern))
    subprocess.run([sys.executable, *command], cwd=REPO, check=True)
    new = set(REPO.glob(pattern)) - before
    if len(new) != 1: raise RuntimeError("Expected exactly one new report: " + pattern)
    path = new.pop()
    if json.loads(path.read_text())["status"] != "passed": raise RuntimeError("Fresh stage failed: " + str(path))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    paths = {}
    paths["native"] = fresh(["workloads/native/treesitter/run.py", "run", "--repeat", "1", "--sanitize"], "workloads/results/treesitter-*/validation.json")
    paths["bulk"] = fresh(["workloads/target/treesitter/bulk/verify.py"], "workloads/results/s02-treesitter-*/bulk/validation.json")
    paths["spinal"] = fresh(["workloads/target/treesitter/execute/verify_rtl.py"], "workloads/results/s02-treesitter-*/rtl-validation.json")
    paths["ppe"] = fresh(["hardware/spinal/tools/verify_ppe.py"], "hardware/spinal/build/ppe/run-*/validation.json")
    for script in ("verify_ape_spike.py", "verify_ape_app.py"):
        subprocess.run([sys.executable, "hardware/spinal/tools/" + script], cwd=REPO, check=True)
    paths["legacy"] = fresh(["workloads/s02/verify_legacy.py"], "hardware/spinal/build/s02-legacy/*/validation.json")
    output = args.output or REPO / "workloads/results" / f"s02-closure-{time.time_ns()}.json"
    command = [sys.executable, "workloads/s02/gate.py", "--output", str(output)]
    for name, path in paths.items(): command += ["--" + name, str(path)]
    subprocess.run(command, cwd=REPO, check=True)


if __name__ == "__main__": main()
