# HATS task and engine ABI — HATS-TASK-0.1

Status: **proposed system contract**. The [byte codec](../tools/task_abi.py) and
its tests validate layout and structural rejection, not CP execution, protection,
coherence or RTL behavior. This does not replace APE-0.2's existing physical ports.
It defines the adapter boundary for S02 and the command processor work in S05.

APE (class 1) executes scalar application code with speculative OoO execution.
PPE (class 2) executes programmable parallel code. CP validates, schedules and
publishes completion; CP firmware may run on an embedded RISC-V core. A PPE
scalar path is neither APE nor CP. Engine IDs are `(class << 16) | instance`.
Zero means no engine assigned (for example, a rejected descriptor).

## Descriptor layout

All fields are unsigned little-endian integers. Descriptors are exactly 128 bytes,
aligned to 64 bytes; no native C struct padding or pointer-size assumptions.
Version is major 0, minor 1. Unsupported versions, kinds, flags and nonzero
reserved bits are rejected, not silently ignored. Kind 1 means EXECUTE.

| Offset | Bytes | Field | Meaning |
| --- | --- | --- | --- |
| 0 / 2 / 4 | 2 each | major / minor / bytes | 0 / 1 / 128 |
| 6 / 7 | 1 each | kind / flags | 1 / 0 |
| 8 | 8 | task_id | Nonzero identity unique within the queue epoch |
| 16 | 8 | parent_id | Zero for root; not equal to task_id |
| 24 / 28 | 4 each | engine_class / domain_mask | 1 or 2; nonzero affinity among domain bits 0–3 |
| 32 | 8 | code_handle | Nonzero registered immutable code object, not a raw PC |
| 40 / 48 | 8 each | argument_address / argument_bytes | Immutable argument span in selected address space |
| 56 | 8 | capability_set | Nonzero registered access/resource authority |
| 64 | 8 | dependencies_address | 16-byte-aligned list; zero iff dependency_count is zero |
| 72 / 76 | 4 each | dependency_count / priority | At most 8; advisory priority 0–3 |
| 80 | 8 | completion_cookie | Opaque submitter correlation value; no memory-write authority |
| 88 | 8 | budget_ticks | Nonzero watchdog allowance in registered queue clock units |
| 96 | 4 | group_count | PPE groups; must be 1 for APE |
| 100 / 102 | 2 each | waves_per_group / logical_width | PPE geometry; both must be 1 for APE |
| 104 | 8 | scratch_bytes_per_group | Multiple of 16; zero for APE |
| 112 / 116 | 4 each | address_space / address_generation | Registered context plus mapping generation |
| 120 | 8 | reserved | Must be zero |

All address spans are checked with widened arithmetic, including dependency
count × 16 and scratch reservations. Arithmetic validity is not permission.
Domain affinity selects eligible engines, not necessarily where memory resides.
Code/resource/clock registrations and the queue epoch are trusted queue context,
not caller-created authority embedded in a descriptor. Initial profile: domain
mask 1, address-space/generation 0, no parent/dependencies, priority 0; PPE W=8,
one wave/group and at most 4 KiB scratch. This profile does not claim isolation.

## Queue ownership and publication

**TASK-QUEUE-01:** Initial queues are bounded single-producer/single-consumer
rings of power-of-two capacity N. Producer and consumer indices are monotonic
64-bit sequence numbers, maintained on separate cache lines. The producer owns
a free descriptor slot until it release-publishes the producer index; CP acquire-
observes that index, copies the descriptor and validates it before dispatch.
CP release-publishes consumption only after copying required descriptor and
dependency metadata. Producer acquire-observes consumption before slot reuse.
Multi-producer queues require a separately validated reservation protocol.

**TASK-QUEUE-02:** A queue has a distinct epoch, immutable owner/capability domain,
completion ring and a negotiated watchdog clock. Before any index wraps (or a
reset), submission stops, engines/fabric drain and a new queue epoch is created.
Stale responses never match a new task merely because a slot or ID was reused.
Task IDs remain unique until epoch retirement; accepted IDs have ledger entries.
Mappings/code/capabilities referenced by an accepted task cannot be revoked or
reused until it drains, unless S06 invalidation acknowledgments are implemented.

