# HATS task execution architecture

## Purpose and architectural decision

HATS will execute supported agent-runtime programs on a task-parallel processor,
including the control flow between model and tool operations. The CPU provides
privileged services and compatibility paths instead of scheduling each step.
SpinalHDL and SpinalSim are the microarchitecture development
path. The scalar-execution direction is now RISC-V, with HSA-inspired queues and
memory ordering. The [HATS Application Processing Engine (APE)](APE.md) requires speculative
out-of-order execution independently of the legacy A64 TaskTile described below.
The two prototypes are not yet integrated: APE does not inherit TaskTile's
fork/join support merely by sharing this build.

This is a design direction with a first RTL mechanism prototype. It does not
establish CPU replacement, speedup, power efficiency, or general software support.

## Target package

A RISC-V service subsystem with local LPDDR connects to four programmable compute
domains. Each domain contains independently scheduled task contexts, scalar
execution pipelines, vector/tensor engines, local caches and scratchpad, HBM,
and independently attached LPDDR. Domains are locality regions, not necessarily
separate dies. HBM and LPDDR controller/PHY implementation is a separate task.

The target scheduler creates work near its data, wakes suspended continuations,
and routes bulk operations to vector/tensor engines. A policy-driven runtime
chooses placement, migration, ownership and experiment budgets. It is not a
fixed hardware implementation of an RSI algorithm or agent framework.

CPU-local LPDDR serves latency-sensitive service state. Domain HBM serves hot
high-bandwidth data. Domain LPDDR extends capacity for both compute and authorized
remote CPU accesses. Locality and tier are distinct properties. Durable task
archives require storage; neither HBM nor LPDDR is persistent.

## Legacy first tile (A64 mechanism prototype)

The first tile has one shared scalar execution pipeline, four contexts by
default, and an idle-loadable instruction memory. Each context owns 31 usable
64-bit registers, a 64-bit byte PC, one child slot and one memory continuation.
Context count and instruction capacity are power-of-two generator parameters.

The current scheduler visits one slot per cycle in round-robin order. It does
not scan ahead to a ready context, so idle slots consume opportunities. Response
handling and request acceptance can also displace issue. This explicit,
conservative implementation is not a throughput-optimized scheduler.

Context states are FREE, RUN, ISSUE, MEMORY, JOIN and DONE. A RUN context executes
its own instructions and branches. ISSUE holds a memory request waiting for bus
acceptance; MEMORY waits for its response. JOIN waits for its child's DONE state.
Hardware wakes MEMORY and JOIN contexts; the host never supplies a resume PC.

Telemetry includes invocation cycles, issued instructions, spawned children,
memory-response wakeups and join wakeups. The instruction counter records decode
attempts accepted for execution, including faulting instructions; it is not an
Arm architectural retirement counter. Memory-request retries are excluded.

Supported A64 forms are MOVZ/MOVK X, ADD/SUB X immediate without SP, ADD X register
without shifts, LDR/STR X unsigned immediate without SP, B, CBZ/CBNZ X, NOP and
BRK #0. Register 31 is XZR where supported; SP forms are rejected. BRK #0 is a
prototype completion convention, not architectural exception handling. There
are no flags, stack implementation, BL/RET, FP/SIMD, atomics, barriers, privilege
levels or architectural exceptions. Other encodings fail the invocation.

## Task interface

The following memory-mapped ABI operates within the tile. Addresses are reserved
and cannot be ordinary data memory. No custom A64 opcodes are used.

| Operation | Interface | Semantics |
| --- | --- | --- |
| Submit root | Host launch stream | Supplies PC, X0, allowed data interval and write permission |
| Spawn | STR Xn to 0xff00 | Value is child entry PC; child inherits parent X0 and invocation capability; other child registers are zero |
| Spawn return | Parent X0 | Receives child slot number; no general-purpose future handle API yet |
| Join | LDR Xn from 0xff08 | Suspends parent and writes child's X0 into Xn when child is DONE |
| Complete | BRK #0 | Marks context DONE with result X0; an unjoined child is an error |
| Cancel invocation | Host cancel input | Stops new instruction issue; drains already presented/accepted memory work |

Each parent may own one child at a time. After join, the slot is freed and can
be reused. Children can spawn children, forming a bounded fork/join tree. There
is no work stealing, context spilling, multiple-child fan-out or detached task
support in this version. No free slot produces an explicit resource fault for
the entire invocation; it does not busy-wait into a scheduler deadlock.

All faults are fail-fast for the invocation, including child faults. Precise
architectural exception state and partial-result recovery are not implemented.

## Memory interface and protection

Requests and responses are independent ready/valid streams. There is one shared
held request register and at most one accepted outstanding transaction per
context. Requests carry context, 64-bit address/data, write flag and memory-target
tag; the access size is fixed at eight bytes. Request payload remains stable
while stalled. Responses may arrive in a different order across contexts.

