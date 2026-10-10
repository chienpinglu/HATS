#!/usr/bin/env python3
"""Source-bound actual-RTL checks for the explicit frontend/backend boundary."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from verify_ape import hashes

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/ape_semantics"


def require(value, message):
    if not value:
        raise RuntimeError(message)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inputs = list((ROOT / "src").rglob("Ape*.scala"))
    inputs += [ROOT / p for p in ("build.sbt", "project/build.properties", "project/repositories", "tools/sbtw", "tools/toolchain.py",
                                "tools/verify_ape.py", "tools/verify_ape_semantics.py")]
    initial = hashes(inputs)
    report = {"schema": 1, "status": "running", "issue": 4, "S03_complete": False,
              "claim_class": "actual_shared_semantic_and_RV64_profile_RTL",
              "started_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": initial,
              "limits": ["RISC-V is the only implemented ISA frontend; alternate component policies do not constitute ARM support",
                         "One integer namespace, immutable zero slot and one operation/destination per instruction",
                         "Full core/Spike, real-tool, recovery/formal and physical evidence are separate gates"]}
    path = OUT / "gate.json"

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        files = [OUT / p for p in ("execution.json", "profile.json", "register_layout/validation.json", "predictor.json")]
        for p in files:
            p.parent.mkdir(parents=True, exist_ok=True); p.write_text('{"status":"not_run"}\n')
        command = ["bash", "tools/sbtw", "Test / compile"] + ["Test / runMain hats." + n for n in
                   ("ApeSemanticSim", "ApeRv64ProfileSim", "ApeRegisterLayoutSim", "ApePredictorPolicySim")]
        report["command"] = command; save()
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        print("Semantic/profile RTL gate; log: build/ape_semantics/gate.log", flush=True)
        with (OUT / "gate.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=300)
        execution, profile, layouts, predictor = [json.loads(p.read_text()) for p in files]
        require(all(r["status"] == "passed" for r in (execution, profile, layouts, predictor)), "Unfinished semantic test")
        require(execution["semantic_vectors"] == 4953 and execution["different_sign_zero_results"] > 100
                and execution["alternate_target_vectors"] == 72 and execution["fault_vectors"] > 100, "Missing executable policy contrasts")
        require(profile["checks"] == 135 and predictor["checks"] == 1024 and predictor["index_shifts"] == [1, 3], "Incomplete frontend/predictor boundary")
        require([(r["architectural_registers"], r["zero_slot"], r["argument_slot"], r["physical_registers"])
                 for r in layouts["runs"]] == [(16, 7, 3, 24), (32, 31, 2, 40)], "Wrong alternate register layouts")
        for row in layouts["runs"]:
            require(row["cycles"] == 6000 and row["writable_zero_allocations"] > 0 and row["allocations"] > 1000
                    and row["resource_stalls"] > 0 and row["recoveries"] > 100 and row["retirements"] > 500
                    and row["relaunches"] == 7 and row["out_of_order_writebacks"] > 100 and row["commit_and_recovery"] > 0,
                    "Alternate layout did not exercise live ownership/recovery")
        generated = list(OUT.glob("**/*.v"))
        require(generated, "No generated RTL")
        evidence = hashes(files + generated + [OUT / "gate.log"])
        require(hashes(inputs) == initial, "Semantic sources changed during verification")
        report.update(status="passed", execution=execution, profile=profile, layouts=layouts, predictor=predictor,
                      evidence_sha256=evidence)
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        report["source_sha256_after"] = hashes(inputs)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print("Semantic boundary PASS: 4953 execution vectors, 135 RV64 policy checks, 12000 alternate-layout cycles, 1024 predictor checks")


if __name__ == "__main__":
    main()