**TASK-QUEUE-03:** The producer cannot mutate code, descriptor metadata, dependency
lists or immutable arguments after publication until the relevant ownership is
released. For a trusted single-address-space prototype this is a software rule,
not a security guarantee. S06 must protect or pin/copy untrusted metadata so an
attacker cannot race validation and execution. Registered completion slots are
owned by CP; a descriptor never supplies an arbitrary completion destination.

**TASK-QUEUE-04:** Release/acquire requires real visibility. The initial shared
simulation service is uncached. Noncoherent implementations require documented
flush/invalidate/ownership transfers for descriptors, arguments, results and
completion records. Doorbells are hints to check the producer index; ringing a
doorbell is not a substitute for publishing memory. HSA-style queues alone do
not establish coherence or page-fault handling.

## Validation, dependencies and lifecycle

**TASK-LIFE-01:** CP proceeds through COPIED → VALIDATED → READY → RUNNING →
DRAINING → TERMINAL, or COPIED → REJECTED. Validation covers version, reserved
fields, resource/profile support, unique identity, code/argument/capability
permissions, address arithmetic and dependency graph legality. Unsupported
resources are explicit errors, not silent fallback. READY may wait for a free
engine. Every consumed descriptor receives one submission-sequence completion,
even if its task ID is malformed; this prevents wedging the ring on bad input.

**TASK-LIFE-02:** Dependencies are pairs of 64-bit `(queue_epoch, task_id)`.
The S05 first graph profile permits only previously accepted tasks in the same
queue epoch, making forward references/cycles invalid. Up to eight dependencies
are copied and pinned in the task ledger. READY requires all to succeed; failed
dependencies cause DEPENDENCY_FAILED without executing the dependent task.
Completion payloads can be recycled after consumption, but dependency status
must be retained until references are released. Bounded ledger exhaustion returns
an explicit resource rejection; software must not assume an infinite task table.

**TASK-LIFE-03:** Device-created children/continuations are a distinct S05
extension: validate parent ownership, reserve child resources, and suspend the
parent without holding an engine required by its children. A child may not depend
on an unfinished ancestor it must unblock. This revision does not claim that a
parent_id field or the old A64 task tile already implements that extension.

**TASK-LIFE-04:** Budget counts elapsed registered-clock ticks from engine launch
through drain, not instructions or host time. Queue wait is reported separately.
Cancellation/timeout stops new work, drains accepted memory operations and then
publishes terminal status. It is not rollback: earlier successful writes remain.
A nonresponding memory service requires fabric quiescence/reset; do not recycle
its IDs or publish a safe-to-reuse terminal record before that is established.
The cancel-control channel, priority scheduling and suspend/resume are S05/S06
follow-ups, not implemented features of this codec.

## Completion layout and ordering

Completion slots are 64-byte aligned records in a **separate** bounded ring;
slots are ordered by CP publication, not submission order. CP reserves space
before dispatch or otherwise accounts for every future terminal record to avoid
overflow. Backpressure may stop launches but cannot drop a completion.

| Offset | Bytes | Field | Meaning |
| --- | --- | --- | --- |
| 0 / 2 / 4 / 6 | 2 each | major / minor / bytes / status | 0 / 1 / 64 / terminal status |
| 8 | 8 | task_id | Copied descriptor ID, including an invalid one on rejection |
| 16 | 8 | sequence | Original submission sequence, not completion-ring position |
| 24 | 8 | value | Success value or completion_cookie for rejected descriptor |
| 32 / 40 | 8 each | fault_address / fault_pc | Fault diagnostics, zero when not applicable |
| 48 / 52 | 4 each | cause / engine_id | Cause namespace and assigned engine |
| 56 | 8 | fault_lane_mask | PPE failing lanes; zero for APE or non-lane failures |

