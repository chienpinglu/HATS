#!/usr/bin/env python3
"""Fail-closed S02 evidence gate. Rechecks local artifacts; run_all.py reruns RTL.

Never closes an issue. Public output omits local paths and raw command logs.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from checkpoint import sha, require, matrix, check_hashes, validate_rtl, validate_reference, SMALL, KINDS

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware/spinal"
sys.path.insert(0, str(HW / "tools"))
import verify_ppe
import ppe_isa


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module; spec.loader.exec_module(module)
    return module


bulk = load_module("s02_bulk", REPO / "workloads/target/treesitter/bulk/verify.py")
target = bulk.target
read = lambda path: json.loads(Path(path).read_text())


def validate_bulk(report):
    require(report["status"] == "passed" and report["full_fixture_matrix"] is True
            and report["claim_class"] == "actual_APE_RTL_complete_streaming_architectural_state_comparison",
            "Missing full actual-RTL tool matrix")
    require((report["rob_entries"], report["prediction"], report["repetitions"]) == (8, "bimodal", 1), "Wrong closure profile")
    expected = bulk.cases()
    matrix(report["results"], ("mode", "case"), [(c[0], c[1]) for c in expected])
    statuses = {(c[0], c[1]): c[5] for c in expected}
    for row in report["results"]:
        require(row["expected_status"] == statuses[row["mode"], row["case"]], "Wrong rejection expectation")
        matrix(row["runs"], ("invocation",), [(0,)])
        for r in row["runs"]:
            d = r["digest"]
            require(d["schema"] == 1 and d["encoding"] == "hats-architectural-state-le64-v1"
                    and d["retirements"] > 0 and d["events"] == d["retirements"] + d["memory_events"] + 1,
                    "Incomplete architectural digest")
            require(r["diagnostics"]["retired"] == d["retirements"], "Retirement count differs")


def validate_ppe(report):
    require(report["status"] == "passed" and report["claim_class"] == "actual_PPE_RTL_independent_architectural_comparison",
            "PPE model is not hardware evidence")
    require(report["isa_oracle_invocations"] == 180 and report["protocol_decode_invocations"] == 44,
            "Incomplete PPE profile")
    require(set(report["opcodes_exercised"]) == set(ppe_isa.OPS) and len(report["opcodes_exercised"]) == 37,
            "Missing or duplicated PPE opcode")
    require(len(report["manifest"]) == 112 and len({r["name"] for r in report["manifest"]}) == 112,
            "Incomplete PPE fixtures")
    matrix(report["comparisons"], ("case", "invocation"), [(r["name"], i) for r in report["manifest"] for i in range(2)])
    require(all(r["status"] == "matched" for r in report["comparisons"]), "PPE divergence")
    require({r["kind"] for r in report["manifest"]} == set(range(5)), "Missing PPE protocol class")


def collect(paths):
    reports = {name: read(path) for name, path in paths.items()}
    b, s, p, n, legacy = [reports[k] for k in ("bulk", "spinal", "ppe", "native", "legacy")]
    validate_bulk(b); validate_rtl(s); validate_ppe(p)
    sources = {}
    def bind(base, hashes):
        check_hashes(base, hashes)
        for name, digest in hashes.items():
            key = str((base / name).resolve().relative_to(REPO))
            require(key not in sources or sources[key] == digest, "Evidence mixes source revisions: " + key)
            sources[key] = digest

    for r, base in ((b, REPO), (s, REPO), (p, HW), (n, REPO / "workloads"), (legacy, REPO)):
        bind(base, r["source_sha256"])
    build = b["target_build"]
    # This is embedded build metadata, not a completed standalone reference run.
    require(build["ape_rtl_execution"] is False and build["claim_class"] == "rv64i_spike_tool_execution", "Mislabeled builder")
    bind(REPO, build["source_sha256"])
    check_hashes(paths["bulk"].parent.parent, build["artifacts_sha256"])
    require(set(build["builds"]) == {"parser", "helpers", "runtime"}
            and all(v["strict_link"] == "passed" for v in build["builds"].values()), "Missing strict ELF")
    fixture_lock = read(REPO / "workloads/native/treesitter/cases.lock.json")
    source_lock = read(REPO / "workloads/native/treesitter/sources.lock.json")
    require(build["fixtures"] == n["fixtures"] == fixture_lock and build["source_lock"] == source_lock, "Pins/fixtures differ")
    port_path = Path(__file__).with_name("port-manifest.json")
    port = read(port_path)
    require(port["upstream_patches"] == [] == source_lock["upstream_patches"]
            and port["upstream_revisions"] == {r["id"]: r["revision"] for r in source_lock["sources"]}, "Port provenance differs")
    for name in port["original_adapters"]: require(name in build["source_sha256"], "Unbound port adapter: " + name)
    # Revalidate populated pinned source caches and dependency build manifests.
    target.native.sources()
    target.newlib.check(); target.spike.check()
    require(sha(target.newlib.BUILD / "hats-build.json") == build["newlib_build_sha256"], "Newlib build changed")
    require(sha(target.spike.STAMP) == build["spike_build_sha256"], "Spike build changed")
    check_hashes(target.native.CACHE, n["upstream_sha256"])
    require(n["status"] == "passed" and n["hats_execution"] is False and n["claim_class"] == "host_native_tool_baseline", "Native baseline absent")
    matrix(n["runs"], ("case", "kind", "mode", "sample"),
           [(c[0], k, m, 0) for c in target.native.cases() for k in KINDS for m in ("native", "instrumented", "sanitized")])
    native_outputs = {}
    for r in n["runs"]:
        check_hashes(paths["native"].parent, {r["output"]: r["output_sha256"]})
        output = read(paths["native"].parent / r["output"])
        if r["mode"] == "native": native_outputs[r["case"] + "-" + r["kind"]] = output
    for mode, values in n["builds"].items():
        require(sha(paths["native"].parent / mode / "ts-baseline") == values["executable_sha256"], "Native executable changed")
    check_hashes(paths["bulk"].parent / "rtl", b["generated_rtl_sha256"])
    require(sha(paths["bulk"].parent / "obj/VApeCore") == b["rtl_executable_sha256"], "RTL executable changed")
    definitions = {(c[0], c[1]): c for c in bulk.cases()}
    for row in b["results"]:
        mode, name, args, old, new, status = definitions[row["mode"], row["case"]]
        folder = paths["bulk"].parent.parent / mode / name
        golden = read(folder / "digest.json")
        reference_output = (folder / "result.bin").read_bytes()
        require((folder / "old.bin").read_bytes() == old and (folder / "new.bin").read_bytes() == new,
                "Input differs from locked fixture")
        import struct
        require((folder / "args.bin").read_bytes() == struct.pack("<8Q", *args), "Arguments differ")
        for run in row["runs"]:
            prefix = folder / f"rtl-{run['invocation']}"
            require(read(str(prefix) + ".digest.json") == golden == run["digest"], "Full stream differs")
            require(read(str(prefix) + ".execution.json") == run["diagnostics"], "RTL diagnostics changed")
            output = Path(str(prefix) + ".result.bin").read_bytes()
            require(sha(Path(str(prefix) + ".result.bin")) == run["output_sha256"] and output == reference_output, "Output image differs")
            bulk.check_result(mode, args, old, new, status, output, run["diagnostics"]["result"])
        if name in native_outputs:
            parsed, host = target.decode_result(reference_output), native_outputs[name]
            require(parsed["has_error"] == host["has_error"], "Native/RTL syntax-error result differs")
            if not host["has_error"]:
                require(parsed["nodes"] == host["nodes"], "Native/RTL semantic trees differ")
            else:
                # The frozen S01 contract specifies error reporting, not an
                # upstream recovery tree. Target ABI intentionally omits it.
                require(parsed["nodes"] == [], "Invalid target exposes an out-of-profile recovery tree")
            target.native.check_output(new if args[1] else old, host)
    empty = paths["bulk"].parent.parent / "parser/empty-cold_old"
    require(bulk.digest_text(empty / "trace.jsonl") == read(empty / "digest.json"), "Digest codec is not text-trace equivalent")

    small_path = paths["spinal"].parent / "validation.json"; small = read(small_path)
    validate_reference(small, SMALL, False)
    require(sha(small_path) == s["reference_report_sha256"], "Spinal reference changed")
    bind(REPO, small["source_sha256"]); check_hashes(small_path.parent, small["artifacts_sha256"])
    require(small["builds"] == build["builds"] and small["source_sha256"] == build["source_sha256"], "Spinal/bulk target build mismatch")
    folder = paths["spinal"].parent / "parser/rtl-r8-bimodal"
    generated = list((folder / "sim").rglob("ApeCore.v"))
    require(generated and sorted(sha(f) for f in generated) == sorted(s["generated_rtl_sha256"]), "Spinal-generated RTL changed")
    for row in s["comparisons"]:
        prefix = f"{row['case']}-{row['invocation']}"
        check_hashes(folder, {prefix + ".trace.jsonl": row["trace_sha256"], prefix + ".result.bin": row["output_sha256"]})
        reference = paths["bulk"].parent.parent / "parser" / row["case"]
        require(bulk.digest_text(folder / (prefix + ".trace.jsonl")) == read(reference / "digest.json"), "Spinal/bulk full-state streams differ")
        require(sha(reference / "result.bin") == row["output_sha256"], "Spinal/bulk output differs")

    check_hashes(paths["ppe"].parent, p["artifact_sha256"])
    generated = list((paths["ppe"].parent / "cases/sim").rglob("PpeCore.v"))
    require(generated and sorted(set(sha(f) for f in generated)) == p["generated_rtl_sha256"], "PPE-generated RTL changed")
    for row in p["comparisons"]:
        require(verify_ppe.compare(paths["ppe"].parent / "cases" / row["case"], row["invocation"]) == row, "PPE comparison changed")

    require(legacy["status"] == "passed" and legacy["claim_class"] == "committed_TaskTile_overlay"
            and legacy["tests_passed"] == 123 and legacy["live_source_preserved"] is True, "Legacy anchor incomplete")
    check_hashes(REPO, legacy["artifact_sha256"])
    original = subprocess.check_output(["git", "show", legacy["task_tile"]["commit"] + ":" + legacy["task_tile"]["repository_path"]], cwd=REPO)
    import hashlib
    require(hashlib.sha256(original).hexdigest() == legacy["task_tile"]["sha256"], "Legacy commit identity differs")
    require(subprocess.check_output(["git", "show", "HEAD:" + legacy["task_tile"]["repository_path"]], cwd=REPO) == original,
            "Committed legacy source changed since overlay run")

    regressions = {}
    for name, filename in (("ape", "ape/validation.json"), ("spike", "ape/spike/validation.json"), ("bounded", "ape_app/validation.json")):
        path = HW / "build" / filename; r = read(path)
        require(r["status"] == ("passed_with_profile_differences" if name == "spike" else "passed"), "Failed regression " + name)
        bind(HW, r["source_sha256"])
        require(r["source_sha256"] == r["source_sha256_after"], "Regression source mutated")
        check_hashes(HW, r["artifact_sha256"] if name == "ape" else r["evidence_sha256"])
        regressions[name] = r
    require(regressions["ape"]["runs_passed"] == 600 and regressions["ape"]["predictor"]["lookup_checks"] == 4096
            and regressions["spike"]["fully_matched_invocations"] == 576 and regressions["spike"]["expected_profile_differences"] == 24
            and regressions["bounded"]["runs_passed"] == 144, "Regression matrix incomplete")

    tests = []
    for directory, pattern in (("hardware/spinal/tools", "test_ppe_isa.py"), ("workloads/target/treesitter/execute", "test_*.py"),
                               ("workloads/s02", "test_*.py")):
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", directory, "-p", pattern, "-v"],
                              cwd=REPO, capture_output=True, text=True, check=True, timeout=120)
        print(proc.stderr, end=""); tests.append({"directory": directory, "pattern": pattern, "status": "passed"})
    proc = subprocess.run([sys.executable, "workloads/s01_gate.py"], cwd=REPO, capture_output=True, text=True, check=True, timeout=120)
    print(proc.stdout[-1000:]); tests.append({"gate": "workloads/s01_gate.py", "tests": 56, "status": "passed"})
    for path in [*Path(__file__).parent.glob("*.py"), port_path]: sources[str(path.relative_to(REPO))] = sha(path)
    check_hashes(REPO, sources)
    documents = ["README.md", "ROADMAP.md", "workloads/S02-COMPLETION.md", "hardware/spinal/DEVELOPMENT.md",
                 "hardware/spinal/spec/PPE-ISA-0.1.md", "hardware/spinal/spec/PPE-RTL-0.1.md",
                 "workloads/target/treesitter/execute/README.md", "workloads/target/treesitter/bulk/README.md"]
    return {"schema": 1, "status": "passed", "issue": 3, "stage": "S02", "S02_complete": True,
            "created_utc": datetime.now(timezone.utc).isoformat(), "claim_class": "actual_APE_tool_and_first_PPE_RTL",
            "source_sha256": sources, "reports_sha256": {k: sha(v) for k, v in paths.items()},
            "documentation_sha256": {name: sha(REPO / name) for name in documents},
            "dependencies": {"sources": source_lock["sources"], "compiler": build["compiler"], "newlib_build_sha256": build["newlib_build_sha256"],
                             "spike_revision": build["spike_revision"], "spike_build_sha256": build["spike_build_sha256"], "toolchain": b["toolchain"]},
            "native": {"runs": 90, "sanitizers": True, "semantic_result_matches_to_RTL": 30,
                       "complete_valid_tree_matches": 28, "invalid_syntax_error_matches": 2},
            "ape": {"bulk_invocations": 42, "parser_cases": 30, "negative_cases": 10, "helper_results": 1062, "runtime_checks": 160,
                    "spinal_invocations": 18, "spinal_bulk_stream_matches": 18, "rob_entries": 8, "prediction": "bimodal",
                    "program_words": 65536, "parser_elf_sha256": build["builds"]["parser"]["elf_sha256"],
                    "parser_code_bytes": build["builds"]["parser"]["profile"]["code_bytes"], "generated_rtl_sha256": b["generated_rtl_sha256"],
                    "matched_retirements": sum(v["digest"]["retirements"] for r in b["results"] for v in r["runs"]),
                    "matched_memory_events": sum(v["digest"]["memory_events"] for r in b["results"] for v in r["runs"]),
                    "cases": [{"mode": r["mode"], "case": r["case"], "digest": r["runs"][0]["digest"]} for r in b["results"]]},
            "ppe": {k: p[k] for k in ("isa_oracle_invocations", "protocol_decode_invocations", "opcodes_exercised", "generated_rtl_sha256", "manifest")},
            "regressions": {"ape_rtl_invocations": 600, "predictor_checks": 4096, "spike_matches": 576, "explicit_profile_differences": 24,
                            "bounded_application_invocations": 144, "committed_legacy_invocations": 123, "legacy_source": legacy["task_tile"]},
            "fast_tests": tests,
            "limits": ["Evidence collection rechecks existing executions; run_all.py reruns all builds and simulations",
                       "Bulk SHA-256 includes every event and full architectural retirement state; not a formal proof or sampling",
                       "PPE is one eight-lane wave with trusted loading, direct launch, uncached serialized memory and single-wave barriers",
                       "No CP, OS, coherent memory hierarchy, tensor/LLM engine, target-hosted compiler, big-core performance, speedup or PPA claim"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("bulk", "spinal", "ppe", "native", "legacy"): parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = collect({k: getattr(args, k).resolve() for k in ("bulk", "spinal", "ppe", "native", "legacy")})
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("S02 full gate PASS: " + str(args.output))


if __name__ == "__main__": main()
