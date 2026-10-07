# HATS

**HATS: Heterogeneous Agent Tool Substrate**

HATS explores a GPU-adjacent compiler and runtime substrate for bounded,
local tools used by agentic AI systems. The central idea is to move frequent
memory-resident tool primitives, such as retrieval, schema validation, context
assembly, dependency scheduling, cancellation, and small sandboxed kernels,
closer to GPU-resident model execution.

The project starts as a compiler/runtime investigation inspired by HSA:

- coherent shared virtual memory for model state, tool buffers, and indexes;
- user-mode queues for cheap tool dispatch;
- signals and futures for dependency-heavy agent workflows;
- capability-scoped access to bounded local tools;
- profiling feedback to identify hardware primitives with credible PPA value.

## HATS Execution Engines

The scalar architecture direction is now **RISC-V**, using SpinalHDL and
SpinalSim. [HATS Application Processing Engine (APE)](hardware/spinal/APE.md) is an original
speculative out-of-order integer-core prototype: ROB-tag renaming, oldest-ready
issue, in-order retirement and head-only publication of memory effects. Its
verification entry point is `hardware/spinal/tools/verify_ape.py`; generated
reports distinguish tested mechanisms from full-ISA support and performance.
Speculative out-of-order execution is mandatory for APE. `ApeCore` now includes
configurable bimodal branch and direct-jump prediction; HSE names remain adapters.
It is not yet a complete high-performance big core or HATS task runtime.

- [APE specification](hardware/spinal/spec/APE-0.2.md): instruction subset, OoO rules and interfaces.
- [Verification map](hardware/spinal/spec/APE-VERIFICATION.md): requirements, tests and limits.
- [Development guide](hardware/spinal/DEVELOPMENT.md): source layout and reproducible commands.
- [Processor roadmap](hardware/spinal/spec/APE-ROADMAP.md): remaining application and HATS integration gates.

CPU/GPU are deployment categories rather than mandatory internal boundaries:
scalar, vector/tensor and command/task-control roles can use different ISAs.
The command controller and vector/tensor datapaths remain future integration work.

## Legacy Autonomous Task Tile Prototype

The research now includes a [SpinalHDL task-execution prototype](hardware/spinal/README.md)
that explores moving supported runtime control flow onto the processor itself.
Independent A64-subset contexts create child tasks, wait for memory or children,
and resume without host scheduling after the initial submission.

The [architecture contract](hardware/spinal/ARCHITECTURE.md) separates the target
RISC-V plus vector/tensor, HBM/LPDDR processor from the legacy A64 scalar task tile.
SpinalSim with Verilator passes 41 scenarios at each of 2, 4 and 8 contexts
(123 test instances). This is mechanism verification, not evidence of agent
speedup, PPA, full Arm conformance, or a complete AI processor. The initial paper
below retains its earlier, narrower agentic-prefill scope.

## Agent Workload Suite

The [workload suite](workloads/README.md) pins selected open-source components
from GEPA, ACE, AFlow, DGM, STOP, AHE and Gas City. It provides 21 host-side
component and source-processing cases, including text diff/patch and Python
bytecode compilation. These are not full agent reproductions or HATS execution.
The [coverage map](workloads/COVERAGE.md) records full-run requirements, missing
workloads and the proposed OS cooperation contract.

## Hardware Toolchain

HATS treats hardware as an empirical consequence of the compiler/runtime
bottlenecks. The intended open toolchain is:

```text
HATS agentic-prefill IR
  -> RTL / hardware generators
  -> frontend synthesis and verification
     - Yosys / Surelog / slang / Verilator / CIRCT
  -> backend physical design
     - OpenROAD / OpenROAD-flow-scripts
  -> timing, area, power, congestion, and layout feedback
  -> compiler/runtime placement and hardware primitive updates
```

OpenROAD is included as a pinned submodule at
[`third_party/OpenROAD`](third_party/OpenROAD). It is the backend engine for
floorplanning, placement, clock tree synthesis, routing, timing repair, and
layout-oriented feedback. OpenROAD-flow-scripts is the expected RTL-to-GDS flow
harness around OpenROAD; it is intentionally documented as a workflow dependency
because the project may use either a local checkout, a container image, or a
CI-managed installation.

To initialize the checked-in backend dependency:

```sh
git submodule update --init --recursive third_party/OpenROAD
```

For local flow experiments:

```sh
git clone --depth 1 --branch master \
  https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git \
  third_party/OpenROAD-flow-scripts
```

The AI-assisted backend design loop should use OpenROAD reports as structured
feedback rather than as a one-shot GDS generator:

- generate candidate RTL for HATS blocks such as queues, signals, retrieval
  datapaths, parser units, and prefill/context assembly engines;
- run synthesis, floorplanning, placement, routing, and timing checks;
- summarize timing, area, utilization, congestion, clocking, and memory
  locality issues;
- feed those reports back into the compiler/runtime model and the hardware
  generator;
- keep hardware proposals tied to measured PPA deltas against CPU-mediated
  orchestration.

The initial paper draft is in [`papers/hats_agent_tool_substrate.tex`](papers/hats_agent_tool_substrate.tex).

## Scope

HATS intentionally does not try to accelerate arbitrary external tools such as
browser automation, shell execution, or general web APIs. The first target is a
narrow substrate for local, bounded, memory-oriented tool primitives that recur
inside modern agent loops.

## Repository Layout

```text
README.md
hardware/
  spinal/                         Task tile, architecture contract and RTL tests
workloads/                        Pinned host components and architecture coverage
papers/
  hats_agent_tool_substrate.tex  Initial paper draft
references/
  hsa/                            HSA source index and local fetch metadata
scripts/
  fetch_hsa_specs.sh              Downloads local ignored HSA PDFs
third_party/
  OpenROAD/                       Backend physical design engine submodule
```
