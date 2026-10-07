# HATS Application Processing Engine (APE)

APE replaces the earlier HATS Scalar Engine name. The primary implementation is
`ApeCore`; `verify_ape.py` is the verification entry point. Legacy HSE entry points
remain compatibility adapters, not a second implementation.

The current specification revision is **APE-0.2**. Start with the
[architecture and interface specification](spec/APE-0.2.md),
[verification coverage](spec/APE-VERIFICATION.md), and
[development guide](DEVELOPMENT.md). The [roadmap](spec/APE-ROADMAP.md) separates
the application-processor target from this executable subset.

## Architectural direction

HATS names its components by execution role rather than CPU/GPU product category.
APE is the application-processing execution engine. The design direction is RV64, speculative
out-of-order execution, with a software-compatible scalar path for agent programs.
Vector/tensor engines and a command/task controller remain distinct execution
and control roles; adopting RV64 for APE does not dictate their instruction sets.

Speculative out-of-order execution is a mandatory APE architecture requirement,
not an optional upgrade. Its regression gate must demonstrate younger ready
instructions issuing and completing before older blocked instructions, while
retirement remains ordered and recovery preserves precise architectural state.
An in-order embedded command processor or a CU scalar instruction path is not
a substitute for APE. Full application/OS support remains a target, not a claim
about the current instruction subset.

This first APE implementation is a small, original SpinalHDL mechanism prototype. It is not yet
a high-performance big core, a full RISC-V implementation, or a complete HATS
processor. It does not replace the legacy A64 TaskTile's fork/join functionality.
Both implementations remain available while their integration is designed.

## Implemented structure

```text
Idle-loadable instruction memory
              |
     bimodal branch / direct-jump prediction
              |
     RV64 decode + ROB-tag rename
              |
     ROB / operand waiting slots ------ committed register file
              |                                ^
       oldest-ready selection                   |
              |                         in-order retirement
       integer / branch / AGU ------------------+
              |                                |
         operand broadcast               head-only memory
                                               |
                                     request / response port
```

- One hart, 32 architectural integer registers, x0 fixed at zero.
- Configurable power-of-two ROB; validation configurations have 4, 8 and 16 slots.
- One instruction can be dispatched, issued and retired per cycle. This is not
  a multi-issue/superscalar implementation.
- Register renaming maps an architectural destination to a ROB producer tag.
  Operands either capture a ready value or wait on that producer. WAW/WAR do not
  require serial execution. The ROB also supplies reservation-station storage;
  this version does not have a separate physical register file/free list.
- The oldest ready entry issues even when an older entry is unready. Integer
  work can issue and finish while the oldest load waits for memory.
- ALU/address-generation execution is combinational within one issue cycle;
  memory responses have priority over ALU issue on the single broadcast port.
- A configurable two-bit bimodal predictor selects conditional-branch targets;
  JAL uses its decoded target and JALR predicts fall-through. Prediction can be
  disabled. Branches resolve during execution, but recovery waits until retirement
  and compares the recorded prediction with the actual next PC. All younger
  entries are discarded on a mismatch and renaming restarts from committed state.
  JAL/JALR link writes retire before recovery. No early checkpoint recovery yet.
- Synchronous faults are recorded in the ROB and reported only at its head.
  Faulting instructions never retire or update architectural registers. Younger
  faults on a mispredicted path are discarded.

## Instruction coverage

Supported: LUI, AUIPC; RV64 integer register/immediate arithmetic, logical,
comparison and shifts; the RV64 word-width forms; six conditional branches;
JAL/JALR; LB/LBU/LH/LHU/LW/LWU/LD and SB/SH/SW/SD; FENCE; EBREAK.

Only 32-bit instruction encodings are accepted. Unsupported/reserved encodings
in the implemented decoder trap rather than silently execute. M/A/C/F/D/V,
Zicsr, FENCE.I, ECALL and privileged state are not implemented. Therefore this is
an **RV64I subset**, not an RV64I compliance claim. No HATS custom opcode exists.

EBREAK reports a breakpoint (cause 3); tests use that exception as a stopping
point. This is not a redefinition of EBREAK as successful architectural return.
Halt reports include fault PC, cause and committed a0. There are no machine-mode
CSRs, trap-vector entry, trap return, interrupt delivery or resumable trap handler.

## Memory and externally visible effects

All external memory operations wait until they are at the ROB head. Address
generation may execute speculatively, but **even reads are not sent speculatively**.
Consequently a wrong-path MMIO read or command store cannot reach the external
service. This is a correctness-first design, not a high-performance LSU with
load speculation, store forwarding, disambiguation or replay.

- One held request and one outstanding transaction, never multiple outstanding.
- Ready/valid requests remain stable under backpressure. Each accepted request
  requires exactly one response, no earlier than the following cycle.
- Responses are right-justified bytes; the core handles load sign/zero extension.
- Natural alignment and launch-time `[base, limit)` bounds are checked before
  issuing memory. Write permission is invocation-wide, not page protection.
- A successful store is externally irrevocable. An error response must represent
  a non-effecting access for the testbench's precise-store-fault contract. A bus
  that can report an error after partial writes requires a stronger integration
  protocol; software cancellation cannot roll back those writes.
