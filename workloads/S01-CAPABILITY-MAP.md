# S01 workload-backed architecture decisions

Revision **S01-0.3**, updated 2026-10-09. Tracks [issue #2](https://github.com/chienpinglu/HATS/issues/2).
Status: S01 requirements/native deliverables complete, subject to the recorded
[closure gate](S01-COMPLETION.md). Native demand profiles and a real local
edit/build/test chain supplement the original baseline. Runnable target linkage
is still blocked by specific runtime providers and remains an **S02** gate.
Nothing here establishes HATS speedup or complete agent execution.

## Selected tool and scope

Select **Tree-sitter C runtime + JSON grammar** for the first upstream APE port.
The native baseline executes unmodified library code with original adapters and
deterministic input edits. This choice exposes pointer traversal, retained trees,
dynamic allocation, branches, incremental reuse and atomic reference counts,
without requiring a full CPython, Git process environment or native compiler.

| Candidate | Decision | Reason / limitation |
| --- | --- | --- |
| Tree-sitter + one grammar | First upstream target | Real native runtime, independent structural oracle, bounded integration surface; JSON is narrower than parsing a coding project's languages |
| Existing bounded C diff | Keep regression | Already exercises APE applications, but is an original small program, not an upstream Git port |
| Git diff / patch | Keep host corpus and later port candidate | Valuable realistic source processing; filesystem/process/runtime requirements exceed the first port |
| CPython execution/compiler | Later APE milestone | Python bytecode compilation is measured now; interpreter execution, extensions and native compilation are different workloads |
| LLVM/Clang compile/link | Host workflow now profiled; target compiler deferred | Real compilation/link steps in the local tool chain; large target runtime/OS surface; Clang does not run on APE |

The first PPE work proceeds **in parallel**, with independent batched scans and
integer transforms. Do not force the entire incremental parser onto SIMT simply
because PPE is programmable. APE, PPE and CP remain distinct roles inside one
processor; moving scalar cores on-package alone does not prove the thesis.

## Versioned coverage of every current case

[capabilities.json](capabilities.json) is the machine-readable S01-0.3 map.
Tests require an exact match to all 21 suite IDs and all seven pinned projects;
adding/removing a case or changing its source lock requires review of this map.
Every row below currently executes on the **host**, not APE/PPE/CP. Proposed
engine roles are hypotheses. Shared profile definitions contain APE, PPE, CP,
memory and remaining host-service responsibilities for each individual case.

| Exact case ID | Capability profile | Current evidence |
| --- | --- | --- |
| gepa.pareto | pareto | Upstream candidate selection component |
| gepa.trace-json | serialization | Upstream trace conversion component |
| ace.counter-update | playbook | Extracted unchanged function |
| ace.curator-add | playbook | Extracted unchanged function |
| ace.json-extract | extraction | Extracted unchanged function |
| dgm.edit | editing | Upstream file-edit component, including rejection |
| stop.maxcut | search | Seed algorithm on original fixtures |
| stop.sat | search | Seed algorithm on original fixtures |
| gepa.diff-patch | diff | Git algorithms on source corpus |
| ace.diff-patch | diff | Git algorithms on source corpus |
| aflow.diff-patch | diff | Git algorithms on source corpus |
| dgm.diff-patch | diff | Git algorithms on source corpus |
| stop.diff-patch | diff | Git algorithms on source corpus |
| ahe.diff-patch | diff | Git algorithms on source corpus |
| gascity.diff-patch | diff | Git algorithms on Go source corpus, not Go orchestration |
| gepa.python-compile | bytecode | CPython AST/bytecode compilation |
| ace.python-compile | bytecode | CPython AST/bytecode compilation |
| aflow.python-compile | bytecode | CPython AST/bytecode compilation |
| dgm.python-compile | bytecode | CPython AST/bytecode compilation |
| stop.python-compile | bytecode | CPython AST/bytecode compilation |
| ahe.python-compile | bytecode | CPython AST/bytecode compilation |

| Profile | APE / possible PPE split | CP and memory needs | Host services not yet removed |
| --- | --- | --- | --- |
| pareto | Irregular selection / batched comparisons and reductions | Evaluation fan-out/join; sets, heaps and metric tables | Python runtime; full model/evaluation services |
| serialization | Object traversal / optional byte scans | Buffer publication; strings and heap | Python/json; persistence |
| playbook | Dictionaries and counters / no established PPE benefit | Version ordering; private mutable heap | Python/exceptions; full ACE model/data |
| extraction | Regex/JSON control / batches of independent texts | Batch completions; text, parser stack/heap | Python/re/json; I/O and invalid-input paths |
| editing | Edit validation / optional copy/compare | Edit→test dependencies; bounded old/new buffers | Filesystem authorization and publication; Python |
| search | Branching search / restarts and score reductions | Bounded trials/cancellation; graph/clause state | Python/RNG; full STOP model and isolated evaluator |
| diff | Matching/control / possible hashing or comparison | Diff→apply→test; variable-sized indexes/buffers | Git, processes, temporary files and patch publication |
| bytecode | AST and compiler control / file-level parallelism | Compilation graph; stacks, object/AST heap | CPython compiler, source files and exceptions |

Full GEPA/ACE/AFlow/DGM/STOP/AHE/Gas City requirements remain in
[COVERAGE.md](COVERAGE.md). None of those experiments is reproduced by these
components. The ten native Tree-sitter fixtures are a **separate** suite, not
ten newly accelerated agent workloads.

## Measured evidence and limits

[S01-HOST-BASELINE.json](evidence/S01-HOST-BASELINE.json) preserves a public-safe
summary, source/fixture/output identities, and hashes of the full ignored local
reports. Native source pins and exact reproduction commands are in the
[Tree-sitter README](native/treesitter/README.md). The original complete reports
remain under ignored `results/`; the checked-in summary excludes home paths and
does not vendor upstream source or binaries.

- All 21 existing cases passed three repeats: **63 host component/corpus runs**.
- Tree-sitter passed **150** checked executions: ten fixtures × three modes of
  use (old, new, incremental), with three native repetitions, one instrumented
  run and one ASan/UBSan run. Invalid JSON has a separate error-result contract.
- Native executable: **245,752 bytes**, with **140,072 bytes of host text** in
  this LLVM 23.1.2 Darwin arm64 build. This includes the adapter and unpruned
  runtime, is not a RISC-V image, and cannot set a target I-cache size.
- Independent native-oracle tests, complete map tests and descriptor layout/
  rejection tests are available; none substitutes for RTL tests.

Illustrative results from the frozen run (three-sample medians, not confidence
intervals or speedup claims):

| Fixture | Cold-new parse | Incremental edit+parse | Interpretation |
| --- | --- | --- | --- |
| records_2048, 125,945 → 125,952 bytes | 8.103 ms | 0.349 ms | Local string edit reuses the tree; original parse/setup/cleanup are additional costs |
| repository_lock, 7,920 → 5,672 bytes | 0.158 ms | 0.219 ms | Reserialization changes much of the file; incremental work can cost more than a fresh parse |

On records_2048, full-old parsing requested 53,267 new allocations plus eight
reallocations and reached **5,224,832 live requested bytes**. Incremental parsing
requested another 2,065 allocations plus three reallocations, peaking at
**5,423,024 bytes** with both trees retained. Cleanup returned tracked live bytes
to zero. These numbers exclude libc metadata, input buffers, instrumentation
storage and process memory. The current APE application harness's 64 KiB data
image is insufficient for this **unmodified algorithm/allocator behavior**.

The same incremental operation in the original baseline asked the input callback for just 256 bytes,
but recorded 918,129 compiler edge-probe visits across 465 sites. This is evidence
of work beyond input-byte scanning, **not** a measured branch count, cache miss
count or memory-bandwidth requirement. The instrumented sampled stack span was
1,216 bytes; it is not a complete or worst-case stack bound. Separate instrumentation
dramatically perturbs time; do not compare its latency with the native mode.

The separate [demand profile](profile/README.md) adds 90 independently checked
executions. Compiler load/store probes observe tree/heap/table activity beyond
the callback, actual atomic wrappers retain upstream memory orders, source
coverage records branch outcomes, and a guarded-stack experiment measures the
written stack extent. Those are native requirements evidence, not hardware cache
misses, contention, worst-case target bounds or target performance. The checked-in
[per-case evidence](evidence/S01-DEMAND-PROFILE.json) is authoritative for counts.

### Phase accounting

| Phase | What is measured now | What is not measured / must not be inferred |
| --- | --- | --- |
| Inference | None | No model tokens, tensor throughput or GPU utilization |
| Local tool execution | Component wall/CPU/RSS; native parser phases, branch/memory/atomic probes; actual Git diff/apply | No APE/PPE speed, hardware branch/cache PMU data or energy |
| Compilation | Six CPython AST/bytecode cases; real C compile/link events in the local tool chain | No native compiler running on HATS; no model-driven agent trace |
| Tests | Independent output checks, valid candidate checks, semantic and compile rejection | Not a project's full test suite or held-out agent-quality evaluation |
| Orchestration | Serial dependency trace; controller CPU, completed-child CPU and explicitly attributed wall-clock gaps | No concurrent fork/join profile or measured CP offload |
| Network wait | None during case execution; fetching excluded | Not zero wait in real agents; external model/network APIs remain host services |

There is no valid end-to-end offloadable percentage or CPU:GPU ratio from this
dataset. Summing overlapping worker/child times is not a critical-path analysis.
The new local workflow supplies a serial critical path with all six categories,
without treating unexercised inference/network phases as measured real-agent
costs. S09 owns the eventual complete model-driven loop and outcome comparison.

## Ranked APE gaps before choosing performance dimensions

1. **Code/data capacity and executable loading.** Audit the actual RV64 linked
   runtime, stack, static state and heap, then extend the existing ELF/image
   service. Native text size is only a warning, not a target allocation value.
2. **Runtime and atomic semantics.** Supply allocator, memory/string helpers,
   fatal/error paths and an explicit policy for optional logging/time/file APIs.
   The upstream atomic header uses atomic loads and seq-cst increment/decrement.
   Current APE lacks A-extension instructions; choose and verify a correct
   implementation or an explicitly single-threaded runtime shim. Do not silently
   erase synchronization that a later shared tree requires.
3. **Target ISA/link audit.** Build with the supported RV64 integer profile,
   enumerate disassembly and unresolved helpers, and separate optional API
   linkage from executed paths. Decide M/A or software helpers from the resulting
   requirements, not from host arm64 instructions. The first three-profile
   [static audit](target/treesitter/README.md) is complete; strict executable
   linkage remains blocked, with exact provider lists preserved.
4. **Precise bounds, errors and allocation exhaustion.** Preserve malformed-input
   behavior and checked output under insufficient heap/stack, no host emulation
   of parser results. Full Linux/syscalls are not needed for the first in-memory
   library port, but explicit host input/result services remain.
5. **Only then performance sizing.** Sweep instruction/data working sets,
   concurrency, branch behavior and dependency stalls before changing issue
   width, ROB/PRF/LSQ sizes, cache banks or near/far placement. S03/S04 implement
   a performance core and hierarchy; the current OoO core is not already that.

The missing target `stdio.h` blocker is now resolved with a pinned, local-only
Newlib RV64I build and real target headers. The unchanged Tree-sitter runtime and
grammar compile for I, IM and IMA. The RV64I diagnostic API closure contains
91,500 bytes of reachable text, but strict linking still requires 18 providers:
four integer compiler helpers, three atomic helpers and eleven platform services.
IMA removes the three atomic helper calls; it does not implement A-extension
instructions in APE. This static reachability result is not a runnable ELF or a
target performance result. No upstream files or existing APE RTL were modified.

## Minimum architecture contracts delivered

- [PPE-0.1](../hardware/spinal/spec/PPE-0.1.md): logical lanes, scalar/vector
  state, masks, structured reconvergence, barriers, loads/stores and partial
  store faults; initial W=8 is a test profile, not a performance commitment.
- [HATS-TASK-0.1](../hardware/spinal/spec/HATS-TASK-ABI-0.1.md): descriptor and
  completion layouts, queue ownership, release/acquire, address/capability
  contexts, engine roles, generations, rejection and drain rules.
- [task_abi.py](../hardware/spinal/tools/task_abi.py): executable layout and
  structural checks, with positive/negative tests. It is not CP hardware.

The initial system uses one uncached domain. Four HBM/LPDDR affinity domains and
APE-local versus remote capacity are preserved in the target contract, not
implemented or sized by these profiles. Each engine adapter and every memory
master must eventually enforce the same protection/context rules.

## Comparison protocol and issue closure ledger

Freeze upstream commit, patch manifest, input/output hashes, compiler/options,
ISA profile and resource limits per experiment. First prove equal outputs and
faults. Compare host-native, independent ISA reference and actual RTL on identical
inputs; record excluded services. No model substitution for hardware or host
fallback is permitted. Separate parse setup, cold parse, incremental operation,
cleanup, transfer, dispatch and dependent work. Use larger/randomized/real traces
and more repetitions before any performance claim. Preserve reference programs
and evaluation authority separately from generated candidate code.

| S01 obligation | Current evidence | Remaining action |
| --- | --- | --- |
| Every selected case mapped | Versioned JSON + exact-coverage tests; all seven projects | S09 extends with reviewed full-flow cases, not source names alone |
| Pinned real-tool native baseline | Two source pins/licenses, ten input/output locks, 150 checked runs | Target port and native/ISA/RTL parity belong to S02 |
| PPE and system interfaces | Two reviewed minimum contracts + 13 codec tests, including completions and resource overflow | S02 encoding/code object; S05 queue/runtime RTL |
| Demand characterization | Heap/allocations, host timing; branch outcomes, memory probes, ordered atomic counts, stack watermark; RV64 I/IM/IMA inventories | S02 target execution/bounds; S03/S04 PMU, memory and concurrency |
| Honest workflow accounting | Six phase classes; real serial edit/build/test critical path; absent phases unexercised | S09 authorized model-driven/concurrent agent traces and full-loop comparison |

The [completion review](S01-COMPLETION.md) and [acceptance ledger](s01_acceptance.json)
cover all original S01 obligations. Close issue #2 only after its complete gate
passes and the public-safe implementing commit/evidence are published. The next
target-port action in **issue #3** is to implement enumerated runtime providers
and a checked startup/loader/output adapter, strict-link, and execute the frozen
fixtures under the independent Spike reference before APE RTL parity. In parallel,
freeze the original PPE instruction/code-object encoding. No model credentials,
private traces or expensive full-agent runs are authorized by this baseline;
those need an explicit dataset/compute/service scope.
