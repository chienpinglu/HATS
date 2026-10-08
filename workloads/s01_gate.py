#!/usr/bin/env python3
"""Fail-closed S01 requirements/native-evidence gate. Does not close GitHub issues."""
import argparse
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent


def require(condition, message):
    if not condition: raise ValueError(message)


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def hashes_match(hashes, base=ROOT):
    for name, digest in hashes.items():
        path = (base / name).resolve()
        require(path.is_relative_to(base.resolve()), "Escaping evidence path")
        require(path.is_file() and sha(path) == digest, f"Stale evidence: {name}")


def validate_demand(p):
    require(p["status"] == "passed" and p["hats_execution"] is False and p["full_agent_experiment"] is False, "Wrong evidence class")
    hashes_match(p["source_sha256"])
    hashes_match(p["native_harness_sha256"], ROOT / "native/treesitter")
    fixtures = json.loads((ROOT / "native/treesitter/cases.lock.json").read_text())
    require(p["fixtures"] == fixtures, "Fixture identity mismatch")
    require(p["upstream_sources"] == json.loads((ROOT / "native/treesitter/sources.lock.json").read_text()), "Source pins mismatch")
    expected = set(itertools.product(("memory", "branches", "stack"), (f["id"] for f in fixtures["cases"]), ("cold_old", "cold_new", "incremental")))
    require(len(p["runs"]) == 90 and {(r["mode"], r["case"], r["kind"]) for r in p["runs"]} == expected, "Incomplete or duplicate profile matrix")
    spec = importlib.util.spec_from_file_location("s01_workflow", ROOT / "profile/workflow.py")
    workflow = importlib.util.module_from_spec(spec); spec.loader.exec_module(workflow)
    for r in p["runs"]:
        require(re.fullmatch("[a-f0-9]{64}", r["output_sha256"]), "Missing checked-output identity")
        require(type(r["check"]["valid_json"]) is bool, "No independent syntax check")
        m = r["metrics"]
        if r["mode"] == "memory":
            names = {"setup", "full_parse", "cleanup"} | ({"incremental_parse"} if r["kind"] == "incremental" else set())
            require(set(m) == names, "Missing parser phase")
            require(m["full_parse"]["loads"] > 0 and m["full_parse"]["stores"] > 0, "No memory probes")
            for phase in m.values():
                require(phase["line_touches"] == phase["unique_64b_lines"] + phase["reused_line_touches"], "Memory count mismatch")
        elif r["mode"] == "branches":
            require(0 < m["visited_regions"] <= m["regions"] and m["true_outcomes"] + m["false_outcomes"] > 0, "No branch outcomes")
        else:
            require(0 < m["observed_touched_extent_bytes"] < m["stack_capacity_bytes"], "Stack probe failed")
    w = p["workflow"]
    require(w["status"] == "passed" and w["hats_execution"] is False and w["model_generated_candidates"] is False, "Workflow scope mismatch")
    require(w["accounting"] == workflow.account(w["events"], w["accounting"]["critical_path_ns"]), "Critical path accounting mismatch")
    require(len(w["outcomes"]) == 4, "Missing workflow candidates")
    require(w["subprocesses"] == len(w["commands"]) + len(w["initial_build_commands"]), "Missing process accounting")
    decisions = {o["candidate"]: o for o in w["outcomes"]}
    expected_checks = set(itertools.product((f["id"] for f in fixtures["cases"]), ("cold_old", "cold_new", "incremental")))
    for name in ("chunk128", "chunk512", "wrong-depth"):
        o = decisions[name]
        require(len(o["checks"]) == 30 and {(c["fixture"], c["kind"]) for c in o["checks"]} == expected_checks, "Incomplete workflow checks")
        if name == "wrong-depth":
            require(o["decision"] == "rejected_oracle" and any(not c["passed"] for c in o["checks"]), "Semantic mutation escaped")
        else:
            require(o["decision"] == "accepted" and all(c["passed"] for c in o["checks"]), "Valid edit failed")
    require(decisions["syntax-error"]["decision"] == "rejected_compile" and decisions["syntax-error"]["compile_exit"] != 0, "Compile mutation escaped")
    require(any(r["mode"] == "memory" and r["metrics"]["full_parse"]["atomic_inc_seqcst"] > 0 for r in p["runs"]), "Atomic interposition absent")
    return {"native_demand_runs": 90, "workflow_valid_checks": 60, "workflow_mutation_checks": 30, "compile_rejection": True}


