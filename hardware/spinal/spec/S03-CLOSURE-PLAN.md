# S03 / issue #4 closure plan

Target: complete the speculative out-of-order APE performance-core integration
gate in [ROADMAP S03](../../../ROADMAP.md), preserving every original acceptance
criterion. An APE version increment is not issue closure.

## Required implementation and evidence

| Workstream | Deliverable | Acceptance evidence |
| --- | --- | --- |
| Registered execution | Operand/result registers, completion arbitration, generation-qualified ownership, wrap exclusion, precise cancellation | Current generated-RTL transport and ownership tests; integrated late-result/squash/physical-reuse witnesses; independent architectural comparison |
| Semantic boundary | RISC-V frontend/profile owns instruction size, architectural registers, word-result and target policy, exception mapping and instruction grouping; backend consumes explicit semantics | Interface specification and actual call sites; unchanged RISC-V regressions; no implied AArch64 implementation |
| Width/queue candidate | At least one actual multi-issue RTL configuration evaluated against the narrow registered baseline; explicit dispatch/retire/writeback bottlenecks | Same binaries, inputs and transaction-indexed memory-service contract; observed simultaneous issue, OoO completion, recovery and resource pressure |
| Formal invariants | Selected allocation, rename-map, retirement and recovery properties on actual generated modules | Reproducible solver commands, assertions, assumptions, covers and false-assertion controls; precise bounded/unbounded scope and remaining gaps |
| Physical/design-point evaluation | Reproducible synthesis configurations and constraints across issue width, PRF/ROB/queue capacities and prediction options | Source-bound netlist/cell/QoR and timing feedback; memory/register implementation assumptions; workload measurements motivating defaults |
| Integration closure | Full real-tool, ISA, application, PPE and committed legacy regressions on the selected current configuration | Fresh source/toolchain/input/generated-RTL identities, full architectural stream comparisons, no unexpected exclusions; implementing commits and final evidence attached to the issue |

Workload comparison must use the same realized transaction service, not merely
the same random seed with a cycle-dependent random generator. Separate
microarchitectural cycles and IPC from any technology/library-derived timing
estimate. Generic synthesis counts are not achieved silicon frequency or energy.
Area, timing and energy limitations remain explicit if physical implementation is
outside the gate's early-synthesis scope.

## Checkpoints and regression order

1. Keep the immutable APE-0.3 and APE-0.4 source/evidence checkpoints intact.
2. Complete the APE-0.5 execution gate, checkpoint recovery, pressure and standard
   ISA matrices, then application and real-tool compatibility. Preserve the new
   passing source checkpoint before widening the backend.
3. Make the frontend policy boundary explicit and verify it on the same gates.
4. Implement the wider candidate and controlled workload harness. Extend
   completion lease inventory and adversarial cases to every new lane/queue.
5. Run selected formal and synthesis studies. Retain failed/timed-out experiment
   status separately; choose configuration defaults from the combined evidence.
6. Re-run the complete selected-configuration integration gate and generate the
   final acceptance matrix. Review public-release/provenance boundaries, commit
   only scoped implementation/evidence, and record exact implementing revisions.
7. Resolve issue #4 only after every original acceptance row is supported by its
   actual evidence. Cache/MMU/OS/CP/tensor work remains in its own later stages.

## Completed acceptance path

APE-0.5 passed source-bound focused/formal and full integration gates; its
source/evidence checkpoint is preserved. The [dual-lane candidate](APE-0.6.md)
has passed its focused current-source gate and the narrow recovery regression.
The transaction-indexed service is integrated into an opt-in real-RTL runner;
the first controlled narrow/wide smoke passed, with higher cycle counts for this
dual-lane candidate on all four inputs. The [semantic frontend policy boundary](APE-SEMANTIC-BOUNDARY.md)
is now implemented and has passed component, multi-issue and early-recovery
gates. The physical-rename gate and both selected bounded formal gates also pass
on this source; the initial C4 time-limited attempt is retained separately. Full
current-source P64 integration and all 108 nine-point/two-service workload runs
have passed, as have all nine points of the [technology study](APE-TECHNOLOGY-STUDY.md).
The additional full PRF48 tool/ISA gate passed all 42 tool cases and 108 exact
ISA/recovery matches plus four unchanged standard-profile differences. The final collector
requires all nine physical points, current application/ISA evidence, a measured
design-selection record and an original-criteria completion review. The measured
report, selection and original-criteria review are complete. See
[S03 completion](../../../workloads/S03-COMPLETION.md) and the
[final evidence](../../../workloads/evidence/S03-CLOSURE.json). The collector cannot
promote a completed tool setup or one mapped configuration into S03 closure.
See [S03 progress](S03-PROGRESS.md) for preserved historical
results and the latest verified state.
