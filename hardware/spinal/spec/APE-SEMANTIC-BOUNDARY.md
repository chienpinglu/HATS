# APE semantic frontend/backend boundary

Status: implemented S03 component contract. RISC-V is the only implemented ISA
frontend. Alternate policy tests do not establish AArch64 support. Current-source
full integration and design-point gates are separate from the component gate.

## Executable interfaces

| Boundary | Producer / owner | Consumer / mechanism |
| --- | --- | --- |
| Instruction encoding and legality | `ApeDecode`, RV64I subset profile | Semantic `ApeOp`, branch condition, operand interpretation and memory size/sign |
| Sequential successor and fetch fault | `ApeRv64Frontend`: PC+4, alignment/bounds | ROB stores successor; predictor and execution use it explicitly |
| Register namespace / zero / task ABI | `ApeRv64Profile.registers`: 32 / 0 / 10 | `ApeRename` and checkpoints use layout dimensions and indices |
| Narrow arithmetic vs result representation | Decode selects `narrow32`; RV profile selects `SIGN_32` | Execution separates 32-bit shift semantics from `FULL`, `SIGN_32` and `ZERO_32` extension |
| Indirect target / branch alignment | RV profile supplies clear-bit-zero target mask and four-byte alignment mask | Execution applies request masks; relative and indirect jumps share semantic link handling |
| Exception presentation | Profile translates `ApeFaultKind` to supported RV causes | Shared execution/ROB transport semantic classes; wrapper encodes only the visible halt cause |
| Predictor indexing | Frontend profile supplies instruction-index shift | Prediction table consumes configured shift and explicit sequential successor |

`CONSTANT`, `PC_ADD`, `JUMP_RELATIVE` and `JUMP_REGISTER` are internal operations,
not a new software-visible ISA. Register sources/destinations retain their
architectural meaning only at the selected frontend/wrapper. Execution receives
physical values and a generation-qualified completion identity, not encoded
instruction register conventions.

## Instruction boundaries and faults

The current profile has exactly one semantic operation and one ROB owner per
architectural instruction. `ApeCore` explicitly requires this. Each owner retains
its PC, instruction and sequential successor; its qualified result may finish out
of order, but its visible register update or halt is selected at the ordered head.
One integer destination is supported. There is no expanded-instruction grouping,
flag namespace, paired access or multiple-destination retirement mechanism.

Semantic faults are `ILLEGAL`, `BREAKPOINT`, instruction alignment/access, load
alignment/access and store alignment/access. `NONE` is not a fault. An existing
frontend fault takes precedence over execution detection. Without a prior fault,
the component checks illegal/break operations, then successor alignment, then
memory access constraints; later detections override earlier ones. Memory
misalignment takes precedence over capability/bounds/write permission. The RV
frontend supplies an aligned sequential successor for any valid fetch, so its
successor-alignment failure arises from a taken control transfer, not an
ordinary non-control instruction. Alternate component policies must likewise
define their sequential-successor validity rather than assume that detail.
The external memory response can add an access fault only for the head operation.
See the execution/core code for these priorities and [APE-0.5](APE-0.5.md) for
late-completion ownership and cancellation. The visible RV cause value zero is
meaningful only when a halt is valid; `NONE` encoding is not a trap indication.

The target mask is an explicit policy input, not authority for a frontend to
silently choose different ISA behavior. Every new frontend must verify its own
encoding, result, fault and memory-ordering semantics against an independent
architectural reference.

## Verification

```sh
python3 hardware/spinal/tools/verify_ape_semantics.py
```

The source-bound actual-generated-RTL gate records:

- 4,953 execution vectors: arithmetic and shift semantics, all three result
  extensions, conditional branches, alternate target masks/alignment, link
  values, memory alignment/capability checks and prior-fault precedence.
- 135 RV profile/fetch checks: cause mapping, alignment and code-memory bounds,
  supported add/add-word lowering and illegal decode.
- 12,000 rename cycles in two alternate layouts: `(entries=16, zero=7, arg=3,
  physical=24)` and `(32, 31, 2, 40)`. Independent ownership replay checks
  out-of-order writeback, retirement, pressure, recovery and seven relaunches
  per layout, including a writable architectural index zero.
- 1,024 predictor policy checks: two index shifts, prediction enabled/disabled,
  explicit successors, collisions, training and clear.

The gate passed on 2026-10-10 Asia/Shanghai. Report:
`hardware/spinal/build/ape_semantics/gate.json`. Its hashes identify the actual
tested source and generated modules; that working report is regenerated on a
rerun. This is component policy evidence, not full instruction conformance or
whole-core formal proof. Elastic transport/backpressure, completion qualification,
real-core recovery, Spike and real-tool compatibility have their own gates.

## Remaining architectural generalization

RISC-V-specific fetch storage, visible retirement fields and launch/result ABI
remain deliberately in `ApeCore`'s architectural wrapper. The mechanisms are not
an ISA-independent complete processor by themselves. A future frontend needs
separate support and evidence for its flags, register classes, instruction
expansion, memory ordering, privileges and architectural fault presentation.
No runtime ISA switch, Arm license entitlement or AArch64 execution is claimed.
