# First programmable PPE: RTL and verification contract

PPE means **Parallel Processing Engine**. This is original HATS SpinalHDL,
independently written against [PPE-ISA-0.1](PPE-ISA-0.1.md), not copied from a
private GPU implementation. It is the S02 minimum executable profile, not a
complete GPU, tensor engine, high-throughput CU or physical implementation.

## Implemented microarchitecture

`PpeCore(PpeConfig(programWords = 1024))` stores 1,024 64-bit instructions by
default. Supported generator capacities are powers of two from 16 to 65,536;
S02 verifies the default 8 KiB code profile. The larger code-object format does
not imply every instantiated core has that capacity.

One resident wave has eight logical lanes, 32 scalar 64-bit registers, 32 vector
registers of eight 64-bit elements, eight 8-bit predicates, and eight divergence
frames. Integer vector arithmetic uses eight combinational lane paths; global
and scratch memory operations select the lowest remaining active lane. Masked
lanes do no address, permission or memory work. A second launch is backpressured
until the current completion is accepted. This is runnable-lane selection within
one wave, **not a multi-wave scheduler**. A cluster is not implemented.

The state sequence is:

```text
IDLE -> CLEAR -> FETCH -> EXECUTE -> RETIRE -> FETCH
                            |
                            +-> LANE -> SEND -> WAIT -> LANE
                                  |                    |
                                  +-> LOAD_COMMIT ------+-> RETIRE
RETURN, fault, reject ------------------------------------> HALT -> IDLE
```

CLEAR zeroes all 4 KiB scratch, 64 bits per cycle. Scratch is an asynchronous-read
byte-write-enabled memory, separate from the global port; the declared accessible
reservation may be smaller. Register files are reset at launch. Vector reads
buffer lane results and publish the destination only if all selected reads
succeed. A fault after some stores does not roll back acknowledged stores.
The current asynchronous memories and combinational RF access have no claimed
SRAM mapping, clock target, timing closure, area or energy result.

## Direct-engine adapter and ownership

All `Stream` interfaces use valid/ready handshakes and require payload stability
while stalled. Program writes are accepted only while idle and no launch is
offered. The caller first validates the code object with `Code.decode`, then
loads its instruction words, and finally launches. RTL independently rejects
noncanonical instruction encodings and enforces dynamic stack/uniform-state
rules. Static structured-region ownership/branch validation remains a trusted
loader obligation; bypassing it is outside the application contract. Raw illegal
word tests intentionally bypass it to exercise decoder faults.

Launch carries task/epoch, address-space/generation, argument pointer/length,
group index/count, code-word count, scratch reservation, clock budget and one
global capability interval plus write permission. S0..S6 initialize to arguments,
length, group, group count, lane width 8, wave 0 and task respectively; V0/V1
contain lane IDs. Each group is launched by the host adapter. There is no CP,
queue consumption, child task, aggregate multi-group completion or OS service.

Global requests carry task, epoch, address-space ID/generation, monotonically
increasing transaction ID, address, width, data, write flag and lane identity.
There is one outstanding transaction. The service must register responses:
the earliest response is the cycle **after** request acceptance, never that same
cycle. A matching response completes the transaction. Stale responses are
consumed but do not publish a register/memory event or completion. The service
must itself enforce that error responses have no memory side effect.

The launcher must choose a fresh task/epoch identity before reusing a context;
reset/recovery additionally requires fabric quiescence. Resetting the transaction
counter at launch is not safe protection against replay with a reused identity.
The core faults before the 32-bit transaction counter wraps. These are explicit
direct-adapter obligations, not an implemented CP registration or isolation layer.

Completion is held until accepted. Status 1 is success, 2 is an execution fault,
and 4 is launch rejection. Cause codes 1..7 follow the ISA fault table, except
hardware cause 5 means **clock-budget exhaustion**, not instruction count.
Launch capacity/scratch errors use cause 7; invalid task/group/budget/range or
argument-overflow metadata uses cause 8. Rejected launches do not own or clear
scratch. Completion contains task/epoch, result, PC, fault address and lane mask.

## Timeout, synchronization and reset

The clock budget includes scratch initialization, execution and memory waits.
Expiration stops new work. An already-offered request must remain stable until
accepted; an accepted request must drain before fault publication or reuse.
At a response, a service error takes precedence over timeout. Loads that time
out do not publish buffered lane results; prior acknowledged stores remain.

If a request is never accepted, or an accepted transaction never responds, the
core cannot claim it safely drained. It stays busy and withholds completion.
The test explicitly checks a never-responding transaction past the watchdog,
then models external quiescence before reset. There is no hidden timeout ACK,
automatic cancel, preemption or resumable state-save mechanism.

FENCE/BARRIER require full mask and empty divergence stack. Since no subsequent
instruction retires before earlier memory drains, they order this one uncached
wave/domain. No inter-wave barrier, cache coherence or system-wide ordering is
claimed. Those are S04/S05/S06 obligations.

## Evidence and checker independence

- `ppe_isa.py`: specification-side encoding/model; original independent oracle.
- `build_ppe_cases.py`: binary fixtures and full model-state golden traces.
- `PpeCoreSim.scala`: drives real Verilator RTL, not an ISA interpreter; its
  memory service never reads expected register/results files.
- `verify_ppe.py`: checks every retirement's full registers/predicates/mask/depth,
  joint scratch/global order and retirement index, completion, complete memory
  and scratch images. Missing final-state fields fail, not silently disappear.
- `workloads/s02/test_gate.py`: deliberately corrupts traces, ordering, state,
  completion and final memory to prove rejection.

The 112-fixture matrix runs twice per case: 90 ISA-model cases, nine illegal
raw-word probes, ten launch rejections, two clock-budget protocols and one
never-reply protocol. Tests include all 37 opcodes, mixed/all-true/all-false and
nested/empty-arm divergence, eight/nine-frame limits, inactive predicates,
partial stores, failed-load publication, signed narrow memory, overflow,
scratch/alignment/permission failures, five stale-response identities, seeded
arithmetic, byte-classification groups/tails, random request/response stalls,
held completion and repeated launch. Special watchdog expectations are an
explicit protocol oracle, not disguised instruction-model matches.

DV inspection ports expose architectural state and scratch for comparison;
they are verification collateral, not a final package interface. Correctness
on this matrix is not full ISA certification or a formal security proof.
