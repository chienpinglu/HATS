#!/usr/bin/env python3
"""Partial S04 PPE D-cache integration gate, not whole-issue completion."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import time

import build_ppe_cases as fixtures
from toolchain import java_path
from verify_ppe import compare

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    with path.open("rb") as f:
        digest = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
        return digest.hexdigest()


def hashes(paths, base=ROOT):
    return {str(p.relative_to(base)): sha(p) for p in paths}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def extra_cases():
    p, op = fixtures.p, fixtures.op
    result = []
    def add(name, program, scratch=0, **settings):
        result.append((name, p.assemble(program, scratch), bytes(4096), settings))
    for space in (0, 2):
        for shift in (3, 5, 9):
            add(f"s04_stride_s{space}_{shift}", [op("MOVI", d=8, imm=shift),
                op("VSHL", d=2, a=0, b=8, flags=2), op("VLOAD", d=5, a=0, b=2, flags=space),
                op("MOVI", d=9, imm=100),
                op("VADD", d=3, a=0, b=9, flags=2), op("VSTORE", d=3, a=0, b=2, flags=space),
                op("VLOAD", d=4, a=0, b=2, flags=space), op("FENCE"), op("RETURN")],
                scratch=4096 if space else 0)
        # Aligned 16-byte and 32-byte lane strides span four and eight distinct
        # 32-byte lines, exposing the full 4/8-MSHR points without misalignment.
        for stride, shift in ((16, 4), (32, 5)):
            add(f"s04_stride_s{space}_b{stride}", [op("MOVI", d=8, imm=shift),
                op("VSHL", d=2, a=1, b=8, flags=2),
                op("VLOAD", d=5, a=0, b=2, flags=space), op("MOVI", d=9, imm=100),
                op("VADD", d=3, a=0, b=9, flags=2), op("VSTORE", d=3, a=0, b=2, flags=space),
                op("VLOAD", d=4, a=0, b=2, flags=space), op("FENCE"), op("RETURN")],
                scratch=4096 if space else 0)
        add(f"s04_alias_s{space}", [op("VMOVI", d=2, imm=0), op("MOVI", d=8, imm=201),
            op("VADD", d=3, a=0, b=8, flags=2), op("VSTORE", d=3, a=0, b=2, width=0, flags=space),
            op("VLOAD", d=4, a=0, b=2, width=0, flags=space), op("RETURN")], scratch=16 if space else 0)
        add(f"s04_partial_s{space}", [op("MOVI", d=8, imm=19), op("VADD", d=3, a=0, b=8, flags=2),
            op("VSTORE", d=3, a=0, b=0, width=0, flags=space),
            op("VLOAD", d=4, a=0, b=0, width=0, flags=space), op("RETURN")], scratch=16 if space else 0)
    return result


def adapt_cached_clock_contract(root, manifest, instructions=False):
    """Explicit known-answer protocol fixtures, not ISA timing predictions.

    Four-bank clear takes 128 rows. The 160-cycle budget expires after the first
    word group is offered. Its eight byte-store lanes must drain as one group;
    no further group/retirement is permitted. Never edit the legacy fixtures.
    """
    for row in manifest:
        if row["kind"] < 3:
            continue
        folder = root / row["name"]
        prop = dict(line.split("=", 1) for line in (folder / "case.properties").read_text().splitlines())
        prop["budget"] = "1000" if instructions else "160"
        prop["readyAfter"] = ("1100" if instructions else "200") if row["name"] == "budget_held_request" else "0"
        prop["delay"] = ("1000" if instructions else "80") if row["name"] == "budget_late_response" else "2"
        (folder / "case.properties").write_text("".join(f"{k}={v}\n" for k,v in prop.items()))
        if row["kind"] == 3:
            reference = json.loads((folder / "reference.json").read_text())
            memory = fixtures.p.Memory((folder / "memory.bin").read_bytes())
            for lane in range(8):
                memory.access(lane, 1, store=True, value=99, lane=lane)
            reference["global"] = memory.events
            reference["ordered_access"] = [dict(e, scratch=False, retirement_index=2) for e in memory.events]
            (folder / "reference.json").write_text(json.dumps(reference)+"\n")
            (folder / "reference.memory.bin").write_bytes(memory.data)


def validate(report):
    instructions = report.get("instruction_cache", False)
    require(report["status"] == "passed_partial_integration" and report["issue"] == 5
            and report["S04_complete"] is False
            and report["claim_class"] == ("source_bound_PPE_I_D_L1_fabric_partial_integration" if instructions else
                "source_bound_PPE_coalescer_banked_scratch_D_L1_partial_integration"),
            "Wrong PPE evidence scope")
    base = {row[0] for row in fixtures.cases()}
    modes = [("legacy", base), ("cached", base | {row[0] for row in extra_cases()})]
    if instructions: modes.append(("data_regression", modes[1][1]))
    for mode, names in modes:
        manifest = report[mode + "_manifest"]
        require(len(manifest) == len(names) and {r["name"] for r in manifest} == names, "Wrong PPE fixture matrix")
        require({op for r in manifest if r["kind"] == 0 for op in r["opcodes"]} == set(fixtures.p.OPS) - {"AMOADD"}, "Missing PPE base ISA family")
        expected = {(name, i) for name in names for i in range(2)}
        observed = report["diagnostics"][mode]
        compared = report["comparisons"][mode]
        require(observed["status"] == "executed" and len(observed["runs"]) == len(compared) == len(expected)
                and {(r["case"], r["invocation"]) for r in observed["runs"]} == expected
                and {(r["case"], r["invocation"]) for r in compared} == expected
                and all(r["status"] == "matched" for r in compared), "Incomplete PPE observations/comparisons")
    rows = report["diagnostics"]["cached"]["runs"]
    ai_groups = {f"ai_relu_256_g{i}" for i in range(32)}
    require(ai_groups <= {r["name"] for r in report["cached_manifest"]}
            and ai_groups <= {r["name"] for r in report["legacy_manifest"]},
            "Missing 32-group PPE vector inference epilogue workload")
    ai_rows = [r for r in rows if r["case"] in ai_groups]
    require(len(ai_rows) == 64 and all(r["global_words"] == 15 and r["lanes"] == 27
            and r["retired"] == 16 for r in ai_rows),
            "PPE vector epilogue did not execute expected memory/retirement work")
    configured_mshrs = report["memory_configuration"]["mshrs"]
    require(max(r["max_mshrs"] for r in rows) <= configured_mshrs
            and max(r["max_mshrs"] for r in rows) >= min(configured_mshrs, 4)
            and max(r["max_lines"] for r in rows) >= min(configured_mshrs, 4),
            "No full-cache concurrent miss witness")
    require(max(r["max_words"] for r in rows) >= 4, "No concurrent coalescer read groups")
    require(all(sum(r[k] for r in rows) > 0 for k in ("stalls", "stale", "reorders", "scratch_parallel", "writebacks")),
            "Missing protocol/banking witnesses")
    for r in rows:
        require(r["accepted_lines"] == r["completed_lines"], "Undrained line effects")
        require(r["hits"] + r["misses"] == r["global_words"], "Cache counter mismatch")
    for name in ("s04_alias_s0", "s04_partial_s0"):
        require(all(r["global_words"] == 2 and r["lanes"] == 16 for r in rows if r["case"] == name),
                "Known 16-lane to 2-word coalescing reduction absent")
    require(sum(r["timeout_protocol"] for r in rows) == 6 and sum(r["late_service_drain"] for r in rows) == 2,
            "Incomplete cached timeout/drain protocol matrix")
    if instructions:
        validate_publication(report["instruction_publication"])
        require(report["diagnostics"]["cached"]["instruction_cache"] is True
                and report["diagnostics"]["data_regression"]["instruction_cache"] is False, "Wrong PPE fetch path")
        kinds = {r["name"]:r["kind"] for r in report["cached_manifest"]}
        for r in rows:
            require((kinds[r["case"]] == 2) == (r["instruction_reads"] == 0)
                    and r["instruction_misses"] == r["instruction_reads"]
                    and r["instruction_hits"] + r["instruction_misses"] == r["fetch_requests"], "Missing/incorrect PPE I-cache path")
            require(r["fabric_accepted"] == r["accepted_lines"] == r["fabric_completed"] == r["completed_lines"]
                    and r["fabric_rejected"] == r["stale"], "PPE fabric ledger mismatch")
        app = report.get("delimiter_application", {})
        require(app.get("status") == "passed" and app.get("claim_class") == "actual_PPE_I_D_L1_32_group_task"
                and app.get("groups_completed") == 32 and app.get("input_bytes") == 256
                and app.get("accepted_lines") == app.get("completed_lines")
                and app.get("stores", 0) > 0 and app.get("retired", 0) > 32
                and app.get("i_misses", 0) > 0 and app.get("d_misses", 0) > 0
                and app.get("output_matches_oracle") is True and app.get("canaries_unchanged") is True,
                "PPE multi-group application RTL/oracle evidence incomplete")
        vector_app = report.get("ai_vector_application", {})
        require(vector_app.get("status") == "passed"
                and vector_app.get("kernel") == "ai_relu"
                and vector_app.get("groups_completed") == 32
                and vector_app.get("input_bytes") == 256
                and vector_app.get("accepted_lines") == vector_app.get("completed_lines") > 0
                and vector_app.get("loads", 0) >= 3 * 32
                and vector_app.get("stores", 0) >= 32
                and vector_app.get("d_misses", 0) > 0
                and vector_app.get("output_matches_oracle") is True
                and vector_app.get("canaries_unchanged") is True,
                "PPE vector-ReLU application RTL/oracle evidence incomplete")
    require(report["limits"] and report["cached_clock_contract"], "Undocumented PPE evidence boundary")
    atomic = report.get("atomic_add", {})
    require(atomic.get("status") == "passed" and atomic.get("S04_complete") is False
            and atomic.get("claim_class") == "PPE_scalar_AMOADD_D_LS_engine_D_L1_modeled_line_service"
            and atomic.get("atomic_requests") == 3 and atomic.get("operands") == [1, 2, 3]
            and atomic.get("prior_values") == [10, 11, 13] and atomic.get("load_after_atomic") == "16"
            and atomic.get("backing_after_fence") == "16" and atomic.get("retired") == 10,
            "PPE AMOADD RTL evidence incomplete")
    negative = atomic.get("device_negative", {})
    require(negative.get("status") == "passed" and negative.get("device_atomic_rejected_before_io") is True
            and negative.get("fault_cause") == 4 and negative.get("device_requests") == 0
            and negative.get("cache_atomic_requests") == 0 and negative.get("lower_requests") == 0,
            "PPE atomic-to-device negative control leaked a transaction")


def validate_publication(r):
    expected = {
        "original": (0,3,11), "actual_PPE_code_store": (0,9,(77 << 32) | 0x0c000801),
        "stale_before_publication": (0,3,11), "failed_clean_preserves_old_code": (0,3,11),
        "published_PPE_code": (0,3,77), "host_edit_stays_stale": (0,3,77), "published_host_code": (0,3,43),
        "word_local_fetch_poison": (4,1,0), "whole_line_fetch_fault": (4,0,0),
        "branch_skips_poisoned_word": (0,2,0), "offered_fetch_timeout_drain": (5,0,0),
        "accepted_fetch_timeout_drain": (5,0,0), "recovery_after_late_fault": (0,2,0)}
    require(r["status"] == "passed" and r["claim_class"] == "PPE_instruction_publication_and_drain_RTL"
            and r["runs"] == len(r["tests"]) == 13
            and {t["name"]: (t["cause"],t["retired"],int(t["value"])) for t in r["tests"]} == expected,
            "Incomplete PPE publication/fetch-fault matrix")
    require(r["publications"] == 9 and r["held_ack_cycles"] >= 45
            and r["code_stores"] == r["failed_writebacks"] == r["successful_writebacks"] == 1
            and r["discarded_fetches"] == 2 and r["faulting_instruction_line_replies"] == 5,
            "Missing actual PPE code-write/failure/retry/fetch-drain witnesses")
    require(r["accepted"] == r["completed"] == r["rejected"] == 14 and r["request_stalls"] > 0,
            "PPE publication transport accounting mismatch")


def validate_device(r):
    require(r.get("status") == "passed" and r.get("issue") == 5 and r.get("S04_complete") is False
            and r.get("claim_class") == "actual_PPE_I_D_L1_clean_then_uncached_device_RTL"
            and r.get("instruction_cache") is True
            and r.get("device_requests") == 2 and r.get("device_reads") == 1 and r.get("device_writes") == 1
            and r.get("device_backpressure_cycles", 0) > 0
            and r.get("clean_before_every_device_request") is True
            and r.get("malformed_response_id_rejected") is True
            and r.get("malformed_response_epoch_rejected") is True
            and r.get("lower_accepted") == r.get("lower_completed") > 0,
            "PPE uncached-device RTL evidence incomplete")
    completion = r.get("architectural_completion", {})
    require((completion.get("status"), completion.get("cause"), completion.get("value")) == (1, 0, "305419896"),
            "PPE device workload produced the wrong architectural completion")
    require(any("PPE scalar AMOADD is covered separately" in item for item in r.get("limits", [])),
            "PPE device evidence omits atomic scope boundary")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instructions", action="store_true")
    parser.add_argument("--sets", type=int, choices=(4, 8, 16, 32), default=16)
    parser.add_argument("--mshrs", type=int, choices=(2, 4, 8), default=4)
    parser.add_argument("--evidence-root", type=Path, default=ROOT / "build/s04",
                        help="directory for generated gate artifacts (default: build/s04)")
    args = parser.parse_args()
    out = args.evidence_root.resolve() / f"ppe-memory-{time.time_ns()}"
    out.mkdir(parents=True)
    sources = set((ROOT / "src").rglob("Ppe*.scala")) | set((ROOT / "tools").glob("*ppe*.py"))
    sources.add(ROOT / "src/test/scala/hats/PpeDelimiterApplicationSim.scala")
    sources |= {ROOT / p for p in ("src/main/scala/hats/MemoryHierarchy.scala",
        "src/main/scala/hats/CachedInstructionFetch.scala", "src/main/scala/hats/CacheLineFabric.scala",
        "src/main/scala/hats/BankedScratchpad.scala", "tools/toolchain.py", "tools/sbtw",
        "tools/bootstrap.py", "build.sbt", "project/build.properties", "project/repositories")}
    before = hashes(sorted(sources))
    env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    tool_info = {}
    for name, command in {"java": [java_path(), "-version"], "verilator": ["verilator", "--version"],
                          "cxx": ["c++", "--version"], "make": ["make", "--version"]}.items():
        binary = Path(shutil.which(command[0], path=env["PATH"]) or command[0]).resolve()
        version = subprocess.run(command, env=env, text=True, capture_output=True, check=True)
        tool_info[name] = dict(path=str(binary), sha256=sha(binary), version=(version.stdout+version.stderr).strip())
    report = dict(schema=1, status="running", issue=5, S04_complete=False,
        claim_class=("source_bound_PPE_I_D_L1_fabric_partial_integration" if args.instructions else
                     "source_bound_PPE_coalescer_banked_scratch_D_L1_partial_integration"), instruction_cache=args.instructions,
        memory_configuration={"sets":args.sets,"line_bytes":32,"mshrs":args.mshrs,"instruction_cache":args.instructions},
        source_sha256=before, tools=tool_info, started_utc=datetime.now(timezone.utc).isoformat(),
        limits=[("Actual I-L1 instruction path, one outstanding fetch word, original loader RAM absent" if args.instructions else
                 "Code remains in loader RAM: no PPE I-cache claim in this increment"),
                "Clock-specific known-answer protocol fixtures use explicit separate serial and coalesced-group contracts, not ISA timing certification",
                "External byte storage/latency modeled; no physical HBM/LPDDR or performance claim",
                "Exclusive whole-line ownership is a caller obligation; system ownership enforcement and cross-engine atomic serialization remain open",
                "One wave, read groups concurrent, store groups ordered; no formal proof"])
    path = out / "gate.json"
    def save(): path.write_text(json.dumps(report, indent=2)+"\n")
    save(); print("PPE memory gate: " + str(path), flush=True)
    try:
        legacy = fixtures.build(out / "legacy")
        original = fixtures.cases
        fixtures.cases = lambda: original() + extra_cases()
        try:
            all_cached = fixtures.build(out / "cached")
            data_regression = fixtures.build(out / "data_regression") if args.instructions else None
        finally:
            fixtures.cases = original
        cached = all_cached
        adapt_cached_clock_contract(out / "cached", cached, args.instructions)
        if args.instructions: adapt_cached_clock_contract(out / "data_regression", data_regression)
        inputs = [p for p in out.rglob("*") if p.is_file() and p != path]
        input_hashes = hashes(inputs, out)
        classpath_export = ROOT / "target/streams/test/fullClasspath/_global/streams/export"
        require(classpath_export.is_file(), "Pinned sbt test classpath export is missing")
        classpath = classpath_export.read_text().strip()
        require(bool(classpath), "Pinned sbt test classpath export is empty")
        plugin_matches = list((ROOT / ".tools/coursier").rglob("spinalhdl-idsl-plugin_2.13-1.12.3.jar"))
        require(len(plugin_matches) == 1, "Expected exactly one pinned SpinalHDL compiler plugin")
        compiler = [java_path(), "-Xmx3G", "-cp", classpath, "scala.tools.nsc.Main",
                    "-Xplugin:" + str(plugin_matches[0]), "-classpath", classpath]
        main_sources = sorted((ROOT / "src/main/scala").rglob("*.scala"))
        test_sources = sorted((ROOT / "src/test/scala").rglob("*.scala"))
        compile_main = compiler + ["-d", str(ROOT / "target/scala-2.13/classes")] + list(map(str, main_sources))
        compile_test = compiler + ["-d", str(ROOT / "target/scala-2.13/test-classes")] + list(map(str, test_sources))
        java = [java_path(), "-Xmx4G", "-cp", classpath]
        command = [compile_main, compile_test,
                   java + ["hats.PpeCachedDataSim", str(out / "cached"),
                           "instructions" if args.instructions else "data", str(args.sets), str(args.mshrs)]]
        if args.instructions:
            command.append(java + ["hats.PpeCachedDataSim", str(out / "data_regression"), "data", str(args.sets), str(args.mshrs)])
        command.append(java + ["hats.PpeCoreSim", str(out / "legacy")])
        if args.instructions:
            command.append(java + ["hats.PpeInstructionProtocolSim", str(out / "instruction-protocol")])
        command.append(java + ["hats.PpeDeviceMemorySim", str(out / "device-memory")])
        command.append(java + ["hats.PpeAtomicAddSim", str(out / "atomic-add")])
        if args.instructions:
            command.append(java + ["hats.PpeDelimiterApplicationSim", str(out / "cached"),
                                   str(out / "delimiter-application"), str(args.sets), str(args.mshrs)])
            command.append(java + ["hats.PpeDelimiterApplicationSim", str(out / "cached"),
                                   str(out / "ai-vector-application"), str(args.sets), str(args.mshrs), "ai_relu"])
        recorded_command = [["<sbt-test-classpath>" if token == classpath else token for token in stage]
                            for stage in command]
        report.update(command=recorded_command, classpath_export_sha256=sha(classpath_export),
                      scala_plugin_sha256=sha(plugin_matches[0]), input_sha256=input_hashes,
                      cached_manifest=cached, legacy_manifest=legacy,
                      cached_clock_contract=f"128-row clear, budget{1000 if args.instructions else 160}, one offered word group drains; byte store group has eight lanes",
                      cached_protocol_cases=[r["name"] for r in cached if r["kind"] > 2],
                      ai_vector_epilogue_cases=[f"ai_relu_256_g{i}" for i in range(32)])
        if args.instructions: report["data_regression_manifest"] = data_regression
        save()
        with (out / "simulation.log").open("w") as log:
            for stage in command:
                log.write("$ " + " ".join(stage) + "\n")
                log.flush()
                subprocess.run(stage, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                               check=True, timeout=1200)
        comparisons, diagnostics = {}, {}
        modes = [("cached", cached, "cached-validation.json"), ("legacy", legacy, "rtl-validation.json")]
        if args.instructions: modes.append(("data_regression", data_regression, "cached-validation.json"))
        for mode, manifest, file in modes:
            result = json.loads((out / mode / file).read_text())
            expected = [(r["name"], i) for r in manifest for i in range(2)]
            require(result["status"] == "executed" and [(r["case"], r["invocation"]) for r in result["runs"]] == expected,
                    "Incomplete or duplicate PPE execution matrix")
            comparisons[mode] = [compare(out / mode / name, i) for name, i in expected]
            diagnostics[mode] = result
        require(hashes(inputs, out) == input_hashes and hashes(sorted(sources)) == before, "Input/source changed during verification")
        for tool in tool_info.values(): require(sha(Path(tool["path"])) == tool["sha256"], "Tool changed")
        generated = list(out.rglob("*.v")); require(len(generated) >= 2, "Missing actual generated RTL")
        if args.instructions:
            rtl = "\n".join(p.read_text() for p in (out / "cached/cached-sim").rglob("*.v"))
            baseline = "\n".join(p.read_text() for p in (out / "data_regression/cached-sim").rglob("*.v"))
            code_array = r"\breg\s+\[63:0\]\s+code\s*\["
            require(all("module " + name in rtl for name in ("CachedInstructionFetch", "NonBlockingL1", "CacheLineFabric"))
                    and not re.search(code_array, rtl) and re.search(code_array, baseline),
                    "PPE instruction path was bypassed by loader RAM or baseline path changed")
            report["instruction_publication"] = json.loads((out / "instruction-protocol/validation.json").read_text())
            app_dir = out / "delimiter-application"
            app = json.loads((app_dir / "validation.json").read_text())
            actual = (app_dir / "output-memory.bin").read_bytes()
            source = (out / "cached/delimiter_256_g0/memory.bin").read_bytes()
            expected = bytearray(source)
            for n, byte in enumerate(source[256:512]):
                expected[1024+n] = int(byte in b"{}[]:,")
            require(actual == expected, "PPE multi-group output/canary oracle mismatch")
            app.update(output_matches_oracle=True,
                       canaries_unchanged=actual[:1024] == source[:1024] and actual[1280:] == source[1280:],
                       input_sha256=sha(out / "cached/delimiter_256_g0/memory.bin"),
                       output_sha256=sha(app_dir / "output-memory.bin"))
            report["delimiter_application"] = app
            vector_dir = out / "ai-vector-application"
            vector_app = json.loads((vector_dir / "validation.json").read_text())
            vector_actual = (vector_dir / "output-memory.bin").read_bytes()
            vector_case = out / "cached/ai_relu_256_g0"
            vector_source = (vector_case / "memory.bin").read_bytes()
            vector_expected = bytearray(vector_source)
            for index in range(256):
                left = struct.unpack_from("<i", vector_source, 256 + index * 4)[0]
                right = struct.unpack_from("<i", vector_source, 1280 + index * 4)[0]
                struct.pack_into("<i", vector_expected, 2304 + index * 4, max(0, left + right))
            require(vector_actual == vector_expected, "PPE vector-ReLU output/canary oracle mismatch")
            vector_app.update(output_matches_oracle=True,
                canaries_unchanged=(vector_actual[:2304] == vector_source[:2304]
                    and vector_actual[3328:] == vector_source[3328:]),
                input_sha256=sha(vector_case / "memory.bin"),
                independent_oracle="signed_int32 residual+bias followed by ReLU for all 256 elements",
                output_sha256=sha(vector_dir / "output-memory.bin"))
            report["ai_vector_application"] = vector_app
        report["device_memory"] = json.loads((out / "device-memory/validation.json").read_text())
        validate_device(report["device_memory"])
        atomic = json.loads((out / "atomic-add/validation.json").read_text())
        atomic["device_negative"] = json.loads((out / "atomic-add/device-negative/validation.json").read_text())
        report["atomic_add"] = atomic
        evidence = [p for p in out.rglob("*") if p.is_file() and
                    (p.name.endswith((".json", ".jsonl", ".bin", ".log")) and "sim" not in p.parts and "cached-sim" not in p.parts)]
        evidence = [p for p in evidence if p != path] + generated
        report.update(comparisons=comparisons, diagnostics=diagnostics, evidence_sha256=hashes(evidence))
        with tarfile.open(out / "sources.tar", "w") as archive:
            for source in sorted(sources): archive.add(source, arcname=str(source.relative_to(ROOT)))
        report.update(status="passed_partial_integration", source_archive_sha256=sha(out / "sources.tar"))
        validate(report)
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        report.update(source_sha256_after=hashes(sorted(sources)), finished_utc=datetime.now(timezone.utc).isoformat()); save()
    print(f"PPE {'I/D-cache' if args.instructions else 'D-cache'} exact comparisons: {len(comparisons['cached'])}; "
          f"data-only regression: {len(comparisons.get('data_regression', []))}; serial regression: {len(comparisons['legacy'])}", flush=True)


if __name__ == "__main__": main()
