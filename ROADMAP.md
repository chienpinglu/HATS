# HATS End-to-End Processor Development Roadmap

Date: 2026-10-08

Status: implementation plan; stages are open until their acceptance evidence is reviewed.

Baseline: [cc23093](https://github.com/chienpinglu/HATS/commit/cc23093ae22834af9fcdd462140d995364edd3ce).

## Objective

Build **HATS — Heterogeneous Agent Tool Substrate** as a programmable processor
platform that executes both model inference and the application/tool work around
it. The target is a complete, verifiable path from source programs to APE/PPE
execution, device-resident task control, memory and OS cooperation, and ultimately
a working hardware prototype.

The value hypothesis is improved end-to-end agent execution at equal correctness
and model quality through execution, locality and reduced host interaction.
Moving conventional CPU work into the package alone does not prove acceleration.

## Execution roles and target topology

| Component | Full name and responsibility | Current state |
| --- | --- | --- |
| APE | Application Processing Engine: speculative out-of-order RISC-V application execution | Small integer OoO RTL prototype with bounded applications; not a complete high-performance big core |
| PPE | Parallel Processing Engine: GPU-class programmable scalar/vector/tensor execution | Architecture and implementation pending |
| PpeCore / PpeCluster | PPE compute core (CU) and a group of such cores | Minimum S01 contract specified; model/encoding/RTL remain S02 |
| CP | Command Processor: embedded RISC-V controller for queues, dispatch and completion | Separate core/firmware integration pending |
| Memory/service fabric | Caches, translation/protection, ordering, DMA, locality and asynchronous services | Full system pending; current APE uses a single head-ordered data port |

A PPE scalar path is not the application APE and is not the command processor.
Tensor units are part of PPE, not the whole PPE. Design and verify all three roles
explicitly; PPE work starts alongside APE work.

The target topology has four compute-locality domains, each with HBM and
independently attached LPDDR, plus APE/service-local LPDDR. Domain boundaries do
not prescribe separate dies. Near/far placement and bandwidth/capacity tiers are
independent properties. Controllers, PHYs, packaging and physical performance
remain separate implementation obligations.

SpinalHDL and SpinalSim are the primary microarchitecture development path.
RISC-V is the application ISA. A reusable semantic backend boundary may later
support another frontend; AArch64, runtime ISA switching, CUDA compatibility and
training are not implied by this plan's initial implementation.

## Verified starting point

The baseline has real RTL and bounded verification evidence, not a finished
application processor or integrated HATS platform:

- APE mechanism matrix: 600 RTL invocations and 4,096 predictor checks.
- Independent Spike comparison: 576 fully matched invocations and 24 exact,
  documented profile differences; no unexpected divergence in that run.
- Bounded original line-diff application: 144 RTL invocations matched Spike and
  passed independent edit-script checks. This is not a Git/GNU diff port.
- Legacy task mechanism: 123 RTL tests, separate from APE.
- The 21 host-side workload cases remain host baselines until their actual work
  is ported; they are not 21 agent workloads already running on HATS.
- APE and the legacy task tile are not integrated. PPE, independent CP,
  caches/MMU/coherence, four-domain fabric and physical memory interfaces remain
  open work.

These results were rechecked on the exact staged baseline before its publication.
Generated reports are local build evidence and are not committed binary/log
archives. Reproduce them with the [development guide](hardware/spinal/DEVELOPMENT.md).

## Issue index

Parent tracker: [#1](https://github.com/chienpinglu/HATS/issues/1).

| Stage | Scope | Issue |
| --- | --- | --- |
| S01 | Profile real agent workloads and define the HATS architecture contract | [#2](https://github.com/chienpinglu/HATS/issues/2) |
| S02 | Enable real APE applications and implement the first programmable PPE core | [#3](https://github.com/chienpinglu/HATS/issues/3) |
| S03 | Develop and verify the speculative out-of-order APE performance core | [#4](https://github.com/chienpinglu/HATS/issues/4) |
| S04 | Implement the APE and PPE cache and memory-execution hierarchy | [#5](https://github.com/chienpinglu/HATS/issues/5) |
| S05 | Integrate an embedded RISC-V command processor and device-resident task runtime | [#6](https://github.com/chienpinglu/HATS/issues/6) |
| S06 | Implement OS-aware protection, faults, preemption and service interfaces | [#7](https://github.com/chienpinglu/HATS/issues/7) |
| S07 | Integrate four NUMA compute domains with HBM and LPDDR tiers | [#8](https://github.com/chienpinglu/HATS/issues/8) |
| S08 | Implement PPE tensor execution, compiler support and model inference | [#9](https://github.com/chienpinglu/HATS/issues/9) |
| S09 | Demonstrate an end-to-end agent tool and bounded improvement loop | [#10](https://github.com/chienpinglu/HATS/issues/10) |
| S10 | Close RTL, FPGA and ASIC implementation gates with physical evidence | [#11](https://github.com/chienpinglu/HATS/issues/11) |

The stage numbers identify acceptance gates, not a strictly serial schedule.
GitHub issues are the live execution status; this document defines scope and
closure requirements. Keep both aligned when scope or dependencies change.

## Work sequencing and parallel tracks

- Start S01 now: real-tool selection/profiling and PPE architecture are parallel
  priorities.
- S02 implements APE application support and the first PPE core in parallel.
- S03 (OoO), S04 (memory), S05 (CP/runtime) and S08 numeric/compiler design
  overlap after their minimum interfaces are stable.
- S06 adds protected execution; S07 integrates the locality domains; S09
  demonstrates the full selected agent/improvement loop.
- S10 starts early synthesis and physical feedback during S02/S03. Its final
  FPGA/ASIC gates depend on the integrated design; they do not delay early
  feasibility checks.
- Separate RTL implementation, independent verification, compiler/runtime,
  workload profiling and implementation/QoR responsibilities. Shared contracts
  and regression gates coordinate these tracks.
- Resource assignments and dates follow measured scope. No completion dates,
  PPA targets or core/cache dimensions are promised without evidence.

## Stage specifications

### S01: Profile real agent workloads and define the HATS architecture contract

Progress: [S01 completion review and gate](workloads/S01-COMPLETION.md) cover the
case map, pinned native baseline, branch/memory/atomic/stack demand profiles,
real local edit/build/test critical path and reviewed minimum architecture
contracts. The [RISC-V compile/link audit](workloads/target/treesitter/README.md)
identifies exact missing runtime providers; strict executable links remain
blocked. Target execution remains an S02 gate, not an S01 acceleration claim.

**Goal:** Produce a workload-backed system contract and select the first pinned upstream tool port, with APE, PPE and CP interfaces defined together.

**Dependencies:** Baseline cc23093; no earlier stage.

**Start and overlap:** Start now from baseline cc23093; workload profiling and PPE specification proceed in parallel.

**Work packages**

- [x] Map the existing 21 host-side cases and the GEPA, ACE, AFlow, DGM, STOP, AHE and Gas City coverage to APE, PPE, CP, memory and OS services; distinguish component tests from full experiments.
- [x] Select and pin a real upstream tool, review license/provenance, freeze inputs and expected outputs, and record any port patches separately. Evaluate Tree-sitter runtime plus one grammar as the first candidate rather than treating it as a committed selection.
- [x] Capture executable size, instruction requirements, stack/heap use, allocation, branches, locality, synchronization, file/process services and critical-path time on representative inputs.
- [x] Specify the PPE execution model: thread/wave grouping, scalar/vector register semantics, predication, divergence/reconvergence, synchronization, memory operations and fault reporting.
- [x] Specify versioned task descriptors, queues, completion ownership, engine identifiers and APE/PPE/CP interfaces; record address-space and memory-ordering requirements.
- [x] Set the initial prototype scope and comparison protocol; rank missing capabilities before selecting issue width, ROB size, cache size or tensor shape.

**Acceptance criteria**

- [x] A versioned workload-to-capability matrix identifies the execution engine and remaining host service for every selected case.
- [x] The selected real tool has a reproducible native baseline, pinned source/license, fixed inputs and independent output checks.
- [x] APE/PPE/CP and PPE execution-model specifications resolve the minimum interfaces required to begin S02 and S05; unresolved decisions have explicit follow-up tasks.
- [x] The baseline distinguishes inference, tool execution, compilation, tests, orchestration and network wait instead of attributing all CPU time to an offloadable kernel.

**Required evidence:** Profile commands, pinned source manifest, input hashes, native output checks, capability matrix and versioned architecture/ABI specifications.

**Claim boundaries:** This stage establishes requirements and native baselines. Target execution is an S02 gate; host profiles do not establish HATS acceleration.

### S02: Enable real APE applications and implement the first programmable PPE core

**Goal:** Execute a pinned real tool on APE RTL and independently checked scalar/vector programs on the first PPE RTL core.

**Dependencies:** S01

**Start and overlap:** Begin after the minimum S01 contracts are reviewed; run APE and PPE implementation tracks in parallel.

**Work packages**

- [ ] Extend APE instruction/data capacity, checked executable loading, startup, stack/heap and required library support according to the selected tool's measured needs.
- [ ] Implement and independently verify only the ISA/runtime additions required by the declared application profile; preserve the bounded diff application as a regression anchor.
- [ ] Port the selected upstream tool with explicit platform adapters and a residual-host-work inventory; keep the original source identity and patch set reproducible.
- [ ] Build an independent PPE ISA model and assembler/disassembler with positive and illegal-instruction tests.
- [ ] Implement PpeCore fetch/decode, runnable-thread selection, scalar/vector register files and integer execution, masks, divergence/reconvergence, load/store, scratchpad and barriers.
- [ ] Add SpinalSim/Verilator tests for actual PPE instruction execution, resource conflicts, stalls, relaunch and failure handling.

**Acceptance criteria**

- [ ] Identical inputs produce matching native and APE-target results; the declared supported instruction profile also passes independent architectural comparison.
- [ ] The actual upstream tool logic executes on APE RTL without a host implementation supplying its results.
- [ ] PPE instruction and final-state traces match its independent reference on the supported profile, including divergence and synchronization cases.
- [ ] Current APE, predictor, bounded-application and legacy-task regression anchors remain passing or have an explicitly reviewed architectural-profile change.
- [ ] A reproducible build generates both engines' RTL and records source, toolchain and generated-artifact identity.

**Required evidence:** Upstream lock and patch manifest, application ELF/runtime artifacts, native/reference/RTL comparisons, PPE ISA model/tests, generated RTL hashes and regression reports.

**Claim boundaries:** A first programmable PPE is not a complete GPU or LLM engine. A compiled program for APE is not a compiler running on APE.

### S03: Develop and verify the speculative out-of-order APE performance core

**Goal:** Evolve APE into a workload-evaluated speculative out-of-order application core while preserving architectural correctness.

**Dependencies:** S01, S02

**Start and overlap:** Specification and synthesis experiments can start during S02; closure requires the real-application regression anchor.

**Work packages**

- [ ] Separate semantic decoded operations and ISA-specific architectural state from reusable scheduling/execution interfaces; retain RISC-V as the implemented frontend.
- [ ] Implement physical-register allocation, rename maps, free-list management, issue queues, wakeup/select and precise retirement.
- [ ] Implement branch checkpoints, earlier misprediction recovery and squash rules for younger operations and external effects.
- [ ] Pipeline execution units and evaluate a multi-issue candidate against the narrower baseline using the same workloads and memory assumptions.
- [ ] Define precise faults, instruction boundaries, reset/relaunch behavior and resource-exhaustion handling throughout the enlarged backend.
- [ ] Add randomized control/data hazards and recovery tests, formal properties for allocation/rename/retire/recovery, performance counters and early synthesis/timing feedback.

**Acceptance criteria**

- [ ] Real application and independent ISA regressions preserve supported architectural behavior, including exceptions and wrong-path effect suppression.
- [ ] Tests demonstrate actual out-of-order issue/completion and correct recovery under overlapping dependencies and resource pressure.
- [ ] Selected formal invariants pass under documented assumptions; remaining proof coverage is enumerated.
- [ ] Issue width, register/ROB/queue sizes and predictor choices have workload and synthesis evidence rather than an unsupported big-core label.
- [ ] The performance report separates simulated cycles/IPC from achievable clock frequency and physical energy.

**Required evidence:** Microarchitecture specification, frontend/backend contracts, RTL, adversarial and formal results, design-point comparisons, synthesis constraints and QoR reports.

**Claim boundaries:** An in-order embedded controller cannot satisfy this gate. A future AArch64 frontend needs its own rights review, ISA adapter and independent verification; no dual-ISA implementation is implied.

### S04: Implement the APE and PPE cache and memory-execution hierarchy

**Goal:** Execute both engines through a verified cache hierarchy with the concurrency, ordering and replay behavior required by the selected workloads.

**Dependencies:** S01, S02, S03

**Start and overlap:** Develop alongside S03 after interfaces are agreed; final integration must cover the evolved APE and PPE configurations.

**Work packages**

- [ ] Implement APE load/store queues, store buffering, forwarding, dependence handling and multiple outstanding transactions.
- [ ] Implement PPE memory coalescing, lane masks, scratchpad banking and concurrent miss handling.
- [ ] Implement instruction/data L1 paths, miss-status tracking, refill/writeback handling and a defined shared lower-level cache interface.
- [ ] Specify and implement the initial coherence or explicit-ownership boundary, atomics, fences and device-memory rules.
- [ ] Verify replay, aliases, partial accesses, backpressure, response reordering, faults, instruction publication and wrong-path memory effects.
- [ ] Add cache/memory counters and evaluate capacity/bandwidth choices using the same real workload inputs.

**Acceptance criteria**

- [ ] Both engines execute through the real RTL memory hierarchy, with independent final-state and architectural checks.
- [ ] Ordering, atomics, forwarding, replay and fault tests pass under the declared memory model.
- [ ] Stress tests cover full queues/MSHRs, conflict misses, reordering and reset/drain boundaries without lost or duplicate effects.
- [ ] Formal checks cover selected queue ownership and protocol invariants with explicit environmental assumptions.
- [ ] Reports distinguish behaviorally modeled external memory timing from validated cache/controller behavior.

**Required evidence:** Memory-model and cache specifications, RTL protocol tests, litmus tests, formal results, counters and workload-driven design-point reports.

**Claim boundaries:** Shared virtual addresses alone do not establish coherence. Synthetic memory latency is not measured HBM/LPDDR performance.

### S05: Integrate an embedded RISC-V command processor and device-resident task runtime

**Goal:** Run multi-step APE/PPE task graphs after one host submission using a real command processor and hardware-visible completion mechanisms.

**Dependencies:** S01, S02

**Start and overlap:** Prototype against versioned engine ports in parallel with S03/S04; repeat validation when those ports evolve.

**Work packages**

- [ ] Implement or integrate an appropriately licensed embedded RISC-V CP core, command firmware and queue access path, with original work and imported IP clearly attributed.
- [ ] Implement queue validation, dispatch, task descriptors, completion ownership and engine routing.
- [ ] Implement multiple-child futures, wait/wake, continuations and asynchronous APE-to-PPE and PPE-to-APE handoffs.
- [ ] Define cancellation, watchdogs, timeout, resource-exhaustion policy and completion/backpressure behavior.
- [ ] Add generation-tagged transaction/context identities and contain late, duplicate or malformed responses.
- [ ] Preserve useful legacy task-mechanism tests while explicitly implementing the new integration instead of assuming APE inherited TaskTile fork/join behavior.

**Acceptance criteria**

- [ ] One host submission drives a multi-step task graph including both APE and PPE; the host/testbench does not schedule child work or synthesize results.
- [ ] Correctness tests cover fan-out/join, cancellation at each lifecycle boundary, stale responses and bounded resource exhaustion.
- [ ] All visible side effects obey the specified cancellation/drain contract; cancellation is not mislabeled as rollback.
- [ ] Queue and context ownership checks pass, and task accounting identifies every remaining host intervention.
- [ ] Command firmware, CP RTL and task runtime can be rebuilt and tested together.

**Required evidence:** CP/queue ABI, firmware and RTL identity, task lifecycle traces, negative tests and host-intervention accounting.

**Claim boundaries:** A command-store sink is not CP integration. A CPU hidden inside the package is not by itself evidence of agent acceleration.

### S06: Implement OS-aware protection, faults, preemption and service interfaces

**Goal:** Run protected HATS tasks with defined address spaces, recoverable faults, context switching and explicitly authorized asynchronous OS services.

**Dependencies:** S01, S04, S05

**Start and overlap:** Define contracts early; integrate once memory and task ownership mechanisms are available.

**Work packages**

- [ ] Specify the initial privileged/runtime profile, translation ownership, address-space identifiers and permission checks for every memory master.
- [ ] Implement MMU/TLB or the agreed staged translation path, mapping invalidation and permission/fault reporting for the declared profile.
- [ ] Implement interrupts, preemption safe points, context save/restore and transaction drain or generation-based containment.
- [ ] Implement recoverable fault suspension/replay with no duplicate external effects.
- [ ] Implement capability-scoped asynchronous file/network/service requests, quotas, watchdogs and accounting.
- [ ] Bring up the selected protected runtime/OS profile and process-isolation tests; track full Linux and language-runtime compatibility separately where unsupported.

**Acceptance criteria**

- [ ] Supported tasks boot and execute on the intended RTL/runtime path with a versioned privilege and service contract.
- [ ] Unauthorized access is contained across APE, PPE, CP and DMA/service masters in the implemented system.
- [ ] Preempted tasks resume with correct architectural and task state; fault replay does not duplicate committed side effects.
- [ ] Adversarial service, timeout, invalidation and cross-context tests pass.
- [ ] Independent evaluator authority is separated from candidate-program write authority.

**Required evidence:** Privilege/translation/service specifications, boot and isolation tests, fault/preemption traces and a supported/unsupported OS-service matrix.

**Claim boundaries:** Bare-metal C execution does not establish Linux, POSIX or arbitrary Python support. Hardware provides mechanisms; the OS/runtime retains policy ownership.

### S07: Integrate four NUMA compute domains with HBM and LPDDR tiers

**Goal:** Execute HATS tasks across one validated locality domain and then four domains, with explicit memory placement, ordering and failure contracts.

**Dependencies:** S04, S05, S06

**Start and overlap:** Topology and traffic modeling begin earlier; integration closes only after memory, task and protection contracts are implemented.

**Work packages**

- [ ] Specify one-domain and four-domain configurations with compute-local HBM and independently attached LPDDR, plus APE/service-local LPDDR.
- [ ] Define the physical/virtual address map, local/remote attributes, cacheability, coherence/ownership and cross-domain atomic scopes.
- [ ] Implement routing, DMA, locality-aware placement and migration mechanisms with versioned runtime policies.
- [ ] Implement or model bounded arbitration, backpressure, congestion, quality-of-service and fault containment, clearly labeling each evidence class.
- [ ] Compare placement policies and interference using fixed workloads, data sizes and explicit memory timing/bandwidth assumptions.
- [ ] Define separate integration contracts for HBM/LPDDR controllers, PHYs and package/board constraints.

**Acceptance criteria**

- [ ] Single-domain and four-domain configurations pass functional, ordering, protection and cross-domain task tests.
- [ ] Remote failures and backpressure cannot silently corrupt task ownership or memory state; documented bounded behaviors are tested.
- [ ] Placement/migration tests preserve data and synchronization semantics under concurrency.
- [ ] Local/remote and HBM/LPDDR comparisons are reproducible and state whether timing comes from a model or hardware.
- [ ] Controller/PHY integration status is explicit; routing tags are not presented as implemented physical memory interfaces.

**Required evidence:** Address/topology contracts, fabric RTL and tests, migration and fault traces, traffic/placement studies and memory-IP integration requirements.

**Claim boundaries:** Near/far locality and performance/capacity tiers are separate properties. LPDDR/HBM names alone do not guarantee latency, bandwidth, coherence or persistence.

### S08: Implement PPE tensor execution, compiler support and model inference

**Goal:** Run independently checked model inference through the programmable PPE and real tensor datapaths, integrated with the HATS runtime.

**Dependencies:** S01, S02, S04, S05

**Start and overlap:** Numeric/ISA/compiler design and unit datapaths start alongside S02; single-domain inference need not wait for all four NUMA domains.

**Work packages**

- [ ] Define supported numeric formats, rounding, accumulation, overflow, special-value behavior and per-operation/model error tolerances.
- [ ] Implement actual floating-point/low-precision and tensor datapaths, scheduling and completion paths.
- [ ] Implement data movement and on-chip reuse with explicit register/scratchpad/cache bandwidth accounting.
- [ ] Build the declared PPE compiler/lowering, executable format, linking/loading and runtime interfaces; keep a source-to-target test path.
- [ ] Validate GEMM, reductions, normalization and attention, then complete layers and a pinned small model with prefill/decode where applicable.
- [ ] Integrate inference completion into CP task graphs and evaluate resource contention with agent tools.

**Acceptance criteria**

- [ ] Source-level programs reach actual PPE/tensor RTL through the documented compiler and runtime path.
- [ ] Independent numeric tests meet frozen tolerances across edge cases, individual operators, layers and the selected complete model.
- [ ] Host callbacks do not compute target operator results in the execution path.
- [ ] Inference and tool tasks share the runtime correctly under contention, cancellation and fault conditions.
- [ ] Reports state model/version, shapes, precision, input hashes, supported operations and residual host work.

**Required evidence:** Numeric and tensor ISA contracts, datapath RTL, compiler/runtime artifacts, operator/layer/model comparisons and integrated task traces.

**Claim boundaries:** One GEMM kernel does not close model inference. Training requires a separate approved scope for backward passes, optimizer state, numeric behavior and memory demand; CUDA compatibility is not implied.

### S09: Demonstrate an end-to-end agent tool and bounded improvement loop

**Goal:** Execute a reproducible edit/parse/build-or-interpret/test/evaluate/continue loop through HATS, with isolated evaluation and complete accounting of host work.

**Dependencies:** S02, S03, S04, S05, S06, S08

**Start and overlap:** Build adapters and baselines early; final comparisons include the S07 topology when making four-domain claims.

**Work packages**

- [ ] Freeze representative coding-agent and bounded improvement experiments, model/data versions, seeds, held-out evaluation and resource budgets.
- [ ] Execute source edits/diff/parsing and real compiler passes, then track full compilation/linking separately from compilation for the target.
- [ ] Define and implement the selected Python execution profile with real semantics and tests; track unsupported modules, exceptions, allocation, threads and I/O explicitly.
- [ ] Integrate tests, inference/evaluation and continuations on HATS, with every required external service disclosed.
- [ ] Preserve evaluator isolation, include incorrect candidates/timeouts/resource exhaustion and keep acceptance criteria outside candidate write authority.
- [ ] Compare conventional CPU+GPU, APE-enabled and integrated APE+PPE+task-runtime configurations at equal correctness and model quality.
- [ ] Report completed correct tasks/time, latency tails, host CPU time/interventions, total scalar work including APE, transfers, remote accesses and appropriately evidenced energy.

**Acceptance criteria**

- [ ] At least the selected full coding-agent loop and bounded improvement experiment execute reproducibly on the declared target path.
- [ ] Real compiler and Python coverage is demonstrated for the declared profiles; host substitutes and unrelated small interpreters are not counted as target execution.
- [ ] Evaluation isolation and negative/fault cases pass without changing the frozen acceptance tests.
- [ ] Ablations identify which mechanisms produce any observed benefit and which workloads remain host-bound.
- [ ] Performance claims use comparable execution substrates; simulated RTL wall-clock speed is not compared to a production CPU as hardware speedup.
- [ ] Residual gaps in full upstream framework reproduction and broader RSI claims remain explicitly tracked.

**Required evidence:** Pinned experiment manifests, target execution traces, compiler/interpreter conformance slice, isolated evaluation results, baseline/ablation reports and remaining-host-work inventory.

**Claim boundaries:** Host CPU utilization reduction alone is not proof of efficiency. A bounded improvement experiment does not establish general recursive self-improvement or production-scale framework compatibility.

### S10: Close RTL, FPGA and ASIC implementation gates with physical evidence

**Goal:** Establish progressively stronger implementation evidence: a verified RTL platform, a working FPGA prototype and a separately authorized ASIC-ready implementation.

**Dependencies:** S01, S02, S03, S04, S05, S06, S07, S08, S09

**Start and overlap:** Early synthesis, constraints and feasibility studies start in S02/S03; do not postpone physical feedback until functional integration finishes.

**Work packages**

- [ ] Gate A: package integrated RTL, configuration/filelists, clocks/resets, address/interrupt/boot maps, timing intent, power intent, lint/CDC/RDC status and full-platform regression evidence.
- [ ] Assign design/integration ownership, synthesis/constraints and netlist-QoR ownership, physical closure ownership and independent DV responsibilities.
- [ ] Gate B: select and authorize an FPGA platform, generate a reproducible bitstream, boot/load programs, operate real queues and run representative APE/PPE task workloads.
- [ ] Document FPGA memory substitutions explicitly; DDR emulation of tiers is not physical validation of four HBM-plus-LPDDR domains.
- [ ] Gate C: after explicit process/IP/tool/budget decisions, integrate SRAMs, HBM/LPDDR controllers and PHYs, DFT/scan/MBIST and power/clock/reset implementation.
- [ ] Produce a netlist handoff with SDC, power collateral, synthesis/QoR/timing reports, equivalence results and documented assumptions/waivers.
- [ ] Close floorplan/place/CTS/route feedback, STA, DRC/LVS and power-integrity requirements; prepare package/board and bring-up plans under the selected technology's signoff rules.

**Acceptance criteria**

- [ ] Gate A evidence is reproducible from a named revision and includes functional, integration and selected formal results with remaining coverage documented.
- [ ] Gate B demonstrates actual FPGA execution of the selected integrated workload, with measured clocks and explicit memory/interface limitations.
- [ ] Gate C has technology-specific implementation and signoff evidence, approved IP/tool rights and a reviewed integration/handoff package.
- [ ] Gate A, B and C status is reported separately; the stage remains open while a required gate is unfinished.
- [ ] No tapeout, paid IP acquisition, hardware purchase or cloud/compute spend is inferred from the existence of this issue.
- [ ] Final signoff and release decisions receive explicit review; AI-produced artifacts alone are not a signoff substitute.

**Required evidence:** RTL release package, synthesis/constraints/equivalence reports, FPGA bitstream and hardware results, technology-qualified physical signoff and package/board collateral.

**Claim boundaries:** RTL simulation, synthesis estimates, FPGA validation and tapeout readiness are different evidence classes. A missing PDK, hard IP, board or budget decision is recorded as a dependency, not silently waived.

## Common completion and issue-resolution policy

Every stage issue must have:

1. A frozen positive target: artifact, intended execution path and acceptance gate.
2. An explicit dependency list and current missing capability.
3. Scoped implementation changes with source/license provenance.
4. Independent checks, negative cases and all applicable regression anchors.
5. An evidence record identifying source revision, toolchain, configuration,
   inputs, commands, results, assumptions and known limitations.
6. Links to the implementing commits/PRs and the evidence summary before closure.

Use GitHub's completed state only after the stage's acceptance criteria pass.
An implementation commit or a checked task list alone is insufficient. Large
tasks may be split into linked child issues; the parent stays open until its
required children and integration gate are complete. Deferred requirements need
an explicit scope decision and a linked follow-up, never a silent checkbox edit.

When work is blocked, keep the issue open and record the dependency, safe work
that can proceed, and the next validation command. Start the next ready stage or
independent subtask without treating a partial result as completion of the
original target.

### Evidence classes

| Evidence class | What it can establish |
| --- | --- |
| Specification / contract | Defined behavior and planned interfaces |
| Host/reference execution | Baseline outputs, workload demand and independent semantics |
| RTL simulation / formal | Implemented behavior under the recorded test/proof scope |
| Synthesis / physical estimate | Technology- and constraint-dependent feasibility or QoR |
| FPGA hardware | Actual execution on the declared board and memory/interface configuration |
| ASIC signoff / silicon | Only the implementation or measured claims supported by the corresponding technology-specific evidence |

Never compare host RTL-simulation wall time with native CPU execution and label
the ratio hardware speedup. Behavioral memory models, host-computed kernels and
trace replay may aid diagnostics but cannot close an actual target-execution gate.

## System success criteria

Freeze inputs, model quality/correctness, precision, resource budgets and service
scope before comparisons. Compare at least:

- conventional CPU plus GPU;
- an APE-enabled configuration;
- integrated APE plus PPE plus device-resident task runtime.

Measure completed correct tasks per unit time, end-to-end and tail latency, host
CPU time and interventions, total scalar work including APE, transfer volume,
local/remote memory activity and energy where the execution substrate supports a
credible measurement. Use ablations to isolate benefits from compute, locality,
task control and memory placement. Publish remaining host work alongside results.

Full upstream experiments require their own pinned dependencies, datasets,
model/compute budgets and evaluation conditions. A component port or bounded
improvement loop must not be labeled a complete RSI reproduction.

## Development infrastructure and reproducibility

- Preserve pinned tools and source-hashed reports; make every accepted stage
  reproducible before widening its scope.
- Add automated regression gates and independent review paths as the platform
  grows. Parallel agents or contributors must have bounded ownership and must
  not silently edit each other's uncommitted work.
- Evaluate reproducible local/cloud environments when justified by workload and
  verification needs. Cloud execution, recurring jobs and paid resources require
  explicit configuration and authorization.
- AI assistance can create code, tests and documents; independent architectural
  oracles, formal checks, hardware measurements and signoff remain necessary.

## Implementation ownership and handoff

| Role | Deliverable responsibility |
| --- | --- |
| Architecture / block design | Behavior, microarchitecture, RTL and design bug fixes |
| SoC integration | Top-level connectivity, boot/address/interrupt maps, clock/reset and IP integration |
| Frontend implementation | Synthesis constraints, netlist quality, timing/QoR feedback and equivalence handoff |
| Physical implementation | Floorplan, placement, CTS, routing and physical closure |
| Verification | Independent functional/integration evidence and coverage; not ownership of constructing the chip |
| Compiler/runtime and workload owners | Source-to-target execution, service boundaries, profiles and comparable experiments |

An RTL handoff includes constraints, configuration, power/clock/reset intent,
maps, checks and known issues. A netlist handoff additionally includes synthesis,
timing/QoR, equivalence and applicable DFT collateral. Return impossible timing
or congestion problems to the owning architecture/RTL/constraint decision early.

## Scope and release boundaries

Use original design, public specifications and appropriately licensed sources.
Keep reference provenance separate from implementation provenance. Rewriting
code is not, by itself, proof of a legally established clean-room process.
Private source RTL, company decks, customer context, credentials, raw intake and
unreleased partner details must not enter public roadmap issues or repository
artifacts.

Future training, alternative ISA frontends and broader compatibility targets
need explicit specifications and validation gates. ASIC process selection, hard
IP, boards, paid tools, external compute and fabrication are decision gates, not
automatically authorized purchases.

## Related specifications and evidence

- [APE overview](hardware/spinal/APE.md)
- [APE roadmap](hardware/spinal/spec/APE-ROADMAP.md)
- [APE verification map](hardware/spinal/spec/APE-VERIFICATION.md)
- [Independent Spike gate](hardware/spinal/spec/APE-SPIKE-VALIDATION.md)
- [Bounded application ABI](hardware/spinal/spec/APE-APPLICATION-ABI.md)
- [Shared ISA substrate proposal](hardware/spinal/spec/APE-SHARED-SUBSTRATE.md)
- [Task and memory architecture](hardware/spinal/ARCHITECTURE.md)
- [Workload coverage and OS cooperation](workloads/COVERAGE.md)
- [Tree-sitter runtime build reference](https://tree-sitter.github.io/tree-sitter/using-parsers/1-getting-started.html)
