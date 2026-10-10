# APE generic synthesis probe

This is **early structural feedback**, not technology-mapped timing, physical
area, energy, or S03 closure. `tools/probe_ape_synthesis.py` consumes generated
RTL bound to a passing current-source APE matrix and rejects stale source/artifact
identity. It never substitutes a hand-written reduced processor.

## Reproduction and constraints

From the repository root:

```sh
python3 hardware/spinal/tools/probe_ape_synthesis.py --rob 8 --prediction bimodal
```

The local pinned YoWASP Yosys 0.69 flow reads the actual complete core, flattens it,
maps all memories into generic flip-flops and multiplexers, and runs generic
synthesis without ABC technology mapping. It checks for structural errors and
writes the complete netlist, cell statistics, longest topological path and log
under `hardware/spinal/build/ape_synthesis/r8-bimodal/`.

The configuration is ROB8/P64/C4, one issue/retire, two execution stages, two
generation bits, 16-entry bimodal prediction and **1,024 instruction words**.
It includes observation ports and their retained logic. This is the mechanism-test
configuration, not the 65,536-word real-tool instruction-store capacity.

There is no standard-cell library, wire model, clock target, input delay, output
load, SRAM macro or placement constraint. Generic-cell count is not equivalent
gate area. Longest path counts generic cells and ignores flip-flop arcs; it is
neither a sensitizable timing path nor a propagation-delay/frequency estimate.

## Initial comparable configurations

All three runs keep P64, C4, predictor, pipeline and memory assumptions identical:

| ROB entries | Generic cells, including metadata | Longest topological path, generic cells |
| --- | ---: | ---: |
| 4 | 129,935 | 64 |
| 8 | 148,297 | 64 |
| 16 | 186,084 | 64 |

The ROB8 total includes five nonphysical `$scopeinfo` entries. Its
reported path begins at a renamer free bit, passes through physical
allocation priority/encoding and ready-state update logic, and ends at a PRF
ready bit. This identifies a **candidate structural bottleneck**, not a measured
critical timing path. Library mapping may change its depth and ranking.

Storage dominates the raw accounting: even the small instruction image is
mapped to flip-flops/muxes, so these totals must not be compared with a production
core using compiled SRAM. The current source-bound JSON and netlist retain the
full cell-type breakdown for later apples-to-apples comparisons.

## Required next evidence

- Repeat comparable configurations and retain the identical memory implementation
  assumption; distinguish configuration changes from library/flow changes.
- Evaluate the multi-issue candidate with controlled real-tool memory service.
- Introduce a declared public reference library and explicit timing/load
  constraints before reporting technology-based area or delay estimates.
- Isolate instruction-storage and PRF implementation assumptions in any feasible
  physical design; do not claim that flip-flop expansion implements an SRAM macro.
- Preserve current-source correctness after changing allocator structure or
  inserting additional scheduling/rename stages.

This diagnostic cannot close the workload-driven design-point or physical timing
requirements on its own.
