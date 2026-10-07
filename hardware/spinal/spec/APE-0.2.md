# APE architecture and interface specification

Revision **APE-0.2** defines the current Application Processing Engine RTL, not
the eventual full HATS processor. APE is an original single-hart RV64 integer
engine with mandatory speculative out-of-order execution and in-order retirement.
It targets application work; CP queue management and CU scalar execution are
separate roles. The implementation is [ApeCore](../src/main/scala/hats/ApeCore.scala).

## Configuration

| Parameter | Default | Constraint and meaning |
| --- | --- | --- |
| `robEntries` | 8 | Power of two, at least 4; tested at 4, 8, 16 |
| `programWords` | 1024 | Power of two, at least 16; regression uses 1024 |
| `prediction` | true | Bimodal conditional and direct JAL prediction; false means fall-through |
| `predictorEntries` | 16 | Power of two, at least 2; core matrix uses 16; predictor unit tests use 2 and 16 |

The engine dispatches, issues and retires at most one instruction each per cycle.
These operations can overlap. The implementation is not superscalar. Instructions
are fixed 32-bit words; the PC and architectural integer registers are 64 bits.
Instruction memory is separate from external data memory and uses asynchronous
read in the current generator. It is not an L1 cache or a physical SRAM model.

## Instruction and exception contract

APE implements the RV64I integer ALU, word-width ALU, LUI/AUIPC, conditional
branches, JAL/JALR, integer loads/stores, FENCE and EBREAK described in [APE](../APE.md).
Arithmetic wraps at the selected width; word results sign-extend to 64 bits.
JALR clears target bit zero, then checks four-byte instruction alignment. A
non-taken conditional branch does not fault on its unused target's alignment.
Loads to x0 still access memory and can fault; x0 is never renamed or written.

M/A/C/F/D/V, CSR instructions, privileged execution, ECALL and FENCE.I are absent.
Unsupported encodings in the implemented decoder raise illegal-instruction faults.
There is no Linux boot, syscall ABI, interrupt delivery or resumable trap handler.
This subset must not be advertised as complete RV64I compliance.

| Cause | Meaning and reported PC |
| --- | --- |
| 0 | Misaligned entry/fetch PC or taken control target; branch/jump faults report the branch/jump PC |
| 1 | Instruction PC outside the configured code capacity; reports that fetch PC |
| 2 | Unsupported/illegal instruction; reports its PC |
| 3 | EBREAK breakpoint; test programs use it as the expected stopping exception |
| 4 / 6 | Misaligned load / store; reports the accessing instruction PC |
| 5 / 7 | Bounds, permission or service error for load / store; reports the accessing instruction PC |

For data accesses, alignment takes priority over the bounds/permission checks.
Bounds cover the entire access, using a widened end-address calculation. A
control target outside code capacity causes a subsequent fetch fault, not a
target-access fault at the branch. A misaligned taken target faults the branch
and suppresses its link write. No trap-value register is provided.

## Rename and scheduling rules

**APE-OOO-01:** Dispatch allocates an ordered ROB slot. The rename map holds the
youngest live producer tag for each nonzero architectural destination. Sources
capture committed/completed values or wait for a producer tag. A same-cycle
completion bypass prevents a newly dispatched consumer from missing its wakeup.

**APE-OOO-02:** Issue selects the oldest ready, unissued live entry, not necessarily
the head. A blocked old load must not prevent an independent younger ALU from
issuing and completing. ROB entries also hold reservation-station operands;
there is no separate physical-register free list.

**APE-OOO-03:** Only the completed ROB head can retire. Retirement updates the
committed register file and clears a mapping only if it still names that producer.
The completion broadcast wakes dependents but does not commit architectural state.
A memory response takes the single broadcast port ahead of new ALU issue.

**APE-REC-01:** Every dispatched instruction records its predicted next PC. Actual
control flow resolves at issue. A retiring instruction whose actual next PC differs
from its recorded prediction commits its own valid result, discards all younger
entries and restarts fetch at the actual PC. A fault at the head discards younger
entries and halts without retiring the faulting instruction. Recovery restores
renaming from committed state; early branch recovery/checkpoints are not implemented.

## Prediction rules

**APE-BP-01:** The optional predictor is an untagged array of two-bit saturating
counters indexed by `(PC >> 2) mod predictorEntries`. Reset and every accepted
launch initialize each counter to 1, weakly not taken. States 0/1 predict fall-through;
states 2/3 predict the decoded conditional target. Aliasing is deliberate.

