# PPE execution contract — PPE-0.1

Status: **proposed S01 contract, not implemented RTL or an ISA-conformance claim**.
PPE means **Parallel Processing Engine**. `PpeCore` is the proposed programmable
compute core; `PpeCluster` groups those cores. APE remains the speculative
out-of-order Application Processing Engine. CP schedules tasks; it does not
substitute for either engine. This is an original HATS design, not a reconstruction
of a private GPU. No private reference RTL is required by this specification.

## Scope and initial implementation profile

The first PPE must execute programs, not just accept commands or call host
functions. Its initial useful kernels are independent byte/word scanning,
comparisons, bounded transforms and reductions with an independent result oracle.
A serial incremental parser remains the first APE target; a PPE parsing speedup
is not assumed. Tensor and floating-point extensions belong to S08.

| Property | Initial S02 verification profile | Architectural boundary |
| --- | --- | --- |
| Logical lanes per wave W | 8 | Fixed per code object; at most 64 for this mask format |
| Waves per workgroup | 1 | Additional resident waves require explicit resource and barrier support |
| Workgroups per task | One or more, serial scheduling allowed | Independent groups; no global barrier inside a kernel |
| Resident tasks per core | 1 | CP routes tasks; no preemption or context switching yet |
| Scalar registers | 32 × 64 bits per wave | No hardwired zero register |
| Vector registers | 32 × W × 64 bits per wave | One value per logical lane |
| Predicates | 8 × W bits per wave | Compare writes only currently active bits |
| Scratchpad | Up to 4 KiB per group | Separate from global address space; not a cache |
| Divergence stack | 8 frames per wave | Overflow faults; no silent serialization fallback |
| Memory transactions | One outstanding per core initially | Lane serialization permitted; coalescing is S04 |

These are **small test-profile choices**, not workload-derived optimal sizes or
physical lane counts. Physical execution may time-multiplex logical lanes.
Increasing W or register counts requires measurement, synthesis and verification.
Neither HBM capacity nor a multi-megabyte parser heap sets a register-file size.

## Architectural state and launch

**PPE-STATE-01:** A wave has one code-relative PC, scalar and vector registers,
predicates, an active mask, an immutable launch mask, a divergence stack, a
workgroup ID, a wave ID, and an instruction completion boundary. A logical thread
is one lane, not an independently fetching CPU thread. Initial launch mask is
all W lanes; tail elements are masked by the program. There is no per-lane EXIT.

**PPE-STATE-02:** Launch clears registers, predicates, scratchpad and divergence
state. It sets S0 to argument address, S1 to argument length, S2 to group ID,
S3 to group count, S4 to W, S5 to wave ID and S6 to task ID. V0[lane] is lane ID
within the wave and V1[lane] is `wave_id * W + lane`. Other registers are zero.
Arguments are immutable for the task lifetime; output buffers are separate
capability-authorized ranges. PCs are offsets into a registered code object,
never unchecked pointers supplied by a kernel.

**PPE-STATE-03:** The code object declares profile, W, register use, scratch use,
entry point and instruction boundaries. CP rejects an unsupported profile before
launch. Resource exhaustion queues a task or rejects it explicitly; it cannot
silently execute it on the host. Reserved/unknown instructions fault.

## Minimum instruction semantics for the S02 ISA model

This revision fixes semantics, **not binary opcode allocation**. The S02 ISA
encoding/assembler artifact must freeze instruction lengths, operands, branch
offset units and illegal encodings before `PpeCore` RTL is implemented. It must
not inherit encodings or microarchitecture from private source material.

| Family | Required semantics |
| --- | --- |
| Scalar integer | Move/immediate, add/subtract, AND/OR/XOR, shifts, signed/unsigned comparison, uniform branch |
| Vector integer | Lane-wise versions of the above, predicate compare, scalar broadcast, predicate-controlled select |
| Widths | 64-bit values; explicit 32-bit results zero-extend, signed variants explicitly sign-extend |
| Arithmetic | Modular integer results; shift count masked to 5 or 6 bits; no implicit flags |
| Control | Uniform jump/conditional branch, structured SPLIT/JOIN, group barrier, task-wave return |
| Memory | Global and scratch loads/stores of 1/2/4/8 bytes; explicit load sign/zero extension |
| Ordering | Acquire/release fence at group or task scope; completion publication through CP |

Multiply/divide, floating point, tensor operations, indirect calls and global
atomic read-modify-write are not required in the first profile. Unsupported
requirements cause loader rejection or an illegal-instruction fault. APE runtime
atomic needs do not automatically imply that the first PPE ISA supports atomics.
The compiler/model must reject unsupported operations, not return invented values.

**PPE-REG-01:** Scalar instructions execute once per wave. Scalar writes and
scalar loads/stores require the launch mask to be active and the divergence stack
to be empty. They fault before any effect otherwise. Vector instructions update
active lanes only; inactive destinations and predicate bits remain unchanged.
Vector reads may broadcast a scalar source without changing scalar state.

## Divergence and reconvergence

**PPE-DIV-01:** `SPLIT P, else_pc, join_pc` partitions the current active mask A
into T=`A & P` and F=`A & ~P`. A frame stores A, F, `else_pc`, `join_pc`, and phase.
The then arm starts at the next instruction. Both arms end at the same JOIN
instruction. The loader/model validates structured nested regions and legal
targets; arbitrary jumps across region boundaries are invalid.

- If T is nonempty, push a THEN frame and execute T at the then arm.
- Otherwise, push an ELSE frame and execute F at `else_pc`.
- At JOIN in THEN phase with nonempty F, keep the frame, change its phase to
  ELSE, set mask F and jump to `else_pc`.
