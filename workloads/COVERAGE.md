# Workload coverage and architecture requirements

The workload collection tests the hypothesis that HATS can reduce external CPU
participation in agent execution and improvement loops. It does not establish
that queues, shared memory or moving CPUs onto the package are sufficient.

## Upstream experiment coverage

The links below identify upstream setup instructions at the selected commits.
The local cache contains selected files, not full installations. Full runs need
separate checkouts, dependency/data review, isolated execution, and explicit
model and compute budgets. No full experiment adapter is implemented yet.

| Project and pinned setup | Full experiment still needed | Current local evidence |
| --- | --- | --- |
| [GEPA](https://github.com/gepa-ai/gepa/blob/fb1ed589fd83372caef499cffc2c73173d3b096b/README.md) | Task/reflection model, evaluation split, metric-call budget, optimization run | Candidate-selection and serialization components |
| [ACE](https://github.com/ace-agent/ace/blob/82709de050e1db6e6ef2f07bcb0393560b94992a/README.md) | Generator/reflector/curator models, dataset, playbook evolution and held-out evaluation | Extracted playbook/JSON functions |
| [AFlow](https://github.com/FoundationAgents/MetaGPT/blob/11cdf466d042aece04fc6cfd13b28e1a70341b1f/examples/aflow/README.md) | MetaGPT environment, model configuration, benchmark data, workflow search and evaluation | Source processing only |
| [DGM](https://github.com/jennyzzt/dgm/blob/a565fd2d1dca504ef5104a7cc0f3bdc4ab9b4fd2/README.md) | Model access, Docker, SWE-bench/Polyglot environments, archive/evolution runs | Editing component and source processing |
| [STOP](https://github.com/microsoft/stop/blob/0d6780c54306b2486dd36e9c4ae9b49aceb27ea4/README.md) | Model access, safe candidate execution, task utilities and search budgets | Two original seed algorithms on HATS fixtures |
| [AHE](https://github.com/china-qijizhifeng/agentic-harness-engineering/blob/8b2a55d97590363fe50c3cc6b5e833b020a4bb4c/README.md) | NexAU environment, model/search services, E2B or self-hosted sandbox, datasets and traces | Source processing only |
| [Gas City](https://github.com/gastownhall/gascity/blob/2f33858ba14280b07ba5ea8e740e70f78f59c7a6/README.md) | Full Go build, configured agent/session and state backends, disposable project | Go source diff/patch only; not orchestration execution |

Model inference, tensor kernels, C/C++ compilation, linking, complete Python
applications, process orchestration and training remain uncovered. In particular,
Python bytecode compilation must not be reported as native compiler acceleration.

## Proposed architecture mapping

These are hypotheses to validate, not observed bottlenecks from the current
small test cases. None of these workload paths is implemented on HATS yet.

| Work being moved | Execution requirements to evaluate | OS/runtime requirements |
| --- | --- | --- |
| Diff, patch, scanning | Byte/word loads, comparisons, branches, vectors, caches | Bounded file service, permissions, atomic publication |
| Candidate/graph selection | Indirect access, sets/maps, allocation, atomics, independent tasks | Private heaps/address spaces, bounded budgets |
| Python control and parsing | Calls/stacks, indirect branches, objects, exceptions, interpreter/JIT strategy | Memory allocation, module/library support, threads and I/O services |
| Native compiler passes | Scalar throughput, locality, IR traversal, parallel compilation | Files, process services, executable loading and protection |
| Inference and kernel evaluation | Tensor/vector engines, DMA, explicit memory placement | Resource reservation, device completion, independent evaluator |
| Persistent orchestration | Futures, fan-out, cancellation, preemption | Durable storage, event delivery, recovery and authorization |

The current tile has one scalar issue pipeline, a small A64 subset, fixed-width
memory accesses, invocation bounds and one-child joins. It lacks caches, MMU,
privilege levels, full calling conventions, a language runtime, tensor engines
and OS-service queues. Those are concrete blockers, not software configuration
options that can enable these workloads today.

The [RISC-V HATS Application Processing Engine (APE)](../hardware/spinal/APE.md) is a separate
speculative out-of-order prototype. Its tests exercise RV64 integer programs and
a small compiler-generated C function. Compiling a test *for* APE is not running
a compiler *on* APE. Neither those tests nor a command-store sink establish
execution of this agent workload suite, CP integration or autonomous fork/join.

## OS cooperation contract

HATS should be OS-aware without hardwiring Linux or an agent framework into the
hardware. Proposed responsibility boundaries are:

| Mechanism | Processor/runtime responsibility | OS/service responsibility |
| --- | --- | --- |
| Address spaces | Context/address-space tags, translation, permission checks on every master | Map/unmap policy, page ownership, accounting |
| Recoverable faults | Fault records, suspend/replay with no duplicate side effects, invalidation acknowledgments | Resolve mappings or terminate the task |
| Preemption | Defined safe points, save/restore state, transaction drain or generation tags | Fairness, priorities and quotas |
| Asynchronous I/O | Capability-scoped requests and completions; task waits without blocking a whole tile | Filesystem/network semantics, authorization and durable storage |
| Synchronization | Atomics, memory ordering, wait/wake and cancellation semantics | Runtime scheduling and race-free ownership protocols |
| Executable code | Defined instruction-cache synchronization and executable permissions | Compiler/JIT, loader, ABI, code publication policy |
| Isolation | Fault containment, watchdogs, context-tagged telemetry | Separate evaluator authority; candidate code cannot change acceptance tests |

This is a proposed contract, not implemented RTL. The host/service CPU can
remain responsible for privileged policy while ordinary user-level work moves
onto HATS. Moving conventional CPU cores inside the package alone does not
establish greater efficiency. Count external CPU work and total scalar work
separately.

Linux [HMM](https://docs.kernel.org/mm/hmm.html) is a useful existing reference
for heterogeneous address-space mirroring and memory migration. It is not a
complete process, syscall, runtime or isolation implementation for HATS. Also,
shared virtual addressing does not by itself guarantee cache coherence, shared
performance, or fault isolation.

## Relation to HSA

HSA's [system, programming and runtime standards](https://hsafoundation.com/standards/)
already address heterogeneous cooperation. AMD's
[ROCR runtime](https://rocm.docs.amd.com/projects/ROCR-Runtime/en/latest/what-is-rocr-runtime.html)
implements HSA interfaces including queues, signals, dispatch and memory access.
HSA had concrete problems to solve and is not merely an abandoned ideal.

HATS proposes a particular processor/runtime architecture and workload target,
not a replacement name for HSA. Its hypothesis is efficient execution of the
agent program around inference, including editing, compilation, evaluation and
continuations. Shared memory, queues and device scheduling alone are not novel
claims. Novelty and value require comparison with HSA-based systems, ordinary
CPU/GPU cooperation and specialized inference designs.

## Next gates

1. Capture real, authorized agent traces across prompt/context optimization,
   workflow search, coding and kernel improvement. Freeze model, inputs and
   evaluation budgets; preserve provenance without publishing private traces.
2. Measure CPU time, allocations, working sets, branch behavior, synchronization,
   file/process activity and critical-path time. Separate inference, compilation,
   tests, target-device execution and network waits. Host profiles characterize
   demand; they do not validate HATS speed.
3. Select an actual component for HATS execution; extend ISA/ABI, memory and
   runtime support to execute it without host substitution. Differential-test
   output and faults against the host implementation using the same inputs.
4. Run an entire edit/build/test/evaluate continuation loop, with explicit
   reporting of every remaining host service. Keep evaluators outside candidate
   write authority; include incorrect programs, timeouts and resource exhaustion.
5. Compare completed correct tasks/time, latency tails, total energy, host
   interventions and resource cost. Measure memory placement and interference
   before choosing HBM/LPDDR capacities or adding dedicated units.

The target is improved complete-loop efficiency at equal correctness and quality.
Neither an isolated kernel speedup nor more passing microtests proves it.
