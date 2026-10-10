# APE and PPE development guide

APE is the primary RISC-V application-processing core in this repository.
Develop the SpinalHDL source, run generated hardware in SpinalSim, and keep the
[specification](spec/APE-0.6.md) and [coverage map](spec/APE-VERIFICATION.md) aligned.
The A64 TaskTile remains a separate legacy task-mechanism regression.

## Source layout

| Location | Purpose |
| --- | --- |
| `src/main/scala/hats/ApeCore.scala` | Configuration, ROB, scheduling, execution, retirement and memory publication |
| `src/main/scala/hats/ApeDecode.scala` | RV64 subset decode into typed branch/memory semantics |
| `src/main/scala/hats/ApeSemantics.scala`, `ApeRv64Profile.scala` | Semantic operations/register layout and RISC-V frontend policy |
| `src/main/scala/hats/ApeIssueScheduler.scala`, `ApeDesignPointGenerate.scala` | One/two-lane oldest-ready issue and explicitly parameterized RTL generation |
| `src/main/scala/hats/ApeExecute.scala`, `ApeCompletionGuard.scala` | Registered integer/branch/AGU execution, completion identity and generation-wrap exclusion |
| `src/test/scala/hats/ApeExecuteSim.scala`, `tools/verify_ape_execution.py` | Elastic transport/guard tests and independent pipeline-profile Spike gate |
| `src/main/scala/hats/ApeRename.scala` | Physical integer file, speculative/committed maps, allocation and recovery |
| `src/main/scala/hats/ApeCheckpoints.scala` | ROB-owned map snapshots and younger-allocation reclaim sets |
| `src/test/scala/hats/ApeCheckpointSim.scala`, `tools/verify_ape_recovery.py` | Replay-oracle checkpoint test, actual early timing witnesses and exact Spike comparisons |
| `src/test/scala/hats/ApeRenameSim.scala`, `tools/verify_ape_rename.py` | Physical ownership/value scoreboard and independently checked core pressure matrix |
| `tools/verify_ape_semantics.py`, `tools/verify_ape_multi.py` | Semantic-policy and actual dual-lane/recovery gates |
| `formal/`, `tools/probe_ape_technology.py` | Selected bounded RTL properties and early mapped-area/combinational-delay study |
| `src/main/scala/hats/ApeBranchPredictor.scala` | Bimodal counters and direct-target selection |
| `src/test/scala/hats/ApeCoreSim.scala` | Generated-RTL instruction and memory scoreboard, matrix scenarios |
| `src/test/scala/hats/ApeReference.scala` | Independent local sequential interpreter; do not reuse RTL decode logic here |
| `src/test/scala/hats/ApePredictorSim.scala` | Predictor counter and timing checks |
| `examples/ape/` | Assembly fixtures, freestanding C function and linker script |
| `examples/ape_app/` | LP64 startup, application linker layout and original bounded diff tool |
| `src/test/scala/hats/ApeApplicationSim.scala` | Application execution, actual RTL event capture and memory/stack assertions |
| `tools/ape_app_image.py`, `tools/build_ape_app.py` | Checked static ELF loading and compilation/input preparation |
| `tools/verify_ape_app.py`, `tools/check_ape_diff.py`, `tools/test_ape_app.py` | Application RTL/Spike gate, independent output checks and rejection tests |
| `tools/assemble_ape.py` | LLVM compilation/linking, ELF validation, seeded program generation |
| `tools/verify_ape.py` | Complete matrix, evidence identity and failure aggregation |
| `tools/bootstrap_spike.py`, `tools/spike.lock.json` | Pinned unmodified external reference build and identity checks |
| `tools/spike_adapter.cc` | Original platform adapter around upstream Spike instruction semantics |
| `tools/verify_ape_spike.py`, `tools/compare_ape_spike.py`, `tools/test_ape_spike.py` | Fresh RTL differential gate and fail-closed comparison tests |
| `src/main/scala/hats/PpeCore.scala`, `src/test/scala/hats/PpeCoreSim.scala` | Original programmable eight-lane integer PPE and actual-RTL transport |
| `tools/ppe_isa.py`, `tools/ppe_programs.py`, `tools/build_ppe_cases.py`, `tools/verify_ppe.py` | Independent PPE model, binary fixtures and full-state RTL gate |
| `../../workloads/target/treesitter/execute/`, `../../workloads/target/treesitter/bulk/` | Strict real-tool port, small SpinalSim and full-stream Verilator paths |
| `../../workloads/s02/run_all.py` | Reproducible two-engine build, native/reference comparison and regression gate |
| `APE.md`, `spec/` | Overview, interface contract, verification map and future gates |

