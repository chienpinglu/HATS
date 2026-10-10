#!/usr/bin/env python3
"""Extend a measured PRF48 design point to full tool and independent ISA coverage.

Reuses hash-verified compiled RTL and pinned reference inputs, not their results
as DUT output. Every tool case executes again on the selected actual RTL.
The generic P64 compatibility chain remains a separate regression anchor.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from compare import REPO, HW, bulk, SERVICE_SEED
from design_evidence import validate_study
from evidence import check_hashes, require, sha, matrix

sys.path.insert(0, str(HW / "tools"))
import bootstrap_spike as spike
from compare_ape_spike import compare, read_trace
from verify_ape_spike import case_profile
from assemble_ape import find_tool, extract

POINT = ["prf48", 8, 48, 1, "bimodal", 16]


def read(path):
    return json.loads(path.read_text())


def verify_resume(prior, sources, inputs, generated, original_driver):
    """Reuse actual completed tool runs only; ISA execution always starts fresh.

    A changed orchestration script must be preserved byte-for-byte. All prior
    hardware, harness, workload and reference inputs must still match disk.
    No hardware or DUT-result substitution is allowed by this recovery path.
    """
    driver = str(Path(__file__).relative_to(REPO))
    require(prior["point"] == POINT and prior["inputs_sha256"] == inputs
            and prior["generated_sha256"] == generated, "Resume profile/input/executable mismatch")
    require(prior["status"] in ("failed", "passed_with_profile_differences"), "Cannot resume an active report")
    require(sha(original_driver) == prior["source_sha256"][driver], "Original driver snapshot does not match")
    previous = {p: digest for p, digest in prior["source_sha256"].items() if p != driver}
    require(all(sources.get(p) == digest for p, digest in previous.items()), "Resume execution sources changed")
    check_hashes(REPO, previous)
    check_hashes(REPO, inputs); check_hashes(REPO, generated)
    matrix(prior["tool_runs"], ("mode", "case"), [(c[0], c[1]) for c in bulk.cases()])
    return prior["tool_runs"]


def prepare_isa_workspace(out):
    """Use an isolated fork working directory; preserve all earlier gate files."""
    workspace = out / "isa-workspace"
    standard = workspace / "build/ape/programs"
    shutil.copytree(HW / "build/ape/programs", standard)
    recovery = workspace / "build/ape_recovery/programs"
    recovery.mkdir(parents=True)
    source = Path(__file__).with_name("profile_recovery.S")
    clang = find_tool("HATS_RV_CLANG", ["/opt/homebrew/opt/llvm/bin/clang", "clang"])
    linker = find_tool("HATS_RV_LD", ["/opt/homebrew/opt/lld/bin/ld.lld", "ld.lld"])
    for i in range(6):
        obj, elf, image = [recovery / f"recovery{i}{ext}" for ext in (".o", ".elf", ".hex")]
        subprocess.run([clang, "--target=riscv64-unknown-elf", "-march=rv64i", "-mabi=lp64", "-mno-relax",
                        f"-DAPE_RECOVERY_TEST={i}", "-c", str(source), "-o", str(obj)], check=True)
        subprocess.run([linker, "--no-relax", "-T", str(HW / "examples/ape/link.ld"), str(obj), "-o", str(elf)], check=True)
        image.write_text("".join(f"{w:08x}\n" for w in extract(elf)))
    return workspace, {"clang": {"path": clang, "sha256": sha(Path(clang))},
                       "linker": {"path": linker, "sha256": sha(Path(linker))}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--bulk", type=Path, required=True)
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--resume-tools", type=Path, help="Preserved report with all 42 actual tool runs")
    parser.add_argument("--original-driver", type=Path, help="Exact driver snapshot bound by --resume-tools")
    args = parser.parse_args()
    args.study, args.bulk = args.study.resolve(), args.bulk.resolve()
    study, reference = read(args.study), read(args.bulk)
    validate_study(study)
    require(reference["status"] == "passed" and reference["full_fixture_matrix"] is True
            and reference["repetitions"] == 1, "Full baseline tool/reference gate required")
    check_hashes(REPO, study["source_sha256"])
    check_hashes(REPO, reference["source_sha256"])
    check_hashes(REPO, study["generated"][POINT[0]])
    target = reference["target_build"]
    check_hashes(REPO, target["source_sha256"])
    check_hashes(args.bulk.parent.parent, target["artifacts_sha256"])
    require(target["builds"] == study["target_build"]["builds"], "Different workload binaries")
    rtl = args.study.parent / POINT[0] / "obj/VApeCore"
    require(str(rtl.relative_to(REPO)) in study["generated"][POINT[0]], "Unbound selected RTL executable")
    out = REPO / "workloads/results" / f"s03-profile-{time.time_ns()}"
    out.mkdir()
    report_path = out / "validation.json"
    require(bool(args.resume_tools) == bool(args.original_driver), "Supply both resume report and original driver")
    source_paths = [Path(__file__), Path(__file__).with_name("design_evidence.py"), Path(__file__).with_name("profile_recovery.S")]
    source_paths += [HW / "tools" / p for p in ("compare_ape_spike.py", "verify_ape_spike.py", "bootstrap_spike.py", "spike_adapter.cc")]
    sources = {**study["source_sha256"], **reference["source_sha256"], **target["source_sha256"],
               **{str(p.relative_to(REPO)): sha(p) for p in source_paths}}
    check_hashes(REPO, sources)
    report = {"schema": 1, "status": "running", "issue": 4, "S03_complete": False,
              "claim_class": "actual_selected_profile_full_tool_and_independent_ISA_RTL",
              "point": POINT, "started_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": sources,
              "inputs_sha256": {str(p.relative_to(REPO)): sha(p) for p in (args.study, args.bulk)},
              "generated_sha256": study["generated"][POINT[0]],
              "service": {"response_base": 2, "seed": SERVICE_SEED, "kind": "transaction_ordinal"},
              "limits": ["Selected explicit PRF48 profile, not a change to the generic ApeConfig P64 fallback",
                         "Same fixed supported RV64I subset and two documented profile differences",
                         "No cache, OS, clock, power, energy or whole-core formal claim"]}

    def save():
        report_path.write_text(json.dumps(report, indent=2) + "\n")

    def hashes(paths):
        return {str(p.relative_to(REPO)): sha(p) for p in paths}

    print("Selected PRF48 profile report: " + str(report_path), flush=True)
    save()
    try:
        todo = bulk.cases()
        baseline = {(r["mode"], r["case"]): r for r in reference["results"]}
        matrix(reference["results"], ("mode", "case"), [(c[0], c[1]) for c in todo])

        def execute(case):
            mode, name, arguments, old, new, status = case
            folder = args.bulk.parent.parent / mode
            inputs = folder / name
            prefix = out / f"{mode}-{name}"
            command = [str(rtl), str(folder), str(inputs), str(prefix), "1", "4000000000", "2", str(SERVICE_SEED)]
            result = subprocess.run(command, cwd=REPO, capture_output=True, text=True, timeout=7200)
            require(result.returncode == 0, "Selected-profile RTL failed: " + result.stderr[-4000:])
            paths = [Path(str(prefix) + "-0" + suffix) for suffix in (".digest.json", ".execution.json", ".result.bin")]
            digest, metrics, output = read(paths[0]), read(paths[1]), paths[2].read_bytes()
            require(digest == read(inputs / "digest.json") == baseline[mode, name]["runs"][0]["digest"], "Selected architectural stream differs")
            require(output == (inputs / "result.bin").read_bytes(), "Selected output image differs")
            require(metrics["retired"] == digest["retirements"] and metrics["requests"] == digest["memory_events"]
                    and metrics["response_base"] == 2 and metrics["service_seed"] == SERVICE_SEED
                    and metrics["dual_issue_cycles"] == 0, "Wrong profile/service/count")
            bulk.check_result(mode, arguments, old, new, status, output, metrics["result"])
            print(f"PRF48 RTL PASS {mode}/{name}: {digest['retirements']} retirements", flush=True)
            return {"mode": mode, "case": name, "digest": digest, "metrics": metrics, "artifacts_sha256": hashes(paths)}

        if args.resume_tools:
            prior_path, driver_path = args.resume_tools.resolve(), args.original_driver.resolve()
            report["tool_runs"] = verify_resume(read(prior_path), sources, report["inputs_sha256"],
                                               report["generated_sha256"], driver_path)
            report["resumed_tool_evidence_sha256"] = hashes([prior_path, driver_path])
            for row in report["tool_runs"]:
                check_hashes(REPO, row["artifacts_sha256"])
                paths = [REPO / p for p in row["artifacts_sha256"]]
                def one(suffix):
                    matches = [p for p in paths if p.name.endswith(suffix)]
                    require(len(matches) == 1, "Ambiguous resumed artifact")
                    return matches[0]
                reference_input = args.bulk.parent.parent / row["mode"] / row["case"]
                require(read(one(".digest.json")) == row["digest"] == read(reference_input / "digest.json")
                        == baseline[row["mode"], row["case"]]["runs"][0]["digest"], "Resumed stream changed")
                require(read(one(".execution.json")) == row["metrics"] and one(".result.bin").read_bytes()
                        == (reference_input / "result.bin").read_bytes(), "Resumed output/metrics changed")
            print("Revalidated all 42 previously executed tool runs; running fresh selected-profile ISA/recovery RTL", flush=True)
            save()
        else:
            with ThreadPoolExecutor(max_workers=args.jobs) as pool:
                futures = [pool.submit(execute, case) for case in todo]
                report["tool_runs"] = []
                for future in as_completed(futures):
                    report["tool_runs"].append(future.result()); save()
        matrix(report["tool_runs"], ("mode", "case"), [(c[0], c[1]) for c in todo])
        report["tool_runs"].sort(key=lambda r: (r["mode"], r["case"]))
        workspace, assembler = prepare_isa_workspace(out)
        report["isa_assembler"] = assembler
        # A fresh fork working directory preserves prior successes and failures.
        dirs = {kind: workspace / f"build/ape_multi/core/r8-bimodal-p48-c4-d2-g2-w1-{kind}" for kind in ("standard", "recovery")}
        require(all(not p.exists() for p in dirs.values()), "Preserve prior profile ISA artifacts before another execution")
        command = ["bash", "tools/sbtw", "Test / compile", f'set Test / baseDirectory := file("{workspace}")'] + [
            f"Test / runMain hats.ApeCoreSim 8 bimodal 48 4 early {kind} 2 2 1" for kind in dirs]
        env = dict(os.environ); env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        with (out / "isa.log").open("w") as log:
            subprocess.run(command, cwd=HW, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        reference_build = spike.check()
        comparisons, artifacts, suites = [], hashes([out / "isa.log"]), {}
        for kind, folder in dirs.items():
            suite = read(folder / "validation.json")
            require(suite["status"] == "passed" and suite["physical_registers"] == 48
                    and suite["rob_entries"] == 8 and suite["issue_width"] == 1
                    and suite["prediction"] == "bimodal" and suite["early_recovery"] is True
                    and suite["recovery_suite"] == (kind == "recovery"), "Wrong selected ISA configuration")
            require(suite["runs"] == (100 if kind == "standard" else 12), "Incomplete selected ISA matrix")
            suites[kind] = suite
            artifacts.update(hashes([folder / "validation.json", *folder.glob("sim/**/*.v")]))
            golden = {}
            for row in suite["results"]:
                name, invocation = row["name"], row["invocation"]
                prefix = folder / f"{name}-{invocation}"
                metadata, trace, timing = [Path(str(prefix) + s) for s in (".case.json", ".arch.jsonl", ".trace")]
                case = read(metadata)
                require(row["passed"] is True and case["name"] == name and case["invocation"] == invocation, "Selected test failed")
                if name not in golden:
                    image = workspace / f"build/{'ape_recovery' if kind == 'recovery' else 'ape'}/programs/{case['image']}.hex"
                    ref, raw = out / f"{kind}-{name}.spike.jsonl", out / f"{kind}-{name}.spike.log"
                    with ref.open("w") as stdout, (out / f"{kind}-{name}.stderr").open("w") as stderr:
                        subprocess.run([str(spike.BINARY), str(image), case["entry"], str(int(case["writable"])),
                                        str(int(case["bus_error"])), str(raw)], cwd=HW, stdout=stdout, stderr=stderr, check=True, timeout=30)
                    golden[name] = read_trace(ref)
                    artifacts.update(hashes([image, ref, raw]))
                result = compare(read_trace(trace), golden[name], case_profile(case))
                require(kind != "recovery" or result["status"] == "matched", "Recovery must match exactly")
                comparisons.append({**result, "suite": kind, "name": name, "invocation": invocation})
                artifacts.update(hashes([metadata, trace, timing]))
        require(sum(r["status"] == "matched" for r in comparisons) == 108
                and sum(r["status"] == "expected_profile_difference" for r in comparisons) == 4, "Unexpected profile comparison matrix")
        for r in report["tool_runs"]: check_hashes(REPO, r["artifacts_sha256"])
        artifacts.update(hashes(list((workspace / "build/ape_recovery/programs").glob("*"))))
        for manifest in (sources, report["inputs_sha256"], report["generated_sha256"], artifacts,
                         report.get("resumed_tool_evidence_sha256", {})): check_hashes(REPO, manifest)
        for tool in assembler.values(): require(sha(Path(tool["path"])) == tool["sha256"], "ISA assembler changed")
        check_hashes(args.bulk.parent.parent, target["artifacts_sha256"])
        require(spike.check() == reference_build, "Reference build changed")
        report.update(status="passed_with_profile_differences", isa_suites=suites, comparisons=comparisons,
                      isa_artifacts_sha256=artifacts, reference_build=reference_build,
                      exact_isa_matches=108, unchanged_profile_differences=4)
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print("Selected PRF48 profile: 42 full-tool RTL runs; 108 exact ISA/recovery matches + 4 unchanged profile differences", flush=True)


if __name__ == "__main__":
    main()
