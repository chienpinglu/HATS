# HATS autonomous task tile

This research prototype starts the CPU-offload architecture: supported A64 programs
create child tasks, perform memory operations, suspend, and resume on the tile.
The host supplies code and one initial task. It does not schedule continuations.
SpinalHDL is the primary RTL source; SpinalSim with Verilator is the verification
path.

Verified on 2026-10-03: 41 RTL tests passed for each of the 2-, 4- and 8-context
configurations, 123 test instances total. This is the same scenario suite across
three configurations, not 123 distinct workload classes. Generated RTL,
waveforms, per-case reports and source hashes are generated in the ignored `build`
directory. They are not distributed with the source.

## Scope

The first implementation is one time-multiplexed scalar pipeline with four
independent contexts. It is a task-execution mechanism, not a complete GPU, AI
engine, Linux-capable Arm CPU, or demonstration of agent workload acceleration.
There are no vector/tensor engines, caches, MMU, coherent fabric, memory PHYs,
compiler runtime, or multi-domain execution yet. Arm implementation rights and
architectural conformance remain unresolved; no restricted Arm implementation
material is included.

The architecture direction and interface contract are in [ARCHITECTURE.md](ARCHITECTURE.md).
Current run evidence is generated at `build/validation.json`. A successful Scala
compile or Verilog generation alone is not a simulation pass. Waveforms are
under `build/sim`; program provenance is in `build/programs/manifest.json`.

## Reproduce

Pinned dependencies: Scala 2.13.14, SpinalHDL 1.12.3, sbt 1.10.7. Python 3.9+,
a JDK, Clang with AArch64 assembler support, make, a C++ compiler and Verilator
are also needed.
The initial local environment uses Homebrew OpenJDK 25.0.2 and Verilator 5.052.
`HATS_JAVA` overrides Java discovery; otherwise `JAVA_HOME`, Homebrew OpenJDK,
then `java` on PATH are tried. No system default Java is changed. Other host and
tool versions are unverified.

From this directory:

```sh
python3 tools/bootstrap.py
python3 tools/verify.py
```

This assembles inputs, generates RTL and runs all three configurations. The
top-level report is marked failed if a stage fails; inspect `build/verification.log`.
To rerun just the default tile after assembling inputs:

```sh
bash tools/sbtw 'Test / runMain hats.TaskTileSim 4'
```

Generated hardware is under `build/rtl/c2`, `c4` and `c8`; individual simulation
reports are `build/validation-c2.json`, `validation-c4.json` and `validation-c8.json`.
SpinalSim 1.12.3 expects the former Verilator `WData` C++ typedef. For the tested
Verilator 5.052, the test configuration uses `-DWData=EData`, its equivalent
32-bit wide-vector element type. This local bridge compatibility flag does not
modify RTL behavior. Other simulator versions require compatibility validation.

The bootstrap downloads the pinned sbt launcher from Maven Central and verifies
its SHA-256 before installation; the wrapper rechecks it before execution.
Build dependencies and caches remain under `.tools`. Internet access is needed
on the first build. Local simulation may require permission for simulator IPC.

## Files

- `src/main/scala/hats/TaskTile.scala`: context state, A64 subset, task operations,
  memory request/response contract, region tags, fault and cancellation handling.
- `src/test/scala/hats/TaskTileSim.scala`: Scala tests driving generated RTL,
  randomized memory stalls, delayed/reordered responses, fault and restart tests.
- `examples/workloads.s`: Clang-assembled programs, not a made-up instruction set.
- `tools/assemble.py`: ELF validation, image extraction and hashes.
- `tools/verify.py`: complete RTL verification entry point and evidence manifest.
- `tools/bootstrap.py`: checksum-verified sbt launcher setup.

## Provenance and boundaries

The tile, task ABI, assembly workloads and test harness are original experimental
project code developed with AI assistance. Build configuration uses the standard
[SpinalHDL dependency setup](https://github.com/SpinalHDL/SpinalTemplateSbt).
Third-party tools are downloaded separately and remain subject to their own
licenses. No proprietary CPU RTL or private source documents are included.
