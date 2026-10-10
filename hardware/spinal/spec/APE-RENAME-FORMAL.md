# Selected rename lifecycle formal contract

`formal/RenameLifecycleFormal.sv` instantiates the actual generated P36
`ApeRename`, including its physical registers, maps, free bitmap and retirement /
full-recovery logic. It consumes the immutable generated-RTL identity recorded
by the current passing recovery gate. No replacement behavioral DUT or hierarchical
read of private state is used.

## Environment and scope

The independent port scoreboard maintains a four-entry ordered allocation queue.
Allocation requests can remain asserted at capacity; legal writeback can select
any live unwritten entry, while commit can only remove the oldest already-written
entry. Full recovery can coincide with older commit. Clear represents relaunch.

This proof environment deliberately restricts:

- destination architectural register to x10; the other 31 registers retain their
  initial committed mapping;
- values to an arbitrary low bit with the other 63 bits zero, and launch argument
  to zero;
- recovery to full committed-map restoration; checkpoint capture and selective
  resolution inputs remain disabled;
- writeback to a currently live unwritten allocation, with no writeback during
  full recovery;
- reset to the initial global state, and clear to an edge without other activity.

These restrictions are assumptions, not proven whole-core control behavior.
Cross-register WAR/RAW dependencies, general 64-bit data, selective recovery,
execution-generation ownership and arbitrary external reset are not covered here.
They retain separate simulation/proof obligations.

## Checked properties

The scoreboard checks:

1. Physical free count equals four minus outstanding speculative writers.
2. Allocation readiness agrees with exhaustion and clear/recovery priority.
3. The speculative source tag names the youngest surviving writer, or the
   independently tracked committed mapping when no writer remains.
4. Readiness and same-edge writeback bypass agree with the youngest writer.
5. Ready source values and committed argument equal independently tracked data.
6. Zero-register state and disabled checkpoint occupancy remain correct.
7. Each newly accepted physical tag is in range and is distinct from the
   committed mapping and every live speculative owner.

Generated RTL assertions remain active. There are 24 assertion sites after
lowering, including 13 harness sites (four are the unrolled live-tag exclusion)
and 11 generated-RTL sites. Disabled checkpoint-input properties are not claimed
as exercised selective-recovery proof.

## Proof and reachability

The safety run is **bounded to 16 global transitions after `clk2fflogic`**, not
16 instructions, 16 retirements or an unbounded inductive proof. A separate
32-step cover search must reach all six witnesses:

- full physical pressure with allocation blocked;
- non-head, out-of-order writeback;
- simultaneous commit and allocation;
- simultaneous commit and recovery with younger work;
- allocation after recovery;
- clear after a commit.

A deliberately false harness assertion that free count remains four while a
speculative writer exists must produce a counterexample. It checks that the
proof setup reaches live allocation state; it is not a DUT mutation score.

The first complete run passed the bounded safety checks, all six covers, and the
false-assertion control. The source-bound runner also pins solver/package identity
and verifies generated RTL and report artifacts. Its current report is
`hardware/spinal/build/ape_rename_formal/steps16/validation.json`; `running`,
`failed_or_inconclusive` or timeout is not a current pass.

## Reproduce

From the repository root, with the existing formal tool environment populated:

```sh
python3 hardware/spinal/formal/verify_rename_lifecycle.py
```

No tool/library download is performed by this command. The harness's queue
storage is explicitly lowered with `memory_map` before SAT. The current scope
supplements the [checkpoint proof](APE-CHECKPOINT-FORMAL.md), actual core/Spike
regressions and port scoreboards; it does not close issue #4 by itself.
