#!/usr/bin/env python3
"""Collect original-S03 acceptance evidence only after every required gate.

Revalidates artifacts, not a new RTL run. Never mutates Git or closes GitHub issues.
The completion review must explain the measured design selection and limitations.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

from evidence import REPO, HW, check_hashes, require, matrix, sha, validate_recovery, validate_execution, validate_formal, validate_lifecycle
from multi_evidence import validate_multi
from design_evidence import validate_study, validate_technology
from report_designs import render_with_identity
from profile_evidence import validate_profile, recheck_profile_artifacts


def read(path):
    return json.loads(path.read_text())


def validate_review(text):
    require("Status: accepted against the original S03 criteria." in text.splitlines(),
            "Original-criteria completion review is still pending")
    for item in [*(f"WP{i}" for i in range(1, 7)), *(f"AC{i}" for i in range(1, 6))]:
        require(text.count("| " + item + ":") == 1, "Missing or duplicate original acceptance item: " + item)


def validate_semantic(r):
    require(r["status"] == "passed" and r["claim_class"] == "actual_shared_semantic_and_RV64_profile_RTL"
            and r["source_sha256"] == r["source_sha256_after"], "Missing stable semantic-boundary gate")
    e, p, layouts, predictor = [r[k] for k in ("execution", "profile", "layouts", "predictor")]
    require(all(v["status"] == "passed" for v in (e, p, layouts, predictor)), "Unfinished component policy test")
    require(e["semantic_vectors"] == 4953 and e["different_sign_zero_results"] > 100 and e["alternate_target_vectors"] == 72
            and e["fault_vectors"] > 100 and p["checks"] == 135 and predictor["checks"] == 1024
            and predictor["index_shifts"] == [1, 3], "Incomplete semantic contrasts")
    matrix(layouts["runs"], ("architectural_registers", "zero_slot", "argument_slot", "physical_registers", "cycles"),
           [(16, 7, 3, 24, 6000), (32, 31, 2, 40, 6000)])
    for row in layouts["runs"]:
        require(row["writable_zero_allocations"] > 0 and row["resource_stalls"] > 0 and row["recoveries"] > 100
                and row["retirements"] > 500 and row["relaunches"] == 7 and row["out_of_order_writebacks"] > 100
                and row["commit_and_recovery"] > 0, "Missing alternate-layout ownership witness")
    return {k: r[k] for k in ("execution", "profile", "layouts", "predictor", "limits")}


def validate_rename(r):
    require(r["status"] == "passed_with_profile_differences" and r["source_sha256"] == r["source_sha256_after"], "Missing rename gate")
    units = r["rename_unit"]["runs"]
    matrix(units, ("physical_registers", "cycles"), [(p, 6000) for p in (33, 36, 64)])
    require(all(v["resource_stalls"] > 0 and v["commit_and_recovery"] > 0 for v in units), "Missing rename hazard coverage")
    comparisons = r["pressure_comparisons"]
    names = {v["name"] for v in comparisons}
    require(len(names) == 50, "Wrong pressure scenario count")
    matrix(comparisons, ("name", "invocation", "rob_entries", "prediction", "physical_registers"),
           [(name, i, 16, m, 36) for name in names for i in (0, 1) for m in ("off", "bimodal")])
    require(sum(v["status"] == "matched" for v in comparisons) == r["fully_matched_invocations"] == 192
            and sum(v["status"] == "expected_profile_difference" for v in comparisons) == r["expected_profile_differences"] == 8,
            "Incomplete rename architectural comparison")
    require({v["name"] for v in comparisons if v["status"] != "matched"} == {"unsupported_fence_i", "entry_alignment"}, "New exclusion")
    matrix(r["pressure_counters"], ("rob_entries", "prediction", "physical_registers"), [(16, m, 36) for m in ("off", "bimodal")])
    require(all(v["rename_stall_cycles"] > 0 for v in r["pressure_counters"]), "Missing integrated pressure")
    return {k: r[k] for k in ("rename_unit", "pressure_counters", "fully_matched_invocations", "expected_profile_differences", "limits")}


def resolve_compatibility(compatibility):
    patterns = {"bulk": "workloads/results/s02-treesitter-*/bulk/validation.json",
                "spinal": "workloads/results/s02-treesitter-*/rtl-validation.json",
                "native": "workloads/results/treesitter-*/validation.json",
                "ppe": "hardware/spinal/build/ppe/run-*/validation.json",
                "legacy": "hardware/spinal/build/s02-legacy/*/validation.json"}
    paths = {}
    for name, pattern in patterns.items():
        matches = [p for p in REPO.glob(pattern) if sha(p) == compatibility["reports_sha256"][name]]
        require(len(matches) == 1, "Cannot uniquely resolve integration artifact: " + name)
        paths[name] = matches[0]
    spec = importlib.util.spec_from_file_location("s03_compatibility_gate", REPO / "workloads/s02/gate.py")
    gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
    refreshed = gate.collect(paths)  # rechecks all streams, outputs, tools, RTL, artifacts and regression gates
    for field in ("source_sha256", "reports_sha256", "ape", "ppe", "native", "regressions", "dependencies"):
        require(refreshed[field] == compatibility[field], "Integration evidence changed: " + field)
    return refreshed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compatibility", type=Path, required=True)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--technology", type=Path, nargs="+", required=True)
    parser.add_argument("--profile", type=Path, help="Full selected PRF48 tool/ISA gate when choosing that measured point")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Preserve final evidence; use a fresh output path")
    review_path = REPO / "workloads/S03-COMPLETION.md"
    selection_path = REPO / "workloads/s03/design-selection.json"
    performance_path = REPO / "workloads/S03-DESIGN-STUDY.md"
    require(review_path.is_file() and selection_path.is_file() and performance_path.is_file(),
            "Complete measured performance report, design selection and original-criteria review first")
    validate_review(review_path.read_text())
    paths = {"semantics": HW / "build/ape_semantics/gate.json", "multi": HW / "build/ape_multi/gate.json",
             "recovery": HW / "build/ape_recovery/gate.json", "execution": HW / "build/ape_execution/gate.json",
             "rename": HW / "build/ape_rename/gate.json", "formal": HW / "build/ape_formal/validation.json",
             "lifecycle": HW / "build/ape_rename_formal/steps16/validation.json"}
    reports = {name: read(p) for name, p in paths.items()}
    summaries = {name: validator(reports[name]) for name, validator in
                 (("semantics", validate_semantic), ("multi", validate_multi), ("recovery", validate_recovery),
                  ("execution", validate_execution), ("rename", validate_rename), ("formal", validate_formal), ("lifecycle", validate_lifecycle))}
    for name in ("formal", "lifecycle"):
        require(reports[name]["recovery_report_sha256"] == sha(paths["recovery"]), "Formal proof used different generated RTL")
    sources = {}

    def bind(base, hashes):
        check_hashes(base, hashes)
        for name, digest in hashes.items():
            key = str((base / name).resolve().relative_to(REPO))
            require(key not in sources or sources[key] == digest, "Mixed source revisions: " + key)
            sources[key] = digest

    for r in reports.values():
        bind(HW, r["source_sha256"]); check_hashes(HW, r["evidence_sha256"])
    study = read(args.study)
    study_summary = validate_study(study)
    bind(REPO, study["source_sha256"])
    for hashes in [*study["generated"].values(), *(r["artifacts_sha256"] for r in study["results"])]:
        check_hashes(REPO, hashes)
    for row in study["results"]:
        artifacts = [REPO / n for n in row["artifacts_sha256"]]
        def one(suffix):
            matches = [p for p in artifacts if p.name.endswith(suffix)]
            require(len(matches) == 1, "Ambiguous controlled-study artifact: " + suffix)
            return matches[0]
        reference = args.study.parent.parent / row["workload"] / row["case"]
        require(read(one(".execution.json")) == row["metrics"], "Study counters differ from actual runner output")
        require(read(one(".digest.json")) == row["digest"] == read(reference / "digest.json"), "Study/reference architecture differs")
        require(one(".result.bin").read_bytes() == (reference / "result.bin").read_bytes(), "Study/reference output differs")
    target = study["target_build"]
    require(target["status"] == "passed_reference_preparation", "Target-build artifacts were not finalized")
    bind(REPO, target["source_sha256"])
    check_hashes(args.study.parent.parent, target["artifacts_sha256"])
    technology = [read(p) for p in args.technology]
    tech_summary = validate_technology(technology)
    require(performance_path.read_text() == render_with_identity(study, technology, sha(args.study), [sha(p) for p in args.technology]),
            "Performance report differs from measured design evidence")
    for r in technology:
        bind(REPO, r["source_sha256"])
        check_hashes(REPO, r["gate_snapshots_sha256"])
        check_hashes(REPO, r["control_artifacts_sha256"])
        for snapshot in r["gate_snapshots_sha256"]:
            saved = read(REPO / snapshot)
            bind(HW, saved["source_sha256"])
            require(saved["source_sha256"] == saved["source_sha256_after"], "Unstable physical input gate")
        for row in r["results"]:
            check_hashes(REPO, row["evidence_sha256"])
            artifacts = [REPO / n for n in row["evidence_sha256"]]
            stats = [p for p in artifacts if p.name == "stat.json"]
            cec = [p for p in artifacts if p.name == "comb-equivalence.log"]
            timing = [p for p in artifacts if p.name == "comb-timing.log"]
            require(len(stats) == len(cec) == len(timing) == 1, "Missing physical tool outputs")
            sys.path.insert(0, str(HW / "tools"))
            from probe_ape_technology import parse_delay, final_equivalence, blif_interface, validate_aiger_header
            require(read(stats[0]) == row["statistics"] and final_equivalence(cec[0].read_text()),
                    "Physical summary differs from actual mapping/equivalence output")
            require(parse_delay(timing[0].read_text()) == row["comb_boundary_delay_ps"], "Timing summary differs from tool output")
            original = next(p for p in artifacts if p.name == "input.blif")
            mapped = next(p for p in artifacts if p.name == "output.blif")
            interface = blif_interface(original)
            require(interface == blif_interface(mapped), "Mapped-network port correspondence changed")
            require(len(interface[".inputs"]) == row["comb_interface"]["inputs"]
                    and len(interface[".outputs"]) == row["comb_interface"]["outputs"], "Wrong proof-interface dimensions")
            for name in ("before.aig", "after.aig"):
                validate_aiger_header(next(p for p in artifacts if p.name == name), interface)
    compatibility = read(args.compatibility)
    require(compatibility["status"] == "passed" and compatibility["claim_class"] == "actual_APE_tool_and_first_PPE_RTL", "Missing full compatibility")
    compatibility = resolve_compatibility(compatibility)
    bind(REPO, compatibility["source_sha256"])
    # Prove current semantic/dual-lane sources participated in full integration.
    for name in ("ApeSemantics", "ApeRv64Profile", "ApeRename", "ApeIssueScheduler", "ApeExecute", "ApeCompletionGuard"):
        require(f"hardware/spinal/src/main/scala/hats/{name}.scala" in compatibility["source_sha256"], "Pre-boundary compatibility evidence")
    selection = read(selection_path)
    require(selection["status"] == "reviewed", "Design selection has not been reviewed")
    profile_summary = None
    if args.profile:
        profile = read(args.profile)
        names = {r["name"] for r in reports["multi"]["comparisons"] if r["configuration"][-1] == "standard"}
        from evidence import RECOVERY_NAMES
        profile_summary = validate_profile(profile, compatibility["ape"]["cases"], names, RECOVERY_NAMES)
        require(selection["selected_point"] == profile["point"] and selection["profile_sha256"] == sha(args.profile),
                "Selection is not the fully verified candidate")
        require(profile["generated_sha256"] == study["generated"]["prf48"], "Selected executable differs from the measured RTL")
        require(sha(args.study) in profile["inputs_sha256"].values()
                and compatibility["reports_sha256"]["bulk"] in profile["inputs_sha256"].values(), "Selected inputs differ from final comparison")
        bulk_paths = [REPO / n for n, digest in profile["inputs_sha256"].items()
                      if digest == compatibility["reports_sha256"]["bulk"]]
        require(len(bulk_paths) == 1, "Ambiguous selected input reference")
        recheck_profile_artifacts(profile, read, bulk_paths[0].parent.parent)
        bind(REPO, profile["source_sha256"])
    else:
        require(selection["selected_point"] == ["narrow", 8, 64, 1, "bimodal", 16],
                "A changed selection needs actual selected-profile integration evidence")
    require(selection["study_sha256"] == sha(args.study)
            and sorted(selection["technology_report_sha256"]) == sorted(sha(p) for p in args.technology), "Selection cites different measurements")
    require(all(selection[k] for k in ("issue_width_rationale", "rob_queue_rationale", "prf_rationale", "predictor_rationale", "limitations")), "Missing measured selection rationale")
    for case in study["results"]:
        reference = next(r for r in compatibility["ape"]["cases"] if (r["mode"], r["case"]) == (case["workload"], case["case"]))
        require(reference["digest"] == case["digest"], "Controlled study differs from full integration work")
    tests = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "workloads/s03", "-p", "test_*.py", "-v"],
                           cwd=REPO, capture_output=True, text=True, check=True, timeout=120)
    print(tests.stderr, end="")
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "hardware/spinal/tools", "-p", "test_ape_technology.py", "-v"],
                   cwd=REPO, check=True, timeout=60)
    bind(REPO, {str(p.relative_to(REPO)): sha(p) for p in Path(__file__).parent.glob("*.py")})
    docs = [review_path, selection_path, performance_path, REPO / "ROADMAP.md", REPO / "README.md", HW / "APE.md", HW / "DEVELOPMENT.md"]
    docs += list((HW / "spec").glob("APE-*.md")) + list((HW / "spec").glob("S03-*.md"))
    result = {"schema": 1, "status": "passed", "issue": 4, "stage": "S03", "S03_complete": True,
              "claim_class": "source_bound_original_S03_acceptance_evidence", "created_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": sources, "documentation_sha256": {str(p.relative_to(REPO)): sha(p) for p in docs},
              "reports_sha256": {**{n: sha(p) for n, p in paths.items()}, "compatibility": sha(args.compatibility),
                                 "controlled_study": sha(args.study), "technology": [sha(p) for p in args.technology],
                                 "selected_profile": sha(args.profile) if args.profile else None},
              "focused": summaries, "controlled_workload_design_points": study_summary,
              "technology_design_points": tech_summary, "design_selection": selection,
              "selected_profile": profile_summary,
              "compatibility": {k: compatibility[k] for k in ("native", "ape", "regressions")},
              "collector_tests": {"status": "passed", "scope": "report checks and rejection behavior, not hardware execution"},
              "limits": ["Workload-evaluated RV64I-subset prototype, not a privileged general-purpose production CPU",
                         "Selected bounded formal assumptions/gaps retained; no whole-core or unbounded proof claim",
                         "Optional dual issue, single dispatch/commit/writeback and one head-only memory request",
                         "Early research-library combinational timing and FF/mux area, not achievable silicon clock or physical energy",
                         "No target-hosted compiler/Python, full agent acceleration, HBM/LPDDR/OS/tensor or S10 physical-closure claim"]}
    check_hashes(REPO, sources)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print("Original S03 evidence checks passed; Git/GitHub state unchanged: " + str(args.output))


if __name__ == "__main__":
    main()
