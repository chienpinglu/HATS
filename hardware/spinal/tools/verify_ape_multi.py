#!/usr/bin/env python3
"""Actual one/two-lane RTL, recovery/pressure witnesses and independent Spike gate.

This gate does not measure application speedup, synthesis QoR or close issue #4.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import bootstrap_spike as spike
from compare_ape_spike import compare, read_trace
from verify_ape import hashes
from verify_ape_spike import case_profile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/ape_multi"
# ROB, prediction, physical registers, checkpoints, stages, generation bits, width, suite.
CONFIGS = [(8, "bimodal", 64, 4, 2, 2, w, "standard") for w in (1, 2)]
CONFIGS += [(16, "bimodal", 36, 4, 2, 1, 2, "standard"), (8, "bimodal", 64, 4, 8, 1, 2, "standard")]
CONFIGS += [(16, mode, p, c, 2, 1, 2, "recovery") for mode in ("off", "bimodal")
            for p, c in ((64, 1), (64, 4), (36, 4))]


def directory(cfg):
    n, mode, p, c, depth, bits, width, suite = cfg
    return OUT / f"core/r{n}-{mode}-p{p}-c{c}-d{depth}-g{bits}-w{width}-{suite}"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "gate.json"
    inputs = list((ROOT / "src").rglob("Ape*.scala"))
    inputs += list((ROOT / "examples/ape").glob("*")) + list((ROOT / "examples/ape_recovery").glob("*"))
    inputs += [ROOT / p for p in (
        "build.sbt", "project/build.properties", "project/repositories", "tools/sbtw", "tools/toolchain.py",
        "tools/assemble_ape.py", "tools/assemble_hse.py", "tools/assemble_ape_recovery.py", "tools/verify_ape.py",
        "tools/verify_ape_multi.py", "tools/verify_ape_spike.py", "tools/compare_ape_spike.py",
        "tools/bootstrap_spike.py", "tools/spike.lock.json", "tools/spike_adapter.cc")]
    initial = hashes(inputs)
    report = {"schema": 1, "status": "running", "issue": 4, "S03_complete": False,
              "claim_class": "actual_multi_issue_RTL_and_independent_ISA_comparison",
              "started_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": initial,
              "limits": ["Single dispatch, completion/writeback and retirement; one/two execution-issue lanes",
                         "Head-only external memory; compatibility service is not controlled performance service",
                         "Component scheduler checks and architectural regressions are not whole-core formal proof",
                         "Real-tool, formal and synthesis/design-point gates remain separate"]}

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        report["reference_build"] = spike.check()
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        for tool in ("assemble_ape.py", "assemble_ape_recovery.py"):
            subprocess.run([sys.executable, "tools/" + tool], cwd=ROOT, env=env, check=True, timeout=180)
        unit_path = ROOT / "build/ape_issue/validation.json"
        for p in [unit_path, *(directory(cfg) / "validation.json" for cfg in CONFIGS)]:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('{"status":"not_run"}\n')
        command = ["bash", "tools/sbtw", "Test / compile", "Test / runMain hats.ApeIssueSchedulerSim"]
        for n, mode, p, c, depth, bits, width, suite in CONFIGS:
            command += [f"Test / runMain hats.ApeCoreSim {n} {mode} {p} {c} early {suite} {depth} {bits} {width}"]
        report["command"] = command; save()
        print("Multi-issue RTL gate; log: build/ape_multi/gate.log", flush=True)
        with (OUT / "gate.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        unit = json.loads(unit_path.read_text())
        require(unit["status"] == "passed", "Scheduler unit failed")
        require([(r["rob_entries"], r["issue_width"]) for r in unit["configurations"]]
                == [(n, w) for n in (4, 8, 16) for w in (1, 2)], "Incomplete scheduler matrix")
        for row in unit["configurations"]:
            require(row["checks"] > 0 and (row["issue_width"] == 1 or
                    row["dual_grants"] > 0 and row["blocked_lane_bypasses"] > 0), "Missing scheduler witnesses")
        evidence = hashes([unit_path, OUT / "gate.log"])
        golden, definitions, comparisons, suites = {}, {}, [], []
        for cfg in CONFIGS:
            n, mode, p, c, depth, bits, width, kind = cfg
            folder = directory(cfg); suite_path = folder / "validation.json"
            suite = json.loads(suite_path.read_text())
            require(suite["status"] == "passed", "Failed core suite")
            require(tuple(suite[k] for k in ("rob_entries", "prediction", "physical_registers", "checkpoint_capacity",
                    "execution_stages", "generation_bits", "issue_width")) == cfg[:7], "Wrong core configuration")
            require(suite["early_recovery"] is True and suite["recovery_suite"] == (kind == "recovery"), "Wrong recovery mode")
            cases = [(r["name"], r["invocation"]) for r in suite["results"]]
            expected = 12 if kind == "recovery" else 100
            require(len(cases) == len(set(cases)) == suite["runs"] == expected and all(i in (0, 1) for _, i in cases), "Wrong case multiplicity")
            require(all(r["passed"] and r["issue_width"] == width for r in suite["results"]), "Failed/mixed issue-width cases")
            counters = {k: sum(r[k] for r in suite["results"]) for k in (
                "dual_issue_cycles", "issued_operations", "completion_stall_cycles", "execution_stall_cycles",
                "rename_stall_cycles", "checkpoint_stall_cycles", "generation_stall_cycles", "late_rejected",
                "rejected_after_slot_reuse", "physical_reuse_while_pending", "commit_and_redirect", "resolved_younger_squashes")}
            if kind == "standard":
                require((counters["dual_issue_cycles"] == 0) == (width == 1), "No actual simultaneous dual issue / wrong baseline")
                require(width == 1 or counters["completion_stall_cycles"] > 0, "Completion arbitration not backpressured")
                require(p != 36 or counters["rename_stall_cycles"] > 0, "Physical pressure missing")
                require(depth <= 2 or counters["rejected_after_slot_reuse"] > 0, "No stale dual-lane completion after slot reuse")
            suites.append({"configuration": cfg, "counters": counters})
            evidence.update(hashes([suite_path, *folder.glob("sim/**/*.v")]))
            for name, invocation in cases:
                prefix = folder / f"{name}-{invocation}"
                metadata, actual, timing = [Path(str(prefix) + ext) for ext in (".case.json", ".arch.jsonl", ".trace")]
                case = json.loads(metadata.read_text()); key = (kind, name)
                require((case["schema"], case["name"], case["invocation"]) == (1, name, invocation), "Wrong case identity")
                definition = {k: v for k, v in case.items() if k != "invocation"}
                require(key not in definitions or definitions[key] == definition, "Different inputs across width/configurations")
                definitions[key] = definition
                if key not in golden:
                    image = ROOT / f"build/{'ape_recovery' if kind == 'recovery' else 'ape'}/programs/{case['image']}.hex"
                    reference, raw = OUT / f"{kind}-{name}.spike.jsonl", OUT / f"{kind}-{name}.spike.log"
                    with reference.open("w") as stdout, (OUT / f"{kind}-{name}.stderr").open("w") as stderr:
                        subprocess.run([str(spike.BINARY), str(image), case["entry"], str(int(case["writable"])),
                                        str(int(case["bus_error"])), str(raw)], cwd=ROOT, stdout=stdout, stderr=stderr,
                                       check=True, timeout=30)
                    golden[key] = read_trace(reference); evidence.update(hashes([image, reference, raw]))
                result = compare(read_trace(actual), golden[key], case_profile(case))
                require(kind != "recovery" or result["status"] == "matched", "Recovery must exactly match")
                comparisons.append({**result, "name": name, "invocation": invocation, "configuration": cfg})
                evidence.update(hashes([metadata, actual, timing]))
        matched = sum(r["status"] == "matched" for r in comparisons)
        gaps = sum(r["status"] == "expected_profile_difference" for r in comparisons)
        require((len(golden), len(comparisons), matched, gaps) == (56, 472, 456, 16), "Unexpected independent comparison matrix")
        evidence.update(hashes(list((ROOT / "build/ape_issue").glob("r*/**/*.v")) +
                               [ROOT / f"build/{d}/programs/manifest.json" for d in ("ape", "ape_recovery")]))
        require(all(spike.digest(ROOT / name) == digest for name, digest in evidence.items()), "Evidence changed")
        require(hashes(inputs) == initial and spike.check() == report["reference_build"], "Source/reference changed")
        report.update(status="passed_with_profile_differences", scheduler=unit, core_suites=suites,
                      comparisons=comparisons, fully_matched_invocations=matched, expected_profile_differences=gaps,
                      evidence_sha256=evidence)
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        report["source_sha256_after"] = hashes(inputs)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print("Multi-issue PASS: 456 Spike matches + 16 unchanged profile differences; no issue-closure claim")


if __name__ == "__main__":
    main()
