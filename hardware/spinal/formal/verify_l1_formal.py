#!/usr/bin/env python3
"""Bounded safety proof of the generated 4-MSHR NonBlockingL1 RTL."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

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
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True, type=Path,
                        help="passing source-bound verify_memory_l1.py gate")
    parser.add_argument("--steps", type=int, choices=(4, 6, 8), default=8)
    args = parser.parse_args()
    gate_path = args.gate.resolve()
    gate = json.loads(gate_path.read_text())
    require(gate.get("status") == "passed_component" and
            gate.get("source_sha256") == gate.get("source_sha256_after"),
            "Requires a passing source-stable actual-L1 component gate")
    rtl_rel = next((p for p in gate["evidence_sha256"]
                    if p.endswith("/rtl/s8-l32-m4/NonBlockingL1/rtl/NonBlockingL1.v")), None)
    require(rtl_rel is not None, "Generated 4-MSHR L1 RTL missing from the gate")
    rtl = HW / rtl_rel
    require(rtl.is_file() and sha(rtl) == gate["evidence_sha256"][rtl_rel],
            "Generated L1 RTL is absent or differs from the passing gate")
    yosys = ENV / "bin/yowasp-yosys"
    require(yosys.is_file(), "Pinned local formal tool unavailable")
    out = HW / "build/s04/formal" / f"l1-4mshrs-steps{args.steps}-{time.time_ns()}"
    out.mkdir(parents=True)
    env = dict(os.environ)
    env["YOWASP_CACHE_DIR"] = str(ENV / "cache")
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    proof = (f"read_verilog -formal -sv {rtl}; prep -top NonBlockingL1 -flatten; "
             f"memory_map; opt -full; clk2fflogic; opt_clean; check -assert; "
             f"chformal -cover -remove; sat -seq {args.steps} -prove-asserts "
             f"-set-init-zero -set-assumes -verify -timeout 180")
    script = Path(__file__)
    report = {"schema": 1, "status": "running", "issue": 5, "S04_complete": False,
        "claim_class": "bounded_generated_nonblocking_L1_internal_safety_assertions",
        "started_utc": datetime.now(timezone.utc).isoformat(), "bounded_global_steps": args.steps,
        "configuration": {"sets": 8, "line_bytes": 32, "mshrs": 4, "epoch_bits": 2},
        "source_sha256": {str(script.relative_to(HW)): sha(script)},
        "component_gate_sha256": sha(gate_path), "generated_rtl": str(rtl.relative_to(HW)),
        "generated_rtl_sha256": sha(rtl),
        "initial_condition": "Yosys SAT set-init-zero; generated state initialized to zero; reset input unconstrained",
        "assumptions": [],
        "scope": ["Bounded checks of assertions embedded in the actual generated 4-MSHR L1 RTL",
                  "External request, reply, ready, flush and drain inputs are unconstrained",
                  "No proof of functional refinement, unbounded induction, fairness, or full APE/PPE protocol"]}
    log = out / "safety.log"
    (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    try:
        with log.open("w") as stream:
            result = subprocess.run([str(yosys), "-Q", "-T", "-p", proof], cwd=HW,
                env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=240)
        text = log.read_text()
        require(result.returncode == 0 and "SAT proof finished - no model found: SUCCESS!" in text,
                f"L1 bounded proof failed or was inconclusive; see {log}")
        imports = text.count("Import proof for assert:")
        require(imports > 0 and imports % args.steps == 0, "Could not count per-step assertion checks")
        coverage = {}
        artifacts = [log]
        for label, signal in (("lower_line_miss", "io_lower_valid"),
                              ("multiple_outstanding", "io_outstanding[1]"),
                              ("refill", "io_refills[0]"),
                              ("stale_reply_rejection", "io_rejectedReplies[0]")):
            cover = (f"read_verilog -formal -sv {rtl}; prep -top NonBlockingL1 -flatten; "
                f"memory_map; opt -full; clk2fflogic; opt_clean; "
                f"chformal -cover -remove; chformal -assert -remove; "
                f"sat -seq 8 -set-init-zero -set-assumes -prove {signal} 0 -timeout 180")
            cover_log = out / f"reachability-{label}.log"
            with cover_log.open("w") as stream:
                cover_result = subprocess.run([str(yosys), "-Q", "-T", "-p", cover], cwd=HW,
                    env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=240)
            cover_text = cover_log.read_text()
            require(cover_result.returncode == 0 and "SAT proof finished - model found: FAIL!" in cover_text,
                    f"No {label} witness within eight steps; see {cover_log}")
            coverage[label] = {"status": "reachable_within_bound", "bound_steps": 8,
                "query": f"{signal} != 0", "log": str(cover_log.relative_to(HW)),
                "log_sha256": sha(cover_log)}
            artifacts.append(cover_log)
        report.update(status="passed_bounded_safety", assertion_checks_per_step=imports // args.steps,
            reachability=coverage,
            artifacts_sha256={str(p.relative_to(HW)): sha(p) for p in artifacts},
            finished_utc=datetime.now(timezone.utc).isoformat())
    except Exception as error:
        report.update(status="failed_or_inconclusive", error=str(error),
                      finished_utc=datetime.now(timezone.utc).isoformat())
        raise
    finally:
        report["source_sha256_after"] = {str(script.relative_to(HW)): sha(script)}
        (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Generated L1 bounded safety proof passed: {report['assertion_checks_per_step']} checks/step")


if __name__ == "__main__":
    main()
