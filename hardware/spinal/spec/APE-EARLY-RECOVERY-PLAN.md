# APE early branch recovery: design obligations and implementation status

**Partially implemented in [APE-0.4](APE-0.4.md).** Map checkpoints, selective
execution-time recovery, older-work preservation and the synchronous RTL witnesses
are implemented. [APE-0.5](APE-0.5.md) adds generation-qualified delayed completions
and resident-token wrap exclusion. Broader formal proofs and performance/physical
design-point evidence remain open. This document preserves
the broader obligations; it is not a claim that all of them are already satisfied.
It does not add an ISA or change the memory model.

## Objective

Redirect fetch when a live, nonfaulting branch resolves incorrectly, retaining
all older instructions and the resolving branch while discarding only younger
work. Preserve the architectural traces of the current independent Spike and
real-tool gates. Demonstrate the earlier redirect in actual RTL under an older
blocked load; a final-result match alone does not prove early recovery.

Start with one dispatch, one issue and one retirement per cycle. Registered
execution is now implemented; wider issue remains a separate design point. Keep head-only external memory so
this increment does not also introduce speculative loads or store rollback.

## Checkpoint state

Each dispatched control instruction that can redirect needs a bounded checkpoint:

- A ROB identity and position in program order. APE-0.5 qualifies completion by
  allocation generation and physical destination before resolving a slot-owned checkpoint.
- The speculative register map **after** that instruction's own link destination
  allocation, if any. Its source operands still come from the pre-allocation map.
- The tail position immediately after the branch. The current core derives this
  from slot and ring distance relative to the live head/count after generation qualification.
- A set of physical registers allocated by younger instructions while this
  checkpoint is live. Every new physical allocation updates older live checkpoints.

Use a configurable checkpoint capacity. Exhaustion stalls a control instruction
requiring a checkpoint without losing its fetch/decode identity. Do not silently
fall back to untracked speculation. Size selection requires measured occupancy
and timing; no capacity is selected as a high-performance optimum here.

## Why restoring a saved free bitmap is insufficient

Older instructions may retire after a branch checkpoint was made. Their retired
mapping changes and released physical registers must survive recovery. Restoring
the old free bitmap can lose newly freed registers or reintroduce stale ownership.

The implemented synchronous recovery rule is:

1. Retain the current committed map, including any legal same-edge older retirement.
2. Restore the resolving branch's post-destination speculative map.
3. Reclaim its younger-allocation set into the current free set, excluding any
   retained ownership; do not roll committed state back to checkpoint time.
4. Preserve older checkpoints; invalidate younger ones and the resolved checkpoint.
5. Remove younger ROB/issue entries, update tail/occupancy and redirect fetch.

An instruction younger than an unresolved branch cannot retire before it, so its
destination cannot become committed during that checkpoint's lifetime. Nested
recovery may free and reallocate a physical tag; the outer checkpoint must continue
to classify the new allocation as younger. Assertions and the reference scoreboard
must check these facts instead of relying on an undocumented free-list shortcut.

Correctly predicted resolution releases the checkpoint without freeing physical
destinations. Branch retirement still commits its destination normally. A branch
with a misaligned target is a fault, not a successful early redirect: preserve
precise head-only fault delivery and suppress its link write.

## Completion and publication ownership

Completion identity must name the live allocation, not merely a reused ROB index
or physical register number. The registered pipeline now carries a
generation-qualified ROB token with a destination-ownership check. A squashed
producer must never write a physical tag subsequently assigned to another producer.

A single global epoch that rejects every pre-redirect completion is insufficient:
older nonsquashed loads or execution units may still be outstanding. Accept their
valid completions; reject only invalidated allocations. Generation wrap safety
needs a bounded outstanding-lifetime argument or a drain/reuse protocol. APE-0.5
uses the latter: allocation cannot alias a token in any execution stage.

With current head-only memory, an older accepted request remains owned and must
complete through recovery. Younger loads/stores may have prepared addresses but
must not have published external requests. Reset still requires a quiesced service.
Adding speculative memory later needs its own replay and side-effect contract.

## Fault and observation priorities

A precise fault retiring at the head dominates a younger redirect. A redirect
from an instruction already squashed by an older redirect is ignored. The first
implementation may serialize competing completions, but must specify the order
and demonstrate forward progress under a responding memory service.

After a branch redirects early, its later retirement must not redirect again.
Retain the original prediction for statistics and retirement-time predictor
training; separately track whether recovery has already been applied. Changing
`io.redirect` from a retirement event to an execution event is an observation
contract revision. Update trace consumers explicitly; do not reinterpret old
counts as proof of the new timing.

## Required tests before accepting the increment

| Requirement | Actual RTL witness |
| --- | --- |
| Earlier recovery | Younger branch redirects while an older load is still outstanding, then that load retires correctly |
| Link ownership | Mispredicted JAL/JALR retains its own result; misaligned target never commits it |
| Nested branches | Younger redirect followed by an older redirect preserves the right map/free ownership both times |
| Interleaved retirement | Older commit and recovery on the same edge retain newly committed mappings and freed registers |
| Resource pressure | Checkpoint and physical free-list exhaustion, ROB wrap and repeated tag reuse without loss or double allocation |
| Squashed completions | Inject delayed younger completion after reallocation; no value/readiness/map corruption |
| Precise exceptions | Older fault defeats younger redirect; wrong-path faults and MMIO never become externally visible |
| Trace compatibility | Full APE/Spike, bounded application and S02 real-tool/PPE/legacy gates remain valid |

APE-0.4's focused gate implements all synchronous witnesses above, including
the older-load timing observation and nested ownership replay. The squashed
*delayed completion* row is explicitly unimplemented because no such execution
interface exists yet. The full compatibility result must be freshly reproduced
against the same source hashes; see [S03 progress](S03-PROGRESS.md). The checkpoint
capacity currently limits live occupancy in a ROB-indexed snapshot array, not
the physical number of snapshot rows.

Selected formal properties should cover map range/injectivity, committed/free
exclusion, unique allocation ownership, no squash of older work, no accepted stale
completion and precise retirement. A formal harness must model legal allocation,
completion and retirement sequencing and state its fairness/reset assumptions.
Simulation assertions alone are not the formal acceptance result.

Report branch-resolution-to-fetch-redirect delay and recovery/stall cycles as
microarchitectural diagnostics. Compare workload cycles only under identical
binary/input/memory assumptions; separately obtain synthesis/timing evidence.
The current focused early/retirement summaries share a randomized service policy
but not necessarily the same realized waits, and are not a controlled performance
study. S03 still needs a matched-memory comparison for design-point selection.
