#!/usr/bin/env python3
"""Run real APE applications through integrated APE+LSQ+D-L1 RTL at matched factorial points."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

from toolchain import java_path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
CONFIGS = tuple((mode, sets, mshrs)
                for mode in ("D_L1", "I_D_L1")
                for sets in (8, 16, 32) for mshrs in (2, 4, 8))
APPLICATIONS = ("repo_source_edit", "empty", "insert", "delete", "replace", "duplicate_tie",
                "line_endings", "binary_bytes", "max_lines", "max_bytes", "too_many_lines", "too_many_bytes")
APP_REGRESSION_CONFIGS = (("D_L1", 16, 4), ("I_D_L1", 16, 4))
RUN_POINTS = ([ ("repo_source_edit", *config) for config in CONFIGS ] +
              [ (application, *config) for application in APPLICATIONS if application != "repo_source_edit"
                for config in APP_REGRESSION_CONFIGS ])


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def validate_report(report):
    require(report.get("status") == "passed_integrated_application_design_points"
            and report.get("S04_complete") is False, "cached APE report scope/status mismatch")
    rows = report.get("runs", [])
    require([(r.get("application"), r.get("mode"), r.get("sets"), r.get("mshrs")) for r in rows] == RUN_POINTS,
            "cached APE report is missing the 12-input regression or full factorial repo_source_edit design points")
    for application in APPLICATIONS:
        app_rows = [r for r in rows if r.get("application") == application]
        require(len({r.get("application_trace_sha256") for r in app_rows}) == 1
                and len({r.get("application_memory_sha256") for r in app_rows}) == 1,
                f"cached APE points did not use common references for {application}")
    for row in rows:
        require(row.get("architectural_trace_matches_direct_APE") is True
                and row.get("final_memory_matches_direct_APE") is True
                and row.get("line_requests") == row.get("line_completions") > 0
                and all(isinstance(row.get(k), int) and row[k] >= 0
                        for k in ("cache_hits", "cache_misses", "cache_refills", "cache_writebacks"))
                and row["cache_hits"] + row["cache_misses"] > 0 and row["cache_refills"] > 0
                and row.get("cycles", 0) > 0 and row.get("max_cache_outstanding", 0) > 0
                and (row.get("fetch_requests", 0) > 0 and row.get("instruction_cache_misses", 0) > 0
                     and row.get("max_fabric_outstanding", 0) > 0
                     if row["mode"] == "I_D_L1" else row.get("fetch_requests", 0) == 0)
                and len(row.get("generated_rtl_sha256", "")) == 64
                and len(row.get("validation_sha256", "")) == 64,
                "cached APE point lacks architectural, memory, or RTL witnesses")
    require(report.get("source_sha256") == report.get("source_sha256_after")
            and report.get("input_sha256") and report.get("tools"),
            "cached APE report lacks stable source/input/tool identities")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-root", type=Path, default=ROOT / "build/ape_app",
                        help="source-current 144-run direct APE/Spike bundle root")
    parser.add_argument("--evidence-output", type=Path,
                        default=REPO / "workloads/evidence/S04-APE-CACHED-APPLICATION.json")
    parser.add_argument("--use-local-compiled-classpath", action="store_true",
                        help="skip sbt compile and use the existing exported SpinalSim test classpath")
    args = parser.parse_args()
    app = args.application_root.resolve()
    app_gate = app / "validation.json"
    gate = json.loads(app_gate.read_text())
    require(gate.get("status") == "passed" and gate.get("runs_passed") == 144,
            "current 144-run APE application/Spike gate is required")
    require(gate.get("source_sha256") == gate.get("source_sha256_after"), "APE application gate is stale")
    for relative, digest in gate.get("source_sha256", {}).items():
        source = ROOT / relative
        require(source.is_file() and sha(source) == digest,
                f"direct APE application gate source is stale: {relative}")
    paths = [app_gate, app / "code.hex", app / "runtime.properties"]
    for application in APPLICATIONS:
        paths.extend((app / f"{application}.bin",
                      app / f"r8-bimodal/{application}-0.arch.jsonl",
                      app / f"r8-bimodal/{application}-0.memory.bin"))
    evidence = gate.get("evidence_sha256", {})
    for path in paths[1:]:
        rel = str(path.relative_to(ROOT))
        require(evidence.get(rel) == sha(path), f"application artifact is not bound by gate: {rel}")
    inputs = {str(p.relative_to(REPO)): sha(p) for p in paths}
    out = ROOT / "build/s04" / f"cached-app-{time.time_ns()}"
    out.mkdir(parents=True)
    sources = sorted((ROOT / "src/main/scala").rglob("*.scala")) + [ROOT / p for p in (
        "src/test/scala/hats/CachedApplicationSim.scala", "tools/verify_ape_cached_application.py",
        "tools/toolchain.py", "tools/sbtw", "build.sbt", "project/build.properties", "project/repositories")]
    source_hashes = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    tools = {}
    for name, command in (("java", [java_path(), "-version"]), ("verilator", ["verilator", "--version"]),
                          ("cxx", ["c++", "--version"]), ("make", ["make", "--version"])):
        executable = Path(subprocess.check_output(["which", command[0]], env=env, text=True).strip()).resolve()
        result = subprocess.run(command, env=env, text=True, capture_output=True, check=True)
        tools[name] = {"path": str(executable), "sha256": sha(executable),
                       "version": (result.stdout + result.stderr).strip()}
    classpath_export = ROOT / "target/streams/test/fullClasspath/_global/streams/export"
    compile_command = ["bash", "tools/sbtw", "Test / compile"]
    java = java_path()
    java_commands = []
    for application, mode, sets, mshrs in RUN_POINTS:
        target = out / f"{application}-{mode.lower()}-s{sets}-m{mshrs}"
        cache_mode = "icache" if mode == "I_D_L1" else "dcache"
        java_commands.append([java, "-Xmx3G", "-XX:ActiveProcessorCount=4", "-cp", "<sbt-test-classpath>",
            "hats.CachedApplicationSim", str(app), str(target), str(sets), str(mshrs), cache_mode, application, "0"])
    commands = {"compile": compile_command, "direct_java_mains": java_commands,
                "classpath_export": str(classpath_export.relative_to(ROOT))}
    report = {"schema": 1, "issue": 5, "status": "running", "S04_complete": False,
              "claim_class": "real_APE_application_on_integrated_APE_LSQ_D_L1_and_I_D_L1_RTL",
              "application_gate_sha256": sha(app_gate), "input_sha256": inputs,
              "source_sha256": source_hashes, "tools": tools, "command": commands,
              "external_service_model": "behavioral line memory; randomized lower ready and response order",
              "started_utc": datetime.now(timezone.utc).isoformat(), "runs": []}
    report_path = out / "gate.json"
    def save():
        report_path.write_text(json.dumps(report, indent=2) + "\n")
    save()
    try:
        with (out / "run.log").open("w") as log:
            if not args.use_local_compiled_classpath:
                subprocess.run(compile_command, cwd=ROOT, env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=900)
            else:
                log.write("Compile skipped by explicit local-classpath mode; Scala compilation was performed separately.\n")
            require(classpath_export.is_file(), "sbt test classpath export is missing")
            classpath = classpath_export.read_text().strip()
            require(classpath and all(Path(item).exists() for item in classpath.split(":")),
                    "sbt test classpath export contains missing entries")
            for java_command in java_commands:
                actual = [item if item != "<sbt-test-classpath>" else classpath for item in java_command]
                log.write("\nDirect Java main: " + " ".join(actual) + "\n"); log.flush()
                subprocess.run(actual, cwd=ROOT, env=env, stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=1800)
            report["classpath_export_sha256"] = sha(classpath_export)
        for application, mode, sets, mshrs in RUN_POINTS:
            run_dir = out / f"{application}-{mode.lower()}-s{sets}-m{mshrs}"
            validation = run_dir / "validation.json"
            rtl = run_dir / "rtl/tmp/job_1/ApeCachedDataTile.v"
            require(validation.is_file() and rtl.is_file(), "cached APE validation or generated RTL missing")
            result = json.loads(validation.read_text())
            require(result.get("status") == "passed" and
                    (result.get("application"), result.get("mode"), result.get("sets"), result.get("mshrs")) == (application, mode, sets, mshrs),
                    "integrated application did not pass at requested point")
            report["runs"].append({**result,
                "application_trace_sha256": sha(app / f"r8-bimodal/{application}-0.arch.jsonl"),
                "application_memory_sha256": sha(app / f"r8-bimodal/{application}-0.memory.bin"),
                "validation_path": str(validation.relative_to(REPO)), "validation_sha256": sha(validation),
                "generated_rtl": str(rtl.relative_to(REPO)), "generated_rtl_sha256": sha(rtl)})
        require(report["source_sha256"] == {str(p.relative_to(ROOT)): sha(p) for p in sources},
                "cached APE sources changed during run")
        require(inputs == {str(p.relative_to(REPO)): sha(p) for p in paths}, "application inputs changed during run")
        for tool in tools.values():
            require(sha(Path(tool["path"])) == tool["sha256"], "tool changed during run")
        report["status"] = "passed_integrated_application_design_points"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        report["source_sha256_after"] = {str(p.relative_to(ROOT)): sha(p) for p in sources}
        report["run_log_sha256"] = sha(out / "run.log") if (out / "run.log").is_file() else None
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    validate_report(report)
    report["build_gate_path"] = str(report_path.relative_to(REPO))
    save()
    evidence = {**report, "build_gate_sha256": sha(report_path)}
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"Verified integrated APE application D-L1 and I/D-L1 design points: {report_path}")


if __name__ == "__main__":
    main()
