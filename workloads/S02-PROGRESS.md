# S02 progress: real APE tool execution and PPE ISA reference

**Historical checkpoint, superseded by [S02 completion](S02-COMPLETION.md).**
The statements and `S02-CHECKPOINT.json` below describe the earlier partial
snapshot; they are not current-source evidence or current issue status.

Checkpoint: 2026-10-09, before PPE RTL implementation. [Issue #3](https://github.com/chienpinglu/HATS/issues/3)
was **open and incomplete**. S01 / issue #2 was complete. This checkpoint
advances execution, not the later high-performance big-core or CP milestones.

## Delivered and verified

| Area | Evidence | Boundary |
| --- | --- | --- |
| Real upstream tool | Unmodified pinned Tree-sitter C runtime + JSON grammar, strict RV64I/LP64 executable, 94,944 bytes of code | Original HATS runtime adapter; not Linux, a compiler or Python interpreter |
| Independent ISA execution | All 10 frozen fixtures × 3 parse modes = 30 passing Spike runs; full semantic output oracle | Large fixtures are currently Spike-only, not RTL coverage |
| Runtime correctness | 177 arithmetic vectors × 6 results; 160 target runtime self-checks; 10 explicit resource/argument failures | These auxiliary suites run on Spike; isolated single-hart atomic contract only |
| Actual APE RTL | Empty/scalars/Unicode × 3 modes × 2 launches = 18 invocations; 1,534,220 retirements and 624,924 memory events matched exactly to Spike | One ROB=8/bimodal configuration, 256 KiB instruction capacity and modeled external memory |
| PPE original ISA | 37 opcodes, fixed 8-byte encoding, validated code object, assembler/disassembler API, independent wave model | No PPE RTL yet |
| PPE verification | 21 tests, including nested divergence, inactive-lane suppression, partial stores, overflow, scratch and a masked byte-classification program | Functional behavior, not hardware timing or synchronization validation |
| Loader/evidence tests | 8 loader/output/provenance tests and 4 checkpoint-validation tests | Negative coverage is bounded, not exhaustive malformed-input certification |

The same parser ELF and inputs are used by Spike and APE RTL. RTL results come
from real core execution, not a host parser callback. The complete output region
matches, and a separate semantic-tree oracle checks node types, UTF-8 byte spans,
depth/order, error reporting and zero live parser allocations after cleanup.

The larger program store uses the existing `ApeCore` configuration parameter;
**this checkpoint does not modify the OoO core RTL**. APE remains the existing
small speculative out-of-order prototype, with head-only external memory
publication and one outstanding transaction. This is not the completed
high-performance application core, an L1 hierarchy or a physically implemented
256 KiB instruction SRAM. The 10 MiB parser heap is a simulation reservation,
not a memory-controller or HBM/LPDDR capacity decision.

## Regression anchors

- Existing APE: 600 RTL invocations across ROB 4/8/16 and prediction off/bimodal,
  plus 4,096 predictor checks.
- Independent Spike comparison: 576 fully matched invocations and 24 explicitly
  checked existing profile differences; no unexpected divergence.
- Existing bounded line-diff application: 144 RTL invocations, exact Spike
  traces and independent minimum-edit checks.
- Legacy task tile: 123 tests across 2/4/8 contexts. This run used the pre-existing
  locally modified `TaskTile.scala`; that unrelated change is preserved and not
  part of this checkpoint's implementation or clean-checkout evidence.
- Existing S01 evidence gate and its 56 checker tests pass unchanged.

## Source and reproduction entry points

- [Runtime and real-tool execution guide](target/treesitter/execute/README.md).
- [PPE binary ISA and executable semantics](../hardware/spinal/spec/PPE-ISA-0.1.md).
- [PPE model](../hardware/spinal/tools/ppe_isa.py) and
  [original program fixtures](../hardware/spinal/tools/ppe_programs.py).
- [APE large-image SpinalSim adapter](../hardware/spinal/src/test/scala/hats/ApeToolSim.scala).
- [Public-safe checkpoint evidence](evidence/S02-CHECKPOINT.json).

The checkpoint stores source/artifact identities, per-case reference execution,
selected RTL coverage and explicit exclusions. Full traces, logs, generated
executables and third-party build products remain in ignored local directories.
The only external code used by the executable is pinned public upstream code
and its retained notices; no private reference ISA/RTL is copied.

After running the execution and regression commands in the guides, produce a
fresh summary with the actual report paths printed by those runs:

```sh
python3 workloads/s02/checkpoint.py \
  --reference workloads/results/s02-treesitter-<full-run>/validation.json \
  --rtl workloads/results/s02-treesitter-<rtl-run>/rtl-validation.json \
  --output workloads/evidence/S02-CHECKPOINT.json
```

This command checks existing report/artifact/source identities and reruns fast
tests. It **does not rerun RTL** and cannot turn a partial gate into S02 completion.

## Remaining S02 work, in execution order

1. **PPE SpinalHDL core and direct engine adapter.** Implement instruction fetch,
   decode, scalar/vector/predicate registers, integer execution, masks, structured
   reconvergence, scratch and serialized global accesses. Start with the original
   byte-classification binary fixture. Keep the Python model independent of RTL.
2. **PPE independent RTL comparison.** Match retired PCs, masks, register changes,
   memory effects and fault/completion records. Exercise all instructions,
   resource rejection, held launch/completion, delayed responses, barriers,
   inactive-lane faults, partial stores, budget/drain and repeated launches.
3. **APE coverage expansion.** Execute helper/runtime/resource-failure binaries
   on RTL, extend parser coverage to nesting/invalid JSON and multiple core
   configurations. Choose a bounded strategy for large traces before claiming the
   full tool matrix. Larger simulated capacity alone is not a performance fix.
4. **One reproducible two-engine gate.** Record both generated RTL configurations,
   source/build identities and independent results, while preserving existing
   APE/predictor/diff/legacy anchors. Separate unchanged committed legacy behavior
   from any other local work before making a clean-checkout release claim.
5. **Close issue #3 only against its acceptance criteria.** Larger OoO backend
   performance work belongs to S03 / issue #4; caches/coalescing to S04 / issue #5;
   CP queues and autonomous APE↔PPE task continuations to S05 / issue #6. Do not
   count host-driven model launches as that CP implementation.

No end-to-end agent speedup, CPU replacement ratio, coherent heterogeneous
memory, general-purpose software compatibility, silicon PPA or tapeout-quality
claim is supported by this checkpoint.
