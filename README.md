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
papers/
  hats_agent_tool_substrate.tex  Initial paper draft
references/
  hsa/                            HSA source index and local fetch metadata
scripts/
  fetch_hsa_specs.sh              Downloads local ignored HSA PDFs
third_party/
  OpenROAD/                       Backend physical design engine submodule
```
