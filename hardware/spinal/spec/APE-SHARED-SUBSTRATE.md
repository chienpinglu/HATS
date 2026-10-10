# APE shared microarchitecture across instruction sets

A common speculative out-of-order backend can serve different ISA frontends.
For HATS, the recommended direction is a RISC-V implementation first, with
explicit boundaries that allow a future AArch64 frontend to reuse execution
machinery. RISC-V remains the only implemented instruction frontend. The current
S03 RTL implements explicit semantic execution, register-layout, predictor and
fault-presentation boundaries, with port-level tests of alternate policies.
It does not implement dual-ISA support; the current `ApeCore` is the RISC-V
architectural wrapper around these reusable mechanisms.

## Layer responsibilities and longer-term boundaries

| Layer | Reusable mechanism | ISA-specific responsibility |
| --- | --- | --- |
| Fetch and prediction | Fetch queues, prediction tables, target storage | Instruction length, instruction boundaries, call/return recognition and alignment |
| Decode and lowering | Internal operation format and flow control | Encodings, legality, immediates, register interpretation and instruction expansion |
| Rename and scheduling | Producer tags, physical-register allocation, wakeup/select, ROB allocation | Architectural register classes, flag dependencies and multi-destination instructions |
| Execution | Integer ALUs, shifters, multiplier/divider, branch and address units | Width/extension rules, flags, address writeback and specialized operations |
| Memory | Queues, caches, miss tracking and transport | Ordering, barriers, atomics, alignment, translation and device-memory semantics |
| Commit and recovery | Age ordering, squash machinery and checkpoint storage | Architectural instruction boundaries, legal visible effects, faults and architectural state updates |
| System state | Common interrupt/fault transport and context storage mechanisms | Privilege levels, CSRs/system registers, exception entry/return and page-table rules |

HATS queues, capability descriptors, completion ownership and locality identifiers
should have a versioned system ABI independent of the scalar ISA. An application
ABI remains ISA-specific: the same source may be recompiled, but its RISC-V and
AArch64 binaries and register conventions are not interchangeable.

## Internal operations must express semantics

A decoded operation should carry its original PC/instruction identity, operation
class, explicit source/destination register classes, immediate, width and result
extension, branch condition, memory size/sign/ordering, and fault metadata.
Expanded instructions also need a macroinstruction identifier and their position
within that instruction. The internal representation is an implementation
contract, not a new software-visible ISA.

Do not carry raw RISC-V `funct3` fields into the shared scheduler/LSU. Convert
them into semantic fields such as load width and signedness or a branch-condition
enum. `ApeDecode.scala` performs that conversion; `ApeRv64Frontend` and
`ApeRv64Profile` now own sequential instruction size, fetch alignment, encoded
register conventions, RV64 word-result extension, indirect-target masking and
exception-number presentation. `ApeExecute` consumes explicit `sequentialNext`,
target/alignment masks, `narrow32`, result-extension policy and semantic fault
classes. No RISC-V exception number is generated inside that execution component.

`ApeRename` consumes an `ApeRegisterLayout` rather than hard-coding x0 or x10.
It supports one power-of-two integer namespace, one immutable zero slot and one
argument/result slot. Tests exercise 16- and 32-entry layouts, nonzero zero-slot
indices and writable architectural index zero. This is reuse of a component,
not a second implemented CPU ISA. Flags and multiple destinations remain absent.

The predictor consumes the frontend's sequential successor and a configured
instruction-index shift. Its component tests exercise shifts one and three and
varying successor distances; the RISC-V wrapper uses shift two and PC+4.

See [the executable semantic boundary](APE-SEMANTIC-BOUNDARY.md) for exact fields,
fault ordering, instruction ownership and current verification limits.

The initial shared interface can represent one micro-operation per instruction.
It must reject unsupported forms explicitly. Adding a second frontend requires
real multi-operation and multiple-destination support where needed, not merely
extra enum values that the backend does not execute.

## Important AArch64 differences

Arm's [A64 overview for compiler writers](https://developer.arm.com/community/arm-community-blogs/b/architectures-and-processors-blog/posts/the-a64-isa-and-compilers)
describes context-dependent register-31 interpretation, conditional flags,
paired loads/stores and address modes. These features have backend consequences:

- Represent the stack pointer and zero register separately after decoding;
  do not reuse RISC-V's unconditional x0 behavior for encoded register 31.
- Rename and recover NZCV flag dependencies. A flag-producing arithmetic
  instruction may have more than one architectural destination.
- Distinguish zero-extension of AArch64 W-register results from RISC-V's
  sign-extending RV64 word operations.
- Define the visible register/memory effects and exception behavior of expanded
  instructions, including paired transfers and address writeback. Grouped
  retirement alone must not be assumed to make multiple memory accesses atomic.
- Parameterize required ordering and fault behavior, while verifying each ISA
  against its own architectural model. Sharing a cache or queue does not prove
  the required memory semantics. Arm provides separate
  [memory and exception architecture guides](https://www.arm.com/architecture/learn-the-architecture/a-profile).

This is not an attempt to implement every Arm or RISC-V extension in one universal
operation format. Start with the needed scalar features, then extend the internal
contract with evidence from a concrete ISA profile and workload.

## Development sequence

1. Preserve the current RISC-V RTL, Spike matrix and compiled application as
   regression anchors.
2. Extract a typed RISC-V decoded-operation boundary, replacing raw encoding
   fields with semantics. Prove unchanged architectural traces before widening
   the backend.
3. Preserve the implemented register-layout, result-extension and fault-policy
   boundary with executable tests. Add flags, multiple destinations and expanded
   instruction groups only alongside an actual frontend that needs them.
4. Prototype a separately selected AArch64 subset frontend after defining its
   supported profile and completing the relevant rights review. Use an independent
   AArch64 reference and fault tests; the legacy A64 TaskTile is not that evidence.
5. Share components only where both profiles preserve correctness and useful
   implementation tradeoffs. Maintain separate privilege/MMU adapters and ABIs.

Prefer build-time selection initially: one ISA personality per generated core.
Runtime ISA switching or simultaneous mixed-ISA processes would add state,
context-switch, cache and tooling obligations and are not part of this proposal.
There is no justified percentage estimate for backend reuse before both paths
are implemented and evaluated.

## Relationship to CUDA host support

ISA flexibility, CUDA host support and CUDA accelerator compatibility are separate
axes. A RISC-V APE does not automatically run CUDA. A CUDA-capable host needs the
corresponding OS, drivers, runtime, toolchain and GPU integration. Running CUDA
kernels on a non-NVIDIA execution engine would require a distinct backend and
compatibility effort; neither follows from a shared CPU microarchitecture.

The [2025 RISC-V International interview with NVIDIA](https://riscv.org/blog/nvidia-cuda-rva23/)
describes RISC-V host systems running Linux/drivers and dispatching work to NVIDIA
GPUs. That host-platform direction does not imply CUDA kernel execution on a
non-NVIDIA accelerator or a completed HATS software stack. The primary HATS question remains
whether device-resident tool execution reduces end-to-end agent work at comparable
correctness, not which CPU ISA appears on the package.
