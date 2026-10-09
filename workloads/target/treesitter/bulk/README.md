# Full Tree-sitter matrix on APE RTL

Run from the repository root after the [executable-port setup](../execute/README.md):

```sh
python3 workloads/target/treesitter/bulk/verify.py
```

This builds a fresh strict RV64I ELF and generates actual `ApeCore` SpinalHDL RTL,
then compiles that RTL with Verilator. `rtl_runner.cc` is a clock/port/memory
adapter around `VApeCore`, **not a software ISA emulator**. It does no target
parsing, allocation, compiler-helper arithmetic or result generation. The
independent reference is the pinned upstream Spike library with the same ELF,
arguments, bounded memory map and input bytes.

Default coverage is ROB 8/bimodal, one launch per fixture: all ten locked inputs
in three modes, ten argument/resource errors, one compiler-helper executable
(177 vectors, 1,062 results) and one runtime executable (160 checks): 42 actual
RTL invocations. `--repeat 2` adds reset-free relaunch, and subset/profile flags
are available for diagnostics. Subsets never qualify as the full S02 gate.
The separate SpinalSim transport runs nine small cases twice and is cross-checked
against this transport by the closure collector.

## Complete-stream comparison

Large inputs retire hundreds of millions of instructions. Every retirement
contributes PC, instruction, next PC and all 32 architectural registers to a
streaming SHA-256; every memory event and the final trap are also included, in
order. This is **not sampling**. RTL register values are reconstructed from its
architectural commit ports; Spike register values are read from its real state.
All words are explicit unsigned 64-bit little-endian values:

| Tag | Following fields |
| --- | --- |
| 1 | PC, instruction, next PC, X0..X31 |
| 2 | address, bytes, write, data, error |
| 3 | PC, cause, trap value |

The two drivers share a small encoding helper, not execution logic. Python's
independent `struct`/`hashlib` encoding of the complete small text trace validates
the representation. S02 also checks all 18 SpinalSim full text traces against
the corresponding bulk state digest. Record totals must match. Mutation tests
exercise changed fields, missing/duplicated/reordered events and state omissions.
A matching cryptographic digest is practical complete-stream evidence, not a
mathematical collision-free proof or full architectural certification.

The entire 960 KiB result image must additionally match Spike. A separate JSON
span/structure oracle checks output semantics; the S02 collector compares full
semantic results with the native build on the same 30 inputs/modes: 28 complete
valid trees and two syntax-error flags with zero live allocations. The frozen
contract does not specify invalid-input recovery trees; the target ABI omits
them, while the native harness can retain them as diagnostics. Host timing and generated
RTL simulation cycles do not establish silicon performance or CPU-offload gain.

## Build and evidence

The tested platform is macOS arm64, Homebrew LLVM/LLD 23.1.2, Python 3.14.3,
OpenSSL 3 (`/opt/homebrew/opt/openssl@3`), Verilator 5.052, Java 25.0.2,
Scala 2.13.14, sbt 1.10.7 and SpinalHDL 1.12.3. OpenSSL supplies EVP SHA-256.
The current native adapters use that Homebrew include/library prefix explicitly;
another host requires a reviewed toolchain-path port and fresh evidence.

Reports and executables stay under ignored `workloads/results/s02-treesitter-*`.
`bulk/validation.json` binds source, generated Verilog, executable, dependency,
input/output and stream identities. Its `target_build` field is build metadata
from the reusable executor, not a standalone completed reference report; only
the top-level gate status reports bulk completion. Source/artifact changes fail
the run. The [S02 gate](../../../s02/run_all.py) integrates this proof with PPE,
native and preserved regression anchors. No CP, cache, MMU, HBM/LPDDR controller,
compiler-on-target, Python-on-target, tensor engine or PPA result is implied.
