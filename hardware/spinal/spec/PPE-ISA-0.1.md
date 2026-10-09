# PPE-ISA-0.1: original executable encoding

Status: **S02 model/codec and independently implemented SpinalHDL RTL**. This document
instantiates the [PPE-0.1 semantic contract](PPE-0.1.md). The encoding, model and
tests are original HATS work; they do not incorporate private GPU ISA or RTL.
PPE means **Parallel Processing Engine**.

## Profile and code object

The initial profile has eight logical lanes, 32 scalar and 32 vector registers
of 64-bit values, eight predicates, one wave per group, and eight divergence
frames. Scratch is zero to 4096 bytes in multiples of 16. Logical lanes need not
be eight physical execution units. No caches, CP, concurrent tasks or physical
implementation follow from this profile.

The code object starts with a 32-byte little-endian header, followed by exactly
`instruction_count * 8` bytes. There are no implicit trailers or relocations.

| Byte offset | Bytes | Field / required value |
| --- | --- | --- |
| 0 | 8 | Magic: ASCII `HATSPPE` followed by NUL |
| 8 | 2 | Major: 0 |
| 10 | 2 | Minor: 1 |
| 12 | 4 | Flags: 0 |
| 16 | 2 | Logical lane width: 8 |
| 18 | 2 | Scalar register count: 32; vector/predicate counts fixed by profile |
| 20 | 4 | Scratch bytes: 0..4096, multiple of 16 |
| 24 | 4 | Instruction count: 1..65536 |
| 28 | 4 | Entry instruction index: 0 |

Register counts describe reserved resources, not a liveness analysis. Code-object
validation is not capability registration or a security boundary. A future CP
must register immutable code and validate its own resource/permission context.

## Instruction encoding

Each instruction is one little-endian 64-bit word. Byte PCs are relative to the
first instruction, excluding the header. All control-flow targets are instruction
boundaries; there is no compressed format.

| Bits | Field |
| --- | --- |
| 7:0 | Opcode, listed below |
| 12:8 | Destination `d` |
| 17:13 | Source `a` |
| 22:18 | Source `b` |
| 25:23 | Predicate source `p` |
| 27:26 | `width` |
| 29:28 | `flags` |
| 31:30 | Reserved, zero |
| 63:32 | Signed 32-bit immediate, except unsigned SPLIT target pair |

Unknown opcodes, unsupported flags, nonzero unused fields and unsupported widths
are rejected. For example, `ADD d=1,a=2,b=3,width=3` is the byte sequence
`03 41 0c 0c 00 00 00 00`.

| Opcode values | Operations in numeric order |
| --- | --- |
| 1..12 | MOVI, MOV, ADD, SUB, AND, OR, XOR, SHL, SHR, SAR, LT, LTU |
| 13..22 | VMOVI, VMOV, VADD, VSUB, VAND, VOR, VXOR, VSHL, VSHR, VSAR |
| 23..26 | VCMPEQ, VCMPLT, VCMPLTU, SELECT |
| 27..30 | JMP, JNZ, SPLIT, JOIN |
| 31..34 | LOAD, STORE, VLOAD, VSTORE |
| 35..37 | FENCE, BARRIER, RETURN |

### Integer and predicate operations

Arithmetic/moves/select/compare require width 2 (32 bits) or 3 (64 bits). Sources
are interpreted at that width. Results are modular; 32-bit results zero-extend
unless flag bit 0 requests sign extension. That flag is illegal for 64-bit
results and predicate comparisons. Shift amounts use their low 5 or 6 bits.
LT/VCMPLT and SAR/VSAR use signed interpretation; LTU/VCMPLTU use unsigned.

Scalar binary operations use S[a], S[b] and write S[d]. MOV uses S[a]; MOVI uses
the signed immediate. Vector operations use V[a], V[b] and write active V[d]
lanes. Flag bit 1 broadcasts S[b] for vector binary operations and comparisons;
VMOV instead broadcasts S[a]. VMOVI uses the signed immediate. Flag bit 1 is
illegal on scalar operations and immediate moves. Full 64-bit constants can be
constructed with multiple instructions; no literal pool is hidden in the model.

Comparisons write predicate `d` (0..7); inactive predicate bits are preserved.
SELECT uses predicate `p` to select V[a] when true and V[b] when false, and does
not broadcast. Scalar writes require an empty divergence stack and all launch
lanes active, even inside an all-true arm. No register is hardwired to zero.

### Control flow

JMP and JNZ use a signed offset in **instructions from the current instruction**.
JNZ tests the full S[a] for nonzero. SPLIT uses `p`; immediate bits 15:0 hold the
absolute else instruction index and bits 31:16 hold the absolute JOIN index.
JOIN has no operands. Its dynamic mask/phase behavior is defined by PPE-0.1.

The loader checks unique JOIN ownership, proper nesting within one arm, and
branches that remain in their arm or reach its innermost JOIN. The then arm must
end with an explicit JMP to that JOIN. Empty else arms use `else == join`; an
empty then arm contains only the required JMP. All-true/all-false splits still
push a frame. The ninth nested frame faults before changing divergence state.
Uniform loops are permitted. Falling off code faults rather than returning.

