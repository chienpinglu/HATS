# HATS Application Processing Engine (APE)

APE replaces the earlier HATS Scalar Engine name. The primary implementation is
`ApeCore`; `verify_ape.py` is the verification entry point. Legacy HSE entry points
remain compatibility adapters, not a second implementation.

The current implementation revision is **APE-0.6**, with focused correctness,
complete controlled workload comparisons and full P64 compatibility verified.
The nine-point technology study and selected ROB8/P48/one-lane profile also pass
their declared gates; see the [S03 acceptance review](../../workloads/S03-COMPLETION.md).
Start with the [dual-lane issue contract](spec/APE-0.6.md), the retained
[registered execution contract](spec/APE-0.5.md), the retained
[early-recovery specification](spec/APE-0.4.md), the underlying
[physical-renaming contract](spec/APE-0.3.md), the retained
[instruction and interface contracts](spec/APE-0.2.md),
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
     RV64 semantic decode + physical rename
              |
     ROB / operand waiting slots ------ physical register file
              |                                ^
       oldest-ready issue (1/2 lanes)            |
              |                         committed map / free list
       per-lane operand register                |
              |                                 |
       per-lane integer / branch / AGU          |
              |                                 |
       result registers -> arbiter -> ownership guard
              |                                 |
              +---------------------------------+
              |                                |
         operand broadcast               head-only memory
                                               |
                                     request / response port
```

- One hart, 32 architectural integer registers, x0 fixed at zero.
- Configurable power-of-two ROB; validation configurations have 4, 8 and 16 slots.
- One instruction can be dispatched and retired per cycle. Issue width is one
  or two, selecting actual registered execution lanes; writeback remains single-
  port. The dual-lane candidate is not a two-wide frontend or retirement path.
- Register renaming allocates a physical destination independent of the ROB slot.
  Speculative and committed maps, a physical register file and a free list track
  ownership. Operands capture ready values or wait on physical tags. WAW/WAR do
  not require serial execution. The ROB still supplies reservation-station storage.
- Generic fallback physical-register capacity is 64. The focused renamer gate
  also tests 33 and 36 entries, including integrated ROB16/P36 resource-pressure
  cases. The controlled workload study includes P36/P48/P64; P48's complete
  candidate-profile regression is separate from the generic P64 baseline.
- The oldest ready entry issues even when an older entry is unready. Integer
  work can issue and finish while the oldest load waits for memory.
- ALU/address-generation execution has an operand register and a result register;
  accepted issue completes no earlier than two cycles later. Memory responses
  backpressure completion on the single broadcast port. Squashed late results
  cannot write back: ROB generation and physical ownership must still match.
  Allocation also excludes finite-generation aliases with any resident token.
- A configurable two-bit bimodal predictor selects conditional-branch targets;
  JAL uses its decoded target and JALR predicts fall-through. Prediction can be
  disabled. Branches now recover during execution: checkpointed maps restore
  the resolving branch's state, only younger entries are discarded, and older
  instructions/memory remain live. JAL/JALR retains its own link destination.
  Four live checkpoints are admitted by default; exhaustion stalls dispatch.
  A retirement-recovery configuration is retained for comparison, not as the default.
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

Instruction storage is an idle-loadable memory: 4 KiB in the standard profile,
256 KiB in the real-tool profile. Every reachable word must be
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
ISA certification. A separate [pinned Spike differential gate](spec/APE-SPIKE-VALIDATION.md)
now compares actual RTL architectural events with unmodified upstream instruction
semantics. It fully matches 576 invocations and explicitly checks 24 profile
differences; broader architectural-test coverage remains a milestone.

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
achieved hardware performance, energy efficiency or physical PPA.

For the full enlarged-backend evidence path, use the
[S03 guide](../../workloads/s03/README.md). Separate gates cover semantic policy,
physical rename, checkpoint recovery, registered completion, simultaneous issue,
selected bounded formal properties and the complete upstream tool. Controlled
workload cycles and research-library mapped area/delay are measured separately;
neither is a silicon clock or physical energy measurement.

### Current S03 progress and historical APE-0.2 result

The S03 increments implement physical renaming, typed branch/memory decode fields
checkpointed early branch recovery, registered completion and optional dual-lane
issue. See the [S03 progress and evidence record](spec/S03-PROGRESS.md)
for current tests, completed S03 acceptance and explicit later-stage limits.

On 2026-10-07, APE-0.2 passed 600 core invocations across 4/8/16-entry ROBs and
both prediction modes, plus 4,096 predictor lookup checks. The legacy TaskTile
regression passed 123 test instances. The HSE simulation compatibility entry
point also passed its delegated 100-invocation, 8-entry, prediction-off suite.
See the [verification map](spec/APE-VERIFICATION.md) for scope and evidence paths.

The [bounded application path](spec/APE-APPLICATION-ABI.md) adds a static ELF
loader, LP64 startup/stack checks and an original line-diff tool. Its 144 RTL
invocations match Spike exactly and pass independent edit-script checks. This
executes tool logic on APE, not a full Git/compiler/interpreter stack or a measured
physical acceleration result. A [shared microarchitecture proposal](spec/APE-SHARED-SUBSTRATE.md)
describes future RISC-V/AArch64 reuse; no dual-ISA backend is implemented yet.

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

1. Broaden the existing external ISA differential tests and application coverage;
   stronger randomized control-flow/memory tests,
   assertions and formal checks for rename/ROB/fault invariants.
2. Preserve the measured ROB8/P48/one-lane/bimodal16 profile and its complete
   regression chain. Future wider frontend/writeback or stronger prediction requires
   new same-workload evidence; existing dual issue did not improve cycles.
3. LSU store buffering/forwarding, nonblocking L1 caches, translation, atomics,
   privilege, interrupts and explicit memory-model validation.
4. An independent embedded-RISC-V command controller and HATS task ABI. Integrate
   real create/wait/resume operations at non-speculative publication boundaries.
   No compiler/runtime capability is inferred merely from core ISA support.
5. Reproduce actual tool workloads on this execution path; include all scalar
   execution and controller overhead in comparison with the CPU baseline.
6. Replace early FF/mux research-library assumptions with SRAM and physical
   implementation evidence before claiming achieved big-core frequency or energy.

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
