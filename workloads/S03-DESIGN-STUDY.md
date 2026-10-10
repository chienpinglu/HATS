# S03 APE design-point measurements

## Scope and comparison contract

Nine actual APE RTL configurations execute the same three compiled programs: integer helper vectors, runtime self-tests and the upstream Tree-sitter JSON parser. The six program/input cases run under two memory-service profiles, for 108 RTL invocations. Complete retirement-state/memory-event digests and output images match the independent Spike reference before any cycle ratio is accepted.

Each transaction receives an ordinal-indexed acceptance wait of 0–3 cycles and a response wait of either 2–9 or 16–23 cycles after acceptance. Compared designs have identical realized service and architectural work, not merely an equal cycle-dependent random seed. These are abstract service profiles, not an HBM/LPDDR or cache-latency model.

Dispatch, writeback and retirement widths are one; memory admits one head-only request. Execution has two registered stages and two-bit completion generations. Four branch checkpoints are configured. ROB capacity also sizes the fused reservation rows: this is not a separately sized issue-queue comparison.

## Configurations

| Point | ROB / reservation rows | Physical registers | Issue lanes | Predictor |
| --- | ---: | ---: | ---: | --- |
| narrow | 8 | 64 | 1 | bimodal, 16 entries |
| dual | 8 | 64 | 2 | bimodal, 16 entries |
| rob4 | 4 | 64 | 1 | bimodal, 16 entries |
| rob16 | 16 | 64 | 1 | bimodal, 16 entries |
| prf36 | 8 | 36 | 1 | bimodal, 16 entries |
| prf48 | 8 | 48 | 1 | bimodal, 16 entries |
| predict_off | 8 | 64 | 1 | disabled |
| predict4 | 8 | 64 | 1 | bimodal, 4 entries |
| predict64 | 8 | 64 | 1 | bimodal, 64 entries |

## Simulated cycles and IPC

The reference is `narrow` (ROB8 / P64 / one issue lane / bimodal16). Positive cycle change means slower. The geometric mean weights each of the twelve case/service combinations equally; it is not an agent-workload frequency estimate. IPC ranges are per invocation, not a clock-frequency or host-speedup measurement.

| Point | Geometric-mean cycle change | Per-case cycle-change range | Simulated IPC range |
| --- | ---: | ---: | ---: |
| narrow | +0.000% | +0.000% to +0.000% | 0.0919–0.7121 |
| dual | +1.685% | +0.040% to +8.013% | 0.0915–0.6592 |
| rob4 | +4.846% | +0.477% to +18.363% | 0.0904–0.6016 |
| rob16 | -0.608% | -2.244% to -0.062% | 0.0921–0.7271 |
| prf36 | +3.226% | +0.112% to +14.744% | 0.0911–0.6206 |
| prf48 | +0.000% | +0.000% to +0.000% | 0.0919–0.7121 |
| predict_off | +1.650% | -0.001% to +9.155% | 0.0917–0.6523 |
| predict4 | +0.153% | -0.008% to +0.401% | 0.0917–0.7116 |
| predict64 | -0.145% | -0.476% to -0.004% | 0.0920–0.7128 |

### Actual width-one / width-two pairs

Both lanes really issue work in the dual configuration; counts below are observed simultaneous-issue cycles. A larger issue count is not assumed to reduce total cycles.

| Program / input | Response base | Narrow cycles | Dual cycles | Dual cycle change | Dual-issue cycles |
| --- | ---: | ---: | ---: | ---: | ---: |
| helpers / integer-vectors | 2 | 1,159,169 | 1,252,055 | +8.013% | 166,791 |
| helpers / integer-vectors | 16 | 1,186,348 | 1,279,149 | +7.822% | 166,436 |
| runtime / runtime-tests | 2 | 127,220 | 127,341 | +0.095% | 250 |
| runtime / runtime-tests | 16 | 272,981 | 273,091 | +0.040% | 243 |
| parser / empty-incremental | 2 | 269,601 | 271,790 | +0.812% | 5,113 |
| parser / empty-incremental | 16 | 574,715 | 576,701 | +0.346% | 4,953 |
| parser / unicode-incremental | 2 | 607,316 | 612,277 | +0.817% | 11,765 |
| parser / unicode-incremental | 16 | 1,294,600 | 1,299,131 | +0.350% | 11,431 |
| parser / repository_lock-incremental | 2 | 55,617,765 | 56,072,901 | +0.818% | 1,081,212 |
| parser / repository_lock-incremental | 16 | 118,230,677 | 118,641,166 | +0.347% | 1,048,854 |
| parser / records_256-incremental | 2 | 160,920,340 | 162,274,196 | +0.841% | 3,182,255 |
| parser / records_256-incremental | 16 | 343,601,273 | 344,844,741 | +0.362% | 3,101,719 |

## Observed resource pressure

