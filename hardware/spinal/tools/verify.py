#!/usr/bin/env python3
"""Run the actual SpinalHDL -> Verilog -> SpinalSim/Verilator path and record provenance."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import subprocess
import sys
from toolchain import java_path

root = Path(__file__).resolve().parents[1]
build = root / "build"
build.mkdir(exist_ok=True)
report_path = build / "validation.json"
report = {
    "status": "running",
    "started_utc": datetime.now(timezone.utc).isoformat(),
    "claim": "RTL task-mechanism verification; not agent speedup, PPA, full Arm or memory-controller validation",
    "path": "Clang A64 assembly -> SpinalHDL RTL -> SpinalSim -> Verilator",
    "configurations": [2, 4, 8],
    "dependencies": {"scala": "2.13.14", "spinalhdl": "1.12.3", "sbt": "1.10.7"},
    "limits": ["Single scalar issue pipeline", "One owned child per context",
               "Behavioral memory service", "No caches/MMU/coherence/vector/tensor/agent runtime",
               "Shared invocation capability, not mutually untrusted child isolation"]
}
def save():
    report_path.write_text(json.dumps(report, indent=2) + "\n")

save()
env = dict(os.environ)
env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
try:
    report["verilator"] = subprocess.check_output(["verilator", "--version"], env=env, text=True).strip()
    report["clang"] = subprocess.check_output(["clang", "--version"], text=True).splitlines()[0]
    report["java"] = subprocess.check_output(
        [java_path(), "-version"],
        stderr=subprocess.STDOUT, text=True).splitlines()[0]
    subprocess.run([sys.executable, "tools/assemble.py"], cwd=root, check=True)
    command = ["bash", "tools/sbtw", "compile", "Test / compile", "runMain hats.Generate"]
    command += [f"Test / runMain hats.TaskTileSim {n}" for n in report["configurations"]]
    report["command"] = command
    save()
    print("Running RTL checks; detailed output: build/verification.log", flush=True)
    with (build / "verification.log").open("w") as log:
        subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    suites = [json.loads((build / f"validation-c{n}.json").read_text()) for n in report["configurations"]]
    assert all(s["status"] == "passed" and s["tests"] == len(s["results"]) for s in suites)
    assert all(t["passed"] for s in suites for t in s["results"])
    report["suites"] = [{"contexts": s["contexts"], "passed": s["tests"],
                         "report": f"build/validation-c{s['contexts']}.json"} for s in suites]
    report["tests_passed"] = sum(s["tests"] for s in suites)
    files = [root / "build.sbt", root / "project/build.properties", root / "project/repositories"]
    files += sorted((root / "src").rglob("*.scala")) + sorted((root / "examples").glob("*.s"))
    files += sorted((root / "tools").glob("*.py")) + [root / "tools/sbtw"]
    files += sorted((build / "rtl").glob("c*/TaskTile.v"))
    files += [build / "programs/manifest.json"]
    report["sha256"] = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    report["status"] = "passed"
except Exception as exc:
    report["status"] = "failed"
    report["error"] = str(exc)
    raise
finally:
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save()
print(f"PASS: {report['tests_passed']} RTL tests across {report['configurations']} contexts")
