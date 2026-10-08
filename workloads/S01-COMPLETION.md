# S01 completion and S02 handoff

Date: 2026-10-09. Scope: [issue #2](https://github.com/chienpinglu/HATS/issues/2).
S01 establishes **requirements and native baselines**, not a finished processor.
The executable [acceptance ledger](s01_acceptance.json) maps all six work packages
and four original acceptance criteria to evidence and review decisions. The
[completion gate](s01_gate.py) checks evidence identity, complete matrices,
negative tests, phase accounting and stage ownership. The checked-in
[closure record](evidence/S01-CLOSURE.json) records the final rerun commands and
hashes; a failed/missing record is not completion.

## Deliverables and acceptance

- S01-0.3 maps all 21 cases and seven public projects to proposed APE/PPE/CP,
  memory and remaining OS/host services. It explicitly distinguishes component
  coverage from full agent experiments.
- The selected upstream tool is unmodified pinned Tree-sitter C + JSON grammar,
  with license/notices, ten frozen fixture pairs, independent semantic output
  checks and 150 native/instrumented/ASan/UBSan checked executions.
- Demand evidence adds 90 independent-oracle-checked executions with branch
  outcomes, memory locality, actual ordered atomic operations and observed
  touched-stack extents. The RV64I/IM/IMA static inventory records exact missing
  runtime providers instead of declaring a blocked link executable.
- A real local edit/diff/apply/compile/link/test chain records 110 serial events,
  including 60 successful fixture checks, 30 semantic-mutant checks and one
  compile-time rejection. Inference and network are explicitly unexercised.
- PPE-0.1 and HATS-TASK-0.1 define the minimum engine and scheduling boundaries;
  13 ABI tests cover layouts, integer/range/resource overflow, profile rejection,
  completion decode/validation and fault/correlation rules. They are not CP RTL.

## Boundary review: enough to start implementation, not to claim it

| Boundary | S01 decision | Implementation owner / gate |
| --- | --- | --- |
| APE application | Preserve speculative OoO scalar execution; first port uses explicit isolated runtime services, not implicit Linux | [S02 #3](https://github.com/chienpinglu/HATS/issues/3): helpers, startup, loader, heap/stack, actual Spike then APE RTL fixture parity |
| PPE execution | W=8 test profile, scalar/vector/masks, structured split/join, one wave/group, bounded scratch, partial-store fault semantics | [S02 #3](https://github.com/chienpinglu/HATS/issues/3): original encoding, code object, independent model/assembler and SpinalHDL/SpinalSim |
| CP/engine launch | Registered code, arguments, task/epoch/address-generation context; stable ready/valid; completion only after drain | S02 direct test adapter; [S05 #6](https://github.com/chienpinglu/HATS/issues/6) actual CP publication and device continuation |
| Queue/result ownership | 128-byte descriptor, 64-byte completion, SPSC epoch/sequence; correlate by epoch + submission sequence, not success value | S05 queue-full, completion-full, stale IDs, dependency rejection and exactly-once/drain tests |
| Memory visibility | Initial single uncached domain; shared address does not imply coherence; total scratch reservation overflow is rejected | [S04 #5](https://github.com/chienpinglu/HATS/issues/5) ordering/cache tests; [S07 #8](https://github.com/chienpinglu/HATS/issues/8) near/far placement |
| Trust / OS | Trusted prototype metadata rules are not isolation; no implicit authorization from descriptor fields | [S06 #7](https://github.com/chienpinglu/HATS/issues/7) permissions on all masters, pin/copy/invalidate, syscall/error/preemption rules |

No fixed ROB/issue width, cache capacity, memory channel count or tensor tile is
selected from this small corpus. The observed multi-megabyte native retained-tree
heap and ~91 KiB RV64I relocatable text closure already exceed the old 64 KiB
data/4 KiB code harness, but are not a final resource allocation. Runtime/capacity,
atomic semantics and fault handling come first. Performance sizing belongs to
S03/S04; tensor/inference to S08; full agent comparison to S09; physical proof
to S10. Every follow-up has an existing issue in the ledger.

## Reproduce the completion gate

```sh
python3 workloads/suite.py fetch --check
python3 workloads/native/treesitter/run.py check
python3 workloads/target/treesitter/newlib.py check
python3 workloads/s01_gate.py --run-workloads --summary workloads/evidence/S01-CLOSURE.json
```

Populate absent caches using the corresponding READMEs' pinned fetch/build
commands; never change a lock or silently regenerate an expected output to pass.
The full gate reruns 63 component/corpus samples, the 150 native matrix, the
90-run demand matrix and coding-tool chain, the three-profile static audit, plus
unit regressions and independent-reference checker sensitivity tests. No RTL
was changed by S01, so these checks do not renew prior RTL performance claims.

## Explicit limits and the earlier open-status notes

Previous progress notes asked for hardware PMU counters, complete stack bounds,
full agent traces and runnable RISC-V linkage before closing S01. Those are useful
**downstream** requirements, not the original S01 target-execution criterion.
S01 required representative native demand characterization and phase separation;
the new probes and real local tool chain supply that evidence without claiming
those stronger measurements. They are not relabeled as measured or dropped:
S02 owns target execution/resource correctness, S03/S04 hardware performance and
memory, and S09 complete model-driven trajectories under an approved data/compute
scope. Original issue acceptance wording is unchanged.

No CPU:GPU ratio, end-to-end HATS speedup, full RSI reproduction, completed big
OoO core, working PPE/CP or tapeout-quality claim follows from S01 closure. The
next actual execution gate is **issue #3**, pursued on APE and PPE in parallel.
