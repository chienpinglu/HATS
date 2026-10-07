# APE development guide

APE is the primary RISC-V application-processing core in this repository.
Develop the SpinalHDL source, run generated hardware in SpinalSim, and keep the
[specification](spec/APE-0.2.md) and [coverage map](spec/APE-VERIFICATION.md) aligned.
The A64 TaskTile remains a separate legacy task-mechanism regression.

## Source layout

| Location | Purpose |
| --- | --- |
| `src/main/scala/hats/ApeCore.scala` | Configuration, RV64 subset decoder, rename/ROB, scheduling, execution, retirement and memory publication |
| `src/main/scala/hats/ApeBranchPredictor.scala` | Bimodal counters and direct-target selection |
| `src/test/scala/hats/ApeCoreSim.scala` | Generated-RTL instruction and memory scoreboard, matrix scenarios |
| `src/test/scala/hats/ApeReference.scala` | Independent local sequential interpreter; do not reuse RTL decode logic here |
| `src/test/scala/hats/ApePredictorSim.scala` | Predictor counter and timing checks |
| `examples/ape/` | Assembly fixtures, freestanding C function and linker script |
| `tools/assemble_ape.py` | LLVM compilation/linking, ELF validation, seeded program generation |
| `tools/verify_ape.py` | Complete matrix, evidence identity and failure aggregation |
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

## Focused iteration

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
The standard tests assume 1,024 instruction words and a 16-entry predictor.

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
