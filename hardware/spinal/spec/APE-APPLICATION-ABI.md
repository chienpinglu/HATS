# APE bounded application ABI and source diff

The application path loads a linked RV64I LP64 executable and runs an original
line-diff tool on APE RTL. Tokenization, line comparison, longest-common-subsequence
calculation and edit-script construction execute as target instructions. This is
a bounded tool implementation, not a port of Git, GNU diff, LLVM or Python.

## Executable and runtime contract

`tools/ape_app_image.py` accepts little-endian ELF64 static RISC-V executables
with entry zero, soft-float flags and no compressed instructions flag. It checks
file/table bounds, load-segment placement, non-overlap, alignment, permissions,
runtime symbols and unresolved relocation sections. Dynamic linking, TLS and
unrecognized program-header types are rejected. This is a deliberately restricted
loader, not an arbitrary ELF loader or security boundary for hostile executables.

`examples/ape_app/link.ld` separates executable code, read-only data, initialized
writable data and a zero-fill BSS tail. The application is linked without linker
relaxation, small-data addressing, libc, stack protectors or runtime libraries.
Multiply/divide and new CPU instructions are not needed by this workload.

The startup code sets sp to `0x20000`, clears BSS, checks a nine-argument C call,
and calls `ape_main` with the launch argument in a0. The argument points to the
input descriptor at `0x16000`. It checks preservation of s0 through s11 and
restoration of sp before reaching the designated `ape_exit` EBREAK. EBREAK still
means breakpoint cause 3; only the test harness interprets this particular PC
and a0 status as application completion.

The tested ABI slice uses 64-bit pointers/longs, eight integer argument registers,
a ninth stack argument and a 16-byte-aligned downward-growing stack, following
the [RISC-V integer calling convention](https://docs.riscv.org/reference/abi/v1.0/riscv-cc-procedure-calling-convention.html).
It does not certify all LP64 aggregate, varargs or language-runtime behavior.

## Memory layout

All intervals below are half-open. Instruction storage is separate from the
external data service; this is not yet a unified cached address space.

| Region | Address interval | Contract |
| --- | --- | --- |
| Instruction image | `0x00000–0x01000` | Loaded while idle; fixed 4 KiB capacity |
| Static application data | `0x10000–0x14000` | Linker-placed rodata, data and BSS |
| Reserved | `0x14000–0x16000` | No application writes |
| Input descriptor and two buffers | `0x16000–0x16410` | Read-only by software contract |
| Remaining input/reserved space | `0x16410–0x18000` | No application writes |
| Output buffer | `0x18000–0x19000` | Status and edit records |
| Stack guard/reserved | `0x19000–0x1c000` | No application writes |
| Stack | `0x1c000–0x20000` | 16 KiB reserved, 16-byte-aligned sp |

The RTL still has invocation-wide bounds and write permission, not page-level
protection. The application harness asserts region ownership and stack alignment;
these assertions are not an MPU/MMU implementation. It models one outstanding
transaction with variable latency and backpressure.

## Tool input and output

The input descriptor is two little-endian uint64 lengths followed by two
512-byte buffers. Each buffer is split at LF bytes, retaining line terminators.
An absent final LF, CRLF, NUL and non-ASCII bytes remain byte-exact. Empty input
has zero lines. Inputs are limited to 512 bytes and 32 lines on each side.

The output starts with five little-endian uint32 fields: status, record count,
edit cost, old line count and new line count. Each following 12-byte record is
`kind, old_line, new_line`, with zero-based cursor positions before the operation.
Kinds are keep = 0, delete = 1 and insert = 2. Inserts refer to the new input,
which must remain available; this is an edit script, not a self-contained patch
file or a Git-compatible unified diff. At most 64 records are emitted.

Status 0 is success; 1 rejects excessive byte lengths; 2 rejects excessive line
counts. Rejected inputs publish no records and zero counts/cost. Runtime data
initialization failures return 224; ABI sentinel failures halt at a different PC
with 225 and fail validation. The application chooses deletion on LCS ties.

## Verification path

From `hardware/spinal`:

```sh
python3 tools/bootstrap_spike.py
python3 tools/verify_ape_app.py
python3 tools/verify_ape_spike.py
python3 tools/verify.py
```

The first verification command compiles the executable and runs 12 input cases
twice on each of the six existing ROB/prediction configurations: 144 application
invocations. Cases cover empty input, insertion, deletion, replacement, duplicate
lines, newline differences, binary bytes, a repository-source edit, both maximum
sizes and both over-limit rejections. The source-edit case loads this repository's
`examples/ape/kernel.c` and a one-expression variant; it is not a large-repository
benchmark or an execution of the compiler itself.

Every invocation must match pinned upstream Spike's ordered retirement, next-PC,
register, memory and terminal-trap events with no profile exceptions. Full final
data memory must also match Spike's published writes. An independent host checker
applies the device edit script, reconstructs the new input, and verifies minimum
insertion/deletion cost using a prefix edit-distance recurrence. It never supplies
an answer to the executing target.

The harness poisons BSS after normal ELF zero-fill so that target startup must
clear it. It loads each input memory image again for the second launch without
resetting RTL, holds/consumes halt, and checks nested calls, saved registers,
stack use, read-only/reserved-region writes and stable memory backpressure.
This demonstrates repeatable relaunch, not persistent in-process task service.
Ten host-side tests check malformed ELF and corrupt/nonminimal edit-script
rejection; the [existing differential gate](APE-SPIKE-VALIDATION.md) retains its
separate trace-corruption checks and OoO mechanism assertions.

Evidence is in `build/ape_app/validation.json`, with per-configuration traces,
final memory images, generated-RTL hashes and timing diagnostics. The 2026-10-07
run passed all 144 invocations, matching 1,126,512 retirements and 266,832 memory
events across repeated runs. The linked code occupied 1,404 bytes; maximum observed
stack use was 144 bytes, not a general stack bound for other programs.
A build, isolated configuration or
Spike-only execution is not the full application gate. Interrupted `running`
status and any failed comparison are not success.

## Remaining host work and next scope

The host compiles and links the program, loads code/data, launches simulations,
provides the modeled memory service and validates results. There is no host
tokenization/diff callback in the target execution path. All RTL simulation still
runs on the host machine; this is not physical accelerator offload or measured
energy/performance improvement.

Next select a larger real tool port and measure its executable, heap, stack and
instruction requirements. Add the required loader/runtime/ISA support and preserve
this small diff as a regression anchor. An OS, filesystem, allocator, compiler,
interpreter, nonblocking cache hierarchy and device-resident task runtime remain
separate milestones. A possible [shared ISA substrate](APE-SHARED-SUBSTRATE.md)
does not change this application's RISC-V execution contract.