**APE-BP-02:** Only a successfully retiring conditional branch trains its counter.
Taken increments toward 3; not taken decrements toward 0. The actual branch
condition is used even when its target equals PC+4. Faulting and squashed branches
do not train. Lookup observes pre-clock-edge state when training the same index;
clear has priority over training. Predictor state is not architectural state.

**APE-BP-03:** With prediction enabled, valid JAL instructions use their decoded
target immediately; JALR still predicts PC+4. With prediction disabled, all
instructions predict PC+4. Invalid fetch/decode cannot enable target prediction.
Recovery compares next PCs, not just the taken/not-taken direction.

## External interfaces

All interfaces share the core clock domain. `Stream` transfers occur on an edge
with valid and ready asserted. `Flow` has valid but no backpressure. Payloads are
meaningful only when valid; trace Flows are observation ports, not a control ABI.

| Interface | Direction | Payload and contract |
| --- | --- | --- |
| `program` | Input Flow | `index[log2(programWords)]`, `instruction[32]`; accepted only while `busy=false` |
| `launch` | Input Stream | `pc, argument, base, limit[64]`, `writable[1]`; captures one invocation |
| `memory` | Output Stream | `address, data[64]`, `size[2]`, `write[1]`; size is log2(bytes) |
| `response` | Input Stream | `data[64]`, `error[1]`; exactly one response for each accepted request |
| `halt` | Output Stream | `pc, value[64]`, `cause[4]`; stable until consumed, value is committed a0 |
| `retired` | Output Flow | `pc[64]`, `instruction[32]`, `rd[5]`, `writes[1]`, `value[64]`; successful retirement only |
| `issued`, `finished` | Output Flows | `pc[64]`; speculative events, including instructions that never retire |
| `predicted` | Output Flow | `pc, next[64]`; one event per dispatched instruction |
| `controlRetired` | Output Flow | `pc, predictedNext, actualNext[64]`, `conditional, taken[1]`; taken is meaningful for conditional branches |
| `redirect` | Output Flow | `from, to[64]`; retirement-time mismatch only, not a halt event |
| `busy`, `occupancy` | Outputs | Active or holding halt; number of live ROB entries |

**APE-LIFE-01:** Launch is accepted only when idle, without a held halt or memory
transaction. It zeros architectural registers except a0, which receives `argument`,
clears ROB/rename state and predictor state, and captures the data capability.
Code persists across launches. The host must initialize every reachable code word.
Instruction writes while active or holding a halt are ignored. Consuming a halt
does not accept a new launch on that same edge; launch becomes ready afterward.

## Memory and publication rules

**APE-MEM-01:** Address generation may issue out of order. External loads and stores
may be presented only from the nonfaulting ROB head, after address preparation.
No external MMIO read or command write can arise from a wrong path. Head ordering
is the current publication boundary; it is not speculative-load hardware.

**APE-MEM-02:** At most one request is held or one response awaited, never both.
A stalled request keeps its payload and valid stable. After acceptance, the
service returns exactly one response, no earlier than the following cycle.
Response ready is asserted only while awaiting that response. There are no IDs,
reordering, timeouts, cancellation or protection against stale/duplicate replies.

**APE-MEM-03:** Data addresses must be naturally aligned and wholly inside the
launch's half-open interval `[base, limit)`. Stores also require `writable`.
Memory is little-endian; request and response data are right-justified. Stores
use the low `8 * 2^size` bits. The engine performs load sign/zero extension.
All requests, including stores, require a response; successful store response data
is ignored. An error response causes a precise load/store fault.

**APE-MEM-04:** An error response must denote an access with no architectural side
effect. This is an integration assumption, not a rollback mechanism. A successful
store is irrevocable; the engine waits for its response before retirement. If
the backend can partially write before reporting an error, it does not satisfy
this contract. A nonresponding service can stall forever. Reset requires the
service to be quiesced or reset as well.

FENCE is satisfied by this single-hart head-ordered port. Multi-agent coherence,
RVWMO litmus coverage, HSA ordering, address translation and cache behavior are
outside this revision. Bounds are invocation-wide, not an OS security boundary.

## Verification and evolution

The [verification map](APE-VERIFICATION.md) ties requirement IDs to executable
checks. The [roadmap](APE-ROADMAP.md) records future architectural gates. New
interfaces must specify fault, ordering and reset behavior before integration;
renaming the component or compiling its generator cannot establish correctness.

Public instruction semantics are referenced in [APE](../APE.md#public-semantic-sources).
The scheduling, predictor, launch and memory-interface choices above are HATS
design decisions, not requirements attributed to the RISC-V or HSA standards.
