"""Selected-configuration evidence checks; not a substitute for RTL execution."""
from evidence import check_hashes, require, matrix, REPO
from verify_profile import POINT


def validate_profile(r, compatibility_cases, standard_names, recovery_names):
    require(r["status"] == "passed_with_profile_differences"
            and r["claim_class"] == "actual_selected_profile_full_tool_and_independent_ISA_RTL"
            and r["point"] == POINT, "Missing selected PRF48 execution gate")
    require(r["service"] == {"response_base": 2, "seed": 0x48415453, "kind": "transaction_ordinal"}, "Wrong profile memory service")
    rows = r["tool_runs"]
    require(len(compatibility_cases) == 42, "Full reference cases required")
    expected = {(c["mode"], c["case"]): c["digest"] for c in compatibility_cases}
    matrix(rows, ("mode", "case"), list(expected))
    for row in rows:
        digest, m = row["digest"], row["metrics"]
        require(digest == expected[row["mode"], row["case"]], "Selected profile changed architectural work")
        require(m["retired"] == digest["retirements"] and m["requests"] == digest["memory_events"]
                and m["cycles"] > 0 and m["response_base"] == 2 and m["service_seed"] == 0x48415453
                and m["dual_issue_cycles"] == 0, "Selected profile counters differ")
    suites = r["isa_suites"]
    require(set(suites) == {"standard", "recovery"} and len(standard_names) == 50 and len(recovery_names) == 6,
            "Missing selected ISA/recovery coverage")
    for kind, suite in suites.items():
        require(suite["status"] == "passed" and
                tuple(suite[k] for k in ("rob_entries", "physical_registers", "issue_width", "prediction",
                                        "checkpoint_capacity", "execution_stages", "generation_bits")) == (8, 48, 1, "bimodal", 4, 2, 2)
                and suite["early_recovery"] is True and suite["recovery_suite"] == (kind == "recovery"), "ISA profile mismatch")
        names = standard_names if kind == "standard" else recovery_names
        matrix(suite["results"], ("name", "invocation"), [(n, i) for n in names for i in (0, 1)])
        require(suite["runs"] == len(suite["results"]) and all(row["passed"] is True for row in suite["results"]), "Selected ISA failure")
        if kind == "recovery":
            for row in suite["results"]:
                if row["name"] == "older_load":
                    require(row["early_memory_redirects"] > 0 and row["target_issues_before_memory"] > 0, "Missing selected early target witness")
                if row["name"] == "nested_checkpoints":
                    require(row["resolved_younger_squashes"] > 0 and row["commit_and_redirect"] > 0, "Missing selected nested/concurrent recovery")
                if row["name"] == "older_bus_fault":
                    require(row["early_memory_redirects"] > 0, "Missing selected older-fault recovery")
                if row["name"] == "checkpoint_exhaustion":
                    require(row["checkpoint_stall_cycles"] > 0, "Missing selected checkpoint pressure")
    comparisons = r["comparisons"]
    matrix(comparisons, ("suite", "name", "invocation"),
           [(k, n, i) for k, names in (("standard", standard_names), ("recovery", recovery_names)) for n in names for i in (0, 1)])
    for row in comparisons:
        gap = row["suite"] == "standard" and row["name"] in ("unsupported_fence_i", "entry_alignment")
        require(row["status"] == ("expected_profile_difference" if gap else "matched"), "New selected-profile exclusion")
    require(r["exact_isa_matches"] == 108 and r["unchanged_profile_differences"] == 4, "Wrong selected-profile totals")
    return {"point": POINT, "full_tool_invocations": 42, "exact_isa_matches": 108, "unchanged_profile_differences": 4,
            "matched_retirements": sum(row["digest"]["retirements"] for row in rows),
            "matched_memory_events": sum(row["digest"]["memory_events"] for row in rows), "limits": r["limits"]}


def recheck_profile_artifacts(r, read, reference_root):
    for key in ("source_sha256", "inputs_sha256", "generated_sha256", "isa_artifacts_sha256"):
        check_hashes(REPO, r[key])
    if r.get("resumed_tool_evidence_sha256"):
        from verify_profile import verify_resume
        check_hashes(REPO, r["resumed_tool_evidence_sha256"])
        paths = [REPO / p for p in r["resumed_tool_evidence_sha256"]]
        original = [p for p in paths if p.name == "verify_profile.py.original"]
        prior = [p for p in paths if p.name == "validation.json"]
        require(len(original) == len(prior) == 1, "Incomplete original execution provenance")
        reused = verify_resume(read(prior[0]), r["source_sha256"], r["inputs_sha256"], r["generated_sha256"], original[0])
        require(reused == r["tool_runs"], "Resumed actual execution results changed")
    from pathlib import Path
    from evidence import sha
    for tool in r["isa_assembler"].values():
        require(sha(Path(tool["path"])) == tool["sha256"], "Selected ISA assembler changed")
    for row in r["tool_runs"]:
        check_hashes(REPO, row["artifacts_sha256"])
        paths = [REPO / name for name in row["artifacts_sha256"]]
        def one(suffix):
            matches = [p for p in paths if p.name.endswith(suffix)]
            require(len(matches) == 1, "Ambiguous selected execution artifact")
            return matches[0]
        reference = reference_root / row["mode"] / row["case"]
        require(read(one(".digest.json")) == row["digest"] == read(reference / "digest.json"), "Selected stream changed")
        require(read(one(".execution.json")) == row["metrics"], "Selected counters changed")
        require(one(".result.bin").read_bytes() == (reference / "result.bin").read_bytes(), "Selected output changed")
