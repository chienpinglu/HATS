# S03 / issue #4: APE backend progress

Issue: [Develop and verify the speculative out-of-order APE performance core](https://github.com/chienpinglu/HATS/issues/4).
**Status: original S03 criteria accepted on 2026-10-10.**
The [completion review](../../../workloads/S03-COMPLETION.md),
[measured report](../../../workloads/S03-DESIGN-STUDY.md) and
[closure evidence](../../../workloads/evidence/S03-CLOSURE.json) are authoritative.
Historical increment records below retain their narrower scopes.

## Current candidate and preserved baseline

The [APE-0.6 dual-lane candidate](APE-0.6.md) is now in the main sources. Its
source-bound multi-issue/Spike gate passed (456 exact matches plus 16 unchanged
profile differences), as did its controlled eight-run real-tool smoke. The
108-invocation narrow recovery gate also passed after the fixture timing change.
The first controlled candidate was 0.095%–8.01% slower in simulated cycles; the
complete 108-run study and nine-point technology matrix have since passed. The
APE-0.5 record below is a **preserved historical baseline**, not a
passing claim for the changed current source. Selected issue width remains one
based on the complete study. The historical pipeline source archive is
`hardware/spinal/build/s03-pipeline-baseline.tar`, SHA-256
`576014d084f63089274dd3ccb52b409ce8f72dae7173721292513d5e0bb785fc`;
all 126 source/document/summary members were verified against its checkpoint.

## Current semantic-boundary verification

The [semantic boundary](APE-SEMANTIC-BOUNDARY.md) now separates RV result, target,
fault and register-layout policy from the reusable components. The actual-RTL
gate passed 4,953 execution vectors, 135 RV profile checks, 12,000 alternate-layout
rename cycles and 1,024 alternate-index/successor predictor checks. Current-source
multi-issue, recovery, registered-execution and physical-rename gates also passed.
Both current-source selected formal gates passed: checkpoint safety at 12 global
steps (nine covers/two controls), and restricted rename lifecycle at 16 global
steps (six covers/one control). The first C4 checkpoint attempt timed out; its
retained log and unchanged-depth rerun budgets are documented in the formal
contract. The full nine-point/two-service study has now passed all 108 actual-RTL
invocations, including full architecture-state digests and result images. The
fresh full P64 compatibility chain also passed on 2026-10-10: 42 bulk tool runs
(860,981,474 retirements and 357,201,875 memory events), 18 independent small
SpinalSim runs, 90 native checks, 224 PPE runs, 600 standard APE invocations,
4,096 predictor checks, 576 exact Spike matches plus 24 unchanged profile
differences, 144 bounded-diff runs and 123 committed legacy tests. Its aggregate
is `workloads/results/s03-semantic-compatibility.json`; this is current-source
integration evidence, not an inference from an older checkpoint.

The complete compatibility source/document/report snapshot is preserved in
`hardware/spinal/build/s03-semantic-sources.tar`, SHA-256
`bfbab0996ba7fdb78cee12b5476de2bc459a7eb21f507c880bc2bc7dd9c39597`.
All 105 members match the compatibility manifest. Generated traces and detailed
run artifacts remain in their separate ignored run roots, not in that source
archive. Original APE-0.3/0.4/0.5/0.6 increment checkpoints remain untouched.

The controlled study's equal-case geometric-mean cycle changes relative to
ROB8/P64/one lane/bimodal16 are: dual issue +1.685%, ROB4 +4.846%, ROB16 -0.608%,
PRF36 +3.226%, PRF48 0.000%, prediction disabled +1.650%, four-entry prediction
+0.153%, and 64-entry prediction -0.145%. Positive changes mean slower. PRF48
matches baseline cycles in every case/service pair, with at least eight free
physical entries observed. The separate full PRF48 gate has passed all 42 actual
tool cases and 108 exact ISA/recovery comparisons plus four unchanged standard
profile differences. It uses ROB8-sized recovery witnesses and unchanged harness
assertions; the original ROB16 suite and failed ROB8 attempt remain preserved.

The [technology study](APE-TECHNOLOGY-STUDY.md) now synthesizes actual APE
configurations into the pinned research library. It requires mapped-network
equivalence before accepting any area or boundary-delay result. Its physical
assumptions and distinction from clock/energy are explicit. The final collector
`workloads/s03/closure_evidence.py` also requires a measured configuration-selection
record and completion review; both now select the fully verified explicit PRF48
profile. All nine physical rows completed mapping and
equivalence. The [measured report](../../../workloads/S03-DESIGN-STUDY.md) is complete.
PRF48 maps to
387,003.666 library area units and 2,844.33 ps combinational boundary delay,
versus 398,345.906 and 2,869.98 ps for narrow P64. Its area is 2.85% smaller
under these assumptions. All nine rows miss the 1,000 ps combinational mapping
target. The final comparison must retain those misses and distinguish early
boundary delay from achievable processor clock.

## Implemented increments

APE-0.3 replaces the ROB-tag/value-array renaming mechanism with an actual physical
integer register file, speculative/committed maps, allocation/free-list state,
physical-tag wakeup and precise retirement/recovery. The RISC-V decoder now emits
typed branch conditions and memory size/signedness. See the
[contract](APE-0.3.md) and [implementation overview](../APE.md).

[APE-0.4](APE-0.4.md) adds actual ROB-owned map checkpoints and execution-time
selective recovery. Older work and pending head-memory requests survive; younger
physical allocations and ROB entries are reclaimed. Link destinations, nested
restores, checkpoint pressure and precise older faults have dedicated RTL witnesses.
That preserved revision uses synchronous single-issue completion.

[APE-0.5](APE-0.5.md) now implements an operand/result pipeline, memory-priority
completion arbitration and `(ROB slot, generation, physical destination)`
qualification. Its [closure plan](S03-CLOSURE-PLAN.md) retains the full original
S03 target. Full integration verification passed on 2026-10-10 Asia/Shanghai;
the APE-0.4 results below remain historical and separate from this pipeline record.

This is backend infrastructure for the required speculative out-of-order APE,
not an embedded in-order controller and not yet a performance-qualified big core.
No private reference RTL was read or imported for this increment.

## Work-package coverage

| Issue #4 work package | Current implementation | Acceptance and retained limits |
| --- | --- | --- |
| Semantic frontend/backend boundary | Typed decode plus explicit result extension, fault classes, successor/target policy and register layout; one operation per instruction enforced; current P64 and selected-profile integration passed | Flags and expanded groups remain outside the implemented profile |
| Physical rename/scheduling/retirement | PRF, speculative and committed maps, free list, physical-tag wakeup, oldest-ready issue and precise retirement | Physical/workload comparison selects P48/ROB8/fused reservations; separately sized queues are not implemented |
| Branch recovery | Checkpoints, early selective restore, nested ownership; qualified pipeline results and finite-generation lease exclusion; narrow/wide recovery and both integration profiles passed | No unrestricted whole-core formal proof |
| Pipeline and issue-width design | Registered operands/results; one/two-lane issue and qualified arbitrated completion; complete 108-run controlled study | Complete early synthesis/timing comparison supports one issue lane; no achieved clock claim |
| Fault/lifecycle/resource behavior | Precise faults, free-list pressure and relaunch retained; pipeline clear and rejected late results tested; both profiles passed | Arbitrary reset with outstanding external transactions remains unsupported |
| Adversarial/formal/physical evidence | Replay scoreboards, timing/pressure witnesses, RTL assertions; selected checkpoint and rename-lifecycle bounded proofs; nine technology points | Broader proof and physical implementation coverage remain explicitly documented gaps |

The completed original-criteria review combines all six work packages with actual
application/ISA compatibility, demonstrated OoO under pressure, selected formal
proofs and workload/physical evidence for configuration choices.

## Historical APE-0.5 verification record

The current focused registered-execution gate passed on 2026-10-10 Asia/Shanghai:

| Gate | Observed result | Scope |
| --- | --- | --- |
| Elastic execution RTL | 16,800 test cycles, depths 2/8/16 and 1-/2-bit generations | Port-only add/sub transport, latency, pending-token inventory, long backpressure and clear |
| Completion guard RTL | 16,000 checks; 1-/2-bit finite generations | Dead/unissued/duplicate/wrong-generation/wrong-destination rejection and resident-token wrap exclusion |
| Pipeline core / Spike | 300 invocations: 288 exact matches and 12 unchanged profile differences | ROB8/P64 shallow/deep and ROB16/P36 narrow pressure; no new architectural exclusion |
| Actual late completion | 306 / 996 / 70 rejected results in the three configurations | Squash-history oracle follows public issue/completion identities |
| Reuse witness | Deep configuration: 30 rejected results after an earlier-edge ROB slot reuse; 332 physical reuse observations while a killed token remained pending | Physical reuse count includes same-edge draining tokens; slot-reuse count does not |
| Integrated pressure | 70,652 rename-stall cycles in ROB16/P36/bimodal | Diagnostic aggregate, not application performance |
| Recovery regression | 32,000 unit cycles; all 108 core invocations exactly match Spike | Older accepted memory, nested resolved-younger squash, concurrent older commit and checkpoint pressure preserved |
| Standard core / predictor / Spike | 600 core invocations, 4,096 predictor checks; 576 exact matches and 24 unchanged profile differences | Fresh run in the completed full compatibility aggregate |
| Full real-tool integration | 42 bulk invocations, 860,981,474 retirements, 357,201,875 memory events; 18 small SpinalSim invocations | Complete architectural streams and outputs match the independent reference |
| Other compatibility anchors | 144 bounded diff runs, 224 PPE runs, 123 committed legacy tests, 90 native checks | All passed; unrelated live TaskTile edits preserved |
| Rename regression | 18,000 unit cycles; 192 pressure Spike matches and eight unchanged differences | Passing current-source ownership/pressure gate |
| Selected rename lifecycle formal | 16-global-step bounded safety, all six covers and false-assertion control passed | P36, x10 only, four speculative writers, one-bit values; ordered commit, out-of-order writeback, full recovery and clear |

The integrated pipeline suites recorded **zero execution-input stalls and zero
generation-allocation stalls**. Those mechanisms are exercised by unit tests;
they are not claimed as integrated-core coverage. Full external memory and issue
width remain one. The deep pipeline's extra registers are delay stress, not
arithmetic timing optimization.

Current reports are `hardware/spinal/build/ape_execution/gate.json`,
`hardware/spinal/build/ape_recovery/gate.json` and
`hardware/spinal/build/ape_rename/gate.json`. The selected checkpoint formal rerun
passed at 12 global steps for C1/C4, with all nine covers and both negative
controls; its scope remains component-level and bounded. The fresh full
aggregate passed at `workloads/results/s03-pipeline-compatibility.json`.
The [pipeline checkpoint](../../../workloads/evidence/S03-PIPELINE-CHECKPOINT.json)
binds that aggregate to the focused execution, rename, recovery and selected
formal gates. It remains an increment record with `S03_complete: false`.

The [rename lifecycle proof](APE-RENAME-FORMAL.md) adds actual allocation,
readiness/map, retirement and full-recovery invariants under a restricted
port-level environment. Its current-source report is
`hardware/spinal/build/ape_rename_formal/steps16/validation.json`. It is not a
general cross-register or unbounded proof; those gaps remain enumerated.

An initial [generic synthesis probe](APE-SYNTHESIS-PROBE.md) completed for
ROB8/P64: 148,297 generic cells (including five metadata cells) and a 64-cell
longest topological path through renamer allocation/ready logic. All memory is
flip-flop/mux mapped, including 1,024 instruction words. These are structural
diagnostics, not technology-based area, delay, frequency or S03 design-point closure.

## Historical APE-0.4 verification record

The focused gates passed on 2026-10-09 UTC (2026-10-10 Asia/Shanghai):

| Gate | Observed result | Boundary |
| --- | --- | --- |
| Checkpoint/rename RTL replay oracle | 32,000 cycles: P36/C1, P36/C4, P64/C2, P64/C4 | Independent surviving-instruction replay; not formal proof |
| Focused core recovery matrix | Six programs, nine configurations, two launches each | 108 exact Spike matches, no profile exclusions |
| Early timing | Old load response at cycle 22; redirect at 7 and correct-target issue at 9 in `older_load-0`, ROB16/P64/C4/off | Direct actual-RTL observation, not an application speedup claim |
| Nested recovery / concurrent commit | All applicable focused configurations passed | Younger resolved branches can be squashed by an older branch |
| Resource and exception witnesses | Checkpoint stalls, physical pressure, link retention/fault suppression, older bus fault after younger redirect | Head-only memory; no delayed execution-unit completions |
| Rename compatibility | Fresh 18,000 unit cycles; 200 core pressure runs | 192 exact Spike matches and the same 8 checked profile differences |
| Selected checkpoint formal | P36/eight slots/C1 and C4 passed 12-global-step bounded proofs; all nine covers reached; both false-assertion controls rejected | Eight assertions per configuration; x10 snapshot field, arbitrary watched slot/tag; not unbounded or full-core proof |
| Full real-tool streaming comparison | 42 invocations; 860,981,474 retirements and 357,201,875 memory events | Exact complete-stream digests match Spike and the previous APE-0.3 architectural results |
| Small real-tool SpinalSim path | 18 invocations passed | Independent full-trace cross-check of overlapping bulk cases |
| Standard APE / predictor / Spike | 600 RTL invocations; 4,096 predictor checks; 576 exact Spike matches and the same 24 checked profile differences | Fresh matrix after the predicted-exit fixture correction below |
| Bounded diff / PPE / legacy | 144 exact application runs; 224 PPE runs; 123 committed legacy tests | Live user-modified TaskTile was preserved |
| Host-native baseline | 90 checks including sanitizer builds | Semantic reference, not HATS execution |

The then-current focused reports were `hardware/spinal/build/ape_recovery/gate.json` and
`hardware/spinal/build/ape_rename/gate.json`. These working paths are regenerated
for later revisions; use the immutable recovery checkpoint for historical identity.
The full real-tool/ISA/application/PPE/legacy aggregate **passed on 2026-10-09 UTC**
(2026-10-10 Asia/Shanghai). Its separate path is
`workloads/results/s03-recovery-compatibility.json`.

The first full standard-matrix attempt exposed a test-coverage gap at ROB16:
early recovery fetched the three-branch short command loop before retirement
could train its exit prediction. Its architecture/output checks passed but the
required predicted-taken exit did not occur. The fixture now pads its loop body
to occupy the largest tested ROB before the next iteration. The original exit
and exactly-two-command assertions remain; fresh standard/pressure gates passed.
No core RTL or real-tool binary was changed by this test correction. The original
aggregate runner stopped at the coverage assertion; affected mechanism gates
were rerun, the remaining application/legacy stages completed, and `s02/gate.py`
revalidated all current-source artifacts before producing the passing aggregate.
The already-passed real-tool reports remained source-identical and were not
misrepresented as new executions after the fixture-only correction.

Current bulk evidence is
`workloads/results/s02-treesitter-1791562574348401000/bulk/validation.json`, with
generated `ApeCore.v` SHA-256
`f48347122ab172df6338928e5fc555ad8d4306d0ab73bc2865b442fb77a207ed`.
The small-tool report is
`workloads/results/s02-treesitter-1791563531147169000/rtl-validation.json`.
The [new recovery checkpoint](../../../workloads/evidence/S03-RECOVERY-CHECKPOINT.json)
binds compatibility, both focused RTL gates and the selected bounded formal gate.
The historical APE-0.2 and APE-0.3 records are not overwritten.

Early/retirement cycle summaries share the randomized memory-service policy but
can encounter different realized waits. They are diagnostic only, not a controlled
performance result. No synthesis, timing closure or energy result exists yet.

The separate [formal contract](APE-CHECKPOINT-FORMAL.md) specifies the bounded
properties, legal-input assumptions, field/configuration restrictions, covers and
negative controls. Its report is `hardware/spinal/build/ape_formal/validation.json`.
Initial unbounded-induction exploration did not close; deeper SMT exploration
timed out. Neither is counted as a pass or hidden by the bounded result.

## Historical APE-0.3 verification record

The focused gate was run on 2026-10-09 using actual generated RTL:

| Gate | Observed result | Meaning |
| --- | --- | --- |
| Rename-unit port scoreboard | 18,000 cycles across P=33/36/64 | Allocation, data/readiness, map ownership, exhaustion, non-FIFO completion and recovery |
| Same-edge commit and recovery | 89 / 190 / 174 occurrences at P=33/36/64 | Committed-after-edge state is retained across recovery |
| Integrated ROB16/P36 matrix | 200 invocations, off/bimodal, each scenario launched twice | Existing actual-OoO, precise-fault and wrong-path checks preserved under pressure |
| Independent pressure Spike comparison | 192 exact architectural-event matches; 8 checked profile differences | Same FENCE.I and misaligned-entry exclusions as the baseline; no new exclusion |
| Integrated rename stalls | 61,081 off / 64,043 bimodal across each 100-invocation suite | Exhaustion was exercised; these are diagnostic aggregate cycles, not performance scores |
| Full real-tool streaming comparison | 42/42 actual RTL invocations; 860,981,474 retirements and 357,201,875 memory events | Every architectural retirement state and memory event enters the independent Spike/RTL stream digest; outputs also match |
| Small real-tool SpinalSim path | 18 invocations passed | Full-state traces cross-check the bulk path on overlapping fixtures |
| Standard APE / predictor | 600 invocations and 4,096 lookup checks passed | ROB4/8/16, prediction off/bimodal, P=64 |
| Standard independent Spike | 576 exact matches; 24 checked profile differences | No unexpected divergence; same two documented profile gaps |
| Bounded line-diff application | 144 RTL invocations passed | Exact Spike traces and independent minimum-edit/output checks |
| PPE regression | 224 invocations passed | 180 ISA-oracle comparisons and 44 protocol/decode checks |
| Committed legacy TaskTile | 123 RTL tests passed | Recorded committed-source overlay; dirty live TaskTile left untouched |
| Host-native tool baseline | 90 checks passed, including sanitizer builds | Host semantic baseline only, not HATS execution |

The gate is `hardware/spinal/tools/verify_ape_rename.py`; local evidence is
`hardware/spinal/build/ape_rename/gate.json`. It records source stability, generated
RTL and trace hashes, pinned reference identity and exact pressure configurations.
Simulation assertions are not formal proofs, and seed counts are not coverage
closure. One-register slack (P=33) is tested in the unit, not in the integrated
core; its queue cannot exhibit non-FIFO completions.

The fresh bulk report is
`workloads/results/s02-treesitter-1791560065406224000/bulk/validation.json`.
Its generated `ApeCore.v` SHA-256 is
`77d368cb431a7cbff26e0d8bf1d1eba3cef221131b42903afc8c3b7d812b2445`.
For all 42 cases, complete architectural digests and cycle/retirement/memory/stack
diagnostics match the historical S02 report at
`workloads/results/s02-treesitter-1791516413106224000/bulk/validation.json`;
the parser ELF is unchanged. This is a bounded same-workload compatibility
observation: **no simulated-cycle improvement is demonstrated by this increment**.
It is not a frequency, area or energy comparison.

The fresh full compatibility aggregate **passed on 2026-10-09** against APE-0.3:

```sh
python3 workloads/s02/run_all.py --output workloads/results/s03-compatibility.json
```

The source-bound report is `workloads/results/s03-compatibility.json`.
The previous `workloads/evidence/S02-CLOSURE.json` remains the historical APE-0.2
anchor and was not overwritten. The new
[increment evidence](../../../workloads/evidence/S03-RENAME-CHECKPOINT.json)
summarizes the then-current APE-0.3 gates while explicitly keeping S03 incomplete.
It is immutable historical evidence, not validation of the changed APE-0.4 RTL.

## Next implementation sequence

The [closure plan](S03-CLOSURE-PLAN.md) retains all original acceptance criteria.
Physical-renaming and synchronous-recovery evidence were preserved before the
registered execution extension.

1. Preserve the passing APE-0.4 compatibility/focused/formal record as a regression
   anchor alongside, not in place of, the earlier physical-renaming record.
2. Treat the implemented checkpoints, nested recovery and older-fault timing
   witnesses as mandatory regression anchors for subsequent pipeline changes.
3. Complete and preserve the registered-execution integration checkpoint, then
   extend the tested completion-lease inventory to every wider execution lane.
4. Extend the selected checkpoint formal starter to allocation/free/commit/recovery
   invariants, stronger induction and broader field/configuration/depth coverage.
   Keep all input assumptions and bounded/unbounded proof status explicit.
5. Compare a pipelined narrow baseline and a multi-issue candidate under identical
   tool binaries, inputs and memory service. Report cycles, retired instructions,
   IPC and stall causes separately from synthesis timing, area and SRAM assumptions.
6. Use those results to choose register/ROB/queue capacities and predictor options;
   close #4 only when all original acceptance criteria have their required evidence.

After all three focused gates, the selected bounded formal gate and full compatibility pass, a public-safe record can be
collected without changing issue state:

```sh
python3 workloads/s03/evidence.py --output workloads/evidence/S03-PIPELINE-CHECKPOINT.json
```

This collector checks sources and focused-gate artifacts; the S02 driver remains
responsible for full compatibility-artifact revalidation. It explicitly records
`S03_complete: false` and rejects the historical pre-PRF S02 report as current evidence.

The order can overlap specification and physical feasibility studies, but no
simulation-speed or architectural-count metric substitutes for hardware timing
or end-to-end agent acceleration. Cache/MMU/OS/CP and tensor execution are not
silently folded into this increment.