Generated RTL, tool caches, ELF images, traces and simulation outputs stay under
ignored `.tools/`, `target/` and `build/`. They are regenerated, not source edits.
Private reference RTL or proprietary encodings must not be copied into this tree.

## Prerequisites

Use Python 3.9+, a JDK, make, a host C++ compiler, Verilator and LLVM Clang with
the RISC-V backend plus LLD. Scala 2.13.14, SpinalHDL 1.12.3 and sbt 1.10.7 are
pinned in the build. The tested host tool versions are listed in the coverage map.
Apple's bundled Clang is not the RISC-V compiler used for these tests.

`HATS_RV_CLANG` and `HATS_RV_LD` override compiler/linker discovery. The scripts
otherwise try Homebrew paths and then PATH. `HATS_JAVA` selects the Java executable;
the build otherwise checks JAVA_HOME, Homebrew and PATH. No system default compiler
or Java setting needs changing. The existing simulator bridge uses `-DWData=EData`
for the tested Verilator version; another version needs its own compatibility check.

## Full verification

From `hardware/spinal`:

```sh
python3 tools/bootstrap.py
python3 tools/verify_ape.py
python3 tools/verify.py
```

Bootstrap verifies a pinned launcher checksum before use. The first dependency
resolution needs network access. Local simulator/sbt IPC may require execution
permission beyond a restricted sandbox. The two verification commands cover APE
and the legacy TaskTile independently; both must succeed before reporting both
as passing. Inspect each aggregate report rather than relying on stale traces.

For independent instruction-semantics validation, also install `dtc` and host
Clang/Clang++, then run:

```sh
python3 tools/bootstrap_spike.py
python3 tools/bootstrap_spike.py --check
python3 tools/verify_ape_spike.py
```

The differential command reruns the full APE matrix. It checks a pinned upstream
model rather than replacing it with the local interpreter. See the
[Spike validation contract](spec/APE-SPIKE-VALIDATION.md) for the two explicit
profile differences, provenance checks and evidence paths. APE instruction
changes must update both verification gates without weakening unexpected-mismatch
failures or modifying upstream semantics to match the DUT.

Run `python3 tools/verify_ape_app.py` for the separate 144-invocation
[application ABI and diff gate](spec/APE-APPLICATION-ABI.md). It compiles its own
executable, loads data, executes startup and checks complete architectural traces
plus tool outputs. The application suite does not replace the 600-invocation
mechanism suite or legacy regression. Run sbt-based aggregate suites sequentially
to avoid concurrent builds in the same workspace.

## Focused iteration

For the complete S02 two-engine gate, use Python 3.12+ from the repository root:

```sh
python3 workloads/s02/run_all.py
```

This rebuilds and runs all tool/PPE/legacy matrices sequentially; it is not a
fast unit-test shortcut. First populate the pinned Tree-sitter, Newlib and Spike
caches and install the documented [S02 host dependencies](../../workloads/S02-COMPLETION.md).
The native digest adapters currently use Homebrew OpenSSL 3 paths. The gate's
legacy test builds the committed TaskTile source through a recorded temporary
sbt override; it does not overwrite a dirty TaskTile checkout. To test local
TaskTile edits themselves, continue to use `tools/verify.py` separately.

