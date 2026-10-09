# Tree-sitter on the APE execution path

This S02 port strict-links the pinned upstream Tree-sitter C runtime and JSON
grammar into a real RV64I LP64 executable. It supplies original compiler helpers,
startup, a bounded Newlib service layer, a checked ELF loader, a Spike platform
and an APE SpinalSim memory adapter. **The parser itself runs as target
instructions; no host parser result is injected into the target.**

This is a separate executable path from the frozen S01 static link audit. S01's
unresolved-symbol findings remain historical evidence; they are not relabeled
as target execution. Upstream sources remain unchanged in ignored caches.

## Reproduce

Use Python 3.12+ and the toolchain described in
[the hardware development guide](../../../../hardware/spinal/DEVELOPMENT.md).
The tested host uses Homebrew Python 3.14, LLVM/LLD 23, the pinned Newlib build,
SpinalHDL 1.12.3, Verilator 5.052 and Homebrew OpenSSL 3 (EVP SHA-256). The native
adapters currently use `/opt/homebrew/opt/openssl@3` explicitly. Bootstrap pinned dependencies following the
existing [target audit guide](../README.md) and
[Spike guide](../../../../hardware/spinal/spec/APE-SPIKE-VALIDATION.md).

From the repository root:

```sh
python3 workloads/target/treesitter/newlib.py check
python3 hardware/spinal/tools/bootstrap_spike.py --check
python3 -m unittest discover -s workloads/target/treesitter/execute -p 'test_*.py' -v
python3 workloads/target/treesitter/execute/run.py
python3 workloads/target/treesitter/execute/verify_rtl.py
```

`run.py` covers all ten frozen fixtures in cold-old, cold-new and incremental
modes (30 runs), 177 compiler-helper vectors with six results each, 160 runtime
self-checks, and ten explicit argument/resource failures. Each valid JSON result
is checked against an independent semantic tree oracle, including node type,
byte span, depth and preorder. Invalid JSON must report an error; a particular
upstream error-recovery tree is not part of the semantic output contract.

`verify_rtl.py` defaults to empty/scalars/Unicode, all three modes and two launches
per case: **18 actual APE RTL invocations**, ROB=8, bimodal prediction. It creates
a fresh ELF and Spike trace, then compares every RTL retirement and memory event,
the complete output region and the independent semantic result. It tests delayed
responses, request stalls, stable pending requests/completion, stack bounds,
drain and relaunch. The memory image is reloaded between invocations; core reset
is not. BSS is poisoned before startup, so successful execution also exercises
the target's explicit BSS clearing.

`--case`, `--kind`, `--rob` and `--prediction` select subsets/configurations.
Text traces deliberately reject fixtures larger than 4096 combined input bytes
to avoid accidental multi-gigabyte logs. The separate [bulk RTL gate](../bulk/README.md)
covers all 30 parser cases plus helper, runtime and negative executables on actual
Verilator RTL, comparing a streaming hash of **every** retirement state and memory
event. It does not sample traces. The S02 collector also checks that the 18 small
SpinalSim traces produce exactly those bulk digests and complete output images.

## Memory and binary ABI

All ranges below are half-open. Addresses are byte-addressed and little-endian.

| Range | Purpose |
| --- | --- |
| `0x000000..0x040000` | 256 KiB instruction-store capacity; executable segment bounds checked |
| `0x100000..0x180000` | Static data/BSS capacity, ELF-derived read-only prefix / writable tail |
| `0x180000..0x180040` | Eight 64-bit argument fields, read-only |
| `0x181000..0x1c0000` | Read-only old-input reservation |
| `0x1c1000..0x200000` | Read-only new-input reservation |
| `0x210000..0x300000` | Result region, 960 KiB |
| `0x400000..0xe00000` | Bounded heap capacity, 10 MiB |
| `0xf00000..0x1000000` | Stack reservation, 1 MiB |

The test service allocates a 16 MiB backing image at `0x100000`; holes are not
accessible. Memory guards protect entire reservations, not individual heap
allocations or the logical input length; the target input callback enforces that
length. This is not a memory-safety proof. These are simulation capacities,
**not implemented caches, SRAMs,
HBM/LPDDR controllers or workload-optimal physical sizes**. `ApeCore` itself is
unchanged: its existing program-store parameter is enlarged to 65,536 words.
The enlarged asynchronous instruction memory is not a timing/PPA result.

`platform.h` fixes the eight argument words: magic, mode (cold=0/incremental=1),
old/new byte lengths, heap limit, output limit and two reserved zero words.
Result words are magic, status, parse-error flag, node count, live requested bytes,
peak requested bytes, allocation count and heap bytes granted. Each node is four
32-bit values: semantic type, byte start, byte end, depth. Status values are
success=0, invalid argument=1, no memory=2, output full=3, bad tree=4 and runtime
failure=5. Actual target return uses a registered EBREAK exit sentinel and A0;
arbitrary traps are not application success.

The loader requires static ELF64 little-endian RISC-V, entry zero, nonoverlapping
bounded segments, no dynamic/TLS/relocation content, no undefined global symbols,
and the expected startup/runtime symbols. Final disassembly must remain RV64I
plus the exit EBREAK. The build never suppresses unresolved symbols.

## What the runtime does and does not provide

- Original shift/add/bitwise multiply, unsigned division/remainder, signed
  remainder and 128-bit multiply helpers execute on the target. Expected vector
  results come from Python arbitrary-precision arithmetic outside the executable.
- Newlib malloc/calloc/realloc/free operate on a bounded target `_sbrk` heap.
  Tree-sitter allocation wrappers measure requested live/peak bytes and require
  zero live bytes after successful parser/tree cleanup. Observed peaks and stack
  high-water marks are input-specific, not worst-case proofs.
- Atomic helper calls retain their compiler ABI but rely on **one isolated hart,
  no interrupts, no DMA/other writer, and no shared parser tree**. Volatile accesses
  plus fences are valid only under this exclusion. They are not general shared
  atomics, an implementation of the RISC-V A extension, or a concurrent runtime.
- Diagnostic writes use a bounded target-resident buffer with real short-write
  and failure behavior. No filesystem, host syscall emulation, clock or process
  launch is supplied. Unsupported optional services return explicit errors.

Residual host work: compile/link, validate/load code and frozen inputs, drive
launch and simulated memory service, collect traces, and check outputs. The host
does not perform target parsing, target allocation or incremental edit logic.
There is no Linux, CP queue, HSA task launch, protected address translation,
coherent shared-memory system or autonomous APE/PPE workflow in this port.

## Provenance and evidence

Public source pins are the existing native `sources.lock.json` and target Newlib
lock/build manifest. Tested versions are Tree-sitter v0.25.10, JSON grammar
v0.24.8, Newlib 4.5.0.20241231 and Spike commit
`fdc1ffa05152707a00ca22a9cf50c59a1b487875`. Original HATS adapters are checked in;
upstream source, libraries and generated executables stay in ignored caches or
results directories. Preserve upstream licenses when redistributing dependencies.

Each run creates `workloads/results/s02-treesitter-<timestamp>/validation.json`;
RTL runs add `rtl-validation.json`. Reports bind source, fixture, ELF, image,
dependency-build, output and trace identities. Source/artifact changes during a
run fail validation. Trace agreement is architectural correctness evidence for
the selected program/configuration, **not measured CPU offload speedup**.
