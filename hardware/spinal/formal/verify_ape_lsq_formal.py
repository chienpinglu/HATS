#!/usr/bin/env python3
"""Generate and bounded-check the selected ROB8/P48 APE LSQ invariants."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

HW = Path(__file__).resolve().parents[1]
ENV = HW / ".tools/ape-formal"
SOURCES = [HW / p for p in (
    "src/main/scala/hats/ApeLoadStoreQueue.scala",
    "src/main/scala/hats/ApeCore.scala",
    "src/main/scala/hats/MemoryHierarchy.scala",
    "src/main/scala/hats/GenerateApeLoadStoreQueueFormal.scala",
    "formal/ApeLoadStoreQueueAssumptions.svfrag",
    "formal/verify_ape_lsq_formal.py",
    "tools/sbtw", "tools/toolchain.py", "tools/bootstrap.py", "build.sbt",
    "project/build.properties", "project/repositories")]


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
    parser.add_argument("--steps", type=int, choices=(4, 6, 8), default=8)
    args = parser.parse_args()
    out = HW / "build/s04/formal" / f"ape-lsq-steps{args.steps}-{time.time_ns()}"
    out.mkdir(parents=True)
    rtl_dir = out / "rtl"
    rtl_dir.mkdir()
    before = {str(p.relative_to(HW)): sha(p) for p in SOURCES}
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    env["YOWASP_CACHE_DIR"] = str(ENV / "cache")
    compile_command = ["bash", "tools/sbtw", "Test / compile"]
    classpath_export = HW / "target/streams/test/fullClasspath/_global/streams/export"
    java_path = subprocess.check_output(["python3", "tools/toolchain.py"], cwd=HW, text=True).strip()
    command = [java_path, "-Xmx3G", "-XX:ActiveProcessorCount=4"]
    build_log = out / "generation.log"
    with build_log.open("w") as stream:
        result = subprocess.run(compile_command, cwd=HW, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=900)
        require(result.returncode == 0, f"Test compilation failed; see {build_log}")
        require(classpath_export.is_file(), "sbt test classpath export is missing")
        classpath = classpath_export.read_text().strip()
        entries = classpath.split(":" )
        require(classpath and all(Path(entry).exists() for entry in entries),
                "sbt test classpath export contains missing entries")
        command += ["-cp", classpath, "hats.GenerateApeLoadStoreQueueFormal", str(rtl_dir)]
        stream.write("\nDirect generator command: " + " ".join(command) + "\n")
        stream.flush()
        result = subprocess.run(command, cwd=HW, env=env, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=900)
    require(result.returncode == 0, f"LSQ RTL generation failed; see {build_log}")
    generated = rtl_dir / "ApeLoadStoreQueueFormalTop.v"
    require(generated.is_file(), "Generated LSQ formal top missing")
    original = generated.read_text()
    require(original.count("endmodule") == 2, "Unexpected generated top/child module structure")
    fragment = HW / "formal/ApeLoadStoreQueueAssumptions.svfrag"
    augmented = out / "ApeLoadStoreQueueFormal.v"
    pos = original.rfind("endmodule")
    augmented.write_text(original[:pos] + fragment.read_text() + "\n" + original[pos:])
    yosys = ENV / "bin/yowasp-yosys"
    require(yosys.is_file(), "Pinned local formal tool unavailable")
    version = subprocess.run([str(yosys), "-V"], cwd=HW, env=env,
                             text=True, capture_output=True, check=True).stdout.strip()
    proof = (f"read_verilog -formal -sv {augmented}; prep -top ApeLoadStoreQueueFormalTop -flatten; "
             f"memory_map; opt -full; clk2fflogic; opt_clean; check -assert; "
             f"chformal -cover -remove; sat -seq {args.steps} -prove-asserts "
             f"-set-init-zero -set-assumes -verify -timeout 180")
    log = out / "safety.log"
    report = {"schema": 1, "status": "running", "issue": 5, "S04_complete": False,
        "claim_class": "bounded_selected_APE_LSQ_internal_lease_safety",
        "started_utc": datetime.now(timezone.utc).isoformat(), "bounded_global_steps": args.steps,
        "configuration": {"rob_entries": 8, "physical_registers": 48, "leases": 8,
                           "cache_sets": 8, "line_bytes": 32, "mshrs": 4},
        "source_sha256": before, "generated_rtl_sha256": sha(generated),
        "augmented_rtl_sha256": sha(augmented),
        "classpath_export_sha256": sha(classpath_export),
        "formal_tool": {"path": str(yosys), "sha256": sha(yosys), "version": version},
        "initial_condition": "Yosys SAT set-init-zero; reset input otherwise unconstrained",
        "assumptions": ["For each physical ROB row i, rows[i].identity.slot == i; this matches ApeCore's actual q.io.rows(i).identity.slot := i wiring"],
        "scope": ["All embedded LSQ assertions are checked over the bounded trace",
                  "All other row fields and request/response/ready inputs remain unconstrained",
                  "No proof of memory-value refinement, unbounded correctness, or complete APE ROB/LSQ composition"]}
    (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    try:
        with log.open("w") as stream:
            result = subprocess.run([str(yosys), "-Q", "-T", "-p", proof], cwd=HW,
                env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=240)
        text = log.read_text()
        require(result.returncode == 0 and "SAT proof finished - no model found: SUCCESS!" in text,
                f"APE LSQ bounded proof failed or was inconclusive; see {log}")
        imports = text.count("Import proof for assert:")
        require(imports > 0 and imports % args.steps == 0, "Could not count per-step LSQ assertion checks")
        after = {str(p.relative_to(HW)): sha(p) for p in SOURCES}
        require(after == before, "LSQ/formal sources changed during verification")
        coverage = {}
        artifacts = [generated, augmented, build_log, log]
        for label, signal in (("lease_allocation", "io_allocated[0]"),
                              ("multiple_outstanding_leases", "io_outstanding[1]"),
                              ("dependence_replay", "io_replays[0]")):
            cover = (f"read_verilog -formal -sv {augmented}; prep -top ApeLoadStoreQueueFormalTop -flatten; "
                f"memory_map; opt -full; clk2fflogic; opt_clean; "
                f"chformal -cover -remove; chformal -assert -remove; "
                f"sat -seq 8 -set-init-zero -set-assumes -prove {signal} 0 -timeout 120")
            cover_log = out / f"reachability-{label}.log"
            with cover_log.open("w") as stream:
                cover_result = subprocess.run([str(yosys), "-Q", "-T", "-p", cover], cwd=HW,
                    env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=180)
            cover_text = cover_log.read_text()
            require(cover_result.returncode == 0 and "SAT proof finished - model found: FAIL!" in cover_text,
                    f"No {label} witness within eight steps; see {cover_log}")
            coverage[label] = {"status": "reachable_within_bound", "bound_steps": 8,
                "query": f"{signal} != 0", "log": str(cover_log.relative_to(HW)),
                "log_sha256": sha(cover_log)}
            artifacts.append(cover_log)
        report.update(status="passed_bounded_safety", assertion_checks_per_step=imports // args.steps,
            generated_rtl=str(generated.relative_to(HW)),
            reachability=coverage,
            artifacts_sha256={str(p.relative_to(HW)): sha(p) for p in artifacts},
            finished_utc=datetime.now(timezone.utc).isoformat())
    except Exception as error:
        report.update(status="failed_or_inconclusive", error=str(error),
                      finished_utc=datetime.now(timezone.utc).isoformat())
        raise
    finally:
        report["source_sha256_after"] = {str(p.relative_to(HW)): sha(p) for p in SOURCES}
        (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"APE LSQ bounded safety proof passed: {report['assertion_checks_per_step']} checks/step")


if __name__ == "__main__":
    main()
