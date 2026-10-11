# S04 PPE instruction/data hierarchy increment

Status: this increment is partial on its own; the combined source-bound S04 completion audit is recorded in [README](README.md) and `S04-PPE-INSTRUCTION-CURRENT-CHECKPOINT.json`.
The previous [data-path increment](PPE-DATA-PROGRESS.md) remains an archived
regression point. All original [S04 work packages](../../ROADMAP.md) retain their
scope, including ownership, atomics, formal and real-workload design studies.

## Latest source-current evidence (2026-10-12)

The current authoritative PPE I/D-L1 gate is
[`ppe-memory-1791750201180159000/gate.json`](../../hardware/spinal/build/s04/ppe-memory-1791750201180159000/gate.json),
not the historical run IDs below. It passes 316 exact cached I/D-L1
comparisons, 316 data-only comparisons and 288 serial-reference comparisons.
It executes two complete 32-group applications through actual I-L1/D-L1:
the delimiter prefilter and a 256-element residual+bias+ReLU epilogue. The
vector application checks 608 loads, 256 stores, exact full-memory output and
canaries; 134/134 lower requests drain at 32 sets/8 MSHRs. The same two
applications run at all three matched I/D-L1 design points (8/2, 16/4, 32/8)
with identical input/output hashes; see
[`PPE-DESIGN-POINTS.json`](PPE-DESIGN-POINTS.json).

The updated source-bound shared APE/PPE ownership gate is
[`ownership-1791750984439340000/gate.json`](../../hardware/spinal/build/s04/ownership-1791750984439340000/gate.json),
with the 12-step active line-ledger proof at
[`ownership-steps12-1791750996844599000/validation.json`](../../hardware/spinal/build/s04/formal/ownership-steps12-1791750996844599000/validation.json).
The integrated fabric reaches its full 4/4 outstanding capacity and drains all
75 accepted requests, including reordered responses, before ownership transfer.
The combined checkpoint also binds current APE cached-tool runs and six
selected-case 128-byte-heap ENOMEM runs, one for each empty/scalar/Unicode
cold-old and incremental fixture. The combined checkpoint is the authoritative
acceptance record; statements below describe only this PPE increment or scope
limits, not unresolved original acceptance criteria.

## Actual execution path

The PPE now fetches its real programs through an RTL instruction-word frontend,
I-L1 and source-tagged line fabric. Its coalescer and four-bank scratchpad remain
in use; global data accesses use D-L1. The instruction-cache mode has no internal
program RAM. The testbench drives the obsolete programming port with illegal
zeros and supplies executable bytes only through the external line interface.
Generated-Verilog checks confirm the loader RAM is absent in this mode and
present in the data-only regression mode.

This completes instruction/data-path integration for each individual engine.
The combined S04 implementation separately validates the jointly
ownership-enforced APE/PPE system. The external memory store and
latency are modeled; cache storage, controllers, queues, arbitration and response
ownership execute in actual Spinal-generated RTL.

## Executed comparison matrix

Previously accepted source-bound gate:
`hardware/spinal/build/s04/ppe-memory-1791618786917089000/gate.json`.

| PPE execution path | Exact ISA-model runs | Decode/launch checks | Clock-protocol checks | Total |
| --- | ---: | ---: | ---: | ---: |
| I/D-L1 + fabric + coalescer + banked scratch | 208 | 38 | 6 | 252 |
| D-L1 data-only regression | 208 | 38 | 6 | 252 |
| Original serial-memory regression | 180 | 38 | 6 | 224 |
| Total | 596 | 114 | 18 | 728 |

The independent checker compares per-retirement register/predicate/mask/depth
state, logical lane memory events, completion, and final global/scratch bytes.
All original cases run twice in every applicable profile, including all 37
opcodes and real delimiter-kernel groups. Clock-specific cases have explicit
profile-specific deadlines (serial 540, D-only 160, I/D 1,000 cycles), with the
same required offered-group drain behavior; they are not ISA timing predictions.

Aligned 16-byte and 32-byte strides exercise full 2/4/8-MSHR and lower-line
occupancy at matched D-L1 and I/D-L1 points. The I/D matrix preserves response
reordering, scratch-bank parallelism, byte-store authorization and coalescing witnesses. Independent
line-traffic accounting reconciles accepted, completed and rejected messages with
the fabric's RTL counters. Rejected launches generate no instruction traffic.
Final memory is checked only after successful clean/invalidate.

## Code publication and instruction-fault tests

An additional actual-PPE protocol test executes 13 programs without reset and
performs nine publication commands, holding their acknowledgements for 45 cycles.
Its independent known-answer checks establish:

- The actual PPE writes a replacement instruction through D-L1. I-L1 continues
  to execute the old instruction before publication.
- A failed dirty writeback retains both dirty data and old executable behavior.
  Successful retry publishes the instruction and changes the returned result
  from 11 to 77. Exactly one code store produces one failed and one successful
  writeback attempt.
- An external code edit remains stale until publication, then returns 43.
- Word-local instruction poison faults at the demanded word after the exact
  preceding retirement prefix. A whole-line transport failure faults before the
  first retirement. A branch skipping a poisoned word executes correctly.
- Both an offered-but-stalled fetch and an accepted fetch drain after timeout.
  Their late errors do not replace the timeout result or publish instructions.
  A subsequent launch executes correctly.
- Fourteen accepted line requests produce exactly fourteen matching replies;
  fourteen deliberately wrong-generation replies are rejected. Five instruction
  line responses contain injected errors/poison, and two late fetches are discarded.

These 13 runs are protocol evidence, not extra ISA-model-certified runs. PPE has
no speculative instruction prefetch in this profile; branch skipping does not
claim speculative wrong-path execution coverage. APE's separate speculative
instruction-fault tests retain that responsibility.

