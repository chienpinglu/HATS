# Native Tree-sitter baseline (S01)

This executes the pinned **upstream C runtime and JSON grammar**, not a surrogate
parser, APE, PPE, a complete coding agent or an RSI experiment. It is the selected
first real upstream tool target for S02. The current run is host-native only.
Original adapter/instrumentation lives here; upstream source remains unmodified
in the ignored cache. Port patches are currently empty and must be listed
separately when S02 adds target support.

## Reproduce

Requires Python 3, Git and LLVM Clang/llvm-size/llvm-nm (tested with Homebrew
LLVM 23.1.2 on Darwin arm64). Homebrew LLVM is preferred when present; otherwise
the tools must be on PATH. The script does not install dependencies.

```sh
python3 workloads/native/treesitter/run.py fetch
python3 workloads/native/treesitter/run.py check
python3 -m unittest discover -s workloads/native/treesitter -p 'test_*.py' -v
python3 workloads/native/treesitter/run.py run --repeat 3 --sanitize
```

Only `fetch` needs network access. Existing changed/mismatched checkouts are
rejected, never overwritten. Fetch checks out exact commits, not moving tags;
release labels are descriptive, not claims to be the latest version. No upstream
build scripts, packages, grammar generator or WASM engine are executed.

`sources.lock.json` records repositories, immutable revisions, top-level license
hashes and bundled notices. Tree-sitter uses MIT plus bundled Unicode/ICU notices;
the JSON grammar uses MIT. Retain all applicable notices when distributing
source or binaries; this runner does not publish third-party binaries. Public
API references: [C integration](https://tree-sitter.github.io/tree-sitter/using-parsers/1-getting-started.html)
and [incremental parsing](https://tree-sitter.github.io/tree-sitter/using-parsers/3-advanced-parsing.html).

## Frozen cases and independent correctness

Ten fixtures cover empty/scalar JSON, UTF-8 and escapes, 48-level nesting,
invalid-to-valid edits, 16/256/2048-record arrays and a repository lockfile edit.
They are deterministic synthetic inputs, **not real agent trajectories**.
`cases.lock.json` freezes old/new bytes and expected semantic-output hashes.
The `fixtures` command prints a candidate manifest; it does not silently update
the checked-in lock. A change requires explicit fixture review.

For every case, run cold-old, cold-new and old→new incremental parsing. Valid
outputs must exactly match an independent Python JSON structure/UTF-8 byte-span
oracle, including type, start, end, depth and order. Document/pair/string-content
wrappers are excluded from this semantic comparison. Invalid inputs must report
an error; the exact error-recovery tree is deliberately not frozen. All library
allocations must be released. Test mutations show corrupted spans, types, depth,
errors, missing nodes and leaks are rejected. Incremental and cold-new outputs
are each checked against the same independent expected result.

With `--repeat 3 --sanitize`, the matrix is 90 native + 30 instrumented + 30
ASan/UBSan executions = **150**. Sanitizers apply to both upstream and adapter
code. The native timing mode still includes allocation accounting and the input
callback counters; it is not an uninstrumented performance baseline.

## What each metric means

| Recorded quantity | Meaning / limitation |
| --- | --- |
| Executable bytes and sections | Host build, including instrumentation storage; not RISC-V footprint or cache demand |
| Setup/full/incremental/cleanup wall and CPU time | These phases only; input loading, edit discovery, tree serialization and process launch excluded |
| Allocation/reallocation/free calls | Tree-sitter's registered allocator only; calloc and realloc(NULL) count as allocations |
| Allocated bytes / peak live | Requested bytes, not allocator headers, resident pages or entire process; realloc counts the full new request |
| Coverage edge visits / distinct sites | Instrumented compiler CFG probes, not instruction/branch counts or branch prediction misses |
| Function entries / call depth | Compiler-instrumented upstream functions, including compiler treatment of inlining; not a target return-stack requirement |
| Sampled stack span | Difference between observed callback stack addresses; neither exact stack use nor an upper bound; excludes libc/adapter paths |
| Input-read calls / chunks / backward reads | 256-byte callback delivery locality only; excludes tree/heap/table accesses and is not cache traffic |
| Undefined symbols | Whole runtime object linkage requirements; optional logging/query paths may be linked but not executed |
| Host build time | Setup cost to build this baseline; not compilation on APE and not an agent edit/build critical path |

The selected execution is single-threaded; no worker contention or OS scheduler
offload is measured. Upstream tree reference counting uses atomic operations
(`lib/src/atomic.h`); a single-thread fixture does not authorize dropping their
semantics in a shared runtime. File input/output and process creation happen in
the host adapter/runner. Parsing uses already loaded input. Source audit and
symbol inventory are not a syscall trace.

Hardware branch misses, cache misses, full stack bounds, concurrency, end-to-end
agent critical paths and a RISC-V linked instruction inventory remain open.
Report these as **unmeasured**, never as zero. Do not use these fixtures to size
the ROB, caches, HBM/LPDDR channels or tensor units.

## Evidence and failure behavior

Unique reports, binaries, build logs, inputs and output trees go under ignored
`workloads/results/treesitter-*`. Reports record source hashes, build commands,
toolchain identity, native binary hash and every output hash. The final gate
rechecks source and output hashes and expected matrix size. An exception yields
a failed report and a nonzero exit; there is no HATS backend or host-fallback
option. Each binary execution has a 30-second timeout and a minimal environment.
This is reviewed native code execution, **not a hostile-code sandbox**.

See [S01 decisions and capability map](../../S01-CAPABILITY-MAP.md) for the chosen
prototype scope, remaining host services and next target-port blockers.
