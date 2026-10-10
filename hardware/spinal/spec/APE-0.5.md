# APE-0.5: registered execution and qualified completion

Status: implementation under verification; S03 / issue #4 remains open.

This increment replaces issue-time combinational completion with a registered
integer/branch/address pipeline. The preserved APE-0.4 source/evidence checkpoint
is the historical regression anchor, not evidence for the changed RTL.

## Execution contract

`ApeExecute` accepts a typed request containing operands, operation, memory
protection bounds, fault metadata and a completion identity. The default path is:

```text
ROB oldest-ready selection -> operand register -> integer / branch / AGU
                                                  |
                                              result register
                                                  |
                              memory-priority completion arbitration
                                                  |
                                   ROB ownership qualification
                                                  |
                              PRF writeback / wakeup / ROB completion
```

Default latency is two cycles from accepted issue to the earliest completion.
Both pipeline registers are elastic: downstream backpressure can retain their
payloads indefinitely. Selection is held while the input is backpressured.
The configurable depth range is 2–32; stages beyond two are result-delay
registers for stress/design experiments, **not additional arithmetic timing
cuts**. No clock-frequency benefit is inferred from adding these registers.

Branch resolution, checkpoint release, faults and address preparation occur only
on qualified completion. A load/store's address completion does not perform an
external transaction: external requests still require the non-speculative ROB
head. A memory response has priority on the single PRF broadcast port and stalls
execution completion. Selection and issue may continue if the operand pipeline
has space.

## Completion identity and finite generation safety

Each dispatched ROB owner receives `(slot, generation, destination)`; generation
advances modulo its configured 1–4-bit width. Every pipeline stage retains that
identity. `ApeCompletionGuard` accepts a completion only if the selected ROB owner
is live, issued, not already complete/address-prepared, and has matching
generation and physical destination. Qualification is followed by active/flush
gating in the core. Only accepted results can write registers, wake dependents,
set completion, resolve control flow or prepare memory effects.

A large counter is not a wrap-safety argument. Before dispatch, the core compares
the proposed `(tail, next generation)` against **all** occupied execution stages.
A collision stalls allocation, even if the old token has already been squashed.
Physical destination is intentionally excluded from this allocation check: a
different destination does not make reuse of the same generation safe. The
pending-token inventory is the lease set; no bounded execution/stall time is
assumed. The lease is conservatively retained through the edge that consumes a
completion. Reuse is permitted on a later cycle.

The pending inventory must grow with every future execution lane, queue or
delayed-result producer. An untracked result source cannot use this contract.
External memory is a separate, single head-owned transaction and cannot survive
owner retirement/reuse; it is not an execution lease.

## Recovery and lifecycle priority

1. Precise head fault or retirement-mode redirect clears the execution pipeline
   synchronously and restores committed rename state. A completion cannot publish
   on that edge. Older memory has already drained before such retirement.
2. A qualified early branch redirect preserves older ROB entries and pending
   head memory. Younger ROB entries and physical allocations are reclaimed.
   Younger execution tokens remain in the local pipeline and are subsequently
   rejected. Newly dispatched instructions may reuse their physical tags safely.
3. Dispatch and issue are suppressed on the early-redirect edge. Older retirement
   can still coincide with the checkpoint restore.
4. Launch clears all local execution registers, ROB ownership and rename state.
   It is accepted only after the previous halt is consumed and memory is drained.
   Generation counters need not reset because no local tokens survive the clear.
5. Hardware reset clears valid/ownership state. As before, the external memory
   environment must reset/quiesce with the core; arbitrary reset of only the core
   during an accepted external transaction is not a supported system contract.

## Verification obligations

- Port-only pipeline scoreboard: accepted requests, exact pending lease inventory,
  register latency, ordered transport, output hold under long backpressure and
  cancellation on clear, with shallow/deep pipelines and 1-/2-bit generations.
- Guard tests: stale generation, different physical destination, dead/unissued
  owner and duplicate completion; wrap exclusion with resident tokens.
- Core scoreboard: observe issue identities and squash events independently of
  internal guard state; require every completion to belong to an outstanding
  token and every killed token to be rejected. Verify architecture at retirement.
- Retain actual OoO, wrong-path external-effect suppression, precise faults,
  checkpoint pressure, older-memory survival and relaunch witnesses.
- Exact external Spike comparison and real-tool regression on current RTL.

The first two are unit evidence, not a proof of whole-core lease completeness.
Integrated counters distinguish rejected late results, rejection after slot reuse,
physical-tag reuse while a killed token remains pending, and canceled tokens at
precise stop. A zero counter is not reported as exercised coverage.

## Remaining S03 scope

Issue width and retirement width remain one. The reservation operands still share
ROB rows, and the execution datapath retains RV64 word/PC/fault policy. Multi-issue
evaluation, the remaining semantic/architectural-policy separation, broader
allocation/rename/retire/recovery formal checks, source-bound application
compatibility, synthesis constraints and workload-driven design-point selection
are separate requirements before issue #4 closure. Simulation latency and IPC do
not establish achieved frequency, silicon energy or end-to-end agent speedup.

## Commands

From `hardware/spinal`:

```sh
bash tools/sbtw 'Test / runMain hats.ApeExecuteSim' \
  'Test / runMain hats.ApeCompletionGuardSim'
python3 tools/verify_ape_recovery.py
python3 tools/verify_ape_spike.py
```

The core test accepts optional `executionStages generationBits` after its existing
suite selector; for example:

```sh
bash tools/sbtw 'Test / runMain hats.ApeCoreSim 8 off 64 4 early standard 2 1'
```

Variant outputs are isolated under `build/ape_execution/core/`; they do not
replace the default compatibility matrix.
