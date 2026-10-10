# S03 early technology study

This is early implementation feedback for the actual APE RTL, not S10 physical
closure. The study compares mapped cell area and combinational-boundary delay
across the same ROB/PRF/issue-width/predictor choices as the controlled workload
study. All nine current-source points have passed mapping checks and complete
extracted-network combinational equivalence. Their measurements are in the
[design-point report](../../../workloads/S03-DESIGN-STUDY.md). All nine miss the
1,000 ps combinational mapping target; passing the evidence checks is not timing
closure or an achieved clock. S03 acceptance also requires application/ISA,
selected formal and configuration-review evidence.

## Reproduction and provenance

```sh
python3 hardware/spinal/tools/bootstrap_ape_timing.py
python3 hardware/spinal/tools/probe_ape_technology.py --jobs 2
```

The bootstrap uses ignored local tool storage, verifies archive/library hashes,
checks source identity and builds native ABC without installing system packages.
It preserves upstream copyright/license files. No third-party implementation is
copied into the processor sources.

- [ABC source](https://github.com/berkeley-abc/abc/tree/a3001b72edc5de22442e942165487fddf150e3d0),
  revision `a3001b72edc5de22442e942165487fddf150e3d0`, under its upstream
  University of California permissive license.
- [Nangate45 platform](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts/tree/ef421749a1050a8e9a197e7dfcd05396807f889d/flow/platforms/nangate45),
  ORFS revision `ef421749a1050a8e9a197e7dfcd05396807f889d`, with its Apache-2.0
  license retained locally. This is a generic non-manufacturable research library.
- Liberty `NangateOpenCellLibrary_typical.lib`, SHA-256
  `8d540a4d4cf6d09d27c87ad067857a9c0c2eeb023ab7a56e058cd3113db4e9b1`.
- Pinned YoWASP/Yosys environment from `formal/requirements.txt`; each report
  records its version and WASM hash as well as the native ABC executable hash.

## Actual implementation path

`ApeDesignPointGenerate` elaborates `ApeCore`, including rename/checkpoint state,
the actual one/two execution lanes, completion arbitration and predictor. A fixed
1,024-word instruction memory keeps physical-study storage assumptions identical
across points. The real-tool study uses 65,536 words; their total areas must not be
equated. All memories, including code and PRF, are mapped to flip-flops and muxes.
Trace and counter outputs remain observable and contribute to the synthesized
design. There is no replacement of the core with a hand-written toy datapath.

Yosys flattens and synthesizes the generated core, maps sequential cells with
`dfflibmap`, then maps the combinational network through ABC using the pinned
Liberty library. The gate rejects remaining generic logic cells and verifies
the generated mapped netlist. Native ABC independently compares the extracted
pre-mapping combinational BLIF to the mapped BLIF, requiring an equivalence
result before accepting area/delay evidence. Both networks are converted to AIG
without abstracting internal logic, after checking that their complete ordered
input/output name lists match. The binary AIG headers must preserve all inputs,
outputs and the zero-latch combinational scope. ABC's `&cec` then compares them;
only its final equivalent outcome, including any successful fallback on the
reduced miter, passes. An undecided final result never passes. Small identical
and deliberately different Boolean networks check the solver path itself; these
controls do not replace the actual-core comparisons or measure DUT mutation
coverage.

This comparison treats register and primary-port boundaries as combinational
inputs/outputs. It does not prove the original RTL's sequential behavior; the
source-bound RTL simulation, independent ISA reference and selected formal gates
remain required. The complete application/architectural digest must still match.

## Constraints and interpretation

The mapping target is 1,000 ps. All combinational inputs use a `BUF_X1` boundary
driver; outputs use a 5 fF load. Native ABC `stime -p` reports the library-based
critical combinational boundary path. A missed mapping target is reported as
missed, not silently relabeled as an achieved clock. Passing the evidence gate
means the estimate was produced and checked, not that a 1 ns processor exists.

These constraints omit sequential clock-to-Q and setup/hold costs, clock trees,
placement, routing, extracted parasitics and multi-corner closure. They do not
differentiate external input/output timing from DFF pin constraints. They are
useful consistent early comparisons, not full STA, clock frequency or signoff.
Mapped cell area includes register-mapped storage and is not die area. There is
no switching-activity, power or physical energy estimate.

The controlled workload report provides simulated cycles, IPC and measured stall
counters separately. Do not multiply its ratios by a reciprocal ABC delay and
present the result as real hardware speedup. S04 must evaluate a real memory
hierarchy, and S10 must replace the register-memory/clock/interconnect assumptions
with an implementation flow before such claims are justified.

## Evidence integrity

The study snapshots passing current-source semantic and multi-issue gates, hashes
all `Ape*.scala` files, build inputs, study code and tools, and rejects source or
artifact changes during a run. Reports preserve generated RTL, mapped netlists,
commands, logs, library identity, equivalence outcomes and parsed timing values.
They remain under ignored `hardware/spinal/build/ape_technology/<run>/` paths.
The final S03 collector must bind all nine completed configurations to the same
current-source workload study and integration gate. It must also keep formal
timeouts/failures separate from successful reruns.

RTL elaboration is serial within the driver; only independent synthesis/proof
jobs run concurrently. The driver retries only the specifically identified sbt
boot-socket startup collision, retaining each attempt's log. It does not retry or
hide Scala/Spinal elaboration failures. A failed worker cancels queued jobs.

The first scheduling attempt hit that socket collision and was stopped with all
files preserved. The first narrow mapping completed, but its monolithic legacy
CEC attempt was stopped after the same full network passed the AIG-based path.
The original flow source is retained in `build/s03-timing/first-flow-source.tar`,
SHA-256 `260e902b01658e08c4499b2ae2b03b72f4e12ea24a3b7eb583c3f9f3f61d73eb`.
Its partial mapped area and 2,869.98 ps boundary-delay diagnostic are not used as
completed final-study evidence. All nine points are regenerated with the corrected
source-bound driver. These are tool-flow attempts, not silently omitted processor
RTL test failures.
