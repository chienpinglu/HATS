# APE-0.3: physical integer renaming

Historical physical-renaming baseline. [APE-0.4](APE-0.4.md) now supersedes this
revision's retirement-only recovery and extends the observation interface; the
physical allocation/commit rules below remain its foundation. Dated APE-0.3
evidence is preserved separately and must not be presented as current RTL evidence.

This revision implements the first backend increment of [S03 / issue #4](https://github.com/chienpinglu/HATS/issues/4).
It is not completion of the performance-core milestone. The instruction, exception,
prediction, launch, memory and publication contracts in [APE-0.2](APE-0.2.md)
remain unchanged. This document supersedes that revision's rename/scheduling
implementation and extends its configuration and observation interfaces.

## Implemented boundary and configuration

`ApeDecode.scala` owns RISC-V encoding extraction and produces `ApeDecodedOp`.
Branch condition, memory width and load signedness are typed semantic fields;
raw `funct3` no longer reaches the scheduler or load extension logic.

This is a first boundary, not a completely ISA-independent backend. Fixed
instruction length, x0, the 32-register integer class, word sign extension,
RISC-V fault numbers and JALR masking remain RISC-V policies in the core/renamer.
Flags, multiple destinations and macroinstruction grouping are not implemented.
No AArch64 frontend or dual-ISA capability is claimed.

`ApeConfig.physicalRegisters` defaults to **64**, with an elaboration constraint
of 33 through 256 (non-power-of-two counts are permitted). The rename unit is
tested at 33, 36 and 64; the integrated core at 36 and 64. Other counts are not
validated merely because elaboration accepts them. ROB capacity remains separate
from physical-register capacity. The default is a correctness baseline, not a
workload/synthesis-optimized size.

For this one-destination, no-checkpoint-replay implementation, each unretired
writer owns at most one additional physical register beyond the 32 committed
mappings. Thus `P >= 32 + robEntries` is a structural no-rename-exhaustion sizing
bound for the present dispatch policy, not a performance optimum or formal RTL
proof. P=64 has ample slack for the tested ROB4/8/16 configurations; ROB16/P36
deliberately allows only four additional destinations and exercises backpressure.
Future recovery/pipeline designs must reassess this bound with their ownership
rules. A larger PRF alone does not widen issue or permit more memory transactions.

## Physical state and ownership

`ApeRename.scala` contains a physical 64-bit integer register file, readiness bits,
speculative and committed maps, a free bitmap and a committed-live bitmap.
These are actual generated RTL state, not software-emulated registers.

| State | Rule |
| --- | --- |
| Physical register 0 | Always zero, ready, committed and never free |
| Initial mappings | Architectural x0..x31 map to physical 0..31 |
| Initial free entries | Physical 32..P-1 |
| Speculative map | Names the youngest dispatched destination for each architectural register |
| Committed map | Names the last successfully retired destination |
| Physical ready bit | Cleared on allocation; set by successful writeback |
| ROB destination tag | Physical destination ownership independent of the ROB slot index |

**APE-PRF-01 — Allocation:** A valid nonzero destination consumes the lowest free
physical register and an ordered ROB slot in the same dispatch. An exhausted free list
stalls only instructions requiring a destination; stores, branches, x0 destinations
and fetch/decode faults do not need one. When the list is empty, a register freed
by a simultaneous retirement becomes allocatable on the following cycle, not via
a same-cycle free-list bypass. The ROB remains the fused reservation station.

**APE-PRF-02 — Operand capture and writeback:** Sources read the speculative map
before the new destination mapping is installed, including a read/modify/write
of the same architectural register. Ready sources capture physical values; other
sources wait on physical tags. A same-cycle writeback bypass feeds newly dispatched
consumers. One successful integer/load completion broadcasts its physical tag and
value and wakes existing waiters. Memory response has priority over ALU issue.
Failed loads and faulting instructions do not produce valid physical writeback.

**APE-PRF-03 — Retirement:** The completed, nonfaulting ROB head may retire. A
destination-writing retirement installs its physical register in the committed
map and releases the previous committed mapping, even if a younger speculative
mapping exists. The speculative map is not overwritten by normal retirement.
In-order retirement guarantees that consumers of the released old value have
already completed. The committed map and physical file replace the separate
architectural-value array; ROB result storage remains for retirement observation.

**APE-PRF-04 — Precise recovery:** Recovery still occurs at the ROB head. It
discards all younger entries, restores speculative mappings from committed state
and sets the free bitmap to the complement of the committed-live bitmap. A
same-edge successful retiring link write is included in both recovered mappings
and retained ownership. A faulting head does not commit a destination. Stale data
in released physical registers is harmless: each new allocation clears readiness.
There is no speculative checkpoint, replay queue or early branch recovery yet.

**APE-PRF-05 — Reset and relaunch:** Reset initializes the maps/readiness/free
state. An accepted launch takes priority over normal renamer state updates,
reinitializes all maps and registers and places the argument in physical a0.
The core only accepts launch after quiescence as in APE-0.2. Arbitrary late
writebacks after recovery or reset are not a supported component interface;
future pipelined units require squash/epoch ownership before integration.

## Timing and observation interfaces

Reads, allocation selection and operand forwarding are combinational. This is
currently a flop-based model, not a SRAM macro selection or evidence of timing
closure. Dispatch/issue/retirement are each at most one instruction per cycle.

The existing public core ports are preserved. Added diagnostic outputs:

- `physicalFree`: number of currently free physical registers, width `log2Up(P+1)`.
- `renameBlocked`: active dispatch is otherwise eligible (ROB space, no flush),
  needs a destination and lacks a free register.

`rename_stall_cycles` counts this signal in the core regression harness. It is
not wall-clock latency, a silicon IPC improvement or energy measurement.

## Executable verification

From `hardware/spinal`:

```sh
python3 tools/verify_ape_rename.py
python3 tools/verify_ape_spike.py
python3 tools/verify_ape_app.py
```

The first gate freshly runs 6,000 cycles per 33/36/64-register renamer using a
port-only ownership/value scoreboard, then runs 50 core scenarios twice in each
of the ROB16/P36 prediction-off and bimodal configurations. It independently
reruns pinned Spike and checks every architectural event, with the same two exact
profile differences as the standard matrix. Source, reference and evidence hashes
are recorded in `build/ape_rename/gate.json`. A nonzero rename-stall count is
required in each pressure configuration; a merely passing unconstrained run is
not exhaustion coverage.

The randomized unit gate includes directed exhaustion after relaunch, non-FIFO
writeback, WAW mapping chains, clear/relaunch and simultaneous commit/recovery.
RTL assertions check x0, committed/free exclusion and valid allocation,
writeback and retirement ownership. These are **simulation checks, not formal
proofs**. End-to-end tools and PPE/legacy anchors require the full S02 regression:

```sh
python3 workloads/s02/run_all.py --output workloads/results/s03-compatibility.json
```

Run the last command from the repository root and run all sbt-based gates
sequentially. Exact result counts and the remaining S03 work are recorded in
[S03 progress](S03-PROGRESS.md); old APE-0.2 evidence does not validate new RTL.

## Still required by S03

Branch checkpoints and earlier selective recovery; pipelined execution with stale
completion rejection; evaluated multi-issue/scheduling options; selected formal
invariants with assumptions; expanded reset/resource-pressure tests; workload-
justified sizes/prediction and synthesis/timing evidence. Wider memory, OS and
CP/runtime integration remain separate roadmap work. This revision establishes
physical renaming, not the completion or acceleration of an agentic-AI processor.