Status 1=SUCCESS, 2=FAULT, 3=CANCELLED, 4=REJECTED, 5=DEPENDENCY_FAILED.
Cause 0=none, 1=illegal/profile, 2=alignment, 3=range/permission,
4=memory service, 5=budget, 6=structured control, 7=resource,
8=descriptor/version, 9=dependency/identity. Cause is task-ABI-wide, not copied
untranslated from the different APE exception numbering. FAULT on an APE fault
requires this mapping; EBREAK used as a test stop is not automatically SUCCESS.

SUCCESS requires an assigned APE/PPE engine and cause 0. FAULT requires an
assigned engine and nonzero cause. REJECTED and DEPENDENCY_FAILED have engine 0
and a nonzero cause (9 for dependency failure). CANCELLED can be published before
or after engine assignment, after the corresponding drain obligation is met.
Fault PC/address are zero outside FAULT; lane masks are zero except on PPE FAULT.
The receiver correlates **every status** by `(queue_epoch, sequence)`, retaining
the submitter's cookie in its own ledger; the cookie is not echoed on success.
This avoids interpreting a successful program's `value` as a cookie. These
structural checks still cannot establish registration permissions or exactly-once
publication; that requires S05/S06 stateful implementations and tests.

**TASK-COMP-01:** Engine result, writes and accepted requests must drain before
CP writes the full record and release-publishes the **completion producer index**.
The receiver acquire-observes that index, reads results and the record, then
release-publishes consumption. CP acquire-observes consumption before reuse.
The sequence field is correlation data, not a separate publication flag.
Exactly once is required per consumed descriptor within a live queue epoch;
crash recovery across reset requires an external ledger and is not claimed.

**TASK-COMP-02:** Arguments/outputs remain allocated until completion consumption
and release of all dependent references. Successful completion means every
required group/wave finished and the task's writes are visible at the queue's
scope. Fault/cancel does not mean no writes occurred. PPE can report partial
vector-store progress; APE faults are precise at its architectural retirement
boundary. Neither implies transactional rollback of earlier successful stores.

## Memory placement and engine adapters

The target has four affinity domains, each with HBM performance capacity and
LPDDR extended capacity, plus APE-local LPDDR as a possible scalar-local tier.
This ABI neither fixes capacities nor requires a fifth memory controller. A
single address-space registration maps objects to tiers; allocation policy can
prefer local HBM for PPE and local LPDDR for APE while remote LPDDR remains a
capacity tier. Near/far cost and coherence must be measured, not inferred from
address equality. S07 supplies topology discovery and allocation/migration APIs.

An engine launch adapter resolves registered code to entry/profile, verifies
resources, and carries task/epoch/address-generation context with every memory
request and response. Ready/valid payloads must remain stable under stall. The
initial one-outstanding service still needs stale-response and reset rules at
the system boundary; current APE-0.2 has no such tags. S02 direct test launches
can validate an adapter but cannot claim CP autonomy. S05 must replace testbench
scheduling with actual CP execution and show APE → PPE → APE handoff.

## Verification obligations and unresolved work

| Evidence | Status / owner |
| --- | --- |
| 128/64-byte layouts, endianness, overflow, reserved/version rejection | Executable Python codec tests in S01; not hardware validation |
| Registered code format, allocator/libc and ISA audit, PPE encoding | S02 / issue #3; required before claiming actual program support |
| Adapter memory/backpressure/partial failure tests | S02 / issue #3 |
| Ring-full, completion-full, duplicate task, stale epoch and dependency failure | CP implementation and DV in S05 / issue #6 |
| Fault containment, TOCTOU prevention and invalidation on every master | S06 / issue #7 |
| Cross-cache/domain release/acquire and near/far placement | S04 / #5 and S07 / #8 |

Run `python3 -m unittest discover -s hardware/spinal/tools -p 'test_task_abi.py' -v`.
These checks cannot close queue, hardware, OS or physical-design acceptance gates.