- The memory service must be quiesced/reset along with the core. Late/duplicate
  responses, watchdog recovery and asynchronous cancellation are not supported.
- FENCE is satisfied by head-only ordering on this single-hart port. This is not
  a multi-agent coherence or complete RVWMO verification claim.

Instruction storage is a 4-KiB idle-loadable memory. Every reachable word must be
initialized before launch. Writing it while the engine is active or holding a
halt is ignored. A halt remains stable until consumed; only then can another
launch be accepted. Launch resets architectural/rename state; argument arrives
in a0. Code is retained across launches. Data memory is external.

## Reproduce and inspect evidence

Use the existing pinned Scala/SpinalHDL/sbt toolchain. In addition, install LLVM
Clang with the RISC-V backend and LLD. On the tested Mac the Homebrew `llvm` and
`lld` packages are used by absolute path; the system default compiler is unchanged.
`HATS_RV_CLANG` and `HATS_RV_LD` can select other installations.

```sh
cd hardware/spinal
python3 tools/verify_ape.py
```

The script compiles/links RV64 assembly and a freestanding C function, checks the
ELF identity, entry, allocated sections and unresolved relocations, then runs
the generated hardware in SpinalSim/Verilator. Each retired instruction is checked
against a separately written local sequential interpreter. Several directed
programs also have fixed known-answer checks. This local oracle is not external
ISA certification; Spike/Sail differential testing remains a milestone.

Directed coverage includes ALU/word arithmetic, renaming hazards, observed
out-of-order issue and completion, speculation and recovery, calls/returns,
ROB wraparound, memory widths, x0, precise faults and memory backpressure. An
error-path command store must never reach the memory service; a matching live-path
store must reach it exactly once. That service is a **test command sink**, not a
CP or a task-runtime implementation. Every scenario also repeats after a held
halt without resetting the RTL.

Generated status, tool versions, input/RTL hashes and logs are in
`build/ape/validation.json` and `build/ape/verification.log`. Per-configuration
retirement/issue traces and reports are in `build/ape/r*-*/`; waveforms are under
`build/ape/sim/`. A Scala compile or Verilog generation does not establish that
these tests passed. Synthetic memory latency and simulator cycles do not establish
performance, energy efficiency, memory-system performance or PPA.

### Current APE result

On 2026-10-07, APE-0.2 passed 600 core invocations across 4/8/16-entry ROBs and
both prediction modes, plus 4,096 predictor lookup checks. The legacy TaskTile
regression passed 123 test instances. The HSE simulation compatibility entry
point also passed its delegated 100-invocation, 8-entry, prediction-off suite.
See the [verification map](spec/APE-VERIFICATION.md) for scope and evidence paths.

### Historical HSE baseline

The initial 2026-10-07 HSE validation passed **39 scenarios, each launched twice without
reset, at each of 4/8/16 ROB entries: 234 RTL invocations**. Inputs comprise
29 directed linked programs (including the compiled C function), eight seeded
random integer programs, and two additional launch-PC fault scenarios.
The existing A64 TaskTile regression also passed all 123 test instances.

The HSE run used LLVM/LLD 23.1.2, SpinalHDL 1.12.3 and Verilator 5.052.
RTL assertions checked occupancy, x0, live rename-map ownership and head-only
external transactions. The scoreboard checked memory requests at acceptance
as well as retired instructions and final memory. These are bounded regression
results, not an exhaustive correctness proof or evidence of agent acceleration.

## Next gates toward the full execution engine

1. External ISA differential tests; stronger randomized control-flow/memory tests,
   assertions and formal checks for rename/ROB/fault invariants.
2. Earlier branch recovery, stronger prediction, pipelined/multiple execution
   units, physical-register allocation and measured performance design points.
3. LSU store buffering/forwarding, nonblocking L1 caches, translation, atomics,
   privilege, interrupts and explicit memory-model validation.
4. An independent embedded-RISC-V command controller and HATS task ABI. Integrate
   real create/wait/resume operations at non-speculative publication boundaries.
   No compiler/runtime capability is inferred merely from core ISA support.
5. Reproduce actual tool workloads on this execution path; include all scalar
   execution and controller overhead in comparison with the CPU baseline.
6. Synthesis/timing/area studies with explicit SRAM/library assumptions before
   describing any configuration as a high-performance big core.

## Public semantic sources

- [RISC-V RV32I base semantics](https://docs.riscv.org/reference/isa/v20260120/unpriv/rv32.html).
- [RISC-V RV64I base semantics](https://docs.riscv.org/reference/isa/v20260120/unpriv/rv64.html).
- [HSA queue and memory contracts](https://hsafoundation.com/standards/), for future
  task/controller integration, not a conformance claim for this core.

APE RTL, tests and the local interpreter are project-authored. This implementation
does not import a third-party CPU/GPU RTL core, proprietary instruction encoding,
or private interconnect interface. Source-reference review and original coding
are not described as a strict clean-room process. Publication and third-party
rights review remain separate from local prototyping.
