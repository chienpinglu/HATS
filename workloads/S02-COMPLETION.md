# S02 completion: real APE tool and first programmable PPE

Date: 2026-10-09. Stage: [issue #3](https://github.com/chienpinglu/HATS/issues/3).
The complete gate passed on the declared profiles. Machine-readable public-safe
evidence is [S02-CLOSURE.json](evidence/S02-CLOSURE.json). Earlier
[checkpoint notes](S02-PROGRESS.md) and `S02-CHECKPOINT.json` are historical, not
current-source proof. This closes S02, not the full HATS processor roadmap.

## What executes in hardware

**APE — Application Processing Engine:** the pinned, unmodified Tree-sitter
C runtime and JSON grammar execute as a strict-linked RV64I/LP64 program on the
existing speculative out-of-order `ApeCore`. Startup, software arithmetic helpers,
bounded Newlib allocation, incremental edits, parsing, tree traversal and cleanup
all run as target instructions. No host parser supplies target results. The
original platform adapters and empty upstream patch set are enumerated in
[port-manifest.json](s02/port-manifest.json).

**PPE — Parallel Processing Engine:** an original SpinalHDL `PpeCore` executes
37 scalar/vector integer instructions. It has one resident eight-lane wave,
scalar/vector/predicate registers, full-mask scalar control, structured
divergence/reconvergence, 4 KiB scratch, serialized tagged global memory,
fences/single-wave barriers, launch rejection, faults, held completion and
safe drain before reuse. Binary programs are loaded through a direct engine
adapter; this is not a CP or multi-wave scheduler.

## Verified evidence

| Gate | Passed coverage | What is compared |
| --- | --- | --- |
| Native tool | 90 executions: 30 each native, instrumented and ASan/UBSan | Frozen inputs, independent semantic oracle, cleanup |
| Full APE real-tool gate | 42 RTL invocations: 30 parser modes/cases, 10 errors, helpers and runtime | Complete stream digest, full output image, independent output checks |
| Full APE architectural stream | 860,981,474 retirements; 357,201,875 memory events | Every PC/instruction/next PC and all 32 architectural registers, every memory event and final trap; no sampling |
| Native/APE parity | 30 semantic results | 28 full valid trees and two invalid-syntax flags, with zero live allocations; error-recovery trees are outside the frozen contract |
| Independent SpinalSim transport | Nine small parser cases/modes × two launches = 18 | Exact event-by-event Spike trace match; all 18 full-state digests and output images also match the bulk transport |
| Arithmetic/runtime | 177 vectors × six results; 160 runtime checks | Actual RTL helper/runtime instructions vs independent arithmetic/check expectations |
| PPE | 112 fixtures × two launches = 224 | 180 full ISA-model state comparisons; 44 separately classified decode/resource/watchdog/quiescence checks |
| Existing APE | 600 invocations, six ROB/predictor configurations; 4,096 predictor checks | Existing mechanism and predictor assertions |
| Existing external reference | 576 matches + 24 explicitly checked profile differences | No new or unexpected divergence; unchanged launch-alignment/FENCE.I boundaries |
| Existing bounded diff | 144 invocations | Exact Spike events and independent minimum-edit script checks |
| Committed legacy TaskTile | 123 tests, 2/4/8 contexts | Committed source, generated RTL, task-mechanism anchors; unrelated live edits preserved |
| Fast checks | 21 PPE-model, eight loader/output, 17 S02 checker, 56 S01 tests | Malformed inputs, source identity, missing/duplicate evidence and deliberate trace/state corruption |

Bulk SHA-256 is complete-stream cryptographic evidence, not a formal proof.
Registers are reconstructed from RTL architectural retirement ports and compared
with Spike's actual register state. The independent small-text encoding check
and separate SpinalSim adapter guard against transport/encoding mistakes. PPE
uses direct full-state trace comparison, including all scalar/vector/predicate
values at every retirement, ordered memory effects and final memory/scratch.

## Work-package and acceptance review

| Issue #3 item | Implementation/evidence |
| --- | --- |
| WP1: executable capacity and runtime | Existing APE configuration expanded to 65,536 instruction words in the tool profile; 94,944-byte strict ELF, validated loader, BSS clearing, stack, bounded 10 MiB heap and Newlib services |
| WP2: required ISA/runtime support | No speculative new ISA extensions; original RV64I software helpers and isolated-hart atomic adapters independently tested; bounded diff remains passing |
| WP3: upstream tool and host inventory | Immutable Tree-sitter/grammar/Newlib/Spike identities, no upstream patches, source hashes and explicit [port guide](target/treesitter/execute/README.md) |
| WP4: independent PPE ISA | [Binary encoding and model](../hardware/spinal/spec/PPE-ISA-0.1.md), assembler/disassembler APIs, 21 tests with legal/illegal programs |
| WP5: programmable PpeCore | [Original RTL](../hardware/spinal/src/main/scala/hats/PpeCore.scala), fetch/decode, active-lane selection, integer register paths, masks/stack, memory/scratch and single-wave synchronization |
| WP6: actual PPE verification | [SpinalSim](../hardware/spinal/src/test/scala/hats/PpeCoreSim.scala) and independent full-state comparison; stalls, resource rejection, relaunch, stale responses, partial stores and never-reply handling |
| AC1: native/target and ISA agreement | 30 native/target semantic results; 42 complete architectural-stream matches, 18 exact small SpinalSim event matches, independent output checks |
| AC2: actual upstream logic on RTL | Verilator executes generated `ApeCore`; both adapters provide clock/launch/memory only, no target ISA/parser interpreter |
| AC3: PPE traces and synchronization | 180 full ISA comparisons plus 44 protocol/decode checks; divergence and memory-draining barriers covered |
| AC4: preserved regression anchors | 600 APE, 4,096 predictor, 576+24 Spike, 144 bounded-app and 123 committed legacy checks |
| AC5: reproducible two-engine build | [run_all.py](s02/run_all.py), [gate.py](s02/gate.py); source, dependency, toolchain, ELF, generated-RTL and result identities in closure evidence |

## Reproduce

The tested platform is macOS arm64 with Python 3.14.3 (3.12+ required),
LLVM/LLD 23.1.2, host Clang++, make, dtc, Homebrew OpenSSL 3, Verilator 5.052,
Java 25.0.2, Scala 2.13.14, sbt 1.10.7 and SpinalHDL 1.12.3. The native digest
adapters currently use `/opt/homebrew/opt/openssl@3`; other platforms require
a toolchain-path port and fresh evidence. Dependencies are not installed silently.

Populate the public, pinned caches using the [native](native/treesitter/README.md),
[Newlib](target/treesitter/README.md), [Spike](../hardware/spinal/spec/APE-SPIKE-VALIDATION.md)
and [hardware bootstrap](../hardware/spinal/DEVELOPMENT.md) instructions first.
First bootstrap/dependency resolution needs network access; no paid services,
model credentials or private source repositories are required.

From the repository root:

```sh
python3 workloads/s02/run_all.py
```

This creates fresh native/bulk/SpinalSim/PPE reports, reruns existing APE/Spike/diff
and committed-legacy regressions, then invokes the full collector and fast tests.
It does not silently reuse earlier execution reports, mutate source files,
commit, push or close issues. Large actual-RTL simulations take minutes and are
not a fast unit-test target. Do not run concurrent sbt jobs in the same checkout.

To recheck previously executed evidence without rerunning hardware, use the
paths printed by the corresponding runs:

```sh
python3 workloads/s02/gate.py \
  --native workloads/results/treesitter-<native>/validation.json \
  --bulk workloads/results/s02-treesitter-<bulk>/bulk/validation.json \
  --spinal workloads/results/s02-treesitter-<small>/rtl-validation.json \
  --ppe hardware/spinal/build/ppe/run-<ppe>/validation.json \
  --legacy hardware/spinal/build/s02-legacy/<legacy>/validation.json \
  --output workloads/results/s02-rechecked.json
```

The collector validates exact matrices, current source hashes, frozen inputs,
artifact hashes, native parity, cross-transport state streams, PPE comparisons,
dependency builds and old regressions. Missing/stale reports fail closed. The
legacy script builds a generated snapshot of committed `TaskTile.scala` through
a temporary sbt source override, without overwriting any local modification.
Its source commit/hash is explicit in the evidence. This is not a claim that
uncommitted TaskTile edits were validated or included in S02.

## Source and claim boundaries

Only original HATS code/specifications and public-safe evidence are committed.
Pinned external source, generated executables, full traces, local paths and raw
build logs remain in ignored caches/results. Preserve all upstream per-file
licenses when distributing their binaries. No private ISA/RTL was imported.

The parser profile has a 256 KiB asynchronous instruction store and modeled
external data service. Its memory reservations are simulation bounds, not cache,
SRAM, HBM/LPDDR-controller or physical-capacity results. Atomic helper correctness
assumes an isolated hart with no interrupt/DMA/shared writer; it is not RISC-V A.
PPE launch/code validation is trusted, responses are registered and tagged, and
the caller must supply fresh identities and quiesce the fabric before reset.
Never-responding transactions remain busy: no fabricated successful drain.

APE remains a small real speculative OoO integer core. S02 does **not** finish
the high-performance application processor, memory hierarchy, CP, OS protection,
four-domain NUMA fabric, floating-point/tensor engine, general Python execution,
compiler-on-target, full RSI agent loop, FPGA/ASIC implementation or measured
agent acceleration. The old 21 host component cases remain host-only.

Next gates: S03 / #4 for the performance APE microarchitecture; S04 / #5 for
caches/coalescing and concurrent memory; S05 / #6 for embedded RISC-V CP and
autonomous APE↔PPE task graphs. Early synthesis/physical feedback is S10 / #11;
none of those are automatically completed by this functional S02 result.