RETURN uses S[a] as its result, and requires the full launch mask and an empty
stack. RTL publishes a held direct-engine completion, not a CP queue descriptor.

### Memory and ordering

Memory width 0/1/2/3 means 1/2/4/8 bytes. Flag bit 0 sign-extends loads narrower
than 64 bits; it is illegal for stores and 64-bit loads. Flag bit 1 selects
scratch instead of global memory. LOAD/STORE address S[a] + signed immediate;
VLOAD/VSTORE address S[a] + V[b][lane] + signed immediate. Address addition is
widened, not modular: overflow/underflow faults. `d` is the load destination or
store data source. Global and scratch spaces both check natural alignment,
whole-access range and write permission before an effect.

Inactive lanes perform no access or permission check. Active lanes access memory
in increasing lane order in this profile. Vector loads publish no destination
lanes unless all reads succeed. Earlier successful vector stores remain visible
if a later lane fails; the failing access itself has no effect. Aliasing stores
must not be treated as a portable lane-order programming primitive.

FENCE is the profile's task-domain acquire/release operation; BARRIER is the
single-wave group's drain/acquire/release operation. Both require full mask and
empty stack. In the synchronous uncached reference they have no outstanding work
to drain. RTL completes each memory instruction only after every selected lane
drains; delayed-response tests require that no subsequent retirement, including
a fence or barrier, occurs with an outstanding request. This verifies the
declared single-wave ordering, **not coherence, multi-wave synchronization or
CP publication**.

## Reference model and fault records

[`ppe_isa.py`](../tools/ppe_isa.py) provides `Instruction`, `Code`, a two-pass
Python `assemble` API, diagnostic `disassemble`, `Memory` and `Wave`. Assembly
accepts labels and `(opcode, keyword-fields)` tuples, not executable source text.
The disassembler is diagnostic output; a textual assembler/compiler is not yet
implemented. Launch initializes state exactly as PPE-0.1 specifies, with wave ID
zero. A caller runs one wave/group; the model is not a multi-group scheduler.

Retirement traces contain byte PC, opcode, active mask, next PC and changed
scalar/vector/predicate values. Each memory object records its accesses/errors.
Faulting instructions do not retire. Fault records contain byte PC, cause,
address (low 64 bits on address overflow) and failing lane mask; scalar faults
use a zero lane mask.

| Cause | Meaning |
| --- | --- |
| 1 | Illegal execution / PC outside code |
| 2 | Misaligned access |
| 3 | Address, permission or scratch-range failure |
| 4 | Injected memory-service error |
| 5 | Reference instruction-budget exhaustion |
| 6 | Structured-control / uniform-state violation |
| 7 | Divergence-stack resource exhaustion |

Malformed code objects fail host-side validation before launch. The model's
instruction budget is a termination guard, **not HATS-TASK's hardware cycle
watchdog**. Synchronous service injection cannot demonstrate a never-responding
transaction or safe hardware drain/reset.

## Validation and implementation boundary

From the repository root:

```sh
python3 -m unittest discover -s hardware/spinal/tools -p test_ppe_isa.py -v
python3 hardware/spinal/tools/verify_ppe.py
```

The 21 tests cover known encoding bytes, illegal encodings/headers/targets,
scalar/vector arithmetic, masking, nested and empty-arm reconvergence, inactive
predicate preservation, eight/nine-frame boundaries, partial stores, atomic
load-result publication, address overflow, scratch/permission/alignment errors,
conditional loops, launch state and budget exhaustion. The original
[`ppe_programs.py`](../tools/ppe_programs.py) delimiter-candidate program handles
eight bytes per group with explicit tail masking. It marks punctuation even
inside strings: this is a byte-class prefilter, not JSON parsing. Six fixtures
(including empty, tail, Unicode and all 256 byte values) check complete output,
untouched canaries and exact store addresses against an independent byte oracle.
Group launches are driven by the direct-engine test adapter, not a CP.

[`PpeCore`](../src/main/scala/hats/PpeCore.scala) independently implements the
decoder, fetch/execute/retire states, register files, lane masks, reconvergence,
scratch and global-memory protocol. The [RTL contract](PPE-RTL-0.1.md) describes
launch rejection, clock watchdog, drain and response ownership. `verify_ppe.py`
executes 112 fixtures twice: 180 full ISA-oracle comparisons and 44 explicitly
classified decode/resource/watchdog/quiescence checks. The hardware clock budget
is not compared to the model's instruction budget.

Each successful comparison includes every retirement's entire scalar/vector/
predicate state, mask/depth, ordered global and scratch accesses tied to retirement
boundaries, completion, and final register/global/scratch images. Passing the
Python model alone is not hardware evidence. Full S02 closure additionally needs
the APE real-tool and legacy regression gate in `workloads/s02/run_all.py`.
