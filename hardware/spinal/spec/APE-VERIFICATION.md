# APE verification coverage

APE-0.2 is verified by executing linked RV64 programs in generated RTL through
SpinalSim and Verilator. Each successful retirement is checked against a local,
separately authored sequential interpreter. External memory requests are checked
at acceptance, before side effects, and final memory is compared at halt.
This is bounded regression coverage, not independent ISA certification or a
formal proof. The requirement definitions are in [APE-0.2](APE-0.2.md).

## Required matrix

`python3 tools/verify_ape.py` runs 4/8/16-entry ROB configurations, each with
prediction disabled and with the 16-entry bimodal predictor. Each configuration
runs 50 scenarios twice without a reset between the two invocations: 600 core
invocations in total. Those repeats check restart; they are not 600 distinct
workloads. The 48 linked inputs consist of 32 directed programs, eight seeded
integer streams and eight seeded control-flow/memory programs. Two additional
scenarios reuse an image with an invalid launch PC.

The predictor unit gate checks enabled/disabled configurations with 2/16 entries.
Each has 512 cycles checked before and after the update edge: 4,096 lookup checks.
It covers both saturation limits, direction transitions, index aliases, simultaneous
lookup/training, disabled training inputs and clear priority over training.

## Requirements and executable checks

| Requirement | Test or assertion | Boundary of coverage |
| --- | --- | --- |
| APE-OOO-01 rename | `rename_raw_waw_war`, `random_0` through `random_7`; live-producer map assertion | Bounded streams, not exhaustive interleavings |
| APE-OOO-02 actual OoO | `rename_raw_waw_war` requires PC12 to issue before PC8 and finish before PC4 | Observed in RTL in every matrix configuration |
| APE-OOO-03 retirement | Every retirement checked for PC, instruction, destination enable/register and value | Local sequential oracle, not Spike/Sail |
| APE-REC-01 recovery | `wrong_path_effects`, `nested_redirect`, `predicted_taken_exit`, `illegal_precise`, fault cases | Retirement-time recovery only |
| APE-BP-01 counters | `ApePredictorSim`; `loop_rob_wrap` requires learned taken predictions and fewer than 10 misses | Tests use 2/16 predictor entries; not all possible sizes |
| APE-BP-02 training | Predictor unit update/clear tests; core update wired only to successful conditional retirement; `taken_fallthrough_target` | Retirement qualification is structural; no full speculative-history formal proof |
| APE-BP-03 targets | `direct_jump_prediction`, `call_return`, `jalr_clear_bit0`, `jump_alignment`, `untaken_misaligned_target` | No indirect-target or return-address prediction |
| APE-LIFE-01 restart | Every scenario holds halt for eight cycles, consumes it, relaunches without reset | Arbitrary mid-execution reset and busy-time code-write rejection are not separately stimulated |
| APE-MEM-01 publication | Head-owner RTL assertion; every accepted request checked against the next architectural instruction; wrong-path read/write tests | Behavioral external service, not integrated CP/MMIO hardware |
| APE-MEM-02 handshake | Random request backpressure, stable-held-payload checks, delayed responses, one-outstanding assertion | Conforming backend only; no late/duplicate-response containment |
| APE-MEM-03 accesses | `memory_sizes`, alignment/bounds/readonly tests, `zero_load_fault`, bus-fault cases | Invocation bounds, not virtual-memory isolation |
| APE-MEM-04 precise service fault | `load_bus_fault`, `store_bus_fault`; no memory modification on error in test service | No rollback of backend partial writes |

All core tests include x0, ROB occupancy and live rename-owner RTL assertions.
The command sink checks zero wrong-path writes, one live write in `command_store`,
and exactly two live writes in `predicted_taken_exit`, with no third write on the
predicted but unexecuted loop body. It does not execute a HATS task.

## Evidence and failure behavior

The aggregate report is `build/ape/validation.json`; detailed output is in
`build/ape/verification.log`. Each `build/ape/rN-MODE/` contains a report and
per-invocation traces with predict, issue, finish, retire, control, redirect and
memory events. Predictor results are in `build/ape/predictor/validation.json`.
Waveforms and simulator builds are under `build/ape/sim/`.

The runner invalidates previous per-suite status before building, records source
hashes before and after execution, and rejects a run if those sources changed.
It checks all expected configurations, scenario counts and per-case results;
compares architectural result/count summaries across the matrix; and records
tool versions, program and generated-RTL hashes. Assembly, compilation, simulation,
timeouts and evidence inconsistencies produce a failed aggregate and nonzero exit.
A forcibly killed process can leave `running`, which is not a passing result.

## Verified local result

The 2026-10-07 APE-0.2 run passed all **600 core invocations and 4,096 predictor
checks** on LLVM/LLD 23.1.2, Scala 2.13.14, SpinalHDL 1.12.3, sbt 1.10.7 and
Verilator 5.052. The matrix's architectural outcome comparison passed.

For the 100-iteration `loop_rob_wrap` fixture, every tested ROB size recorded
99 branch mispredictions with prediction off versus 2 with bimodal prediction.
The corresponding invocation lengths were 505 versus 311 simulated cycles.
These are mechanism diagnostics for a small test loop with the same instruction
path, not application speedup, a frequency estimate, energy savings or PPA.

## Remaining verification gates

- Spike/Sail or architectural-test differential coverage of the implemented subset.
- Fault, reset, malformed-response and protection adversarial tests as interfaces expand.
- Formal rename, retirement, recovery and publication invariants.
- Additional code-memory configurations, workload-driven branch traces and predictor sizes.
- Real cache/MMU/coherence tests when those components exist.
- Compiler, interpreter and agent workloads executing on APE, with no host fallback.

The legacy TaskTile suite uses `python3 tools/verify.py`. It is a separate task
mechanism regression and cannot substitute for APE execution coverage.
The 2026-10-07 rerun passed its 123 test instances. The retained
`HseCoreSim 8` entry point separately passed 100 delegated APE invocations with
prediction off; these repeat a matrix configuration and add no workload diversity.
