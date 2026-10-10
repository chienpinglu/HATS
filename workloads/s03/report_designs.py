#!/usr/bin/env python3
"""Render measured S03 design evidence; does not choose defaults or close S03."""
import argparse
import json
from pathlib import Path

from design_evidence import POINTS, CASES, SERVICE_BASES, validate_study, validate_technology
from multi_evidence import REPO, check_hashes, require, sha


def render(study, technologies):
    measured = validate_study(study)
    physical = validate_technology(technologies)
    rows = study["results"]
    phys = {r["point"][0]: r for r in physical}
    metadata = {r["point"][0]: r["statistics"]["design"]["num_cells_by_type"].get("$scopeinfo", 0)
                for report in technologies for r in report["results"]}
    by_point = {p[0]: [r for r in rows if r["point"] == p[0]] for p in POINTS}
    lines = ["# S03 APE design-point measurements", "",
             "## Scope and comparison contract", "",
             "Nine actual APE RTL configurations execute the same three compiled programs: "
             "integer helper vectors, runtime self-tests and the upstream Tree-sitter JSON parser. "
             "The six program/input cases run under two memory-service profiles, for 108 RTL invocations. "
             "Complete retirement-state/memory-event digests and output images match the independent "
             "Spike reference before any cycle ratio is accepted.", "",
             "Each transaction receives an ordinal-indexed acceptance wait of 0–3 cycles and a response "
             "wait of either 2–9 or 16–23 cycles after acceptance. Compared designs have identical "
             "realized service and architectural work, not merely an equal cycle-dependent random seed. "
             "These are abstract service profiles, not an HBM/LPDDR or cache-latency model.", "",
             "Dispatch, writeback and retirement widths are one; memory admits one head-only request. "
             "Execution has two registered stages and two-bit completion generations. Four branch "
             "checkpoints are configured. ROB capacity also sizes the fused reservation rows: this is "
             "not a separately sized issue-queue comparison.", "",
             "## Configurations", "",
             "| Point | ROB / reservation rows | Physical registers | Issue lanes | Predictor |",
             "| --- | ---: | ---: | ---: | --- |"]
    for name, rob, prf, width, prediction, entries in POINTS:
        mode = f"bimodal, {entries} entries" if prediction == "bimodal" else "disabled"
        lines.append(f"| {name} | {rob} | {prf} | {width} | {mode} |")
    lines += ["", "## Simulated cycles and IPC", "",
              "The reference is `narrow` (ROB8 / P64 / one issue lane / bimodal16). "
              "Positive cycle change means slower. The geometric mean weights each of the twelve "
              "case/service combinations equally; it is not an agent-workload frequency estimate. "
              "IPC ranges are per invocation, not a clock-frequency or host-speedup measurement.", "",
              "| Point | Geometric-mean cycle change | Per-case cycle-change range | Simulated IPC range |",
              "| --- | ---: | ---: | ---: |"]
    for row in measured:
        name = row["point"][0]
        ratios = row["baseline_over_candidate_cycles_range"]
        change = 100 * (1 / row["equal_case_geometric_mean_cycle_ratio"] - 1)
        low, high = [100 * (1 / v - 1) for v in reversed(ratios)]
        ipc = [r["simulated_ipc"] for r in by_point[name]]
        lines.append(f"| {name} | {change:+.3f}% | {low:+.3f}% to {high:+.3f}% | {min(ipc):.4f}–{max(ipc):.4f} |")
    lines += ["", "### Actual width-one / width-two pairs", "",
              "Both lanes really issue work in the dual configuration; counts below are observed "
              "simultaneous-issue cycles. A larger issue count is not assumed to reduce total cycles.", "",
              "| Program / input | Response base | Narrow cycles | Dual cycles | Dual cycle change | Dual-issue cycles |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for workload, case in CASES:
        for base in SERVICE_BASES:
            a, b = [next(r for r in by_point[p] if (r["workload"], r["case"], r["response_base"]) == (workload, case, base))
                    for p in ("narrow", "dual")]
            x, y = a["metrics"]["cycles"], b["metrics"]["cycles"]
            lines.append(f"| {workload} / {case} | {base} | {x:,} | {y:,} | {100 * (y / x - 1):+.3f}% | {b['metrics']['dual_issue_cycles']:,} |")
    lines += ["", "## Observed resource pressure", "",
              "Totals cover the twelve invocations for each point, so larger inputs dominate them. "
              "Stall categories overlap; summing them does not partition execution time or prove a "
              "causal explanation for the cycle changes. Peak occupancy and minimum free count are "
              "extrema across these runs, not average utilization.", "",
              "| Point | Peak ROB occupancy | Minimum free PRF entries | Rename-stall cycles | ROB-stall cycles | Completion-stall cycles | Branch misses / branches |",
              "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for point in POINTS:
        name = point[0]
        m = [r["metrics"] for r in by_point[name]]
        total = lambda key: sum(r[key] for r in m)
        lines.append(f"| {name} | {max(r['peak_occupancy'] for r in m)} | {min(r['minimum_free_registers'] for r in m)} | "
                     f"{total('rename_stall_cycles'):,} | {total('rob_stall_cycles'):,} | {total('completion_stall_cycles'):,} | "
                     f"{total('branch_misses'):,} / {total('branches'):,} |")
    lines += ["", "## Early mapped area and combinational delay", "",
              "Every physical point uses the same Nangate45 typical research library, 1,000 ps mapping "
              "target, BUF_X1 combinational input driver and 5 fF output load. All storage is mapped to "
              "flip-flops/muxes, including the 1,024-word code store and physical registers; observation "
              "ports remain. The workload configurations use 65,536 code words. Their total areas "
              "must not be equated with this smaller physical-study memory.", "",
              "Mapped combinational logic passed a complete pre/post-mapping equivalence check with "
              "identical ordered inputs/outputs and no internal abstraction. Sequential processor "
              "correctness is covered separately by RTL/ISA and selected formal gates.", "",
              "| Point | Cell area (library units) | Change from narrow | Sequential-cell area | Netlist entries / metadata | Combinational boundary delay | Meets 1,000 ps mapping target |",
              "| --- | ---: | ---: | ---: | ---: | ---: | --- |"]
    baseline_area = phys["narrow"]["mapped_area_library_units"]
    for point in POINTS:
        name = point[0]; r = phys[name]
        lines.append(f"| {name} | {r['mapped_area_library_units']:,.3f} | {100 * (r['mapped_area_library_units'] / baseline_area - 1):+.3f}% | "
                     f"{r['sequential_area_library_units']:,.3f} | {r['mapped_cells']:,} / {metadata[name]} | {r['comb_boundary_delay_ps']:,.2f} ps | "
                     f"{'yes' if r['meets_comb_mapping_target'] else 'no'} |")
    lines += ["", "Netlist-entry totals include the separately shown Yosys `$scopeinfo` metadata entries. "
              "Those are not physical logic cells; the library area calculation does not assign them cell area.", "",
              "A missed mapping target is a missed target, not an achieved clock. ABC boundary "
              "delay omits DFF clock-to-Q/setup/hold, clock trees, placement/routing and extracted "
              "parasitics. Nangate45 is a generic non-manufacturable research library. Cell area is "
              "not die area. See the [technology contract](../hardware/spinal/spec/APE-TECHNOLOGY-STUDY.md).", "",
              "| Quantity | Evidence status |",
              "| --- | --- |",
              "| Simulated cycles / IPC | Measured on actual generated RTL with matched work and service |",
              "| Mapped cell area / combinational boundary delay | Measured under the research-library assumptions above |",
              "| Achievable processor clock frequency | Not measured; no setup/hold or physical timing closure |",
              "| Physical power / energy | Not measured; no activity or implementation-based power analysis |",
              "| End-to-end agent, compiler or Python acceleration | Not measured by this selected tool study |", "",
              "Configuration selection is recorded separately in the S03 completion review. This report "
              "does not imply production big-core performance, an operating system, an agent speedup "
              "or S10 implementation closure.", ""]
    return "\n".join(lines)


def render_with_identity(study, technology, study_sha, technology_shas):
    return (render(study, technology) + "\n## Evidence identity\n\n"
            + f"- Controlled study SHA-256: `{study_sha}`.\n"
            + "".join(f"- Technology study SHA-256: `{digest}`.\n" for digest in technology_shas))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--technology", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Preserve existing reports; choose a new output path")
    study = json.loads(args.study.read_text())
    technology = [json.loads(p.read_text()) for p in args.technology]
    result = render(study, technology)
    for report in (study, *technology):
        check_hashes(REPO, report["source_sha256"])
    for hashes in [*study["generated"].values(), *(r["artifacts_sha256"] for r in study["results"])]:
        check_hashes(REPO, hashes)
    for report in technology:
        for row in report["results"]:
            check_hashes(REPO, row["evidence_sha256"])
    args.output.write_text(render_with_identity(study, technology, sha(args.study), [sha(p) for p in args.technology]))
    print("Rendered measured design study: " + str(args.output))


if __name__ == "__main__":
    main()
