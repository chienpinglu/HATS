# APE independent Spike validation

APE now has an independent instruction-semantics check against pinned upstream
Spike, in addition to its project-authored interpreter and microarchitecture
assertions. The 2026-10-07 run fully matched **576 RTL invocations** and verified
**24 explicit profile differences**, with no unexpected divergence. This is a
bounded differential regression, not full RISC-V certification.

## Reference model and provenance

The reference is [riscv-isa-sim at revision
fdc1ffa05152707a00ca22a9cf50c59a1b487875](https://github.com/riscv-software-src/riscv-isa-sim/tree/fdc1ffa05152707a00ca22a9cf50c59a1b487875).
`tools/spike.lock.json` pins its revision and BSD-3-Clause license hash.
`bootstrap_spike.py` downloads the source into ignored `.tools/spike-src`, checks
that it is unmodified, and builds static libraries plus an original environment
adapter. Upstream decode, instruction execution and exception semantics are
unchanged. No upstream source or binary is vendored into HATS.

The adapter uses Spike's processor API to step instructions and obtain register
writes and trap state. It supplies the test platform: separate 4-KiB instruction
storage, a 64-KiB data region at `0x10000`, initial data, write permission and
non-effecting bus errors. It contains no replacement instruction interpreter.
The configured ISA is RV64I in machine mode, with PMP disabled; this Spike revision
implicitly enables Zicsr and Zifencei even for that ISA string. APE does not
implement either extension or machine-mode CSRs.

## What is compared

Both engines execute the same compiled instruction images and scenario inputs.
The RTL simulation emits a separate `.arch.jsonl` stream from DUT signals and
the supplied memory service. It does not export expected register values from
`ApeReference`. The existing human-readable `.trace` files are not inputs to
the independent comparison.

The comparator requires exact ordered events:

- Successful retirement: PC, instruction bits, register-write enable,
  destination/value and next PC. Non-writing destinations and values normalize
  to zero; non-control next PC is sequential PC plus four.
- Accepted memory transaction: address, width, direction, byte payload and
  service-error flag. Denied bounds/permission accesses must issue no transaction.
- Terminal trap: fault PC, cause and committed a0. APE's halt interface is
  compared with Spike's trap state; this does not test APE trap-handler entry.

Matching stores establish matching published byte writes from identical initial
memory. Loads additionally check the supplied data and the retired extended
value. Memory events occur before the corresponding retirement. This comparison
relies on APE's current head-only memory ordering; a future speculative LSU will
need a new observation contract, not an indiscriminate event filter.

## Coverage and explicit differences

The existing [verification matrix](APE-VERIFICATION.md) has 50 scenarios, each
run twice on six ROB/prediction configurations. Spike runs each distinct scenario
once; its result is compared with all twelve corresponding RTL invocations.
The 600 runs therefore do not represent 600 independent programs.

| Result | Scenarios | RTL invocations | Meaning |
| --- | ---: | ---: | --- |
| Full event match | 48 | 576 | Includes 83,052 retirements and 18,924 memory events across repeated runs |
| FENCE.I profile difference | 1 | 12 | APE traps as unsupported; Spike executes FENCE.I |
| Misaligned launch difference | 1 | 12 | APE validates launch PC; Spike is directly initialized at that PC |

The two differences are exact checked outcomes, not skipped tests:

- `unsupported_fence_i`: both retire the initial instruction setting a0 to 42.
  APE then reports illegal instruction at PC 4. Spike retires instruction
  `0x0000100f` at PC 4 and reports EBREAK at PC 8, retaining a0 = 42.
- `entry_alignment`: APE reports cause 0 at launch PC 2, with a0 = 0. Directly
  starting this Spike instance at PC 2 yields cause 2 and reported mepc = 0,
  with a0 = 0. This is not a test of an architecturally executed jump to PC 2;
  jump alignment has separate matched coverage.

Any different prefix, extra event or changed outcome fails. The report uses
`passed_with_profile_differences`, never labels all 600 runs as fully matched,
and records invocation-level classifications.

Bounds, readonly and injected service-fault cases use policy supplied by the
adapter. They test instruction behavior and fault reporting within that platform;
they do not independently validate HATS isolation policy, PMP or virtual memory.

## Reproduce

Install the [APE toolchain prerequisites](../DEVELOPMENT.md), plus Git, host
Clang/Clang++, make and the device-tree compiler `dtc`. On the tested Mac, `dtc`
1.8.1 was installed with Homebrew and Apple Clang 17 built Spike. The bootstrap
disables optional Boost features. Other host platforms have not been validated.

From `hardware/spinal`:

```sh
python3 tools/bootstrap_spike.py
python3 tools/bootstrap_spike.py --check
python3 tools/verify_ape_spike.py
python3 tools/verify.py
```

The first command needs network access when the source is absent. It refuses to
overwrite a wrong or dirty checkout. `--check` verifies existing identities
offline. The differential command always reruns the current full APE matrix;
it does not silently reuse historical RTL traces. The final command separately
checks the legacy TaskTile.

## Evidence and failure checks

`build/ape/spike/validation.json` records source hashes before and after the run,
the reference build identity, all 600 results and hashes of the program images,
RTL traces, metadata and Spike traces/logs. The reference build stamp is
`.tools/spike-build/ape-build.json`; it hashes the adapter, lock, static libraries,
executable and generated build configuration. These are local artifact-identity
checks, not a claim of bit-identical builds across machines.

Seven comparator unit tests cover schema errors, changed instruction/register/
control/memory/trap fields, missing or reordered events, and exact profile-gap
handling. The aggregate additionally corrupts six fields in an actual current-run
RTL trace and requires all six comparisons to fail. These prove checker
sensitivity, not RTL fault-injection coverage. Missing tools, changed inputs,
invalid provenance, incomplete matrices and unexpected differences fail with a
nonzero exit; an interrupted `running` report is not success.

## Remaining gates

Broader architectural tests, constrained instruction generation, formal recovery
invariants and additional trap/reset tests remain necessary. Full RV64I,
privileged execution, interrupts, caches, coherence, OS boot and real agent/tool
execution remain outside this result. Spike is a functional oracle here, not a
performance baseline. No speedup or physical implementation claim follows from
these checks.