def main():
    if sys.version_info < (3, 12):
        raise SystemExit("S01 requires Python 3.12+ for pinned AHE syntax; on this Mac use /opt/homebrew/bin/python3")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-workloads", action="store_true", help="Re-run all selected host, native, demand and static audit matrices; needs populated caches/toolchains")
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    if args.summary and not args.run_workloads: parser.error("A new completion record requires --run-workloads")
    report = {"schema": 1, "status": "running", "claim_class": "S01_requirements_and_native_evidence_only",
              "hats_execution": False, "target_execution": False, "commands": [], "reports": []}
    out = ROOT / "results" / f"s01-gate-{time.time_ns()}.json"; out.parent.mkdir(exist_ok=True)
    def run(argv, timeout=300):
        print("RUN " + " ".join(argv), flush=True)
        p = subprocess.run(argv, cwd=REPO, capture_output=True, text=True, timeout=timeout)
        print((p.stdout + p.stderr)[-6000:], flush=True)
        record = {"argv": ["python3" if a == sys.executable else a for a in argv], "exit_code": p.returncode,
                  "output_sha256": hashlib.sha256((p.stdout + p.stderr).encode()).hexdigest()}
        report["commands"].append(record)
        require(p.returncode == 0, f"Regression failed: {argv}")
        for match in re.finditer(r"^(?:Report|Audit): (.+\.json)$", p.stdout, re.M):
            path = Path(match.group(1)).resolve()
            require(path.is_relative_to(ROOT / "results"), "Unexpected report path")
            data = json.loads(path.read_text())
            require(data["status"] in ("passed", "audit_complete"), "Child report did not pass")
            report["reports"].append({"path": str(path.relative_to(REPO)), "sha256": sha(path), "status": data["status"]})
        return p
    try:
        if args.run_workloads:
            for cmd in (["workloads/suite.py", "fetch", "--check"],
                        ["workloads/native/treesitter/run.py", "check"],
                        ["workloads/suite.py", "run", "--repeat", "3"],
                        ["workloads/native/treesitter/run.py", "run", "--repeat", "3", "--sanitize"],
                        ["workloads/profile/run.py", "--summary", "workloads/evidence/S01-DEMAND-PROFILE.json"],
                        ["workloads/target/treesitter/audit.py"]):
                run([sys.executable] + cmd)
            require(len(report["reports"]) == 4, "Missing fresh full workload reports")
        for directory, pattern in [("workloads", "test_*.py"), ("workloads/native/treesitter", "test_*.py"),
                                   ("workloads/profile", "test_*.py"), ("workloads/target/treesitter", "test_*.py"),
                                   ("hardware/spinal/tools", "test_task_abi.py"), ("hardware/spinal/tools", "test_ape_spike.py")]:
            run([sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", pattern, "-v"])
        p = json.loads((ROOT / "evidence/S01-DEMAND-PROFILE.json").read_text())
        report["demand"] = validate_demand(p)
        ledger = json.loads((ROOT / "s01_acceptance.json").read_text())
        require(set(ledger["work_packages"]) == {f"WP{i}" for i in range(1, 7)}, "Missing S01 work package")
        require(set(ledger["acceptance"]) == {f"AC{i}" for i in range(1, 5)}, "Missing S01 acceptance criterion")
        for item in list(ledger["work_packages"].values()) + list(ledger["acceptance"].values()):
            require(item["evidence"] and item["review"], "Empty acceptance evidence/review")
            for relative in item["evidence"]:
                path = (REPO / relative).resolve()
                require(path.is_relative_to(REPO) and path.is_file(), "Missing contract evidence")
        require({f["issue"] for f in ledger["followups"]} == {3, 4, 5, 6, 7, 8, 9, 10, 11}, "Missing downstream owners")
        artifact_paths = {"workloads/s01_gate.py", "workloads/test_s01_gate.py", "workloads/s01_acceptance.json",
                          "workloads/capabilities.json", "workloads/test_capabilities.py", "hardware/spinal/tools/task_abi.py",
                          "hardware/spinal/tools/test_task_abi.py", "workloads/evidence/S01-HOST-BASELINE.json",
                          "workloads/evidence/S01-RISCV-AUDIT.json", "workloads/evidence/S01-DEMAND-PROFILE.json"}
        for item in list(ledger["work_packages"].values()) + list(ledger["acceptance"].values()): artifact_paths.update(item["evidence"])
        report["artifact_sha256"] = {p: sha(REPO / p) for p in sorted(artifact_paths)}
        report["status"] = "passed"
        report["limits"] = ledger["limits"]
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally:
        out.write_text(json.dumps(report, indent=2) + "\n")
    if args.summary: args.summary.write_text(json.dumps(report, indent=2) + "\n")
    print(f"S01 gate PASS. Report: {out}; no HATS execution or acceleration claim.")


if __name__ == "__main__": main()
