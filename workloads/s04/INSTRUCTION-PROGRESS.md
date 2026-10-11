# S04 APE instruction/data hierarchy increment

Status: this instruction/cache increment is partial on its own; the combined source-bound S04 completion audit is recorded in [README](README.md) and `S04-PPE-INSTRUCTION-CURRENT-CHECKPOINT.json`.
Original requirements remain in [ROADMAP S04](../../ROADMAP.md).
This extends the [data-path increment](README.md) without changing the accepted
S03 profile or relabeling historical measurements as cache-equipped results.

## Actual execution path

The selected speculative OoO APE (ROB8/P48/W1/C4/D2/G2) fetches through an RTL
instruction-word buffer and I-L1. Its LSQ uses D-L1. A source-tagged, locked
round-robin fabric multiplexes both caches onto one whole-line external service.
Tags, data, queues, arbitration, refill/writeback and publication control execute
in Spinal-generated RTL. The external byte store and latency remain modeled.

The I-cache mode has **no internal instruction RAM**. Tests drive the old program
port with illegal zero instructions and independently serve the intended code
via cache-line reads. Both generated-module checks and actual architectural
execution verify this path.

An explicit tile command cleans D-L1, then invalidates I-L1 and the frontend
buffer. It blocks launch throughout maintenance and while its result is held.
Writeback failure retains dirty data and prevents publication success. This is
not a new FENCE.I instruction or an implicit coherence claim.

## Executed gates

Previously accepted source-bound run:
`hardware/spinal/build/s04/ape-memory-1791617327808802000/gate.json`.

| Execution path | Executions | Exact external Spike matches | Explicit prior profile differences |
| --- | ---: | ---: | ---: |
| APE I/D L1 + fabric | 58 | 56 | 2 |
| APE D-L1 regression | 58 | 56 | 2 |
| S03 direct-memory standard | 100 | 96 | 4 |
| S03 selected-profile recovery | 12 | 12 | 0 |
| Total | 228 | 220 | 8 |

The differences are exactly the pre-existing unsupported FENCE.I and misaligned
launch-policy cases, checked against their precise expected shapes. No other
mismatch is ignored. Full register-writing retirement, architectural memory and
terminal events originate from RTL observation ports, not the local oracle.

All 58 I/D-cache runs additionally check final backing-memory bytes after clean
and store authorization when the real data cache accepts each store. Existing
eight-entry LSQ/four-MSHR occupancy, forwarding, dependence, fence, precise-fault
and late-read-drain witnesses continue to pass with real instruction fetch.

An additional actual-RTL protocol test performs 11 executions without processor
reset and five publication operations. It checks:

- Host-published code remains stale without I-cache invalidation and changes
  only after explicit publication.
- The actual APE stores a replacement instruction through D-L1. A failed clean
  leaves dirty ownership and old executable bytes intact; successful retry
  writes back the instruction and permits its execution.
- Maintenance acknowledgement is held for 25 aggregate cycles with no premature
  launch. Exactly one CPU code store leads to one failed and one successful
  writeback attempt.
- A demanded fetch fault traps precisely. Wrong-path instruction faults before
  and after redirect never become architectural traps. Late fetch responses drain.
- The independent port scoreboard reconciles 18 accepted/completed lower
  transactions, rejects 11 wrong-generation replies, and observes two concurrent
  sources, response reordering and request stalls. There are four injected fetch
  failures and three discarded frontend responses in this deterministic run.

These known-answer protocol checks complement the independent Spike matrix;
they are not described as additional Spike-certified programs.

## Reproduce and revalidate

From `hardware/spinal` with Python 3.10+ and the existing local dependencies:

```sh
python3 tools/verify_ape_memory.py --instructions
```

The driver uses a fresh run root, regenerates compiler inputs, executes both
cached profiles and the selected S03 regressions, checks pinned Spike, and binds
sources, input images, tool binaries, traces and generated Verilog by SHA-256.
Its `sources.tar` preserves the exact tested implementation. Earlier successful
and failed directories are left intact. A protocol-test simulator input type
error during bring-up was corrected; no hardware assertions were relaxed.

From the repository root:

```sh
python3 -m unittest discover -s workloads/s04 -p 'test_*.py' -v
python3 workloads/s04/checkpoint.py --instructions \
  --l1 hardware/spinal/build/s04/l1-1791616149851589000/gate.json \
  --ape hardware/spinal/build/s04/ape-memory-1791617327808802000/gate.json
```

The second command rechecks artifact hashes and comparison decisions and writes
an instruction increment record. Historical records retain their original
source identities. Synthetic report-validator tests check rejection logic only.

## Latest APE device-path rerun

The source-bound gate
`hardware/spinal/build/s04/ape-memory-1791674422421814000/gate.json` reruns the
full I/D, publication, device, and selected S03 regression matrix. It records
228 comparisons (220 exact Spike matches; 8 explicitly characterized profile
differences), and passes six uncached device transactions across the D-only and
I/D profiles. The D-only profile rejects the deliberately mismatched response
ID; the I/D profile rejects the mismatched epoch. Both profiles verify clean
before device access, backpressure, and drained transactions. The device is
still a behavioral testbench service, not a hardware peripheral.

The linked [partial checkpoint](../evidence/S04-APE-ID-DEVICE-INCREMENT.json)
binds this gate to the current L1 component run. It does not close Issue #5.

## APE RV64A atomic instruction increment

The latest source-bound [APE gate](../../hardware/spinal/build/s04/ape-memory-1791729375675611000/gate.json)
also runs `ApeAtomicAddSim` through the actual APE decoder, ROB, LSQ, D-L1, and
modeled lower line service. Three AMOADD.D operations return old values 10, 11,
and 13; a subsequent load reads 16, and an explicit clean writes 16 to backing
memory. Unsupported AMOADD.W traps without a cache atomic request. The atomic
subtest and source are included in the gate archive and report validation.

This is single-APE, single-cache serialization. It does not establish a shared
atomic order across APE/PPE caches, PPE instruction support, or real DRAM timing.
The new gate passed 220 exact Spike comparisons plus eight individually checked
pre-existing profile differences; the separate atomic program is checked by
its RTL-directed known answers. The refreshed L1 gate is
`hardware/spinal/build/s04/l1-1791729438617336000/gate.json`; the partial
combined record is `workloads/evidence/S04-INSTRUCTION-INCREMENT.json`.

## Historical increment limits and scope boundaries

PPE coalescing, scratch banking, concurrent misses and actual I/D hierarchy
integration was not covered by this increment. Cross-engine atomic
serialization, PPE instruction-level atomics, and independent system-level
fence litmus tests remain outside the accepted S04 criteria. Conservative APE
unknown-store interlocks are not speculative dependence replay. Selected
formal proofs and workload matrices have bounded scope; they do not claim
application-wide exhaustion bounds or calibrated cache/bandwidth performance.

The frontend has one outstanding fetch word. No fetch-throughput, speedup,
physical-clock, energy, OS, HBM/LPDDR, full coherence or whole-core formal claim is
made. See the combined completion checkpoint for the five original acceptance
criteria and their evidence; these limits are explicit non-claims, not open
acceptance items.