The memory service must return exactly one response per accepted request and
must not respond in the acceptance cycle. The context identifier is sufficient
only under that contract. Generation-tagged transaction identifiers and robust
late/duplicate response containment are future requirements. Reset requires
quiescing or resetting the attached memory service; it is not a transaction
cancellation mechanism.

Data accesses must be aligned, fully inside the launch's [base, limit) interval,
and obey its write permission. All child contexts inherit the same capability:
this is invocation-level containment, not isolation between mutually untrusted
children. Instruction memory is shared within the invocation and immutable while
busy. The host must load every reachable instruction word before launching.

The route tags represent the proposed topology, not physical memory controllers:

| Tag | Address interval | Logical target |
| --- | --- | --- |
| 0 to 3 | 0x10000 to 0x4ffff, four 64 KiB windows | Domain 0 to 3 HBM |
| 4 to 7 | 0x50000 to 0x8ffff, four 64 KiB windows | Domain 0 to 3 LPDDR |
| 8 | 0x100000 to 0x1fffff | CPU-local LPDDR |

The tiny capacities support tests, not capacity planning. One tile emits tags;
there is no nine-controller fabric or measured NUMA model. No cache-coherence,
HSA-conformance or Arm memory-model claim follows from ordered local tests.

Cancellation is not rollback. A store already presented to the service may
still execute. The tile stops new work but holds requests until accepted and
drains responses before publishing completion. Completion remains stable under
backpressure; a new launch is accepted only after completion is consumed. A
nonresponsive memory service can prevent drain; timeout and fault-containment
hardware remain a subsequent milestone.

## Verification contract

Test programs are assembled by Clang for aarch64-none-elf. Unresolved
relocations are rejected. The testbench loads code, submits a root task and
provides memory service. It never picks a context, submits child tasks or
resolves joins. Tests include nested tasks, slot reuse, variable stalls,
cross-context response reordering, all nine tags, rejected accesses, faults,
cancellation, held completions and restart without reset.

SpinalSim executes generated RTL through Verilator. Memory is a behavioral
testbench service with synthetic timing, not a modeled HBM/LPDDR controller.
Observed cycles therefore establish mechanism behavior only. RTL tests cannot
establish agent speedup, PPA, physical memory performance or CPU displacement.

## Next architecture increments

The [workload coverage and OS cooperation contract](../../workloads/COVERAGE.md)
now tracks the CPU-side source workloads and the proposed address-space, fault,
preemption and service interfaces. Its host tests are separate from RTL tests;
the tile does not yet execute them. OS awareness is an architectural requirement,
not a claim that this A64 subset supports an OS or application ABI.

1. Broaden scalar execution and add bounded stacks, calls and a compiler-facing
   task runtime. Keep semantics differential-tested against independent models.
2. Add runnable-task selection, multiple-child futures, generation-tagged
   transactions, watchdogs and context spill or work-first resource handling.
3. Integrate a vector/tensor execution queue. Tasks must suspend/resume on real
   datapath completion; testbench-produced arithmetic is not integration proof.
4. Add L1 caches, translation/protection, explicit ordering and a multi-domain
   fabric. Decide coherence and ownership boundaries before implementing them.
5. Compile and execute an actual agent-control or compiler-pass workload through
   this path; compare CPU work, end-to-end latency and energy at equal quality.
6. Synthesize and evaluate implementation timing/area using explicit memory and
   library assumptions. Change execution width/context count based on evidence.

The full software target is an accelerator-resident agent execution loop. The
small fork/join example is a necessary mechanism test, not that final target.

## Verified starting point

The 2026-10-03 run passed 41 scenarios at each of 2, 4 and 8 contexts through
SpinalSim and Verilator. The four-context nested-task scenario created three
children and completed three joins after one root submission. The response-order
test observed an actual inversion of memory completion order. The suite also
checks cancellation before request acceptance and while waiting for a response.
All scenarios additionally check held completion and cancellation after restart.

Run `python3 tools/verify.py` to produce a source-hashed `build/validation.json`
and detailed per-configuration results. Generated evidence remains untracked.

## Source basis

- [SpinalHDL](https://spinalhdl.github.io/SpinalDoc-RTD/master/SpinalHDL/Introduction/SpinalHDL.html).
- [SpinalSim](https://spinalhdl.github.io/SpinalDoc-RTD/master/SpinalHDL/Simulation/index.html).
- [Spinal Stream interfaces](https://spinalhdl.github.io/SpinalDoc-RTD/master/SpinalHDL/Libraries/stream.html).
- [Official sbt template](https://github.com/SpinalHDL/SpinalTemplateSbt).

The task microarchitecture and restrictions above are original project choices,
not claims made by those references.