## Reproduction and anchors

From `hardware/spinal`, with Python 3.10+ and the installed toolchain:

```sh
python3 tools/verify_ppe_memory.py --instructions
```

The gate binds sources, fixture generation, independent model, testbench, tools,
inputs, generated Verilog and traces by SHA-256, and archives the exact sources.
The latest source-bound APE, PPE and L1 gates are:

- `hardware/spinal/build/s04/ape-memory-1791727568887149000/gate.json`:
  220 exact Spike matches, eight checked pre-existing profile differences,
  and device ID/epoch rejection plus drain coverage.
- Six matched D-L1/I/D-L1 points and exact metrics are in
  [`PPE-DESIGN-POINTS.json`](PPE-DESIGN-POINTS.json); each passes 252 comparisons.
  The refreshed I/D 16/4 source-bound gate is
  `hardware/spinal/build/s04/ppe-memory-1791734085622160000/gate.json`.
- `hardware/spinal/build/s04/l1-1791674490024708000/gate.json`:
  three configurations / 9,344 requests, plus 12 word-poison lifecycle requests.

Revalidate source identities, archived source contents and actual comparison
decisions from the repository root:

```sh
python3 -m unittest discover -s workloads/s04 -p 'test_*.py' -v
python3 workloads/s04/checkpoint.py --instructions \
  --l1 hardware/spinal/build/s04/l1-1791674490024708000/gate.json \
  --ape hardware/spinal/build/s04/ape-memory-1791727568887149000/gate.json \
  --ppe hardware/spinal/build/s04/ppe-memory-1791727524429513000/gate.json
```

The resulting [combined increment record](../evidence/S04-PPE-INSTRUCTION-INCREMENT.json)
keeps `S04_complete: false`. Fifteen synthetic report-validator tests check scope,
matrix and witness rejection logic; they are not hardware tests. The immutable
S03 evidence/source archives and unrelated local edits remain preserved.

The current dual-engine, formal and matched-input design-point runs are recorded in
[the APE/PPE/ownership increment](../evidence/S04-APE-PPE-OWNERSHIP-INCREMENT.json).
This checkpoint is bounded to its explicit evidence scope; bounded/formal and
modeled-service limitations are listed in its audit.

The S04 scalar AMOADD extension (opcode 38; see
[`PPE-S04-ATOMIC-EXTENSION.md`](../../hardware/spinal/spec/PPE-S04-ATOMIC-EXTENSION.md))
now executes through PPE, its memory engine and D-L1. SpinalSim checks three
serialized operations, old values 10/11/13, the following load and FENCE-visible
backing value 16, and rejects an atomic target in a configured device aperture
before any device/cache/lower request. The Python PPE functional model has
corresponding architectural and fault checks. The current dual-engine RTL
ownership test additionally runs PPE AMOADD 43→48, performs a clean/invalidate
handoff, has APE observe 48, then runs APE AMOADD 48→51. This verifies sequential
visibility across exclusive ownership epochs, not simultaneous cross-engine
atomic arbitration or general coherence.

The current-source completion checkpoint is
[S04-PPE-INSTRUCTION-INCREMENT.json](../evidence/S04-PPE-INSTRUCTION-INCREMENT.json).
It binds the refreshed APE and PPE atomic gates, PPE I/D gate, dual-engine
ownership gate, three bounded formal results, and matched-input 8/2, 16/4,
32/8 PPE design points. The dual-engine gate now requests the first ownership
handoff while at least two external line requests are outstanding, checks that
ownership and generation remain unchanged while launches are blocked, and
requires all accepted lines to drain before handoff acknowledgement. The
current completion-mode checkpoint records AC1–AC5 as passed; this older
increment narrative predates the expanded application, full-occupancy and
six-case APE heap-exhaustion evidence below. The combined tile also runs one integrated PPE bounds-fault
case: an out-of-range vector store is faulted, the output bytes remain
unchanged, and the same application subsequently succeeds at full permissions.
This does not replace adversarial APE/PPE fault, partial-store, or replay stress.
The same integrated APE task now retires four reads from distinct
lines mapping to one D-L1 set, while two additional independent-set misses
preserve a four-transaction lower-interface concurrency witness. It also
executes a byte store/load alias and verifies the dirty partial word survives
conflict replacement and clean ownership transfer to backing memory.

An actual `repo_source_edit` application now executes through both APE D-L1 and
APE I/D-L1+fabric paths, each at 8/2, 16/4 and 32/8 set/MSHR points. The I/D
runs poison the obsolete programming port, forcing instruction fetch through
I-L1 and the shared fabric. All six runs match the direct APE retirement
sequence, architectural memory observations and byte-exact final backing
memory after D-L1 clean. Source-bound evidence is in
[`S04-APE-CACHED-APPLICATION.json`](../evidence/S04-APE-CACHED-APPLICATION.json).
This now covers all 12 diff-workload input fixtures: six points for
`repo_source_edit` and matched 16/4 D-L1 and I/D-L1 points for the other 11.
Every run uses a behavioral external line service and this APE matrix does not
include PPE application execution; the separate current PPE gate above covers
the two PPE application workloads. External service timing is behavioral, not
calibrated bandwidth.

## Scope and claim boundaries

The completion audit passes the original S04 acceptance criteria on the
source-bound selected workload matrix. The achieved contract is exclusive
clean/invalidate ownership, not general hardware coherence; proofs are bounded
and per-module rather than unbounded full-chip proofs; six selected ENOMEM
cases are not formal worst-case resource bounds; and line-service timing is
behavioral rather than measured HBM/LPDDR performance. Broader workload, OS,
PMU, silicon PPA, energy and speedup results are outside this S04 acceptance
claim.
