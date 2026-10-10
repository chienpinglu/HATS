# APE-0.4: checkpointed execution-time branch recovery

This S03 / issue #4 increment adds selective early recovery to the physical
rename backend in [APE-0.3](APE-0.3.md). The implemented RV64 subset, precise
exceptions, launch protocol and head-only external memory contracts remain those
of [APE-0.2](APE-0.2.md). The timing of the diagnostic `redirect` output changes.
This is actual SpinalHDL/SpinalSim hardware, not completion of S03 or a claim of
a performance-qualified application core.

## Configuration and implementation boundary

| Parameter | Default | Tested boundary |
| --- | --- | --- |
| `earlyRecovery` | `true` | `false` retains retirement-time recovery as a comparison configuration |
| `branchCheckpoints` | 4 | 1 through `robEntries`; focused core tests use 1, 2 and 4 |
| `physicalRegisters` | 64 | Focused recovery tests use 36 and 64; rename-only unit additionally uses 33 |
| `robEntries` | 8 | Standard matrix uses 4/8/16; focused recovery witnesses use 16 |

`ApeCheckpoints.scala` stores snapshots indexed by ROB slot, with a separately
bounded live-checkpoint count. It physically describes **one snapshot row per ROB
slot**, not a compact array of `branchCheckpoints` rows. Reducing the capacity
changes admission pressure, not necessarily snapshot storage area. No SRAM,
physical timing or optimal capacity is claimed.

The core still dispatches, issues and retires at most one instruction per cycle.
Integer and branch results are synchronous with live issue; there are no delayed
younger execution-unit completions. Memory still has one outstanding head-owned
request. A ROB slot is sufficient for the present synchronous checkpoint interface;
it is **not** a safe completion identity for a future asynchronous pipeline.

## State and transition contract

**APE-ER-01 — Capture and admission.** A dispatched, valid control operation owns
a checkpoint until it resolves. Its snapshot is the speculative register map
*after* its own destination allocation (JAL/JALR link), if any. Source operands
are still read from the pre-allocation map. The checkpoint initially has an empty
younger-allocation bitmap. Each subsequent physical allocation marks every older
live checkpoint. A control operation stalls when no checkpoint is available;
there is no untracked-speculation fallback or same-cycle capacity-release bypass.

**APE-ER-02 — Resolution.** Correctly predicted resolution releases only that
checkpoint. A nonfaulting next-PC mismatch redirects during execution. Fetch can
dispatch from the new PC on the following cycle; it need not wait for the branch
to reach the ROB head. The branch keeps its own link destination and remains
subject to ordered retirement. Faulting control resolution releases its checkpoint
without redirecting or publishing its destination.

**APE-ER-03 — Selective restore.** On a redirect, restore the resolving branch's
post-destination map and reclaim its younger-allocation set into the *current*
free list. Preserve committed state, including any same-edge older commit:

```text
free_after_recovery = free_after_older_commit | younger_allocations
speculative_map    = branch_post_destination_snapshot
committed_map      = committed_map_after_older_commit
```

Restoring an old free-list snapshot would lose interleaved retirement updates.
In-order retirement prevents younger destinations from becoming committed while
an older unresolved checkpoint is live. An assertion rejects reclaiming committed
ownership. Nested redirect/reallocation keeps the outer checkpoint's younger set;
it continues to own the classification of reused younger tags.

**APE-ER-04 — ROB and publication.** Ring distance from the current head defines
age. Remove only entries younger than the resolving branch, move the tail just
after it and account for any simultaneous older retirement in occupancy. Preserve
older checkpoints and invalidate the resolving and younger checkpoints. Dispatch
is suppressed on that redirect edge. A pending older head-memory transaction
survives and may complete normally. Younger addresses may have been calculated,
but no younger load/store can have published an external request.

**APE-ER-05 — Exceptions and lifecycle.** A fault at the head takes priority over
younger issue/recovery, restores the committed map and clears all checkpoints.
An older load may fault after a younger branch already redirected; the eventual
precise halt still discards all uncommitted younger state. A recovered branch
does not redirect a second time at retirement. Its original prediction is retained
for retirement statistics and qualified predictor training. Reset/accepted launch
clear checkpoint ownership. Reset still requires a quiesced external memory service.