Totals cover the twelve invocations for each point, so larger inputs dominate them. Stall categories overlap; summing them does not partition execution time or prove a causal explanation for the cycle changes. Peak occupancy and minimum free count are extrema across these runs, not average utilization.

| Point | Peak ROB occupancy | Minimum free PRF entries | Rename-stall cycles | ROB-stall cycles | Completion-stall cycles | Branch misses / branches |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| narrow | 8 | 24 | 0 | 564,325,242 | 1,055,910 | 4,375,340 / 12,102,472 |
| dual | 8 | 24 | 0 | 567,752,647 | 12,189,668 | 4,374,743 / 12,102,472 |
| rob4 | 4 | 28 | 0 | 594,292,841 | 466,605 | 4,354,397 / 12,102,472 |
| rob16 | 16 | 16 | 0 | 516,348,559 | 2,374,525 | 4,444,885 / 12,102,472 |
| prf36 | 8 | 0 | 386,303,130 | 192,554,488 | 915,331 | 4,373,126 / 12,102,472 |
| prf48 | 8 | 8 | 0 | 564,325,242 | 1,055,910 | 4,375,340 / 12,102,472 |
| predict_off | 8 | 24 | 0 | 555,325,788 | 1,240,369 | 5,990,258 / 12,102,472 |
| predict4 | 8 | 24 | 0 | 561,872,541 | 1,132,934 | 5,081,170 / 12,102,472 |
| predict64 | 8 | 24 | 0 | 566,433,700 | 1,005,400 | 3,731,020 / 12,102,472 |

## Early mapped area and combinational delay

Every physical point uses the same Nangate45 typical research library, 1,000 ps mapping target, BUF_X1 combinational input driver and 5 fF output load. All storage is mapped to flip-flops/muxes, including the 1,024-word code store and physical registers; observation ports remain. The workload configurations use 65,536 code words. Their total areas must not be equated with this smaller physical-study memory.

Mapped combinational logic passed a complete pre/post-mapping equivalence check with identical ordered inputs/outputs and no internal abstraction. Sequential processor correctness is covered separately by RTL/ISA and selected formal gates.

| Point | Cell area (library units) | Change from narrow | Sequential-cell area | Netlist entries / metadata | Combinational boundary delay | Meets 1,000 ps mapping target |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| narrow | 398,345.906 | +0.000% | 215,963.804 | 189,607 / 6 | 2,869.98 ps | no |
| dual | 409,847.214 | +2.887% | 218,947.792 | 198,051 / 7 | 2,988.49 ps | no |
| rob4 | 363,086.808 | -8.851% | 197,292.200 | 171,677 / 6 | 2,973.15 ps | no |
| rob16 | 467,101.852 | +17.260% | 253,276.688 | 226,776 / 6 | 2,830.62 ps | no |
| prf36 | 374,404.044 | -6.010% | 204,791.804 | 175,529 / 6 | 3,080.05 ps | no |
| prf48 | 387,003.666 | -2.847% | 209,579.804 | 181,030 / 6 | 2,844.33 ps | no |
| predict_off | 398,892.004 | +0.137% | 213,069.724 | 191,345 / 6 | 2,775.82 ps | no |
| predict4 | 397,024.418 | -0.332% | 215,836.124 | 187,325 / 6 | 3,032.90 ps | no |
| predict64 | 398,890.674 | +0.137% | 216,474.524 | 190,150 / 6 | 2,929.07 ps | no |

Netlist-entry totals include the separately shown Yosys `$scopeinfo` metadata entries. Those are not physical logic cells; the library area calculation does not assign them cell area.

A missed mapping target is a missed target, not an achieved clock. ABC boundary delay omits DFF clock-to-Q/setup/hold, clock trees, placement/routing and extracted parasitics. Nangate45 is a generic non-manufacturable research library. Cell area is not die area. See the [technology contract](../hardware/spinal/spec/APE-TECHNOLOGY-STUDY.md).

| Quantity | Evidence status |
| --- | --- |
| Simulated cycles / IPC | Measured on actual generated RTL with matched work and service |
| Mapped cell area / combinational boundary delay | Measured under the research-library assumptions above |
| Achievable processor clock frequency | Not measured; no setup/hold or physical timing closure |
| Physical power / energy | Not measured; no activity or implementation-based power analysis |
| End-to-end agent, compiler or Python acceleration | Not measured by this selected tool study |

Configuration selection is recorded separately in the S03 completion review. This report does not imply production big-core performance, an operating system, an agent speedup or S10 implementation closure.

## Evidence identity

- Controlled study SHA-256: `0b62fb263bddd82000e068e1415355abfbf975a91f94940a8ae966bcfea49b8a`.
- Technology study SHA-256: `57831b4fce921e40da71b81d520a6b3705c42d7d6c4e3c87e944608045173564`.
