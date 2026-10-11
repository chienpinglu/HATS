#!/usr/bin/env python3
"""Source-bound APE LSQ/cache and S03-profile regression; not full S04 closure."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
import shlex
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

import assemble_ape as assembler
import bootstrap_spike as spike
from compare_ape_spike import compare, read_trace
from toolchain import java_path
from verify_memory_l1 import sha, require
from verify_ape_spike import case_profile

HW = Path(__file__).resolve().parents[1]
REPO = HW.parents[1]
DIRECTED = {"parallel_loads", "queue_full", "forward_bytes", "youngest_store_bytes", "unknown_store_address", "fence",
            "wrong_path_read_drain", "older_fault_after_younger_read"}
NAMES = {f"p{i}" for i in range(32)} | {f"{kind}{i}" for kind in ("random", "control") for i in range(8)} | {
    "entry_alignment", "entry_bounds"} | DIRECTED


def hashes(paths):
    return {str(p.relative_to(REPO)): sha(p) for p in sorted(paths)}


def validate(result, instructions=False):
    require(result["status"] == "passed" and result["issue"] == 5 and result["S04_complete"] is False
            and result["claim_class"] == ("actual_APE_LSQ_instruction_data_L1_fabric_RTL" if instructions else "actual_APE_LSQ_data_L1_RTL")
            and result["profile"] == "ROB8/P48/W1/C4/D2/G2", "Wrong APE memory execution scope")
    rows = {r["name"]: r for r in result["tests"]}
    require(set(rows) == NAMES and len(result["tests"]) == len(NAMES), "Missing/duplicate APE memory test")
    require(all(r["cycles"] > r["retired"] >= 0 and 0 <= r["max_cache_outstanding"] <= 4
                and 0 <= r["max_outstanding"] <= 8 for r in rows.values()), "Invalid execution accounting")
    require(all(r["counters"]["hits"] + r["counters"]["misses"] == r["word_requests"]
                and r["counters"]["allocated"] == r["word_requests"] + r["counters"]["forwarded"] for r in rows.values()),
            "LSQ/cache/forwarding accounting mismatch")
    p = rows["parallel_loads"]
    require(p["max_outstanding"] >= 6 and p["max_cache_outstanding"] == 4 and p["lower_reorders"] > 0,
            "No concurrent/reordered actual memory execution")
    p = rows["queue_full"]
    require(p["max_outstanding"] == 8 and p["max_cache_outstanding"] == 4 and p["counters"]["allocated"] == 9,
            "No full LSQ/MSHR stress witness")
    require(rows["forward_bytes"]["counters"]["partial_forwarded"] > 0
            and rows["youngest_store_bytes"]["counters"]["forwarded"] > 0, "Forwarding not exercised")
    require(rows["unknown_store_address"]["counters"]["speculative_loads"] > 0
            and rows["unknown_store_address"]["counters"]["memory_replays"] > 0
            and rows["fence"]["counters"]["fence_stalls"] > 0, "Dependence replay/fence not exercised")
    p = rows["wrong_path_read_drain"]
    require(p["counters"]["discarded"] >= 2 and p["counters"]["writebacks"] == 0 and p["retired"] == 4,
            "Missing squash/late-response drain witness")
    p = rows["older_fault_after_younger_read"]
    require(p["retired"] == 1 and p["max_outstanding"] >= 2 and p["counters"]["writebacks"] == 0,
            "Missing precise older fault witness")
    require(result["limits"], "Missing integration limits")
    if instructions:
        require(all(r["instruction_reads"] > 0 and r["fetch_requests"] > 0 for name, r in rows.items()
                    if name not in ("entry_alignment", "entry_bounds")), "Instruction RAM bypass or missing cache fetch")
        require(rows["entry_alignment"]["instruction_reads"] == rows["entry_bounds"]["instruction_reads"] == 0,
                "Faulting entry caused a code-region access")
        require(any(r["instruction_hits"] > 0 for r in rows.values())
                and any(r["max_fabric_outstanding"] >= 2 for r in rows.values()), "No real I-cache hit/shared concurrency")


def validate_publication(result):
    require(result["status"] == "passed" and result["issue"] == 5 and result["S04_complete"] is False
            and result["claim_class"] == "actual_APE_instruction_publication_fault_RTL", "Wrong publication execution scope")
    require(result["executions"] == 11 and result["publications"] == 5 and result["publication_stall_cycles"] == 25
            and result["cpu_code_stores"] == result["successful_code_writebacks"] == result["failed_code_writebacks"] == 1,
            "Incomplete publication/failure/retry coverage")
    require(result["cycles"] > 0 and result["limits"]
            and result["fabric_accepted"] == result["fabric_completed"] > 0 and result["fabric_rejected"] > 0
            and result["fetch_failures"] >= 3 and result["fetch_discarded"] > 0
            and result["max_fabric_outstanding"] >= 2 and result["response_reorders"] > 0
            and result["request_stall_cycles"] > 0, "Missing instruction/fabric adversarial witnesses")


def validate_device(result):
    require(result["status"] == "passed" and result["issue"] == 5 and result["S04_complete"] is False
            and result["claim_class"] == "actual_APE_D_L1_clean_then_uncached_device_RTL"
            and result["instruction_cache_profiles"] == 2 and result["device_requests"] == 6
            and result["device_reads"] == 4 and result["device_writes"] == 2
            and result["device_backpressure_cycles"] > 0 and result["clean_before_every_device_request"],
            "APE uncached device transaction evidence incomplete")
    require(result.get("malformed_response_id_rejected") is True
            and result.get("malformed_response_epoch_rejected") is True,
            "Device response ID/epoch mismatch was not tested")
    require("No concurrent PPE device service or shared atomics claimed" in result["limits"],
            "Device path limitations missing")


def validate_atomic(result):
    require(result.get("status") == "passed" and result.get("S04_complete") is False
            and result.get("claim_class") == "APE_LSQ_D_L1_RV64A_AMOADD_D_modeled_line_service",
            "Wrong APE atomic integration scope")
    rows = {row["name"]: row for row in result.get("tests", [])}
    require(set(rows) == {"amoadd_d", "unsupported_amoadd_w"} and len(result["tests"]) == 2,
            "Missing atomic positive/negative controls")
    good = rows["amoadd_d"]
    require(good["passed"] and good["atomic_requests"] == good["retired_atomic"] == 3
            and good["prior_values"] == {"3": "10", "4": "11", "5": "13"}
            and good["load_value"] == good["backing_word"] == "16",
            "APE AMOADD.D architectural or backing-memory check failed")
    bad = rows["unsupported_amoadd_w"]
    require(bad["passed"] and bad["halted"] and bad["atomic_requests"] == 0,
            "Unsupported AMO encoding reached the cache or failed to trap")
    require("cross-engine atomic serialization not covered" in result["limits"],
            "Atomic integration boundary is missing")


def validate_replay_pressure(result):
    require(result.get("status") == "passed" and result.get("S04_complete") is False
            and result.get("claim_class") == "actual_APE_LSQ_data_L1_RTL"
            and result.get("profile") == "ROB16/P48/W1/C4/D2/G2",
            "Wrong combined replay-pressure stress profile")
    rows = result.get("tests", [])
    require(len(rows) == 1 and rows[0].get("name") == "replay_under_queue_pressure",
            "Dedicated replay-pressure simulation must contain exactly its target program")
    row = rows[0]
    require(row.get("max_outstanding") == 8 and row.get("max_cache_outstanding") == 4
            and row.get("lower_reorders", 0) > 0 and row.get("counters", {}).get("speculative_loads", 0) > 0
            and row.get("counters", {}).get("memory_replays", 0) > 0
            and row.get("counters", {}).get("refills", 0) >= 4,
            "Combined full-LSQ/full-MSHR/conflict/replay stress was not reached")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--instructions", action="store_true", help="Include actual I-L1, shared fabric and publication tests")
    parser.add_argument("--use-local-compiled-classpath", action="store_true",
                        help="skip sbt compile/probe and run with the existing exported test classpath")
    args = parser.parse_args()
    out = args.output.resolve() if args.output else HW / "build/s04" / f"ape-memory-{time.time_ns()}"
    require(out.is_relative_to(HW / "build") and not out.exists(), "Use a fresh local build directory")
    out.mkdir(parents=True)
    sources = list((HW / "src/main/scala/hats").glob("Ape*.scala")) + [HW / "src/main/scala/hats" / p
                for p in ("MemoryHierarchy.scala", "CacheLineFabric.scala", "CachedInstructionFetch.scala")]
    sources += [HW / "src/test/scala/hats" / p for p in ("ApeCachedDataSim.scala", "ApeCoreSim.scala", "ApeReference.scala", "ApeInstructionProtocolSim.scala", "ApeDeviceMemorySim.scala", "ApeAtomicAddSim.scala", "ApeSimArtifactCleanup.scala")]
    sources += [HW / "tools" / p for p in ("verify_ape_memory.py", "verify_memory_l1.py", "verify_ape_spike.py", "verify_ape.py",
                "assemble_ape.py", "toolchain.py", "sbtw", "bootstrap.py", "bootstrap_spike.py", "spike.lock.json",
                "spike_adapter.cc", "compare_ape_spike.py")]
    sources += [HW / p for p in ("build.sbt", "project/build.properties", "project/repositories",
                                "examples/ape/kernel.c", "examples/ape/programs.S", "examples/ape/link.ld")]
    recovery_source = REPO / "workloads/s03/profile_recovery.S"
    sources.append(recovery_source)
    before = hashes(sources)
    env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    clang = assembler.find_tool("HATS_RV_CLANG", ["/opt/homebrew/opt/llvm/bin/clang", "clang"])
    linker = assembler.find_tool("HATS_RV_LD", ["/opt/homebrew/opt/lld/bin/ld.lld", "ld.lld"])
    tools = {}
    for name, command in {"java": [java_path(), "-version"], "verilator": ["verilator", "--version"],
                          "cxx": ["c++", "--version"], "make": ["make", "--version"],
                          "clang": [clang, "--version"], "linker": [linker, "--version"]}.items():
        binary = Path(shutil.which(command[0], path=env["PATH"]) or command[0]).resolve()
        run = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
        tools[name] = {"path": str(binary), "sha256": sha(binary), "version": (run.stdout + run.stderr).strip()}
    report = {"schema": 1, "status": "running", "issue": 5, "S04_complete": False,
              "claim_class": ("source_bound_APE_LSQ_I_D_L1_fabric_and_S03_profile_regression" if args.instructions
                              else "source_bound_APE_LSQ_data_L1_and_S03_profile_regression"),
              "instruction_cache": args.instructions,
              "source_sha256": before, "tools": tools, "started_utc": datetime.now(timezone.utc).isoformat()}
    path = out / "gate.json"
    def save(): path.write_text(json.dumps(report, indent=2) + "\n")
    save(); print("APE memory gate: " + str(path), flush=True)
    try:
        reference = spike.check(); report["reference_build"] = reference
        inputs = out / "inputs"
        # Regenerate inputs in the fresh run root, leaving accepted S03 artifacts
        # untouched. These are compiled programs, not precomputed DUT outputs.
        assembler.OUT = inputs / "build/ape/programs"
        assembler.main()
        recovery = inputs / "build/ape_recovery/programs"; recovery.mkdir(parents=True)
        for i in range(6):
            obj, elf, image = [recovery / f"recovery{i}{ext}" for ext in (".o", ".elf", ".hex")]
            subprocess.run([clang, "--target=riscv64-unknown-elf", "-march=rv64i", "-mabi=lp64", "-mno-relax",
                            f"-DAPE_RECOVERY_TEST={i}", "-c", str(recovery_source), "-o", str(obj)], check=True)
            subprocess.run([linker, "--no-relax", "-T", str(HW / "examples/ape/link.ld"), str(obj), "-o", str(elf)], check=True)
            image.write_text("".join(f"{w:08x}\n" for w in assembler.extract(elf)))
        report["inputs_sha256"] = hashes(p for p in inputs.rglob("*") if p.is_file())
        compile_command = ["bash", "tools/sbtw", "Test / compile"]
        simulation_tasks = [f"Test / runMain hats.ApeCachedDataSim {out / 'cached'} {inputs} {'instructions' if args.instructions else 'data'}"]
        simulation_tasks += [f"Test / runMain hats.ApeCachedDataSim {out / 'replay-pressure'} {inputs} data stress"]
        if args.instructions:
            simulation_tasks += [f"Test / runMain hats.ApeCachedDataSim {out / 'data-regression'} {inputs} data",
                                 f"Test / runMain hats.ApeInstructionProtocolSim {out / 'instruction-protocol'}",
                                 f"Test / runMain hats.ApeDeviceMemorySim {out / 'device-memory'}"]
        simulation_tasks += [f"Test / runMain hats.ApeAtomicAddSim {out / 'atomic-add'}"]
        simulation_tasks += [f"Test / runMain hats.ApeCoreSim 8 bimodal 48 4 early {kind} 2 2 1 {out / kind} {inputs}"
                             for kind in ("standard", "recovery")]
        classpath_command = ["bash", "tools/sbtw", "show Test / fullClasspath"]
        report["command"] = {"compile": compile_command, "classpath_probe": classpath_command,
                              "simulations": simulation_tasks,
                              "execution": "direct Java using sbt Test / fullClasspath; avoids sbt background classpath copies"}
        save()
        log = out / "simulation.log"
        with log.open("w") as stream:
            if args.use_local_compiled_classpath:
                classpath_export = HW / "target/streams/test/fullClasspath/_global/streams/export"
                class_file = HW / "target/scala-2.13/test-classes/hats/ApeCachedDataSim$.class"
                require(classpath_export.is_file() and class_file.is_file() and
                        class_file.stat().st_mtime >= (HW / "src/test/scala/hats/ApeCachedDataSim.scala").stat().st_mtime,
                        "Fresh compiled APE cache test class or exported classpath is unavailable")
                classpath = classpath_export.read_text().strip().split(os.pathsep)
                require(len(classpath) >= 15 and all(Path(item).exists() for item in classpath),
                        "Exported SBT test classpath is incomplete")
                stream.write("Compile skipped by explicit local-classpath mode; modified Scala tests were compiled separately.\n")
            else:
                subprocess.run(compile_command, cwd=HW, env=env, stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=1200)
                classpath_run = subprocess.run(classpath_command, cwd=HW, env=env, capture_output=True, text=True,
                                               check=True, timeout=120)
                classpath = re.findall(r"^\[info\] \* Attributed\((.+)\)$", classpath_run.stdout, re.MULTILINE)
            require(len(classpath) >= 15 and all(Path(item).exists() for item in classpath),
                    "Could not resolve the complete SBT Test runtime classpath")
            report["runtime_classpath_sha256"] = {item: sha(Path(item)) for item in classpath if Path(item).is_file()}
            save()
            for task in simulation_tasks:
                tokens = shlex.split(task)
                require(tokens[:3] == ["Test", "/", "runMain"] and len(tokens) >= 4,
                        "Malformed runMain task")
                direct = [java_path(), "-Xmx4G", "-XX:ActiveProcessorCount=4", "-cp",
                          os.pathsep.join(classpath), *tokens[3:]]
                stream.write("\n$ " + shlex.join(direct) + "\n")
                stream.flush()
                subprocess.run(direct, cwd=HW, env=env, stdout=stream, stderr=subprocess.STDOUT,
                               check=True, timeout=1200)
        cached = json.loads((out / "cached/validation.json").read_text()); validate(cached, args.instructions)
        replay_pressure = json.loads((out / "replay-pressure/validation.json").read_text())
        validate_replay_pressure(replay_pressure)
        report["replay_pressure"] = replay_pressure
        memory_suites = {"cached": cached}
        if args.instructions:
            data_regression = json.loads((out / "data-regression/validation.json").read_text()); validate(data_regression)
            publication = json.loads((out / "instruction-protocol/validation.json").read_text()); validate_publication(publication)
            device = json.loads((out / "device-memory/validation.json").read_text()); validate_device(device)
            memory_suites["data-regression"] = data_regression
            report.update(data_regression=data_regression, instruction_publication=publication, device_memory=device)
            generated = "\n".join(p.read_text() for p in (out / "cached/rtl").rglob("*.v"))
            require(all(f"module {name}" in generated for name in ("CachedInstructionFetch", "CacheLineFabric", "NonBlockingL1")),
                    "Instruction cache/fabric absent from actual generated RTL")
            require(re.search(r"\b(?:reg|logic)\s+\[31:0\]\s+code\s*\[", generated) is None,
                    "Legacy instruction RAM survived in cached fetch profile")
        atomics = json.loads((out / "atomic-add/validation.json").read_text()); validate_atomic(atomics)
        report["atomic_add"] = atomics
        comparisons = []
        for kind, suite in memory_suites.items():
            for row in suite["tests"]:
                name = row["name"]; prefix = out / kind / name
                case = json.loads(prefix.with_suffix(".case.json").read_text())
                ref, raw = prefix.with_suffix(".spike.jsonl"), prefix.with_suffix(".spike.log")
                with ref.open("w") as stdout, prefix.with_suffix(".stderr").open("w") as stderr:
                    subprocess.run([str(spike.BINARY), str(prefix.with_suffix(".hex")), case["entry"], str(int(case["writable"])),
                                    str(int(case["bus_error"])), str(raw)], stdout=stdout, stderr=stderr, check=True, timeout=30)
                profile = "fence_i_gap" if name == "p20" else "launch_alignment_gap" if name == "entry_alignment" else "shared"
                comparison = compare(read_trace(prefix.with_suffix(".arch.jsonl")), read_trace(ref), profile)
                comparisons.append({"suite": kind, "name": name, **comparison})
        legacy = {}
        for kind, count in (("standard", 100), ("recovery", 12)):
            folder = out / kind; suite = json.loads((folder / "validation.json").read_text())
            require(suite["status"] == "passed" and suite["runs"] == len(suite["results"]) == count
                    and (suite["rob_entries"], suite["physical_registers"], suite["issue_width"], suite["checkpoint_capacity"],
                         suite["execution_stages"], suite["generation_bits"]) == (8, 48, 1, 4, 2, 2)
                    and suite["prediction"] == "bimodal" and suite["early_recovery"] is True
                    and suite["recovery_suite"] == (kind == "recovery"), "Incomplete selected S03 profile regression")
            legacy[kind] = suite
            for row in suite["results"]:
                require(row["passed"] is True, "Legacy test failed")
                prefix = folder / f"{row['name']}-{row['invocation']}"
                case = json.loads(prefix.with_suffix(".case.json").read_text())
                image = inputs / f"build/{'ape_recovery' if kind == 'recovery' else 'ape'}/programs/{case['image']}.hex"
                ref, raw = prefix.with_suffix(".spike.jsonl"), prefix.with_suffix(".spike.log")
                with ref.open("w") as stdout, prefix.with_suffix(".stderr").open("w") as stderr:
                    subprocess.run([str(spike.BINARY), str(image), case["entry"], str(int(case["writable"])),
                                    str(int(case["bus_error"])), str(raw)], stdout=stdout, stderr=stderr, check=True, timeout=30)
                comparison = compare(read_trace(prefix.with_suffix(".arch.jsonl")), read_trace(ref), case_profile(case))
                comparisons.append({"suite": kind, "name": row["name"], "invocation": row["invocation"], **comparison})
        exact, differences = (220, 8) if args.instructions else (164, 6)
        require(sum(r["status"] == "matched" for r in comparisons) == exact
                and sum(r["status"] == "expected_profile_difference" for r in comparisons) == differences, "Unexpected comparison matrix")
        require(hashes(sources) == before, "Sources changed during verification")
        require(hashes(p for p in inputs.rglob("*") if p.is_file()) == report["inputs_sha256"], "Input changed during execution")
        require(spike.check() == reference, "External reference changed")
        for tool in tools.values(): require(sha(Path(tool["path"])) == tool["sha256"], "Tool changed")
        artifacts = [log] + [p for p in out.rglob("*") if p.is_file() and p.suffix in (".v", ".jsonl", ".json", ".hex", ".trace", ".log")
                             and p != path and not p.is_relative_to(inputs) and p != log]
        with tarfile.open(out / "sources.tar", "w") as archive:
            for source in sources: archive.add(source, arcname=str(source.relative_to(REPO)))
        report.update(status="passed_partial_integration", cached=cached, legacy=legacy, comparisons=comparisons,
                      artifacts_sha256=hashes(artifacts + [out / "sources.tar"]),
                      limits=cached["limits"] + ["S03 full-tool runtime/PPA gates not rerun here; no speedup claim",
                        "APE uncached device RTL is tested only by the included behavioral device service",
                        "Combined APE/PPE exposes but does not implement PPE device transactions or cross-engine atomic serialization"])
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        report["source_sha256_after"] = hashes(sources)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print(f"APE cache hierarchy + selected S03 regression: {exact} exact Spike matches, {differences} explicit profile differences; S04 open")


if __name__ == "__main__":
    main()
