#!/usr/bin/env python3
"""Bounded safety proof and reachability check on generated ownership RTL."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

HW = Path(__file__).resolve().parents[1]
ENV = HW / ".tools/ape-formal"


def sha(path):
    with path.open("rb") as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True, type=Path)
    parser.add_argument("--steps", type=int, choices=(8, 12, 16), default=12)
    args = parser.parse_args()
    gate_path = args.gate.resolve()
    gate = json.loads(gate_path.read_text())
    require(gate.get("status") == "passed_integration" and gate.get("source_sha256") == gate.get("source_sha256_after"),
            "Requires a passing source-stable ownership RTL gate")
    rtl_rel = next((p for p in gate["generated_rtl_sha256"] if p.endswith("controller/sim/MemoryOwnershipController/rtl/MemoryOwnershipController.v")), None)
    require(rtl_rel is not None, "Ownership controller RTL missing from integration gate")
    rtl = gate_path.parent / rtl_rel
    require(sha(rtl) == gate["generated_rtl_sha256"][rtl_rel], "Generated controller RTL changed")
    fragment = HW / "formal/OwnershipAssumptions.svfrag"
    script = Path(__file__)
    out = HW / "build/s04/formal" / f"ownership-steps{args.steps}-{time_ns()}"
    out.mkdir(parents=True)
    augmented = out / "MemoryOwnershipControllerFormal.v"
    original = rtl.read_text()
    require(original.count("endmodule") == 1, "Unexpected generated module structure")
    augmented.write_text(original.replace("endmodule", fragment.read_text() + "\nendmodule"))
    env = dict(os.environ)
    env["YOWASP_CACHE_DIR"] = str(ENV / "cache")
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    yosys = ENV / "bin/yowasp-yosys"
    require(yosys.is_file(), "Pinned local formal tool unavailable")
    proof = (f"read_verilog -formal -sv {augmented}; prep -top MemoryOwnershipController -flatten; "
             f"memory_map; opt -full; clk2fflogic; opt_clean; check -assert; "
             f"chformal -cover -remove; sat -seq {args.steps} -prove-asserts -set-init-zero -set-assumes -verify -timeout 90")
    report = {"schema": 1, "status": "running", "issue": 5, "S04_complete": False,
        "claim_class": "bounded_ownership_line_ledger_safety_under_ready_valid_assumptions",
        "started_utc": datetime.now(timezone.utc).isoformat(), "bounded_global_steps": args.steps,
        "source_sha256": {str(p.relative_to(HW)): sha(p) for p in (script, fragment)},
        "integration_gate_sha256": sha(gate_path), "generated_rtl_sha256": sha(rtl),
        "initial_condition": "Yosys SAT set-init-zero; reset asserted only in the initial state",
        "assumptions": ["One sampled clock; reset asserted only in the initial state",
          "Each request/reply/handoff/flush-result producer holds valid and payload stable until handshake",
          "A client reporting idle has no valid line request",
          "A source/slot is not reallocated while its prior lower transaction remains live; lower responses may be delayed, reordered, stale, or malformed",
          "Handoffs and cache-maintenance responses are disabled in this proof; ownership transitions are covered by a separate proof and integrated simulation",
          "Lower ready, engine requests, replies, and client-idle indications are otherwise unconstrained; no fairness or memory-latency bound is assumed"],
        "limits": ["Bounded safety proof, not unbounded induction or full-system proof",
          "External line-memory data correctness and APE/PPE datapaths are outside this controller proof",
          "The proof does not establish eventual completion because no fairness assumptions are made"]}
    def run(command, label):
        log = out / f"{label}.log"
        with log.open("w") as stream:
            result = subprocess.run(command, cwd=HW, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
        require(result.returncode == 0, f"{label} failed; see {log}")
        return log.read_text()
    (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    try:
        proof_log = run([str(yosys), "-Q", "-T", "-p", proof], "safety")
        require("SAT proof finished - no model found: SUCCESS!" in proof_log, "Safety proof inconclusive")
        artifacts = [augmented, out / "safety.log"]
        coverage = {}
        for label, signal in (("accepted_request", "io_accepted"),
                              ("multiple_outstanding", "io_outstanding[1]"),
                              ("completed_reply", "io_completed"),
                              ("rejected_stale_reply", "io_rejected")):
            cover_command = (f"read_verilog -formal -sv {augmented}; prep -top MemoryOwnershipController -flatten; "
                f"memory_map; opt -full; clk2fflogic; opt_clean; check -assert; "
                f"chformal -cover -remove; chformal -assert -remove; "
                f"sat -seq {args.steps} -set-init-zero -set-assumes -prove {signal} 0 -timeout 90")
            cover_log = run([str(yosys), "-Q", "-T", "-p", cover_command], f"reachability-{label}")
            require("SAT proof finished - model found: FAIL!" in cover_log,
                    f"No {label} witness within {args.steps} steps")
            coverage[label] = {"status": "reachable_within_bound", "query": f"{signal} != 0",
                "log": str((out / f"reachability-{label}.log").relative_to(HW)),
                "log_sha256": sha(out / f"reachability-{label}.log")}
            artifacts.append(out / f"reachability-{label}.log")
        report.update(status="passed_bounded_safety", assertion_checks_per_step=proof_log.count("Import proof for assert:") // args.steps,
            reachability={"line_traffic_witnesses": coverage,
              "ownership_handoff_success_and_failure": "MemoryOwnershipControllerSim; excluded from this line-ledger proof"},
            artifacts_sha256={str(p.relative_to(HW)): sha(p) for p in artifacts},
            finished_utc=datetime.now(timezone.utc).isoformat())
    except Exception as error:
        report.update(status="failed_or_inconclusive", error=str(error), finished_utc=datetime.now(timezone.utc).isoformat())
        raise
    finally:
        report["source_sha256_after"] = {str(p.relative_to(HW)): sha(p) for p in (script, fragment)}
        (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Ownership controller bounded safety proof passed: {report['assertion_checks_per_step']} assertion checks per step")


def time_ns():
    import time
    return time.time_ns()


if __name__ == "__main__":
    main()
