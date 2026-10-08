# S01 native demand and coding-tool workflow profile

This supplements the [native baseline](../native/treesitter/README.md), not a
replacement parser or target backend. All upstream code remains pinned and
unmodified. The original measurement adapters in this directory change build
instrumentation only. Runs use the same ten frozen fixtures and independent
JSON structure/span oracle. This is a representative **local tool** slice, not
a reproduced GEPA/ACE/AFlow/DGM/STOP/AHE/Gas City experiment.

## Reproduce

Use Python 3.12+, Git and LLVM Clang/llvm-profdata/llvm-cov (tested: Python 3.14.3,
LLVM 23.1.2, Darwin arm64). Source caches must already pass the native baseline's
`check` command. Nothing installs packages or uses model credentials.
On the development Mac, use `/opt/homebrew/bin/python3`; the shell's `python3`
may resolve to an older framework interpreter that cannot run pinned AHE syntax.

```sh
python3 -m unittest discover -s workloads/profile -p 'test_*.py' -v
python3 workloads/profile/run.py --summary workloads/evidence/S01-DEMAND-PROFILE.json
# Entire S01 gate, including re-execution rather than only saved evidence:
python3 workloads/s01_gate.py --run-workloads --summary workloads/evidence/S01-CLOSURE.json
# Fast subsequent regression/evidence check (does not rewrite completion evidence):
python3 workloads/s01_gate.py
```

There are 90 demand runs: memory, source-branch and stack variants × ten fixtures
× cold-old/cold-new/incremental. Each output passes the same independent oracle
and zero-tracked-leak check as the baseline. The three instrumentation variants
are deliberately separate. Do not compare their timings or binaries as though
they were the native timing build.

| Instrument | Observation | Exclusions / meaning |
| --- | --- | --- |
| Clang load/store probes | Per-parser-phase accesses/bytes, distinct 64-byte lines, repeated line touches, consecutive same/adjacent lines | Only probed upstream runtime/grammar loads/stores; not libc, OS, bulk intrinsics or atomic accesses; no cache-miss, reuse-distance or DRAM-bandwidth claim |
| Original atomic wrappers | Seq-cst reference-count increments/decrements and relaxed atomic loads, preserving values and orders | Single-thread, no contention; zero relaxed loads means the observed phases did not use them, not that the runtime never requires them |
| LLVM source branch coverage | True/false outcomes and reached/both-outcome branch regions across a whole invocation | Includes parser, result traversal and cleanup; source regions/macros rather than dynamic machine branches, mispredictions or per-phase timing |
| Guarded native thread stack | Lowest sentinel-overwritten byte to top of supplied 2 MiB stack | Written extent includes pthread startup, adapter and libc; excludes untouched reservations and possible sentinel collisions; neither exact reserved peak nor worst-case/target bound |
| Independent native baseline | Allocations, requested live heap, parse wall/CPU time, host executable/section size | Instrumentation/allocator metadata and process-wide footprint remain separate |
| Separate RISC-V static audit | Instruction families, per-function frame sizes and retained runtime/provider requirements | Strict links are still blocked; no RISC-V or APE execution |

Memory line accounting uses an exact fixed-capacity set and aborts on overflow;
it never silently samples or discards entries. Raw addresses are not published.
Calibration tests exercise cross-line access, reuse, reset, actual atomic values
and orders. Coverage parsing fails on missing/malformed branch records.
Instrumentation references: [Clang SanitizerCoverage](https://clang.llvm.org/docs/SanitizerCoverage.html)
and [source-based coverage](https://clang.llvm.org/docs/SourceBasedCodeCoverage.html).

## Real edit → build → test dependency chain

The controller creates four **reviewed deterministic** edits to the original
adapter, runs real Git diff/check/apply, and verifies exact patch reconstruction.
It builds the unchanged Tree-sitter runtime/grammar once, then compiles and links
each compilable edited adapter with the real native compiler. Two chunk-size
edits must pass all 30 fixture/path checks each. A wrong-depth edit must compile
but fail the independent output oracle. A deliberate syntax error must fail at
compilation. Candidate success cannot overwrite or regenerate the oracle.

The resulting 110 serial events cover real compilation, tools, tests and
controller work. Every event has its predecessor, monotonic start/end, controller
CPU and completed-child CPU. All uninstrumented gaps are attributed explicitly
to orchestration. The critical path is the **serial elapsed span**, not summed
worker CPU; child CPU can exceed wall time and is never added to that span.
The initial full build's five subprocesses and subsequent 109 subprocesses are
accounted separately. The pipeline is intentionally serial; it does not measure
CP parallel scheduling, fork/join contention or a full test project.

Six phase classes are always present: inference, tool, compilation, tests,
orchestration, network wait. Inference/network have no events and are listed as
**unexercised**; their zero contribution to this controlled run is not a claim
about real agents. Compiler/test waits belong to the called phase, not a fictitious
network or independent orchestration delay. File/process service descriptions
cover observed operations, not a fabricated syscall or byte-traffic count.

Git discovery is confined to the experiment's generated directory. Exact patch
byte checks guard against Git silently skipping paths within an unrelated parent
repository. This runner is not a sandbox; never supply unreviewed candidate code.

## Evidence and architectural use

[S01-DEMAND-PROFILE.json](../evidence/S01-DEMAND-PROFILE.json) retains per-case
metrics, command/event identities, outcomes, pins and limitations. Full ignored
reports include build commands, profiles and checked output trees. The public
summary records its full report hash and replaces local workspace paths in
commands. Harness/source/fixture checks fail if identities drift.

These measurements show that input-byte scans alone omit much of a retained
parser's tree/heap/control work. Preserve an APE scalar runtime and propose PPE
for independently validated batched kernels; CP should eventually remove host
dependency management, not substitute a host callback for execution. Allocation
and capacity work precedes performance-core sizing. Full hardware PMU, target
stack/resource bounds, concurrent ownership, model-driven traces and equal-quality
HATS comparisons remain explicit [stage follow-ups](../s01_acceptance.json).
