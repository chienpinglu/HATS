#!/usr/bin/env python3
"""Verify and summarize matched-input PPE cache/MHSR RTL design points."""
import argparse
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gates", nargs=6, type=Path,
                        help="D-L1 8/2,16/4,32/8 then I/D-L1 8/2,16/4,32/8 source-bound gates")
    parser.add_argument("--output", type=Path, default=REPO / "workloads/s04/PPE-DESIGN-POINTS.json")
    args = parser.parse_args()
    gates = [p.resolve() for p in args.gates]
    expected = [(False, 8, 2), (False, 16, 4), (False, 32, 8),
                (True, 8, 2), (True, 16, 4), (True, 32, 8)]
    records = []
    matched_inputs = {False: None, True: None}
    matched_source = None
    matched_tools = None
    for path, (instructions, sets, mshrs) in zip(gates, expected):
        gate = json.loads(path.read_text())
        require(gate.get("status") == "passed_partial_integration" and gate.get("S04_complete") is False,
                f"Not a passing partial PPE gate: {path}")
        config = gate.get("memory_configuration", {})
        require((config.get("sets"), config.get("line_bytes"), config.get("mshrs"), config.get("instruction_cache"))
                == (sets, 32, mshrs, instructions), f"Unexpected design-point configuration: {path}")
        require(gate.get("source_sha256") == gate.get("source_sha256_after"), f"Source changed during gate: {path}")
        root = f"build/s04/{path.parent.name}/"
        normalized = {}
        for name, digest in gate["input_sha256"].items():
            if name.startswith(root):
                relative = name.removeprefix(root)  # legacy repo-relative input manifest
            else:
                candidate = Path(name)
                require(not candidate.is_absolute() and ".." not in candidate.parts,
                        "Input path escaped run directory")
                run_root = path.parent.resolve()
                resolved = (run_root / candidate).resolve()
                require(resolved.is_relative_to(run_root) and resolved.is_file(),
                        "Input path escaped or missing from run directory")
                relative = candidate.as_posix()
            normalized[relative] = digest
        require(matched_inputs[instructions] is None or normalized == matched_inputs[instructions],
                f"{'I/D-L1' if instructions else 'D-L1'} points do not use byte-identical workload/input artifacts")
        require(matched_source is None or gate["source_sha256"] == matched_source,
                "Design points were not built from the same source identities")
        require(matched_tools is None or gate["tools"] == matched_tools,
                "Design points used different tool identities")
        matched_inputs[instructions] = normalized
        matched_source = gate["source_sha256"]
        matched_tools = gate["tools"]
        rows = gate["diagnostics"]["cached"]["runs"]
        comparisons = gate["comparisons"]["cached"]
        require(len(rows) == len(comparisons) == 316 and all(x["status"] == "matched" for x in comparisons),
                "Missing exact architectural workload comparisons")
        ai_names = {f"ai_relu_256_g{i}" for i in range(32)}
        ai_rows = [r for r in rows if r["case"] in ai_names]
        require(set(gate.get("ai_vector_epilogue_cases", [])) == ai_names and len(ai_rows) == 64
                and all(r["global_words"] == 15 and r["lanes"] == 27 and r["retired"] == 16
                        for r in ai_rows), "Missing RTL evidence for PPE vector inference epilogue groups")
        require(all(r["accepted_lines"] == r["completed_lines"] for r in rows), "Unbalanced line transactions")
        sum_fields = ("cycles", "global_words", "all_words", "hits", "misses", "refills", "writebacks",
                      "reorders", "stalls", "scratch_parallel", "instruction_hits", "instruction_misses",
                      "fetch_requests", "fabric_accepted", "fabric_completed", "fabric_rejected")
        metrics = {field: sum(r[field] for r in rows) for field in sum_fields}
        metrics.update(max_mshrs=max(r["max_mshrs"] for r in rows),
                       max_outstanding_lines=max(r["max_lines"] for r in rows),
                       max_fabric_outstanding=max(r["max_fabric"] for r in rows),
                       max_cycles=max(r["cycles"] for r in rows),
                       exact_architectural_comparisons=len(comparisons),
                       ai_vector_epilogue_groups=len(ai_names),
                       total_accepted_lines=sum(r["accepted_lines"] for r in rows),
                       total_completed_lines=sum(r["completed_lines"] for r in rows))
        if instructions:
            app = gate.get("delimiter_application", {})
            vector_app = gate.get("ai_vector_application", {})
            require(app.get("status") == "passed" and app.get("groups_completed") == 32
                    and app.get("input_bytes") == 256 and app.get("output_matches_oracle") is True
                    and app.get("canaries_unchanged") is True,
                    f"Missing full PPE delimiter task evidence: {path}")
            require(vector_app.get("status") == "passed" and vector_app.get("kernel") == "ai_relu"
                    and vector_app.get("groups_completed") == 32
                    and vector_app.get("output_matches_oracle") is True
                    and vector_app.get("canaries_unchanged") is True
                    and vector_app.get("accepted_lines") == vector_app.get("completed_lines") > 0,
                    f"Missing full PPE vector-ReLU application evidence: {path}")
            metrics["delimiter_application"] = {key: app[key] for key in
                ("groups_completed", "input_bytes", "loads", "stores", "retired", "instruction_fetches",
                 "accepted_lines", "completed_lines", "i_hits", "i_misses", "d_hits", "d_misses",
                 "output_sha256", "input_sha256")}
            require(app["accepted_lines"] == app["completed_lines"], "Undrained multi-group application traffic")
            metrics["ai_vector_application"] = {key: vector_app[key] for key in
                ("kernel", "groups_completed", "input_bytes", "loads", "stores", "retired",
                 "instruction_fetches", "accepted_lines", "completed_lines", "i_hits", "i_misses",
                 "d_hits", "d_misses", "output_sha256", "input_sha256", "independent_oracle")}
        records.append({"gate": str(path.relative_to(REPO)), "gate_sha256": sha(path),
                        "configuration": config, "metrics": metrics})
    input_manifests = {}
    for instructions, name in ((False, "D_L1"), (True, "I_D_L1")):
        canonical = json.dumps(sorted(matched_inputs[instructions].items()), separators=(",", ":")).encode()
        input_manifests[name] = {"artifact_count": len(matched_inputs[instructions]),
            "normalized_sha256": hashlib.sha256(canonical).hexdigest()}
    canonical = json.dumps(input_manifests, sort_keys=True, separators=(",", ":")).encode()
    output = {"schema": 1, "issue": 5, "stage": "S04", "status": "matched_workload_rtl_design_point_comparison",
              "S04_complete": False, "claim_class": "behaviorally_modeled_PPE_D_L1_and_I_D_L1_RTL_cycles_and_counters",
              "input_artifact_count": sum(row["artifact_count"] for row in input_manifests.values()),
              "input_manifests_by_mode": input_manifests,
              "normalized_input_manifest_sha256": hashlib.sha256(canonical).hexdigest(),
              "report_generator": str(Path(__file__).resolve().relative_to(REPO)),
              "report_generator_sha256": sha(Path(__file__).resolve()),
              "source_sha256": matched_source, "tools": matched_tools, "design_points": records,
              "limits": ["PPE cached workload suite, including a HATS-authored vector bias/ReLU epilogue, is compared against the same independent ISA oracle at every point",
                "I/D-L1 design points additionally execute complete 32-group delimiter-prefilter and residual+bias+ReLU PPE tasks and compare final bytes/canaries to independent oracles",
                "Reported cycles are SpinalSim RTL cycles under the testbench's modeled external-line service, not measured DRAM/HBM/LPDDR timing",
                "Configurations change set count and MSHR count together; this three-point sweep cannot attribute effects to one parameter independently",
                "No synthesis area, achieved frequency, power, bandwidth, or speedup claim",
                "The original S04 issue remains open"]}
    target = args.output if args.output.is_absolute() else REPO / args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Matched PPE design-point report: {target}")


if __name__ == "__main__":
    main()
