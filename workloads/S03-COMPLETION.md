# S03 completion: workload-evaluated speculative OoO APE

Status: accepted against the original S03 criteria.

Stage: [issue #4](https://github.com/chienpinglu/HATS/issues/4).
The complete P64 compatibility gate, 108-run controlled workload study and
nine-point technology matrix and selected PRF48 profile have passed their declared
checks. The [configuration decision](s03/design-selection.json) and the original
criteria review below define acceptance. The [closure evidence](evidence/S03-CLOSURE.json)
binds the source, artifacts, report checks and limitations; it is an S03 research-
prototype result, not production-CPU or physical-design completion.

## Implemented processor

HATS is the **Heterogeneous Agent Tool Substrate**. Its **Application Processing
Engine (APE)** is an original SpinalHDL implementation of a speculative,
out-of-order integer processor with a supported RV64I-subset frontend. It is not
an in-order embedded controller with an out-of-order label.

The backend contains a physical register file, speculative and committed rename
maps, a free bitmap, physical-tag wakeup, oldest-ready issue, registered execution,
generation-qualified completion and ordered architectural retirement. Reservation
operands share the ROB rows. Configurable one/two-lane execution has one dispatch,
writeback and retirement port; the current memory interface admits one head-only
request. This is not a two-wide frontend or a concurrent memory subsystem.

ROB-owned branch checkpoints capture the post-link rename map and track younger
allocations. A misprediction restores the appropriate snapshot before retirement,
preserves older work and accepted head memory, and reclaims younger state.
Delayed execution tokens carry slot, generation and physical destination. A token
can update state only while its live owner still matches; dispatch excludes any
generation still resident in a pipeline. Reuse safety does not assume a bounded
execution stall.

The [semantic boundary](../hardware/spinal/spec/APE-SEMANTIC-BOUNDARY.md) makes
successors, target masking, alignment, result extension, fault classes and register
layout explicit. RISC-V encoding, visible causes and task ABI remain frontend/
wrapper responsibilities. One semantic operation represents one architectural
instruction. Alternate component policies are tested, but no second ISA, flags,
multi-destination instruction grouping or privileged execution is implemented.

## Original work-package and acceptance review

Each item below corresponds to an original [ROADMAP S03](../ROADMAP.md) row.
Mechanism tests, application results and physical estimates have separate scopes.

| Item | Implementation and authoritative evidence |
| --- | --- |
| WP1: semantic frontend/backend separation | `ApeSemantics`, `ApeRv64Profile`, `ApeDecode`, explicit execution policy, parameterized register layout and predictor indexing; actual-RTL semantic gate plus current-source RV/real-tool compatibility |
| WP2: physical rename, scheduling and retirement | `ApeRename`, `ApeIssueScheduler` and `ApeCore`; independent rename ownership replay, exhaustion/WAW/RAW/WAR tests, port assertions and restricted rename lifecycle formal properties |
| WP3: checkpointed early recovery | `ApeCheckpoints` plus age-based core squash; 108 exact narrow recovery comparisons, 72 exact wide recovery comparisons, nested ownership and concurrent older-retirement witnesses; older memory remains head-owned |
| WP4: pipelined execution and wider candidate | Operand/result registers in `ApeExecute`, held-result arbitration and `ApeCompletionGuard`; complete 108-run matched-work/service study actually exercises both lanes, rather than inferring width from a configuration flag |
| WP5: precise faults and lifecycle | Semantic fault transport and head retirement; standard precise-fault/wrong-path checks, halt backpressure, repeated launch, finite-generation reuse and resource-pressure gates; external reset requires fabric quiescence or coordinated reset |
| WP6: adversarial, formal and early physical evidence | Randomized data/control hazards, independent issue/completion replay, selected actual-RTL bounded proofs, observed counters and all nine mapped/equivalent technology points; complete selected-profile tool/ISA gate |
| AC1: architectural compatibility | Current P64 full tool/ISA/diff/PPE/legacy aggregate and separate PRF48 full-tool/ISA/recovery gate passed with no new profile exclusion |
| AC2: actual OoO and recovery under pressure | Public issue/completion histories and architectural comparisons demonstrate younger execution ahead of older dependencies/memory, late-result rejection, nested restore, register/checkpoint exhaustion and recovery concurrent with older retirement |
| AC3: selected formal invariants | Both selected bounded gates passed on the current generated modules, including all reachability and false-assertion controls; restricted assumptions and broader proof gaps are enumerated below |
| AC4: evidence-based configuration choices | Workload and mapped area/delay comparisons cover issue width, PRF, ROB/fused reservations and prediction; selected ROB8/P48/one-lane/bimodal16 configuration has separate full-profile correctness evidence |
| AC5: performance claim separation | The [measured report](S03-DESIGN-STUDY.md) separates simulated cycles/IPC and early mapped area/combinational-path delay from unmeasured achievable clock and physical energy; all nine mapping-target misses are explicit |

## Verified correctness coverage

| Gate | Current-source result | Scope |
| --- | --- | --- |
| Semantic execution/profile | 4,953 vectors; 135 RV profile checks | Explicit operation, width/extension, branch/target and fault policies |
| Alternate register/predictor policy | 12,000 rename cycles; 1,024 predictor checks | Writable register index zero in alternate layouts; explicit predictor successors/index shifts |
| Physical rename | 18,000 unit cycles; 192 exact pressure comparisons plus eight unchanged profile differences | Independent live-owner replay, free/map/readiness/value state, commit and full recovery |
| Checkpoint recovery | 32,000 unit cycles; 108 exact core comparisons | Older memory, nested restore, link retention, older faults, pressure and concurrent commit |
| Registered execution | 16,800 transport cycles; 16,000 ownership checks; 288 exact core comparisons plus 12 unchanged profile differences | Backpressure, pending-token inventory, cancellation, stale completion and finite-generation wrap exclusion |
| One/two-lane candidate | 456 exact core comparisons plus 16 unchanged profile differences | 400 standard invocations and 72 recovery invocations; real simultaneous issue and held-completion arbitration |
| Full upstream tool | 42 P64 RTL invocations, 860,981,474 retirements and 357,201,875 memory events | Every architectural register state, PC/instruction/successor, memory event and final trap enters the independent Spike comparison; full outputs also match |
| Selected PRF48 profile | 42 actual tool invocations with the same complete architectural work; 108 exact ISA/recovery matches plus four unchanged differences | Fresh standard/recovery SpinalSim execution; ROB8-sized witnesses preserve all early/nested/concurrent/pressure assertions |
| Independent application transport | 18 SpinalSim invocations | Exact event traces and full-state digests cross-check overlapping bulk cases |
| Standard and bounded applications | 600 APE invocations, 4,096 predictor checks, 576 exact Spike matches plus 24 unchanged differences, 144 bounded-diff runs | Supported ISA/fault behavior, repeated launch, exact diff traces and minimum-edit output checks |
| Retained platform anchors | 224 PPE runs, 123 committed legacy tests, 90 native checks | PPE independent ISA/protocol checks, committed TaskTile and host semantic reference; not validation of unrelated local edits |

Counts from overlapping gates are not unique coverage points and must not be
added as an independent-scenario total. The two unchanged architectural-profile
differences are unsupported `FENCE.I` and the launch-entry alignment boundary;
each is checked explicitly, not treated as an unexplained mismatch. Recovery
comparisons allow no exclusions. Complete-stream SHA-256 is cryptographic
comparison evidence, not formal instruction conformance.

## Formal proof boundary

The [checkpoint proof](../hardware/spinal/spec/APE-CHECKPOINT-FORMAL.md) uses the
actual generated P36/eight-row component with one/four checkpoint capacity. It
checks eight assertion sites per configuration for 12 global transitions,
including an arbitrary watched row/tag and the x10 snapshot field. All nine
cover witnesses and both false-assertion controls passed.

The [rename lifecycle proof](../hardware/spinal/spec/APE-RENAME-FORMAL.md) uses
the actual generated P36 rename wrapper. Its environment restricts writers to
x10, values to one arbitrary low bit, outstanding writers to four, and recovery
to the committed-map path. All 24 assertion sites passed at 16 global transitions;
all six covers and the false-assertion control passed.

These are bounded regression properties under legal-input assumptions, not
whole-core or unbounded proofs. Full-width/cross-register map injectivity,
core-computed age/squash correctness, every parameterization, unrestricted reset,
progress/fairness and sequential mapped-core equivalence remain outside these
formal results. Simulation covers additional cases but does not turn those gaps
into proofs. Failed or timed-out exploratory attempts are retained separately
and are not included as passing formal evidence.

## Workload and physical interpretation

Nine configurations execute six real program/input cases under two transaction-
indexed service profiles. Binaries, architectural work and realized acceptance/
response waits match across each comparison. The equal-case geometric mean is
an experimental summary, not an estimate of a real agent's workload mix.

Dual issue increases cycles by 0.040%–8.013% across the twelve pairs, with an
equal-case mean increase of 1.685%. ROB16 reduces the mean by 0.608%; PRF48 has
exactly the same cycle count as P64 in every pair. These are measured cycles,
not achieved throughput or end-to-end agent speedup. Shared dispatch, completion,
retirement and head-only memory are explicit restrictions; stall counters overlap
and do not provide a causal breakdown by themselves.

The [technology study](../hardware/spinal/spec/APE-TECHNOLOGY-STUDY.md) maps each
actual configuration with a pinned Nangate45 research library and checks the
complete extracted pre/post-mapping combinational networks. All storage maps to
flip-flops/muxes, including a 1,024-word code memory; workload configurations use
65,536 code words. Those total areas cannot be equated. The 1,000 ps mapping
target is not an achieved clock; misses remain misses. Sequential timing, clock
distribution, placed/routed parasitics, SRAM macros, multi-corner closure and
physical power/energy are not measured.

The complete [design-point report](S03-DESIGN-STUDY.md) records all measured values,
comparison conditions, pressure counters and source report hashes. The
[configuration record](s03/design-selection.json) selects ROB8/P48/one issue
lane/bimodal16 as the explicit application profile. PRF48 preserves all twelve
baseline cycle counts and reduces mapped area by 2.85% under the declared
physical-study assumptions. The separate PRF48 tool/ISA gate, not the P64 result,
qualifies this selection. P64 remains the generic `ApeConfig` fallback and a
retained compatibility anchor. These single-variable comparisons do not establish
a globally optimal joint configuration.

Generate the selected application-image configuration from `hardware/spinal`:

```sh
bash tools/sbtw 'runMain hats.ApeDesignPointGenerate build/selected-ape 8 48 1 bimodal 16 65536 4'
```

Recovery witnesses must fit the speculative window. The original ROB16 suite
uses eight NOPs behind an older load; it cannot demonstrate pre-response branch
recovery in ROB8. The selected profile uses separate assembly with dependency-
delayed branches and a shorter nested window. The unchanged testbench still
requires actual target issue before the older response, nested resolved-branch
squash, older retirement concurrent with redirect, older-fault priority and
checkpoint exhaustion. All twelve recovery invocations match Spike exactly.

## Reproduction and provenance

Use the [S03 gate guide](s03/README.md) and the existing pinned hardware,
LLVM/LLD, Tree-sitter, Newlib and Spike dependencies. The tested platform is macOS
arm64 with Homebrew Python 3.14.3, Verilator 5.052, Scala 2.13.14, sbt 1.10.7 and
SpinalHDL 1.12.3. Other hosts need a toolchain-path port and new evidence.

The current full compatibility report is
`workloads/results/s03-semantic-compatibility.json`. Its source/document/report
snapshot is `hardware/spinal/build/s03-semantic-sources.tar`, SHA-256
`bfbab0996ba7fdb78cee12b5476de2bc459a7eb21f507c880bc2bc7dd9c39597`.
The snapshot's 105 members were verified against that report; generated traces
are retained separately. Earlier APE-0.3/0.4/0.5/0.6 increment records remain
immutable historical anchors, not current-source substitutes.

The selected-profile report is
`workloads/results/s03-profile-1791599695567119000/validation.json`, SHA-256
`0a83fa678001a25fb7a0f224acee7916fb0d0188016a7bfbd12aeccffaf554bf`.
Its 42 tool executions are hash-revalidated from the preserved first attempt;
all ISA/recovery executions are fresh in an isolated workspace. The initial
ROB16-witness/ROB8 failure, original driver and trace remain retained and bound
by the new report. No failed result is counted as a passing recovery invocation.

Only original HATS implementation/specifications and curated evidence belong in
the public repository. Public upstream source and library/tool locks retain their
provenance; downloaded implementations, full generated traces and raw build logs
remain in ignored local paths. No private reference RTL was read or imported in
these S03 increments. That statement is not a legal clean-room certification.

S03 does not implement S04's cache/LSQ/concurrent memory hierarchy, S05's command
processor, protected OS services, a tensor/LLM engine or the complete HATS NUMA
fabric. It does not execute a compiler or general Python on the target, close an
FPGA/ASIC implementation, or prove an end-to-end agent acceleration claim.