For PPE-only iteration, run `python3 tools/verify_ppe.py` from this directory.
It generates `build/ppe/rtl/PpeCore.v` and compares actual instruction, memory,
register and fault traces with an independent Python oracle; see
[PPE-RTL-0.1](spec/PPE-RTL-0.1.md) for tested scope and direct-adapter obligations.

For physical-renaming changes, first run `python3 tools/verify_ape_rename.py`.
This freshly runs the 33/36/64-register unit matrix and ROB16/P36 core pressure
cases with independent Spike comparisons. It supplements, not replaces, the
normal matrix and real-tool gates. See [S03 progress](spec/S03-PROGRESS.md).

For checkpoint/recovery changes, run `python3 tools/verify_ape_recovery.py` as
well. It builds six separate recovery images, runs 32,000 unit cycles and 108
core invocations including the retirement-recovery baseline. The usual 50-scenario
matrix is unchanged. Run the full S02 gate after both focused gates; current
increment summaries use `workloads/s03/evidence.py` from the repository root;
that script never closes S03. The complete path, including `closure_evidence.py`,
is documented in [the S03 gate guide](../../workloads/s03/README.md).
After recovery evidence is frozen, `python3 formal/verify_checkpoints.py` checks
selected component properties on that exact generated RTL. See the
[bounded formal contract](spec/APE-CHECKPOINT-FORMAL.md) for isolated tool setup,
assumptions, proof depth, covers and explicit remaining gaps.

These commands are diagnostic subsets, not the complete matrix gate:

```sh
python3 tools/assemble_ape.py
bash tools/sbtw compile 'Test / compile' 'runMain hats.GenerateApe'
bash tools/sbtw 'Test / runMain hats.ApePredictorSim'
bash tools/sbtw 'Test / runMain hats.ApeCoreSim 8 bimodal'
bash tools/sbtw 'Test / runMain hats.ApeCoreSim 8 off'
```

`GenerateApe` emits six configurations under `build/ape/rtl/rN-MODE/`.
Core simulations use the same configuration settings but generate their own
simulation RTL. `ApeCoreSim` accepts ROB entries and `off` or `bimodal` as arguments.
An optional third argument selects physical-register count and writes separate
pressure evidence, for example `ApeCoreSim 16 off 36`. The default is 64.
The standard tests assume 1,024 instruction words and a 16-entry predictor.
Additional arguments select checkpoint capacity, `early` or `retire`, then an
optional `recovery` witness suite, for example `ApeCoreSim 16 off 64 4 early recovery`.
Assemble those fixtures first with `python3 tools/assemble_ape_recovery.py`.
Those configurations write separately under `build/ape_recovery/`.

## Adding behavior

1. Assign or extend a requirement in the specification, including illegal inputs,
   fault ordering, reset and externally visible side effects.
2. Add a directed assembly/C fixture and expected architectural result or trap.
   For new instructions, independently extend the sequential interpreter.
3. Add an observable RTL check. Scheduling changes must preserve the actual
   out-of-order and precise-retirement assertions, not merely final a0.
4. Update the assembler's image list, simulator scenarios and aggregate expected
   scenario count together. Include wrong-path and backpressure cases where relevant.
5. Run the full matrix and legacy regression, then update the coverage map with
   tested scope. Keep future requirements visibly unimplemented.

Do not modify test inputs, RTL or verifier sources during an aggregate run;
the source-stability check rejects that run. Documentation-only edits do not
change the RTL evidence. The test service is not a security sandbox or a real
HATS runtime. Compiling a C function for APE is not running LLVM on APE.

## Compatibility and publication

See [HSE compatibility](HSE.md) for preserved entry points. Compatibility adapters
must delegate to APE; there must not be a divergent second core behind the old name.
Historical reports under `build/hse/` cannot establish current APE behavior.

This is original reference-informed implementation, not a strict clean-room
claim. Public release requires a separate provenance review. Private source
material stays outside the public repo; local development does not authorize
publication or establish third-party implementation rights.
