# HATS

**HATS: Heterogeneous Agent Tool Substrate**

HATS explores a GPU-adjacent compiler and runtime substrate for bounded,
local tools used by agentic AI systems. The central idea is to move frequent
memory-resident tool primitives, such as retrieval, schema validation,
dependency scheduling, cancellation, and small sandboxed kernels, closer to
GPU-resident model execution.

The project starts as a compiler/runtime investigation inspired by HSA:

- coherent shared virtual memory for model state, tool buffers, and indexes;
- user-mode queues for cheap tool dispatch;
- signals and futures for dependency-heavy agent workflows;
- capability-scoped access to bounded local tools;
- profiling feedback to identify hardware primitives with credible PPA value.

The initial paper draft is in [`papers/hats_agent_tool_substrate.tex`](papers/hats_agent_tool_substrate.tex).

## Scope

HATS intentionally does not try to accelerate arbitrary external tools such as
browser automation, shell execution, or general web APIs. The first target is a
narrow substrate for local, bounded, memory-oriented tool primitives that recur
inside modern agent loops.

## Repository Layout

```text
papers/
  hats_agent_tool_substrate.tex  Initial paper draft
```

