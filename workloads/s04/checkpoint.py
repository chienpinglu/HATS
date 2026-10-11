#!/usr/bin/env python3
"""Revalidate and summarize partial S04 evidence, never close issue #5."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tarfile
import hashlib

REPO = Path(__file__).resolve().parents[2]
HW = REPO / "hardware/spinal"
sys.path.insert(0, str(HW / "tools"))
from verify_memory_l1 import sha, require, validate as validate_l1
from verify_ape_memory import NAMES, validate as validate_ape, validate_publication, validate_device, validate_atomic
from compare_ape_spike import compare, read_trace
from verify_ape_spike import case_profile
from verify_ppe_memory import validate as validate_ppe, validate_device as validate_ppe_device
from verify_ppe import compare as compare_ppe


def check_hashes(root, values):
    require(bool(values), "Empty identity manifest")
    for name, digest in values.items():
        path = (root / name).resolve()
        require(path.is_relative_to(root) and path.is_file() and sha(path) == digest, "Changed/missing artifact: " + name)


def validate_tree_tool_source_identity(values):
    """Require the Tree-sitter cached run to bind the exact current verifier."""
    check_hashes(HW, values)


def target_resource_observation(report):
    """Extract source-bound selected-run stack/heap observations, not WCET bounds."""
    app = (REPO / report["application_dir"]).resolve()
    require(app.is_relative_to(REPO) and app.is_dir(), "Tree-sitter application directory escaped the repo")
    result_gate = app.parent / "validation.json"
    direct_gate = app.parent / "rtl-validation.json"
    direct_name, result_name = (str(p.relative_to(REPO)) for p in (direct_gate, result_gate))
    require(report.get("input_sha256", {}).get(direct_name) == sha(direct_gate)
            and report.get("input_sha256", {}).get(result_name) == sha(result_gate),
            "Tree-sitter resource observations are not bound to their reference and APE RTL gates")
    reference = json.loads(result_gate.read_text())
    direct = json.loads(direct_gate.read_text())
    run = next((row for row in reference.get("runs", [])
                if f"{row.get('case')}-{row.get('kind')}" == report.get("case")), None)
    require(run is not None and run.get("execution", {}).get("status") == "executed",
            "Missing Spike target resource observation for cached APE case")
    trace = app / "rtl-r8-bimodal" / f"{report['case']}-0.trace.jsonl"
    trace_name = str(trace.relative_to(REPO))
    trace_sha = sha(trace)
    require(report.get("input_sha256", {}).get(trace_name) == trace_sha
            and any(row.get("case") == report["case"] and row.get("invocation") == 0
                    and row.get("trace_sha256") == trace_sha for row in direct.get("comparisons", [])),
            "APE stack-pointer trace is not source-bound to the direct architectural comparison")
    stack_values = []
    for line in trace.read_text().splitlines():
        event = json.loads(line)
        if event.get("kind") == "retire" and event.get("writes") is True and event.get("rd") == 2:
            stack_values.append(int(event["value"]))
    require(bool(stack_values) and all(0xF00000 <= value <= 0x1000000 for value in stack_values),
            "APE stack pointer left the declared selected-workload stack reservation")
    build_gate = (REPO / report["gate_path"]).resolve()
    require(build_gate.is_file() and build_gate.is_relative_to(HW / "build"),
            "Cached APE evidence gate is missing or outside the hardware build tree")
    final_memory = build_gate.parent / "final-memory.bin"
    require(final_memory.is_file() and sha(final_memory) == report.get("final_memory_sha256"),
            "Cached APE final memory is missing or differs from its source-bound report")
    image = final_memory.read_bytes()
    require(len(image) == 0x1000000, "Cached APE final memory has the wrong 16 MiB extent")
    # Target output begins at 0x210000 in a RAM image based at 0x100000.
    ape_result = __import__("struct").unpack_from("<8Q", image, 0x110000)
    require(ape_result[0] == 0x4841545354533031 and ape_result[1] == 0
            and ape_result[2] == 0 and ape_result[4] == 0
            and ape_result[5] == run["result"]["peak_bytes"]
            and ape_result[6] == run["result"]["allocation_calls"]
            and ape_result[7] == run["result"]["heap_granted"],
            "APE RTL output-region heap telemetry differs from its Spike architectural oracle")
    return {"case": report["case"],
            "ape_observed_stack_bytes": 0x1000000 - min(stack_values),
            "spike_observed_stack_bytes": run["execution"]["observed_stack_pointer_bytes"],
            "ape_peak_requested_heap_bytes": ape_result[5],
            "ape_live_heap_after_cleanup_bytes": ape_result[4],
            "ape_heap_bytes_granted": ape_result[7],
            "peak_requested_heap_bytes": run["result"]["peak_bytes"],
            "heap_bytes_granted": run["result"]["heap_granted"],
            "ape_trace_sha256": trace_sha,
            "reference_gate_sha256": sha(result_gate),
            "claim_class": "selected_target_workload_resource_observation_not_worst_case_bound"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--l1", required=True, type=Path)
    parser.add_argument("--ape", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--instructions", action="store_true")
    parser.add_argument("--ppe", type=Path, help="Also revalidate partial PPE cache integration")
    parser.add_argument("--ownership", type=Path, help="Also revalidate the dual-engine ownership integration gate")
    parser.add_argument("--ownership-formal", type=Path, help="Also revalidate bounded ownership-controller safety proof")
    parser.add_argument("--l1-formal", type=Path, help="Also revalidate bounded safety proof of generated 4-MSHR L1 RTL")
    parser.add_argument("--ape-lsq-formal", type=Path, help="Also revalidate bounded selected APE LSQ safety proof")
    parser.add_argument("--design-points", type=Path, help="Also revalidate matched-input PPE cache design-point report")
    parser.add_argument("--ape-trace-design-points", type=Path,
                        help="Also bind APE application memory events replayed through actual L1 RTL")
    parser.add_argument("--ape-cached-application", type=Path,
                        help="Also bind actual APE application execution through APE+LSQ+D-L1 RTL")
    parser.add_argument("--ape-tool-cached", type=Path, action="append",
                        help="Bind a source-bound Tree-sitter case through APE+LSQ+I/D-L1 RTL; repeat for a matrix")
    parser.add_argument("--ape-heap-exhaustion", type=Path, action="append",
                        help="Bind a selected Tree-sitter heap-exhaustion case through actual APE RTL; repeat for a workload matrix")
    parser.add_argument("--acceptance-complete", action="store_true",
                        help="Require and record the complete original S04 AC1-AC5 evidence matrix")
    args = parser.parse_args()
    l1_path, ape_path = args.l1.resolve(), args.ape.resolve()
    l1, ape = [json.loads(p.read_text()) for p in (l1_path, ape_path)]
    require(ape.get("instruction_cache", False) == args.instructions, "Wrong instruction-cache gate mode")
    require(l1["status"] == "passed_component" and ape["status"] == "passed_partial_integration"
            and l1["S04_complete"] is False and ape["S04_complete"] is False, "Wrong gate status/scope")
    validate_l1(l1["result"]); validate_ape(ape["cached"], args.instructions)
    if args.instructions:
        validate_ape(ape["data_regression"]); validate_publication(ape["instruction_publication"])
        validate_device(ape["device_memory"])
    if "atomic_add" in ape:
        validate_atomic(ape["atomic_add"])
    ppe_path = args.ppe.resolve() if args.ppe else None
    ppe = json.loads(ppe_path.read_text()) if ppe_path else None
    ownership_path = args.ownership.resolve() if args.ownership else None
    ownership = json.loads(ownership_path.read_text()) if ownership_path else None
    ownership_formal_path = args.ownership_formal.resolve() if args.ownership_formal else None
    ownership_formal = json.loads(ownership_formal_path.read_text()) if ownership_formal_path else None
    l1_formal_path = args.l1_formal.resolve() if args.l1_formal else None
    l1_formal = json.loads(l1_formal_path.read_text()) if l1_formal_path else None
    ape_lsq_formal_path = args.ape_lsq_formal.resolve() if args.ape_lsq_formal else None
    ape_lsq_formal = json.loads(ape_lsq_formal_path.read_text()) if ape_lsq_formal_path else None
    design_points_path = args.design_points.resolve() if args.design_points else None
    design_points = json.loads(design_points_path.read_text()) if design_points_path else None
    ape_trace_path = args.ape_trace_design_points.resolve() if args.ape_trace_design_points else None
    ape_trace = json.loads(ape_trace_path.read_text()) if ape_trace_path else None
    ape_cached_path = args.ape_cached_application.resolve() if args.ape_cached_application else None
    ape_cached = json.loads(ape_cached_path.read_text()) if ape_cached_path else None
    ape_tool_cached_paths = [p.resolve() for p in (args.ape_tool_cached or [])]
    ape_tool_cached_reports = [json.loads(p.read_text()) for p in ape_tool_cached_paths]
    ape_heap_paths = [p.resolve() for p in (args.ape_heap_exhaustion or [])]
    ape_heap_reports = [json.loads(p.read_text()) for p in ape_heap_paths]
    ape_trace_run_gate = None
    ape_cached_run_gate = None
    ape_tool_cached_run_gates = []
    if ape_trace:
        from verify_ape_memory_trace import validate_report as validate_ape_trace
        validate_ape_trace(ape_trace)
        ape_trace_run_gate=(ape_trace_path.parent.parent.parent / ape_trace.get("build_gate_path", "")).resolve()
        require(ape_trace_run_gate.is_file() and ape_trace.get("build_gate_sha256") == sha(ape_trace_run_gate),
                "APE trace design-point report refers to a missing or changed source-bound run gate")
        run_evidence=json.loads(ape_trace_run_gate.read_text())
        require(run_evidence.get("status")=="passed_trace_design_points" and
                run_evidence.get("runs")==ape_trace.get("runs"),
                "Persistent APE trace evidence differs from its source-bound run gate")
        check_hashes(HW,ape_trace.get("source_sha256",{}))
        check_hashes(REPO,ape_trace.get("input_sha256",{}))
        check_hashes(REPO,{row["generated_rtl"]:row["generated_rtl_sha256"] for row in ape_trace["runs"]})
        check_hashes(REPO,{row["validation_path"]:row["validation_sha256"] for row in ape_trace["runs"]})
    if ape_cached:
        from verify_ape_cached_application import validate_report as validate_ape_cached
        validate_ape_cached(ape_cached)
        ape_cached_run_gate=(ape_cached_path.parent.parent.parent / ape_cached.get("build_gate_path", "")).resolve()
        require(ape_cached_run_gate.is_file() and ape_cached.get("build_gate_sha256") == sha(ape_cached_run_gate),
                "integrated APE application report refers to a missing or changed run gate")
        run_evidence=json.loads(ape_cached_run_gate.read_text())
        require(run_evidence.get("status")=="passed_integrated_application_design_points"
                and run_evidence.get("runs")==ape_cached.get("runs"),
                "persistent integrated APE evidence differs from its source-bound gate")
        check_hashes(HW,ape_cached.get("source_sha256",{}))
        check_hashes(REPO,ape_cached.get("input_sha256",{}))
        check_hashes(REPO,{row["generated_rtl"]:row["generated_rtl_sha256"] for row in ape_cached["runs"]})
        check_hashes(REPO,{row["validation_path"]:row["validation_sha256"] for row in ape_cached["runs"]})
    for ape_tool_cached_path, ape_tool_cached in zip(ape_tool_cached_paths, ape_tool_cached_reports):
        require(ape_tool_cached.get("status")=="passed_cached_tool"
                and ape_tool_cached.get("issue")==5
                and ape_tool_cached.get("S04_complete") is False
                and ape_tool_cached.get("claim_class")=="real_Tree_sitter_tool_on_APE_LSQ_I_D_L1_RTL",
                "Tree-sitter integration evidence has wrong status/scope")
        require(ape_tool_cached.get("architectural_comparison",{}).get("status")=="matched"
                and ape_tool_cached.get("result",{}).get("full_final_memory_matches_spike_reconstructed_state") is True
                and ape_tool_cached.get("result",{}).get("line_requests")==ape_tool_cached.get("result",{}).get("line_completions")>0,
                "Tree-sitter cache integration lacks exact trace, full-memory or drain evidence")
        require(ape_tool_cached.get("limits") and "warm-start" in ape_tool_cached["limits"][0].lower(),
                "Tree-sitter integration does not disclose its warm-start profile")
        ape_tool_cached_run_gate=(REPO/ape_tool_cached.get("gate_path","")).resolve()
        canonical_gate = json.loads(ape_tool_cached_run_gate.read_text()) if ape_tool_cached_run_gate.is_file() else {}
        canonical_gate.pop("gate_path",None); canonical_gate.pop("gate_sha256",None)
        canonical_gate_sha = hashlib.sha256((json.dumps(canonical_gate,indent=2)+"\n").encode()).hexdigest()
        require(ape_tool_cached_run_gate.is_relative_to(HW/"build") and ape_tool_cached_run_gate.is_file()
                and ape_tool_cached.get("gate_sha256") in (sha(ape_tool_cached_run_gate),canonical_gate_sha),
                "Tree-sitter integration report refers to a missing or changed source-bound gate")
        tool_gate=json.loads(ape_tool_cached_run_gate.read_text())
        require(tool_gate.get("status")=="passed_cached_tool"
                and tool_gate.get("architectural_comparison")==ape_tool_cached.get("architectural_comparison"),
                "Persistent Tree-sitter evidence differs from its source-bound gate")
        validate_tree_tool_source_identity(ape_tool_cached.get("source_sha256",{}))
        check_hashes(REPO,ape_tool_cached.get("reference_source_sha256",{}))
        check_hashes(REPO,ape_tool_cached.get("input_sha256",{}))
        for name,digest in ape_tool_cached.get("generated_rtl_sha256",{}).items():
            artifact=(ape_tool_cached_run_gate.parent/name).resolve()
            require(artifact.is_relative_to(ape_tool_cached_run_gate.parent.resolve())
                    and artifact.is_file() and sha(artifact)==digest,
                    "Changed/missing Tree-sitter generated RTL: "+name)
        ape_tool_cached_run_gates.append(ape_tool_cached_run_gate)
    ape_heap_run_gates = []
    for ape_heap_path, ape_heap in zip(ape_heap_paths, ape_heap_reports):
        require(ape_heap.get("status") == "passed_actual_APE_heap_exhaustion"
                and ape_heap.get("issue") == 5 and ape_heap.get("S04_complete") is False
                and ape_heap.get("claim_class") == "actual_Tree_sitter_heap_exhaustion_on_APE_LSQ_I_D_L1_RTL",
                "APE heap-exhaustion evidence has wrong status or scope")
        require(ape_heap.get("full_final_memory_matches_spike") is True
                and ape_heap.get("architectural_comparison", {}).get("status") == "matched"
                and ape_heap.get("actual_result", {}).get("line_requests") == ape_heap.get("actual_result", {}).get("line_completions") > 0
                and ape_heap.get("spike_reference", {}).get("result", {}).get("status") == 2,
                "APE heap-exhaustion evidence lacks exact OOM, memory, trace, or drain checks")
        require(ape_heap.get("source_sha256") == ape_heap.get("source_sha256_after"),
                "APE heap-exhaustion sources changed during simulation")
        check_hashes(HW, ape_heap.get("source_sha256", {}))
        check_hashes(REPO, ape_heap.get("target_source_sha256", {}))
        check_hashes(REPO, ape_heap.get("reference_input_sha256", {}))
        check_hashes(REPO, ape_heap.get("derived_input_sha256", {}))
        ape_heap_run_gate = (REPO / ape_heap.get("gate_path", "")).resolve()
        require(ape_heap_run_gate.is_relative_to(HW / "build") and ape_heap_run_gate.is_file(),
                "APE heap-exhaustion source-bound run gate is missing")
        run_gate = json.loads(ape_heap_run_gate.read_text())
        require(run_gate.get("status") == "passed_actual_APE_heap_exhaustion"
                and run_gate.get("actual_result") == ape_heap.get("actual_result")
                and run_gate.get("full_final_memory_matches_spike") is True,
                "Persistent APE heap-exhaustion report differs from its source-bound run gate")
        check_hashes(ape_heap_run_gate.parent, ape_heap.get("generated_rtl_sha256", {}))
        ape_heap_run_gates.append(ape_heap_run_gate)
    if ppe:
        require(args.instructions, "Combined PPE checkpoint requires the APE I/D regression")
        validate_ppe(ppe)
        validate_ppe_device(ppe.get("device_memory", {}))
        if "atomic_add" in ppe:
            atomic = ppe["atomic_add"]
            require(atomic.get("status") == "passed" and atomic.get("atomic_requests") == 3
                    and atomic.get("prior_values") == [10, 11, 13]
                    and atomic.get("backing_after_fence") == "16",
                    "PPE atomic RTL result missing from source-bound gate")
        poison = l1.get("poison_result", {})
        require(poison.get("status") == "passed" and poison.get("requests") == 12 and poison.get("faults") == 6
                and poison.get("failed_writes") == 1, "Missing word-poison regression")
    if ownership:
        require(args.instructions and ppe and ppe.get("instruction_cache", False),
                "Ownership checkpoint requires the full current APE/PPE I/D regression")
        system = ownership.get("system_result", {})
        controller = ownership.get("result", {})
        require(ownership.get("status") == "passed_integration" and ownership.get("S04_complete") is False,
                "Wrong ownership gate status/scope")
        require(ownership.get("source_sha256") == ownership.get("source_sha256_after"),
                "Ownership gate inputs changed during verification")
        check_hashes(HW, ownership.get("source_sha256", {}))
        require(ownership.get("ppe_application_gate_sha256") == sha(ppe_path),
                "Integrated PPE application is not bound to the selected PPE I/D-L1 gate")
        check_hashes(ppe_path.parent, ownership.get("ppe_application_input_sha256", {}))
        race_path = ownership_path.parent / "dual-engine/launch-race.json"
        race = json.loads(race_path.read_text()) if race_path.is_file() else {}
        require(race.get("simultaneous_launch_presentations") == 1
                and race.get("ape_nonowner_stall_cycles", 0) > 0
                and race.get("ppe_nonowner_stall_cycles", 0) > 0
                and race.get("pending_ape_accepted_after_handoff") is True
                and race.get("pending_ppe_accepted_after_handoff") is True,
                "Missing ready/valid owner-gated APE/PPE launch witnesses")
        require(controller.get("status") == "passed" and controller.get("handoffs") == 2
                and controller.get("failed_handoffs") == 1 and controller.get("rejected") == 2,
                "Missing controller handoff/failure/stale-response witnesses")
        ppe_gate_path = HW / ownership.get("ppe_application_gate", "")
        ppe_memory = ppe_gate_path.parent / "cached/delimiter_256_g0/memory.bin"
        expected_reset_word = int.from_bytes(ppe_memory.read_bytes()[0x300:0x308], "little") if ppe_memory.is_file() else None
        require(system.get("status") == "passed" and system.get("ape_halts") == 5
                and system.get("ppe_completions") == 1 and system.get("ape_rd3_values", [])[:4] == [42, 48, 48, 51]
                and system.get("ape_atomic_old_values") == [48]
                and system.get("ppe_atomic_final_value") == "48"
                and system.get("final_shared_value") == "51"
                and system.get("line_requests") == system.get("line_completions") >= 11
                and system.get("max_lower_outstanding", 0) >= 4
                and system.get("response_reorders", 0) >= 1
                and system.get("lower_backpressure_cycles", 0) >= 1
                and system.get("handoffs_requested_with_live_lines") == 1
                and system.get("handoff_drain_wait_cycles", 0) >= 1
                and system.get("ape_conflict_load_addresses") == [1024, 1536, 2048, 2560]
                and system.get("ape_conflict_line_refills") == [1024, 1536, 2048, 2560]
                and system.get("ape_conflict_set_index") == 0
                and system.get("ape_byte_alias_verified") is True
                and system.get("ape_partial_storebacking_word") == "10752"
                and system.get("ownership_handoffs") == 4
                and system.get("ppe_application_faults") == 1
                and system.get("ppe_application_fault_write_attempts", 0) > 0
                and system.get("ppe_application_fault_output_unchanged") is True
                and system.get("ppe_application_groups") == 32
                and system.get("ppe_application_architectural_accesses") == 608
                and system.get("ppe_application_line_requests", 0) > 0
                and system.get("ppe_application_matches_independent_memory_oracle") is True
                and system.get("ppe_application_output_sha256") == ppe.get("delimiter_application", {}).get("output_sha256")
                and system.get("quiescent_system_resets") == 2
                and system.get("value_after_quiescent_reset") == "51"
                and system.get("ppe_application_reset_readback_matches") is True
                and expected_reset_word is not None
                and system.get("ppe_application_reset_readback_value") == str(expected_reset_word)
                and system.get("ppe_device_requests") == system.get("ppe_device_completions") == 2
                and system.get("ppe_device_reads") == system.get("ppe_device_writes") == 1
                and system.get("ppe_device_backpressure_cycles", 0) >= 1
                and system.get("ppe_clean_before_device") is True
                and system.get("ppe_device_register_value") == "102",
                "Missing dual-engine ownership/shared-data visibility witnesses")
    if ownership_formal:
        require(ownership is not None and ownership_formal.get("status") == "passed_bounded_safety"
                and ownership_formal.get("S04_complete") is False,
                "Formal ownership proof requires its passing integration gate")
        require(ownership_formal.get("integration_gate_sha256") == sha(ownership_path),
                "Formal proof refers to another ownership gate")
        if ownership_formal.get("claim_class") == "bounded_ownership_line_ledger_safety_under_ready_valid_assumptions":
            assumptions = ownership_formal.get("assumptions", [])
            require(any("lower responses may be delayed, reordered, stale, or malformed" in x for x in assumptions)
                    and any("Handoffs and cache-maintenance responses are disabled" in x for x in assumptions),
                    "Line-ledger formal evidence must bind active response-traffic assumptions and state its handoff exclusion")
            witnesses = ownership_formal.get("reachability", {}).get("line_traffic_witnesses", {})
            require({"accepted_request", "multiple_outstanding", "completed_reply", "rejected_stale_reply"} <= set(witnesses)
                    and all(witnesses[k].get("status") == "reachable_within_bound"
                            for k in ("accepted_request", "multiple_outstanding", "completed_reply", "rejected_stale_reply")),
                    "Line-ledger formal run lacks non-vacuous request, overlap, completion, and stale-reply witnesses")
    if design_points:
        require(ppe is not None and design_points.get("status") == "matched_workload_rtl_design_point_comparison"
                and design_points.get("S04_complete") is False
                and design_points.get("report_generator_sha256") == sha(REPO / design_points["report_generator"]),
                "Wrong or stale PPE design-point report")
        rows = design_points.get("design_points", [])
        require([(r["configuration"]["instruction_cache"], r["configuration"]["sets"],
                  r["configuration"]["mshrs"]) for r in rows]
                == [(False, 8, 2), (False, 16, 4), (False, 32, 8),
                    (True, 8, 2), (True, 16, 4), (True, 32, 8)],
                "Incomplete PPE D-L1/I-D-L1 design-point matrix")
        for row in rows:
            gate_path = REPO / row["gate"]
            require(gate_path.is_file() and sha(gate_path) == row["gate_sha256"],
                    "PPE design-point gate changed")
        require(len({r["gate"] for r in rows}) == 6
                and all(r["metrics"]["exact_architectural_comparisons"] == 316 for r in rows)
                and all(r["metrics"]["max_mshrs"] == r["configuration"]["mshrs"] for r in rows),
                "Incomplete PPE design-point evidence")
        require(ownership_formal.get("bounded_global_steps") in (8, 12, 16)
                and ownership_formal.get("assertion_checks_per_step", 0) >= 1,
                "Formal proof has no bounded assertion result")
    if l1_formal:
        require(l1_formal.get("status") == "passed_bounded_safety" and l1_formal.get("S04_complete") is False
                and l1_formal.get("component_gate_sha256") == sha(l1_path),
                "L1 formal proof must refer to the selected passing L1 component gate")
        require(l1_formal.get("configuration", {}).get("mshrs") == 4
                and l1_formal.get("bounded_global_steps") in (4, 6, 8)
                and l1_formal.get("assertion_checks_per_step", 0) >= 1,
                "L1 formal proof has no bounded assertion result")
        witnesses = l1_formal.get("reachability", {})
        require({"lower_line_miss", "multiple_outstanding", "refill", "stale_reply_rejection"} <= set(witnesses)
                and all(witnesses[k].get("status") == "reachable_within_bound"
                        for k in ("lower_line_miss", "multiple_outstanding", "refill", "stale_reply_rejection")),
                "L1 formal proof lacks non-vacuous miss, concurrency, refill and stale-response witnesses")
    if ape_lsq_formal:
        require(ape_lsq_formal.get("status") == "passed_bounded_safety"
                and ape_lsq_formal.get("S04_complete") is False
                and ape_lsq_formal.get("configuration", {}).get("leases") == 8
                and ape_lsq_formal.get("configuration", {}).get("rob_entries") == 8
                and ape_lsq_formal.get("assertion_checks_per_step", 0) >= 1,
                "APE LSQ formal proof has wrong scope or no bounded assertion result")
        witnesses = ape_lsq_formal.get("reachability", {})
        require({"lease_allocation", "multiple_outstanding_leases", "dependence_replay"} <= set(witnesses)
                and all(witnesses[k].get("status") == "reachable_within_bound"
                        for k in ("lease_allocation", "multiple_outstanding_leases", "dependence_replay")),
                "APE LSQ formal proof lacks lease, concurrency and replay reachability witnesses")
    source_manifest = {}
    gates = [(HW, l1, "evidence_sha256"), (REPO, ape, "artifacts_sha256")]
    if ppe: gates.append((HW, ppe, "evidence_sha256"))
    if ownership:
        gates.append((HW, ownership, "generated_rtl_sha256"))
    if ownership_formal:
        require(ownership_formal["source_sha256"] == ownership_formal["source_sha256_after"],
                "Formal inputs changed during proof")
        check_hashes(HW, ownership_formal["source_sha256"])
        check_hashes(HW, ownership_formal["artifacts_sha256"])
        source_manifest.update({str((HW / name).relative_to(REPO)): digest
                                for name, digest in ownership_formal["source_sha256"].items()})
    if l1_formal:
        require(l1_formal["source_sha256"] == l1_formal["source_sha256_after"],
                "L1 formal inputs changed during proof")
        check_hashes(HW, l1_formal["source_sha256"])
        check_hashes(HW, l1_formal["artifacts_sha256"])
        require(sha(HW / l1_formal["generated_rtl"]) == l1_formal["generated_rtl_sha256"],
                "Generated RTL differs from the L1 formal record")
        source_manifest.update({str((HW / name).relative_to(REPO)): digest
                                for name, digest in l1_formal["source_sha256"].items()})
    if ape_lsq_formal:
        require(ape_lsq_formal["source_sha256"] == ape_lsq_formal["source_sha256_after"],
                "APE LSQ formal inputs changed during proof")
        check_hashes(HW, ape_lsq_formal["source_sha256"])
        check_hashes(HW, ape_lsq_formal["artifacts_sha256"])
        require(sha(HW / ape_lsq_formal["generated_rtl"]) == ape_lsq_formal["generated_rtl_sha256"],
                "Generated APE LSQ RTL differs from its formal record")
        source_manifest.update({str((HW / name).relative_to(REPO)): digest
                                for name, digest in ape_lsq_formal["source_sha256"].items()})
    for root, gate, artifacts in gates:
        require(gate["source_sha256"] == gate["source_sha256_after"], "Inputs changed during verification")
        check_hashes(root, gate["source_sha256"])
        if gate is ownership:
            check_hashes(ownership_path.parent, gate[artifacts])
            check_hashes(ownership_path.parent, gate["simulation_evidence_sha256"])
            require(sha(ownership_path.parent / "run.log") == gate["run_log_sha256"],
                    "Ownership simulation log changed")
        else:
            check_hashes(root, gate[artifacts])
        for name, digest in gate["source_sha256"].items():
            key = str((root / name).relative_to(REPO))
            require(key not in source_manifest or source_manifest[key] == digest, "Contradictory source identities")
            source_manifest[key] = digest
    if ppe:
        input_root = HW if any(name.startswith("build/s04/") for name in ppe["input_sha256"]) else ppe_path.parent
        check_hashes(input_root, ppe["input_sha256"])
        archive = ppe_path.parent / "sources.tar"
        require(sha(archive) == ppe["source_archive_sha256"], "Changed PPE source archive")
        with tarfile.open(archive) as saved:
            members = saved.getmembers()
            require(len(members) == len(ppe["source_sha256"]) and all(m.isfile() for m in members), "Wrong source archive members")
            archived = {m.name: hashlib.sha256(saved.extractfile(m).read()).hexdigest() for m in members}
        require(archived == ppe["source_sha256"], "PPE archive differs from tested sources")
        for mode, comparisons in ppe["comparisons"].items():
            for row in comparisons:
                require(compare_ppe(ppe_path.parent / mode / row["case"], row["invocation"]) == row,
                        "PPE stored decision differs from complete RTL state/trace/memory comparison")
    check_hashes(REPO, ape["inputs_sha256"])
    # Recompute comparison decisions from the observed RTL and Spike traces.
    decisions = []
    for row in ape["comparisons"]:
        kind, name = row["suite"], row["name"]
        stem = name if kind in ("cached", "data-regression") else f"{name}-{row['invocation']}"
        prefix = ape_path.parent / kind / stem
        case = json.loads(prefix.with_suffix(".case.json").read_text())
        profile = ("fence_i_gap" if name == "p20" else "launch_alignment_gap" if name == "entry_alignment" else "shared") if kind in ("cached", "data-regression") else case_profile(case)
        result = compare(read_trace(prefix.with_suffix(".arch.jsonl")), read_trace(prefix.with_suffix(".spike.jsonl")), profile)
        require(all(row[key] == value for key, value in result.items()), "Stored comparison differs from actual traces")
        decisions.append(row)
    count, exact, differences = (228, 220, 8) if args.instructions else (170, 164, 6)
    require(len(decisions) == count and sum(r["status"] == "matched" for r in decisions) == exact
            and sum(r["status"] == "expected_profile_difference" for r in decisions) == differences, "Incomplete trace comparison")
    expected = {(kind, name, None) for kind in (["cached", "data-regression"] if args.instructions else ["cached"]) for name in NAMES}
    for kind in ("standard", "recovery"):
        suite = ape["legacy"][kind]
        require(suite["status"] == "passed" and suite["runs"] == (100 if kind == "standard" else 12), "Missing legacy regression")
        expected |= {(kind, r["name"], r["invocation"]) for r in suite["results"]}
    require(len(expected) == count and {(r["suite"], r["name"], r.get("invocation")) for r in decisions} == expected, "Wrong comparison matrix")
    rows = ape["cached"]["tests"]
    docs = [HW / "spec/S04-MEMORY-ARCHITECTURE.md", HW / "spec/PPE-S04-ATOMIC-EXTENSION.md",
            REPO / "workloads/s04/README.md"]
    if design_points_path: docs.append(design_points_path)
    if ape_trace_path: docs.append(ape_trace_path)
    if ape_cached_path: docs.append(ape_cached_path)
    docs.extend(ape_tool_cached_paths)
    docs.extend(ape_heap_paths)
    if args.instructions: docs.append(REPO / "workloads/s04/INSTRUCTION-PROGRESS.md")
    if ppe: docs.append(REPO / "workloads/s04/PPE-DATA-PROGRESS.md")
    if ppe and ppe.get("instruction_cache", False): docs.append(REPO / "workloads/s04/PPE-INSTRUCTION-PROGRESS.md")
    output = {"schema": 1, "issue": 5, "stage": "S04", "S04_complete": False,
              "status": "verified_partial_integration", "created_utc": datetime.now(timezone.utc).isoformat(),
              "claim_class": ("APE_PPE_bilateral_ownership_handoff_increment_only" if ownership else
                              "L1_and_APE_instruction_data_hierarchy_increment_only" if args.instructions
                              else "L1_component_and_APE_data_hierarchy_increment_only"),
              "source_sha256": source_manifest,
              "record_source_sha256": {str(Path(__file__).relative_to(REPO)): sha(Path(__file__))},
              "document_sha256": {str(p.relative_to(REPO)): sha(p) for p in docs},
              "gate_sha256": {str(p.relative_to(REPO)): sha(p) for p in [l1_path, ape_path] + ([ppe_path] if ppe else []) + ([ownership_path] if ownership else []) + ([ownership_formal_path] if ownership_formal else []) + ([l1_formal_path] if l1_formal else []) + ([ape_lsq_formal_path] if ape_lsq_formal else []) + ([design_points_path] if design_points_path else []) + ([ape_trace_run_gate] if ape_trace_run_gate else []) + ([ape_cached_run_gate] if ape_cached_run_gate else []) + ape_tool_cached_run_gates + ape_heap_run_gates},
              "l1_configurations": l1["result"]["configurations"],
              "ape_profile": ape["cached"]["profile"], "ape_cache_runs": len(rows),
              "ape_cache_retirements": sum(r["retired"] for r in rows),
              "ape_directed_witnesses": [r for r in rows if r["name"] in {
                  "parallel_loads", "queue_full", "forward_bytes", "youngest_store_bytes", "unknown_store_address",
                  "fence", "wrong_path_read_drain", "older_fault_after_younger_read"}],
              "ape_combined_replay_pressure": ape.get("replay_pressure", {}).get("tests", []),
              "spike_comparisons": {kind: {"runs": sum(r["suite"] == kind for r in decisions),
                  "exact": sum(r["suite"] == kind and r["status"] == "matched" for r in decisions),
                  "profile_differences": sum(r["suite"] == kind and r["status"] == "expected_profile_difference" for r in decisions)}
                  for kind in (["cached", "data-regression", "standard", "recovery"] if args.instructions
                               else ["cached", "standard", "recovery"])},
              "open_original_acceptance": ["AC1", "AC2", "AC3", "AC4", "AC5"],
              "limits": ape["limits"] + [
                  "Original issue #5 work packages and acceptance criteria remain open"]}
    if not ownership_formal and not l1_formal and not ape_lsq_formal:
        output["limits"].append("No bounded formal proof included in this increment")
    if ownership_formal:
        output["limits"].append(
            "Bounded ownership-state safety only; line traffic, queues and MSHR protocol are not covered by this proof")
    if l1_formal:
        output["limits"].append(
            "Bounded generated-L1 internal assertions only; no functional refinement, unbounded proof or APE/PPE queue proof")
    if ape_lsq_formal:
        output["limits"].append(
            "Bounded APE LSQ internal assertions under fixed ROB row-slot identity; no memory refinement, unbounded proof or full-core composition proof")
    if args.instructions:
        output["instruction_publication"] = ape["instruction_publication"]
        output["ape_device_memory"] = ape["device_memory"]
        if "atomic_add" in ape:
            output["ape_atomic_add"] = ape["atomic_add"]
        output["instruction_cache"] = {"external_line_reads": sum(r["instruction_reads"] for r in rows),
                                       "hits": sum(r["instruction_hits"] for r in rows),
                                       "fetch_word_requests": sum(r["fetch_requests"] for r in rows),
                                       "max_shared_outstanding": max(r["max_fabric_outstanding"] for r in rows)}
    if ppe:
        output["claim_class"] = ("APE_PPE_bilateral_ownership_hierarchy_increment_only" if ownership else
                                 "APE_and_PPE_I_D_hierarchy_increment_only" if ppe.get("instruction_cache", False) else
                                 "APE_I_D_and_PPE_D_hierarchy_increment_only")
        output["l1_word_poison"] = l1["poison_result"]
        output["ppe_comparisons"] = {mode: {"runs": len(compared),
            "ISA_oracle_exact": sum(r["kind"] == 0 for r in compared),
            "decode_launch_protocol_exact": sum(r["kind"] in (1,2) for r in compared),
            "clock_protocol_exact": sum(r["kind"] in (3,4) for r in compared)}
            for mode, compared in ppe["comparisons"].items()}
        output["ppe_diagnostics"] = ppe["diagnostics"]["cached"]
        output["ppe_i_d_application_workloads"] = {
            "delimiter_prefilter": ppe.get("delimiter_application", {}),
            "vector_residual_bias_relu": ppe.get("ai_vector_application", {}),
            "claim_class": "actual_PPE_I_D_L1_application_RTL_with_independent_full_memory_oracles",
            "design_point_configurations": [row["configuration"] for row in design_points["design_points"]
                if row["configuration"]["instruction_cache"]] if design_points else [],
            "design_point_metrics": [row["metrics"].get("ai_vector_application") for row in design_points["design_points"]
                if row["configuration"]["instruction_cache"]] if design_points else []}
        output["ppe_device_memory"] = ppe["device_memory"]
        if "atomic_add" in ppe: output["ppe_atomic_add"] = ppe["atomic_add"]
        if ppe.get("instruction_cache", False): output["ppe_instruction_publication"] = ppe["instruction_publication"]
        output["limits"] += ppe["limits"]
    if design_points:
        output["design_point_study"] = {"claim_class": design_points["claim_class"],
            "input_artifact_count": design_points["input_artifact_count"],
            "normalized_input_manifest_sha256": design_points["normalized_input_manifest_sha256"],
            "design_points": [{"configuration": row["configuration"], "gate": row["gate"],
                "gate_sha256": row["gate_sha256"], "metrics": row["metrics"]}
                for row in design_points["design_points"]]}
    if ape_trace:
        output["ape_application_trace_design_points"] = {
            "claim_class": ape_trace["claim_class"],
            "build_gate_path": ape_trace["build_gate_path"],
            "build_gate_sha256": ape_trace["build_gate_sha256"],
            "application_gate_sha256": ape_trace["application_gate_sha256"],
            "input_sha256": ape_trace["input_sha256"],
            "design_points": [{k: row[k] for k in ("sets", "line_bytes", "mshrs", "application_memory_events",
                "cycles", "hits", "misses", "writebacks", "refills", "lower_reads", "lower_writebacks",
                "lower_backpressure_cycles", "generated_rtl_sha256", "final_memory_matches_application")}
                for row in ape_trace["runs"]],
            "service_model": ape_trace["service_model"]}
        output["limits"].append("APE cache-point study replays one actual application RTL memory trace through isolated L1 RTL; it is sequential, uses behavioral line service, and is not cache-integrated application execution or measured DRAM bandwidth")
    if ape_cached:
        output["ape_integrated_application_design_points"] = {
            "claim_class": ape_cached["claim_class"],
            "build_gate_path": ape_cached["build_gate_path"],
            "build_gate_sha256": ape_cached["build_gate_sha256"],
            "application_gate_sha256": ape_cached["application_gate_sha256"],
            "input_sha256": ape_cached["input_sha256"],
            "design_points": [{k: row[k] for k in ("mode", "sets", "mshrs", "cycles", "line_requests",
                "line_completions", "max_cache_outstanding", "response_reorders",
                "max_fabric_outstanding",
                "instruction_cache_misses", "fetch_requests",
                "architectural_trace_matches_direct_APE", "final_memory_matches_direct_APE",
                "generated_rtl_sha256")} for row in ape_cached["runs"]],
            "external_service_model": ape_cached["external_service_model"]}
        applications = sorted({row["application"] for row in ape_cached["runs"]})
        output["limits"].append(
            f"Integrated APE application evidence covers {len(applications)} named workloads through D-L1 and I/D-L1 at the matched 16-set/4-MSHR point; "
            "repo_source_edit is additionally exercised at six cache points. PPE delimiter-prefilter and vector residual+bias+ReLU applications are separately checked through I/D-L1. Lower-line service is behavioral, not calibrated DRAM bandwidth")
    if ape_tool_cached_reports:
        resource_observations = [target_resource_observation(report) for report in ape_tool_cached_reports]
        output["ape_integrated_upstream_tools"] = [{
            "claim_class": ape_tool_cached["claim_class"],
            "application_dir": ape_tool_cached["application_dir"],
            "case": ape_tool_cached["case"],
            "sets": ape_tool_cached["sets"], "mshrs": ape_tool_cached["mshrs"],
            "architectural_comparison": ape_tool_cached["architectural_comparison"],
            "cycles": ape_tool_cached["result"]["cycles"],
            "retired": ape_tool_cached["result"]["retired"],
            "line_requests": ape_tool_cached["result"]["line_requests"],
            "line_completions": ape_tool_cached["result"]["line_completions"],
            "full_final_memory_sha256": ape_tool_cached["final_memory_sha256"],
            "resource_observation": resource,
            "generated_rtl_sha256": ape_tool_cached["generated_rtl_sha256"],
            "limits": ape_tool_cached["limits"]}
            for ape_tool_cached, resource in zip(ape_tool_cached_reports, resource_observations)]
        output["selected_target_resource_observations"] = {
            "maximum_ape_observed_stack_bytes": max(row["ape_observed_stack_bytes"] for row in resource_observations),
            "maximum_spike_observed_stack_bytes": max(row["spike_observed_stack_bytes"] for row in resource_observations),
            "maximum_ape_peak_requested_heap_bytes": max(row["ape_peak_requested_heap_bytes"] for row in resource_observations),
            "maximum_ape_heap_bytes_granted": max(row["ape_heap_bytes_granted"] for row in resource_observations),
            "cases": resource_observations,
            "claim_class": "six_selected_real_target_workload_observations_only_not_worst_case_or_exhaustion_proof"}
        output["limits"].append(
            f"{len(ape_tool_cached_reports)} Tree-sitter cases run through APE I/D-L1 from Spike-derived parser-entry warm-start images; cold startup is separately validated by direct APE RTL, and the external memory service is behavioral")
    if ape_heap_reports:
        output["ape_heap_exhaustion"] = [{
            "claim_class": ape_heap["claim_class"],
            "case": ape_heap["case"],
            "heap_limit_bytes": ape_heap["heap_limit_bytes"],
            "spike_result": ape_heap["spike_reference"]["result"],
            "ape_result": ape_heap["actual_result"],
            "architectural_comparison": ape_heap["architectural_comparison"],
            "full_final_memory_matches_spike": ape_heap["full_final_memory_matches_spike"],
            "generated_rtl_sha256": ape_heap["generated_rtl_sha256"],
            "limits": ape_heap["limits"]}
            for ape_heap in ape_heap_reports]
        require(len({row["case"] for row in output["ape_heap_exhaustion"]}) == len(ape_heap_reports),
                "Duplicate APE heap-exhaustion workload case")
        output["limits"].append(
            f"{len(ape_heap_reports)} selected Tree-sitter fixtures return clean ENOMEM on actual APE RTL at a deliberately constrained heap; this is workload-matrix evidence, not a formal application-wide exhaustion bound")
    if ownership:
        launch_race = json.loads((ownership_path.parent / "dual-engine/launch-race.json").read_text())
        output["ownership_integration"] = {"controller": ownership["result"],
            "dual_engine_system": ownership["system_result"],
            "ready_valid_launch_admission": launch_race,
            "source_sha256": ownership["source_sha256"],
            "generated_rtl_sha256": ownership["generated_rtl_sha256"],
            "simulation_evidence_sha256": ownership["simulation_evidence_sha256"],
            "run_log_sha256": ownership["run_log_sha256"],
            "claim_class": ownership["claim_class"]}
        output["limits"] += [
            "Exclusive bilateral clean/invalidate ownership is tested only on the selected dual-engine program; sequential atomic visibility across ownership epochs is checked, but concurrent cross-engine arbitration and general coherence are not claimed",
            "Clean-only fences cover ordinary cacheable-RAM writeback; each engine's device path and the shared PPE device path are checked with behavioral services; no concurrent cross-engine I/O is allowed by the ownership model",
            "Full LSQ, per-cache MSHR and integrated four-transaction fabric occupancy are exercised; bounded formal proofs remain per-module and are not an unbounded full-system proof",
            "Six selected workload variants exercise clean heap exhaustion; stack/heap measurements are selected-run observations, not worst-case resource bounds",
            "Target memory-stall PMU correlation where hardware is available remains open; behavioral line-service timing is not a hardware PMU measurement"]
        if not design_points:
            output["limits"].append("Matched-real-workload cache/memory design-point study remains open")
        output["limits"] = [limit for limit in output["limits"]
                            if not limit.startswith("Exclusive whole-line ownership is a caller obligation")
                            and not (ppe and limit.startswith("No PPE/ownership-controller/device/atomic integration yet"))
                            and not (ownership and limit.startswith("Combined APE/PPE exposes but does not implement PPE device transactions"))]
    if ownership_formal:
        output["ownership_formal"] = {"claim_class": ownership_formal["claim_class"],
            "bounded_global_steps": ownership_formal["bounded_global_steps"],
            "assertion_checks_per_step": ownership_formal["assertion_checks_per_step"],
            "assumptions": ownership_formal["assumptions"],
            "reachability": ownership_formal["reachability"],
            "artifacts_sha256": ownership_formal["artifacts_sha256"]}
    if l1_formal:
        output["l1_formal"] = {"claim_class": l1_formal["claim_class"],
            "configuration": l1_formal["configuration"],
            "bounded_global_steps": l1_formal["bounded_global_steps"],
            "assertion_checks_per_step": l1_formal["assertion_checks_per_step"],
            "assumptions": l1_formal["assumptions"], "scope": l1_formal["scope"],
            "generated_rtl_sha256": l1_formal["generated_rtl_sha256"],
            "artifacts_sha256": l1_formal["artifacts_sha256"]}
    if ape_lsq_formal:
        output["ape_lsq_formal"] = {"claim_class": ape_lsq_formal["claim_class"],
            "configuration": ape_lsq_formal["configuration"],
            "bounded_global_steps": ape_lsq_formal["bounded_global_steps"],
            "assertion_checks_per_step": ape_lsq_formal["assertion_checks_per_step"],
            "assumptions": ape_lsq_formal["assumptions"], "scope": ape_lsq_formal["scope"],
            "generated_rtl_sha256": ape_lsq_formal["generated_rtl_sha256"],
            "artifacts_sha256": ape_lsq_formal["artifacts_sha256"]}
    if args.acceptance_complete:
        expected_tool_cases = {"empty-cold_old", "empty-incremental", "scalars-cold_old",
                               "scalars-incremental", "unicode-cold_old", "unicode-incremental"}
        require(args.instructions and ppe and ownership and ownership_formal and l1_formal and ape_lsq_formal
                and design_points and ape_trace and ape_cached and len(ape_tool_cached_reports) == 6
                and len(ape_heap_reports) == 6,
                "AC1-AC5 promotion requires integrated APE/PPE, formal, real-workload, design-point and six-case heap evidence")
        require({row["case"] for row in ape_tool_cached_reports} == expected_tool_cases
                and {row["case"] for row in ape_heap_reports} == expected_tool_cases,
                "AC1-AC5 promotion requires matching six-case valid and heap-exhaustion workload matrices")
        require(len(ppe.get("comparisons", {}).get("cached", [])) == 316
                and len(ppe.get("comparisons", {}).get("data_regression", [])) == 316
                and len(ppe.get("comparisons", {}).get("legacy", [])) == 288
                and ppe.get("ai_vector_application", {}).get("output_matches_oracle") is True
                and ppe.get("delimiter_application", {}).get("output_matches_oracle") is True,
                "AC1/AC2 promotion requires exact PPE oracle matrix and both application outputs")
        require(ownership.get("system_result", {}).get("max_lower_outstanding") == 4
                and ownership.get("system_result", {}).get("line_requests")
                    == ownership.get("system_result", {}).get("line_completions")
                and all(row["metrics"]["max_mshrs"] == row["configuration"]["mshrs"]
                        for row in design_points["design_points"]),
                "AC3 promotion requires full integrated occupancy, drained traffic, and every PPE MSHR point")
        require(ownership_formal.get("claim_class")
                    == "bounded_ownership_line_ledger_safety_under_ready_valid_assumptions"
                and l1_formal.get("assertion_checks_per_step", 0) > 0
                and ape_lsq_formal.get("assertion_checks_per_step", 0) > 0
                and ownership_formal.get("assertion_checks_per_step", 0) > 0,
                "AC4 promotion requires nonempty bounded proofs for L1, APE LSQ and shared line protocol")
        require(any("behavioral" in text.lower() or "modeled" in text.lower()
                    for text in ppe.get("limits", []))
                and any("not measured" in text.lower() or "not calibrated" in text.lower()
                        for text in design_points.get("limits", [])),
                "AC5 promotion requires explicit behavioral-service versus physical-memory boundaries")
        output["acceptance_audit"] = {
            "AC1": {"status": "passed", "evidence": [str(ppe_path.relative_to(REPO)),
                str(ownership_path.relative_to(REPO)), str(ape_cached_path.relative_to(REPO))]},
            "AC2": {"status": "passed", "evidence": [str(ape_path.relative_to(REPO)),
                str(ppe_path.relative_to(REPO)), str(ownership_path.relative_to(REPO))]},
            "AC3": {"status": "passed", "evidence": [str(l1_path.relative_to(REPO)),
                str(ape_path.relative_to(REPO)), str(ppe_path.relative_to(REPO)),
                str(ownership_path.relative_to(REPO))]},
            "AC4": {"status": "passed", "evidence": [str(l1_formal_path.relative_to(REPO)),
                str(ape_lsq_formal_path.relative_to(REPO)), str(ownership_formal_path.relative_to(REPO))]},
            "AC5": {"status": "passed", "evidence": [str(design_points_path.relative_to(REPO)),
                str((HW / "spec/S04-MEMORY-ARCHITECTURE.md").relative_to(REPO))]},
            "limits": ["External memory timing is behavioral and not measured HBM/LPDDR performance",
                "Formal results are bounded and scoped to the proved RTL invariants; they are not unbounded full-chip proof",
                "The implemented ownership contract is exclusive clean/invalidate handoff, not general hardware coherence"]}
        output["S04_complete"] = True
        output["status"] = "verified_complete"
        output["open_original_acceptance"] = []
        output["limits"] = [limit for limit in output["limits"]
                            if limit != "Original issue #5 work packages and acceptance criteria remain open"]
    tag = ("PPE-INSTRUCTION" if ppe.get("instruction_cache", False) else "PPE-DATA") if ppe else "INSTRUCTION" if args.instructions else "MEMORY"
    destination = args.output or REPO / f"workloads/evidence/S04-{tag}-INCREMENT.json"
    destination.write_text(json.dumps(output, indent=2) + "\n")
    print(f"Verified {'complete' if args.acceptance_complete else 'partial'} S04 checkpoint: {destination}")


if __name__ == "__main__":
    main()