- At JOIN in ELSE phase, or THEN phase with empty F, pop the frame, restore A,
  and continue after JOIN. The JOIN PC must match the frame's `join_pc`.

An empty active mask never executes an instruction. All-true and all-false
splits still use a frame; scalar writes remain forbidden until reconvergence.
JOIN with no frame, a mismatched JOIN, an invalid target or depth > 8 faults.
Uniform branches inside an arm must remain inside that arm or reach its JOIN.
RETURN is valid only with an empty stack and the full launch mask. No implicit
reconvergence occurs at an arbitrary common PC, barrier or return.

**PPE-DIV-02:** Registers are shared architectural wave state, not automatically
snapshotted per arm. Masked vector writes preserve each lane's own path result;
the scalar-write restriction prevents cross-arm scalar clobber. The independent
model must test nested splits, empty arms, divergent loads to invalid addresses,
and correct inactive-lane preservation.

## Memory, synchronization and fault semantics

**PPE-MEM-01:** Global memory is byte-addressed, little-endian, with 64-bit
addresses. Every active lane's access must be naturally aligned and wholly inside
an authorized range; widened end-address checks reject overflow. Masked-off lanes
generate no request, exception or permission check. Scratch addresses are offsets
within the current group's reservation and obey the same width/alignment rules.
Global and scratch spaces are distinct instruction operands, not inferred from
numerical address values. No device MMIO is exposed to PPE programs in S02.

**PPE-MEM-02:** The initial adapter issues active lanes in ascending lane order
and completes an instruction before issuing the next one. Every accepted read
or write gets exactly one response. Each write acknowledgment must mean a whole
access succeeded, or failed without side effects for that access. A vector store
is **not all-lanes atomic**: earlier successful lane stores remain visible if a
later lane fails. Aliasing writes are data races, not a portable lane-order
primitive; future coalescing must preserve race-free program results.

**PPE-MEM-03:** A global-load instruction buffers results until all active lanes
succeed, then updates destinations. A fault suppresses that instruction's register
writes but does not undo prior instructions or successful stores. Access failures
record task, wave, instruction PC, lowest failing lane/address in the initial
serialized profile, and the failing-lane mask. Later multi-outstanding designs
must specify which failures and prior writes can be reported before reuse.

**PPE-SYNC-01:** A group barrier is legal only at full launch mask and empty
divergence stack. It drains prior group memory operations, performs the declared
release/acquire, and waits for every wave in that group at the same barrier epoch.
The initial one-wave profile has no inter-wave synchronization to hide; barrier
drain still must be tested. Multi-wave groups must be fully resident or have a
deadlock-free suspension mechanism before being advertised. Groups synchronize
through separate task completions, never a spinning all-grid barrier.

**PPE-SYNC-02:** Shared virtual addresses do not imply coherence. A task-domain
fence is meaningful only when all relevant caches/fabric participants implement
that scope. Initial simulation uses a single uncached memory service. S04/S07
must add cache maintenance/coherence and ordering litmus tests, without treating
initial head-ordered access as proof of those properties.

**PPE-FAULT-01:** Illegal instructions, alignment/range errors, structured-control
violations, resource overflow and budget expiration terminate the task after
draining accepted transactions. Completion is held stable under backpressure.
No automatic replay is allowed after partial stores. Safe preemption, demand
paging and resumable faults require the S06 state/replay contract. A timeout while
a service never responds requires system quiescence/reset; a watchdog is not
memory rollback.

## Engine interfaces and implementation ownership

Both APE and PPE use adapters to [HATS-TASK-0.1](HATS-TASK-ABI-0.1.md). Existing
APE `launch`/`halt` ports are not changed by this document. The future adapter
must map an explicit ABI result to completion; arbitrary EBREAK is not success.

| Boundary | Required payload / behavior | Implementation stage |
| --- | --- | --- |
| CP → engine launch | Task/generation, registered entry, arguments, geometry, resource and capability context | S02 direct adapter; S05 CP |
| PPE → memory | Task/generation, address space, lane mask, width, address/data, access type, transaction ID | S02 one ID outstanding; S04 expansion |
| Memory → PPE | Matching ID/generation, data or no-effect access error, stable ready/valid | S02 |
| PPE → CP completion | Task/generation, status, value, PC/address/cause/lane mask after drain | S02 adapter; S05 publication |
| Verification | Retired instruction PC, active mask, register changes, memory events and fault/completion | S02 independent model + SpinalSim |

The architectural owner supplies semantics and independent tests. RTL frontend
integration owns port/reset/backpressure correctness; DV owns negative tests and
coverage. Synthesis/PPA work uses the exact generated RTL/configuration/constraints
after these checks. Netlist or physical implementation is not delivered by this
contract. No timing, area, clock rate or tapeout readiness is claimed.

## Required follow-ups before claiming implementation

1. **S02 / #3:** Freeze the original binary encoding and code-object format;
   implement independent model/assembler first, then SpinalHDL `PpeCore` and its
   adapter. Match instruction, memory, divergence and fault traces, not just sums.
2. **S02 / #3:** Demonstrate held launch/completion, delayed memory, invalid code,
   inactive-lane faults suppressed, partial-store faults, budget expiration,
   scratch bounds, barriers and relaunch with clean state.
3. **S04 / #5:** Coalescing, caches, multiple outstanding accesses and memory
   ordering require new tests and a versioned profile; do not assume them here.
4. **S05 / #6:** CP queues and device-driven APE ↔ PPE continuations with no host
   scheduler substitution. An embedded RISC-V CP is a viable implementation, not
   a requirement to run APE's OoO microarchitecture in the controller.
5. **S08 / #9:** Tensor/FP semantics, compiler lowering and inference validation.

Issue links and dependencies are maintained in the [roadmap](../../../ROADMAP.md).
