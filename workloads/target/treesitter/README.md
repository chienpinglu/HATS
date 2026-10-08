# Tree-sitter RISC-V compile/link audit

S01 static requirement evidence, 2026-10-09. **No target execution and no APE RTL
execution are performed by this directory.** The complete validated native
parser workload remains in [native/treesitter](../../native/treesitter/README.md).
This audit resolves the earlier missing-target-header blocker and identifies
the next runtime and hardware-capacity requirements without fabricating a
successfully linked application.

## Reproduce

Requirements: Python 3.12+, LLVM Clang/LLD/llvm-ar/llvm-ranlib/llvm-nm/llvm-objdump,
GNU-compatible make and a working host C compiler. Tested with LLVM 23.1.2 on
Darwin arm64. No target GCC, system package installation, container or credentials
are required. From the repository root:

```sh
python3 workloads/native/treesitter/run.py check
python3 workloads/target/treesitter/newlib.py fetch
python3 workloads/target/treesitter/newlib.py build --jobs 4
python3 workloads/target/treesitter/newlib.py check
python3 -m unittest discover -s workloads/target/treesitter -p 'test_*.py' -v
python3 workloads/target/treesitter/audit.py
```

`fetch` downloads the release pinned by [newlib.lock.json](newlib.lock.json) from
the [upstream distribution site](https://sourceware.org/pub/newlib/). It verifies
the archive digest, safe member paths/types, complete extracted file set and
file contents before use. Existing changed files are rejected, not overwritten.
The checksum was pinned after an HTTPS download; it is not a publisher signature.
Newlib is an external dependency, not original HATS code. Its composite per-file
licenses and `COPYING.NEWLIB` are retained in full, including separate licenses
for build infrastructure. No upstream source, archive or binary is vendored by
this work; redistribution requires a review of the actual linked objects.

Builds use a dedicated ignored cache, no `make install`, no libgloss and no
supplied syscall backend. Newlib uses RV64I/LP64, function/data sections, no
multilib, no multithread support and no printf floating-point formatting. This
is a bounded candidate runtime configuration, not full POSIX or concurrent HSA
support. `--rebuild` reruns the same compiler configuration and refreshes evidence;
changed compilation flags require a fresh build directory to avoid mixed objects.
Do not delete source modifications or accept a stale stamp to make checks pass.

## What the audit does

1. Rechecks the native source and fixture locks and the Newlib build identity.
2. Compiles unchanged Tree-sitter runtime `lib/src/lib.c`, generated JSON grammar
   and the original `link_probe.c` separately for **RV64I, RV64IM and RV64IMA**.
3. Uses `HAVE_SYS_ENDIAN_H` and Newlib's real `sys/endian.h`, rather than defining
   a false Linux/Windows host identity or modifying upstream's platform header.
4. Checks ELF64/RISC-V/soft-float/non-compressed object identity, disassembles
   instructions without pseudo aliases, checks them against each declared ISA,
   records undefined symbols and compiler-reported stack frames.
5. Produces a garbage-collected **relocatable** closure rooted at `hats_tool_entry`,
   linked against the same RV64I Newlib archive for all three configurations.
   It retains unresolved symbols and relocations instead of hiding them.
6. Attempts a separate strict executable link with `--no-undefined`, checking
   that every failure is an enumerated missing provider and that no additional
   linker failure is misclassified. Sources/build identities are rechecked.

`link_probe.c` keeps the native baseline's allocator, callback parse, edit,
traversal and cleanup API families reachable. It takes externally prepared
arguments and returns diagnostic node/span counters. It has **no startup,
validated target input loader, output oracle, heap or system service adapter**.
Its counters are not accepted parser correctness evidence. It is deliberately
a static diagnostic entry, not a replacement for executing the frozen native
fixtures with full semantic-tree validation on the target.

## Frozen result

[S01-RISCV-AUDIT.json](../../evidence/S01-RISCV-AUDIT.json) contains a public-safe
summary, source and artifact hashes, and the full ignored report's identity.
The three compile/inventory checks passed; **all three strict executable links
remain blocked**, and no probe executable is counted as a working application.

| Profile | Whole runtime object text | Selected API + Newlib reachable text | Missing link providers |
| --- | ---: | ---: | ---: |
| RV64I | 150,924 B | 91,500 B | 18 |
| RV64IM | 148,564 B | 91,008 B | 18 |
| RV64IMA | 148,220 B | 90,700 B | 15 |

The selected closure is a relocatable section-size sum, **not final executable
size**, instruction-cache working set or a code-capacity commitment. It excludes
missing providers, startup and the final checked adapter. The current APE app
harness has a 4,096-byte code image; this unmodified target runtime clearly
requires a different loading/capacity profile before RTL application testing.

The pure RV64I runtime compiles without M/A/F/D/C/V instructions, but leaves
calls to arithmetic and atomic helpers. RV64IM emits `mul`, `mulhu` and `mulw`
instead of the runtime object's multiply/divide helper dependencies. RV64IMA
additionally emits `amoadd.w.aqrl`, eliminating three atomic helper dependencies.
Those instructions are **not supported by the current APE RTL**. This is an ISA
tradeoff comparison, not a claim that the core can execute all three profiles.

M alone does not remove the closure's arithmetic helper requirements because
Newlib is intentionally kept at RV64I in this comparison. Rebuilding every
library for IM/IMA would be a different experiment. None of these static code
size differences is a throughput/energy benefit measurement.

### Exact remaining provider groups

| Group | Symbols / requirements | Next implementation obligation |
| --- | --- | --- |
| Integer compiler runtime | `__muldi3`, `__multi3`, `__udivdi3`, `__moddi3` | Correct RV64I helpers, independently checked at edge cases; `__multi3` is a 128-bit helper used by Newlib calloc, not proof that APE needs 128-bit registers |
| Atomics (I and IM) | `__atomic_fetch_add_4`, `__atomic_fetch_sub_4`, `__atomic_load_8` | A verified runtime/serialization contract or actual A-extension support; ordinary loads/stores cannot silently stand in for shared-memory atomics |
| Heap growth | `_sbrk` | Bounded backing region, alignment, allocation failure and no corruption on exhaustion |
| I/O/metadata | `_close`, `_fstat`, `_isatty`, `_read`, `_lseek`, `_write` | Explicit service ABI or documented unsupported-operation failure; no fake successful I/O |
| Time/termination/process | `_times`, `_exit`, `_kill`, `_getpid` | Defined clock/exit/error policy for the isolated library profile; not a Linux syscall implementation |

Many I/O/time paths are retained through optional debug, assertion or timeout
branches even though the selected native fixture does not enable them. Link
reachability does not prove they ran. Conversely, removing runtime calls cannot
be justified merely because today's fixtures happen not to take a branch.
Startup, linker layout, code/data bounds, stack placement and the independent
result adapter are additional requirements even after missing symbols are fixed.

## Stack and performance interpretation

The largest whole-runtime frame reported by Clang is `ts_parser_parse`: 624 bytes
for I, 608 for IM and 624 for IMA. The native parse call-stack sample was a
different measurement on a different ISA; do not substitute either for a complete
target stack bound. Recursion, mutually reachable calls, external runtime frames,
allocator behavior and adversarial nesting still need accounting and tests.

Static instruction sites are not dynamic instructions, branch misses, cache
misses or task latency. The large native retained-tree heap remains a separate
data-capacity requirement. No CPU/PPE split, ROB width, cache size, HBM/LPDDR
capacity or speedup is selected from these counts.

## Failure and evidence semantics

`audit_complete` means the static audit ran and all checks of the inventory
passed. Each profile's **strict_link.status** remains authoritative for linking.
The audit returns success when an expected missing-provider set is faithfully
recorded, not when a runnable target exists. Compiler failures, unknown opcode
families, malformed ELF, missing inventories, source changes or unrelated link
failures make the audit fail. There are no dummy providers, ignored undefined
symbols, target emulation or host result substitution.

Eleven unit tests cover object bounds/profile checks, instruction-family
rejection, exact missing-provider extraction, dependency classification, archive
path/link safety and non-overwriting integrity checks. They do not test library
runtime correctness. Logs, objects, stack-usage files and disassembly remain
under ignored `workloads/results/treesitter-rv-audit-*`.

## Next gate

Implement the RV64I runtime adapter and compiler helpers, obtain a strict-linked
ELF with explicit startup and memory layout, and execute the **same ten frozen
fixtures** against the independent semantic-output oracle in the pinned Spike
reference. Only after that gate should the larger-image APE RTL adapter run the
same program. Spike execution would still not prove RTL execution or timing.
Full shared-memory atomic support and a larger OoO performance core remain
separate hardware obligations, not solved by this libc build.