The core tracks `checkpointed` and `recovered` per ROB slot and asserts that live
ROB checkpoint ownership agrees with the rename unit's checkpoint count. The
existing PRF/free/commit and head-only publication assertions remain enabled.

## Observation interface revision

| Output | Meaning in the default early-recovery configuration |
| --- | --- |
| `redirect` | Nonfaulting execution-time next-PC mismatch, not retirement |
| `resolved` | Control issue: slot, PC, predicted/actual next PC, fault and older-work observations |
| `squashed` | ROB slots invalidated by a selective redirect |
| `predicted.slot`, `controlRetired.slot` | ROB-slot association for trace consumers; not persistent generation tokens |
| `checkpointsUsed`, `checkpointBlocked` | Live count and dispatch admission stall |

Successful retirement and architectural memory traces keep their previous
meaning. The core testbench maintains a resolution ledger, checks each retiring
control against its resolution and discards ledger entries on squash. A speculative
redirect may itself later be squashed; redirect counts therefore need not equal
retired misprediction counts. The `earlyRecovery=false` configuration explicitly
keeps the historical retirement-time `redirect` contract.

## Verification and observed scope

From `hardware/spinal`, run the focused gates sequentially:

```sh
python3 tools/verify_ape_recovery.py
python3 tools/verify_ape_rename.py
```

The recovery gate executes 32,000 cycles of the actual rename/checkpoint RTL in
four P/capacity configurations. Its independent port-only oracle reconstructs
mapping and ownership by replaying surviving instructions from committed state,
not by duplicating the DUT's snapshot/bitmap algorithm. It covers nested restores,
same-edge older commits, physical/checkpoint exhaustion and tag reuse.

Six linked RV64 witnesses run twice in nine core configurations: prediction
off/bimodal, P=36/64, capacity=1/2/4 and early/retirement recovery. All **108**
architectural event traces must match pinned Spike exactly; this gate permits no
profile exclusions. Dedicated checks require recovery and target issue while an
older request is pending, nested resolved-branch squash, older commit concurrent
with redirect, link retention/fault suppression and resource stalls.

For example, `older_load-0` with ROB16/P64/C4 and prediction off recorded request
acceptance at cycle 4, redirect at 7, correct-target issue at 9 and the old load's
response at 22. This demonstrates earlier recovery; a final a0 match alone would
not. These are simulation-cycle observations, not achievable clock or speedup.
Early/retirement cycle summaries use the same randomized memory-service policy,
but cycle-driven random draws can produce different realized waits. They are
**not a controlled performance comparison** and cannot select the final design.

The gate hashes sources, generated RTL, fixtures and architectural/diagnostic
traces in `build/ape_recovery/gate.json`. Full compatibility additionally requires,
from the repository root:

```sh
python3 workloads/s02/run_all.py --output workloads/results/s03-recovery-compatibility.json
```

Current completed results and historical anchors are in [S03 progress](S03-PROGRESS.md).
Do not treat a historical source hash or a compile-only run as verification of
the current RTL.

## Explicit remaining gaps

- Pipelined completion identity, stale-result rejection and generation-wrap safety.
- Independent/wider issue queues, multi-issue candidate and completion arbitration.
- Broader/unbounded actual-RTL formal invariants. The selected
  [component gate](APE-CHECKPOINT-FORMAL.md) covers a shallow 12-global-step bound
  at P36/C1 and P36/C4, not the full rename/retirement/recovery state machine.
- Matched-memory workload measurements, synthesis/timing/area and size selection.
- The remaining ISA-policy separation, extended reset/adversarial cases and full
  Issue #4 acceptance evidence.

This revision does not add caches, MMU, OS execution, CP/runtime, tensor execution
or end-to-end agent acceleration. Simulation assertions and the replay scoreboard
are not formal proof; the separate bounded formal gate has its own explicit scope.
The [recovery plan](APE-EARLY-RECOVERY-PLAN.md) retains the
future completion-ownership obligations rather than claiming them satisfied here.
