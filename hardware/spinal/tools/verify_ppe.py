#!/usr/bin/env python3
"""Execute PPE SpinalHDL and compare complete architectural states with Python."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import build_ppe_cases as fixtures
from toolchain import java_path

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open("rb") as f: return hashlib.file_digest(f, "sha256").hexdigest()


def compare(folder, invocation):
    expected = json.loads((folder / "reference.json").read_text())
    actual = folder / f"rtl-{invocation}"
    read = lambda p: json.loads(p.read_text())
    trace = [json.loads(line) for line in (actual / "trace.jsonl").read_text().splitlines()]
    ordered = [json.loads(line) for line in (actual / "access.jsonl").read_text().splitlines()]
    if ordered != expected["ordered_access"]: raise ValueError("Memory/retirement ordering differs: " + folder.name)
    if trace != expected["trace"]:
        index = next((i for i, (a, b) in enumerate(zip(trace, expected["trace"])) if a != b), min(len(trace), len(expected["trace"])))
        a = trace[index] if index < len(trace) else None
        b = expected["trace"][index] if index < len(expected["trace"]) else None
        raise ValueError(f"Architectural divergence {folder.name}/{invocation} step {index}: actual={a} expected={b}")
    for space in ("global", "scratch"):
        events = []
        for line in (actual / "access.jsonl").read_text().splitlines():
            event = json.loads(line)
            event.pop("retirement_index")
            if event.pop("scratch") == (space == "scratch"): events.append(event)
        if events != expected[space]: raise ValueError(f"{folder.name}/{invocation} {space} accesses differ: {events} != {expected[space]}")
    if read(actual / "completion.json") != expected["completion"]: raise ValueError("Completion differs: " + folder.name)
    state = read(actual / "state.json")
    if state != {k: expected[k] for k in ("scalar", "vector", "predicate", "active", "depth")}:
        raise ValueError("Final register state differs: " + folder.name)
    for space in ("memory", "scratch"):
        if space == "scratch" and expected["kind"] == 2: continue # Rejected launch never owns/clears scratch.
        if (actual / (space + ".bin")).read_bytes() != (folder / ("reference." + space + ".bin")).read_bytes():
            raise ValueError("Final memory differs: " + folder.name + "/" + space)
    return {"case": folder.name, "kind": expected["kind"], "invocation": invocation, "retirements": len(trace),
            "memory_events": len(expected["global"]) + len(expected["scratch"]), "status": "matched"}


def main():
    out = ROOT / "build/ppe" / f"run-{time.time_ns()}"; out.mkdir(parents=True)
    inputs = list((ROOT / "tools").glob("*ppe*.py")) + list((ROOT / "src").rglob("Ppe*.scala"))
    inputs += [ROOT / p for p in ("build.sbt", "project/build.properties", "project/repositories", "tools/sbtw", "tools/toolchain.py")]
    hashes = {str(p.relative_to(ROOT)): sha(p) for p in inputs}
    report = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": hashes,
              "claim_class": "actual_PPE_RTL_independent_architectural_comparison",
              "limits": ["Eight logical lanes, one resident wave, uncached single-outstanding memory",
                         "Trusted code loader, no CP/OS/cache/coherence/tensor or PPA claim"]}
    print(f"PPE report: {out / 'validation.json'}", flush=True)
    try:
        manifest = fixtures.build(out / "cases")
        baseline = {str(p.relative_to(out)): sha(p) for p in (out / "cases").rglob("*") if p.is_file()}
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        report["verilator"] = subprocess.check_output(["verilator", "--version"], env=env, text=True).strip()
        report["java"] = subprocess.check_output([java_path(), "-version"], stderr=subprocess.STDOUT, text=True).splitlines()[0]
        command = ["bash", "tools/sbtw", "compile", "Test / compile", "runMain hats.GeneratePpe", f"Test / runMain hats.PpeCoreSim {out / 'cases'}"]
        with (out / "rtl.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        suite = json.loads((out / "cases/rtl-validation.json").read_text())
        expected = [(r["name"], i) for r in manifest for i in range(2)]
        if suite["status"] != "executed" or [(r["case"], r["invocation"]) for r in suite["runs"]] != expected:
            raise ValueError("Incomplete hardware matrix")
        report["comparisons"] = [compare(out / "cases" / name, i) for name, i in expected]
        for name, digest in baseline.items():
            if sha(out / name) != digest: raise ValueError("Fixture/reference mutated: " + name)
        if {str(p.relative_to(ROOT)): sha(p) for p in inputs} != hashes: raise ValueError("Source changed")
        report["manifest"] = manifest; report["diagnostics"] = suite
        report["isa_oracle_invocations"] = sum(r["kind"] == 0 for r in report["comparisons"])
        report["protocol_decode_invocations"] = sum(r["kind"] != 0 for r in report["comparisons"])
        report["opcodes_exercised"] = sorted({op for r in manifest if r["kind"] == 0 for op in r["opcodes"]})
        if set(report["opcodes_exercised"]) != set(fixtures.p.OPS): raise ValueError("Missing ISA family")
        report["artifact_sha256"] = {str(p.relative_to(out)): sha(p) for p in (out / "cases").rglob("*")
                                     if p.is_file() and "sim" not in p.relative_to(out).parts}
        generated = list((out / "cases/sim").rglob("PpeCore.v"))
        if not generated: raise ValueError("Missing generated RTL")
        report["generated_rtl_sha256"] = sorted(set(sha(p) for p in generated))
        report["status"] = "passed"
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"PPE PASS: {report['isa_oracle_invocations']} exact ISA-oracle RTL comparisons; {report['protocol_decode_invocations']} protocol/decode checks")


if __name__ == "__main__": main()
