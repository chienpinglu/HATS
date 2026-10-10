# APE application processor roadmap

This document tracks APE-specific detail. The [HATS end-to-end roadmap](../../../ROADMAP.md)
coordinates APE with the Parallel Processing Engine (PPE), command processor,
memory, software and physical implementation through stage issues and closure gates.

The target is an application-processing engine that executes substantial agent
and tool code within HATS, alongside vector/tensor engines and an independent
command processor. Speculative out-of-order execution is mandatory. APE-0.6
adds optional dual-lane issue to registered, ownership-qualified completion and checkpointed physical renaming;
it does not yet meet the application-processor target below.

## Execution roles

| Role | Responsibility | Current state |
| --- | --- | --- |
| APE | RISC-V application execution, dependencies, branching and eventual OS/runtime support | RV64 integer subset, physical renaming, OoO, prediction, bounded diff and pinned Tree-sitter tool port |
| Command processor | Consume queues, validate dispatch, track completion and route work | Separate embedded-RISC-V controller proposed; not implemented |
| PPE scalar path | Scalar control associated with vector work | First single-wave PPE integer ISA/RTL; not interchangeable with APE |
| Vector and tensor engines | Model inference and suitable data-parallel tool kernels | First eight-lane integer PPE implemented; numeric/tensor execution remains future work |
| Memory and service fabric | Local/remote access, ordering, protection and service requests | APE has one head-ordered data port; full fabric pending |

The names identify responsibilities. Merely moving CPU instructions into a package
with accelerators does not establish acceleration. Benefits must come from measured
execution, locality and reduced host interaction at comparable correctness.

## Milestones and exit evidence

| Gate | Implementation work | Evidence required before closure |
| --- | --- | --- |
| APE-0.2 | Named APE source, RV64 subset OoO, configurable bimodal prediction, specified interfaces | Six-configuration RTL matrix, predictor tests and legacy regression |
| APE-0.3 increment | Physical register file/maps/free list, typed branch/memory decode | Ownership/pressure RTL gate, preserved independent ISA/application and real-tool regressions; not full performance-core closure |
| APE-0.4 increment | Checkpointed maps and execution-time selective recovery | Replay-oracle tests, early timing witnesses, exact Spike comparisons, selected bounded component proof and fresh full compatibility; no delayed-completion/unbounded-proof/PPA claim |
| APE-0.5 increment | Elastic execution pipeline, qualified late completion and finite-generation lease exclusion | Actual transport/guard/core tests, independent Spike comparison and fresh integration regressions; no multi-issue or PPA claim |
| APE-0.6 / S03 | Actual one/two-lane issue candidate, explicit frontend policy and controlled real-tool comparison | Focused RTL/Spike, full P64 compatibility, 108-run workload study, nine technology points and selected P48 profile passed; bounded scope in the S03 completion review |
| Architectural confidence | External ISA oracle and architectural tests, larger randomized programs, formal invariants | No divergence on the declared subset; versioned supported/unsupported instruction map |
| Application ISA and ABI | Multiply/divide, required atomic/CSR support, traps, fuller executable loading and runtime startup | Linked application tests plus corner cases and precise fault tests on RTL |
| Performance core | Earlier branch recovery, pipelined execution units, separate PRF, wider dispatch/issue where justified | Preserved correctness plus measured IPC and synthesis/timing tradeoffs on the same workloads |
| Memory hierarchy | Store queue/forwarding, nonblocking L1, miss tracking, instruction fetch pipeline | Ordering/replay/fault tests, memory-model checks and measured miss behavior |
| OS execution | Privilege, interrupts, translation, page faults, TLB invalidation and context switching | Supported OS/runtime boot and process tests on the actual execution path |
| Command and task integration | Embedded controller, queue ABI, create/wait/resume, cancellation and completion ownership | Device-resident multi-step execution after initial submission, including resource exhaustion and faults |
| NUMA integration | Four locality domains, HBM performance tiers and LPDDR capacity tiers, APE-local LPDDR policy | Explicit access/coherence contracts, measured local/remote behavior and bounded service failures |
| Agent workload proof | Port representative source edits/diff, compiler passes, interpreter and scheduling workloads | Exact intended work on HATS, accounting for residual host CPU work and end-to-end time |
| Implementation viability | Synthesis, SRAM integration, timing/area/power estimation and FPGA or suitable hardware bring-up | Reproducible reports with technology, clock, memory and workload assumptions |

These are dependency gates, not promised delivery dates. A short C function does
not close application, compiler or interpreter coverage. Existing host workload
cases remain host baselines until their actual execution is ported and verified.

## Memory design decisions still required

The system concept has four compute-local HBM regions with attached LPDDR and
an APE/service-local LPDDR region. Locality and memory tier are separate properties:
HBM can be a bandwidth tier for an engine while nearby LPDDR is the lower-latency
placement for application state. Physical latency and bandwidth must be measured;
the labels alone do not guarantee either property.

Before replacing APE's current single port, specify the address map, cacheability,
coherence/ownership model, atomics across domains, translation ownership, fault
routing and migration protocol. The current launch bounds and command sink are
not implementations of those features. HBM/LPDDR controllers and PHYs remain
separate engineering work; this roadmap does not invent a completed controller.

## Near term order

The first [external ISA differential gate](APE-SPIKE-VALIDATION.md) is implemented:
576 invocations fully match pinned Spike and 24 have exact documented profile
differences. The broader architectural-confidence gate remains open for expanded
instruction coverage, adversarial recovery tests and formal invariants.
The [first bounded application](APE-APPLICATION-ABI.md) now establishes static ELF
loading, LP64 startup and an original source-diff tool with 144 RTL invocations.
This partially addresses application enablement, not the full ISA/OS/tool gate.
The [S02 gate](../../../workloads/S02-COMPLETION.md) adds pinned Tree-sitter/JSON
execution and first PPE RTL. The current [S03 increment](S03-PROGRESS.md) establishes
physical renaming, checkpointed recovery, pipelined completion ownership and actual
dual-lane issue. Current P64 integration and controlled workload comparison have
passed, together with all nine physical points and full PRF48 profile acceptance.
The measured S03 configuration is ROB8/P48/one lane/bimodal16. Cache-capacity choices belong to the separate S04
memory hierarchy and cannot be inferred from the abstract current memory service.
The [shared ISA substrate proposal](APE-SHARED-SUBSTRATE.md) separates possible
RISC-V/AArch64 reuse from current RISC-V-only execution.
Keep the existing OoO and publication checks as regression
requirements throughout; an in-order controller cannot replace the APE target.
