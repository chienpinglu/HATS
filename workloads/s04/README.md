# S04 memory hierarchy progress

Issue: [#5](https://github.com/chienpinglu/HATS/issues/5).
Status: AC1–AC5 pass the source-bound completion audit; GitHub issue closure is pending the scoped commit/push handoff.
Specification: [memory architecture](../../hardware/spinal/spec/S04-MEMORY-ARCHITECTURE.md).

## Current-source APE replay and real-tool update

### Current-source partial checkpoint refresh (2026-10-12)

[`S04-PPE-INSTRUCTION-CURRENT-CHECKPOINT.json`](../evidence/S04-PPE-INSTRUCTION-CURRENT-CHECKPOINT.json)
rehashes the APE/PPE/L1 gates, current dual-engine ownership run, three bounded
proof records, six PPE design points, 40 cached APE application runs spanning
12 workload fixtures, and the refreshed Tree-sitter path. All 12 fixtures run
through D-L1 and I/D-L1 at the matched 16-set/4-MSHR point; `repo_source_edit`
also runs across the full 3×3 factorial of 8/16/32 sets and 2/4/8 MSHRs in both
modes. The matrix reports direct cache hit, miss, refill and writeback counters.
The latest completion-mode run reports `verified_complete` with AC1–AC5 passed;
earlier partial checkpoints are preserved as historical increments. Direct APE RTL runs cover three Tree-sitter input
classes (empty, scalar-heavy and Unicode), each cold-old and incremental, twice
per case, with Spike architectural traces and independent output checks. Six
corresponding parser-phase cases pass through cached APE I/D-L1 with full 16 MiB
final-memory oracles and drained line traffic. Each warm start is reconstructed
from that case's own Spike startup prefix; direct runs cover cold startup.
The current ownership integration presents both launch streams simultaneously
while APE owns memory. APE handshakes; PPE remains valid and backpressured until
the PPE ownership handoff, then handshakes once. The reverse APE request is
held while PPE owns memory and handshakes once after transfer back. This tests
ready/valid backpressure semantics rather than withdrawing an unaccepted pulse.
Evidence is recorded in
`hardware/spinal/build/s04/ownership-1791749002565209000/dual-engine/launch-race.json`.
Supporting checks cover 177 compiler-helper vectors (1,062 results), 160
runtime checks, ten rejected-input cases, and eight validator tests. This
remains a small selected parser matrix, not broad toolchain or OS coverage.
The source-bound six-case resource summary observes 1,584 bytes maximum stack
use in both APE retirement traces and Spike, 8,248 bytes peak requested heap,
and 12,288 bytes granted. These are measurements for the selected fixtures
only—not worst-case stack/heap bounds for the complete application envelope.
Each of the six selected Tree-sitter fixtures (three input classes, cold-old
and incremental) now has a deliberately constrained 128-byte-heap run that
returns clean ENOMEM on actual APE RTL and matches Spike's full memory and
architectural trace. This covers the selected matrix's bounded fault paths,
not a formal application-wide exhaustion bound.
The current PPE I/D-L1 gate now runs two complete 32-group applications: the
delimiter prefilter and a 256-element signed-int32 residual+bias+ReLU epilogue.
The latter records 608 loads, 256 stores and byte-exact output/canary checks;
all 134/134 line requests drain at 32 sets/8 MSHRs. Both applications are
re-run at the three matched I/D-L1 points (8/2, 16/4 and 32/8), with identical
input and output hashes. The six-point PPE fixture suite still has exact ISA
comparison at every D-L1 and I/D-L1 point, and reaches each configured MSHR
capacity. Evidence is consolidated in
[`PPE-DESIGN-POINTS.json`](PPE-DESIGN-POINTS.json).
The refreshed integrated APE/PPE owner gate also requires full shared-fabric
occupancy: 4/4 outstanding lower transactions, 75/75 completions, three
response reorderings, and a handoff that waits for live requests to drain.
The current APE memory gate also adds a separate ROB16 pressure run that
simultaneously reaches all eight LSQ entries and four D-L1 MSHRs, executes a
dependence replay, sees four reordered line responses, and drains eight refills;
the selected ROB8 application/profile regressions remain unchanged.

Reproduce the current partial checkpoint from the repository root with:

```sh
python3 workloads/s04/checkpoint.py --instructions \
  --l1 hardware/spinal/build/s04/l1-1791728490584960000/gate.json \
  --ape hardware/spinal/build/s04/ape-memory-1791747405365193000/gate.json \
  --ppe hardware/spinal/build/s04/ppe-memory-1791750201180159000/gate.json \
  --ownership hardware/spinal/build/s04/ownership-1791750984439340000/gate.json \
  --ownership-formal hardware/spinal/build/s04/formal/ownership-steps12-1791750996844599000/validation.json \
  --l1-formal hardware/spinal/build/s04/formal/l1-4mshrs-steps8-1791738811978403000/validation.json \
  --ape-lsq-formal hardware/spinal/build/s04/formal/ape-lsq-steps8-1791744415336260000/validation.json \
  --design-points workloads/s04/PPE-DESIGN-POINTS.json \
  --ape-trace-design-points workloads/evidence/S04-APE-APPLICATION-TRACE-DESIGN-POINTS.json \
  --ape-cached-application workloads/evidence/S04-APE-CACHED-APPLICATION-CURRENT.json \
  --ape-tool-cached workloads/evidence/S04-APE-TOOL-CACHED-EMPTY-COLD-CURRENT.json \
  --ape-tool-cached workloads/evidence/S04-APE-TOOL-CACHED-EMPTY-INCREMENTAL-CURRENT.json \
  --ape-tool-cached workloads/evidence/S04-APE-TOOL-CACHED-SCALARS-COLD-CURRENT.json \
  --ape-tool-cached workloads/evidence/S04-APE-TOOL-CACHED-SCALARS-CURRENT.json \
  --ape-tool-cached workloads/evidence/S04-APE-TOOL-CACHED-UNICODE-COLD-CURRENT.json \
  --ape-tool-cached workloads/evidence/S04-APE-TOOL-CACHED-UNICODE-INCREMENTAL-CURRENT.json \
  --ape-heap-exhaustion workloads/evidence/S04-APE-HEAP-EXHAUSTION-EMPTY-COLD.json \
  --ape-heap-exhaustion workloads/evidence/S04-APE-HEAP-EXHAUSTION-EMPTY-INCREMENTAL.json \
  --ape-heap-exhaustion workloads/evidence/S04-APE-HEAP-EXHAUSTION-SCALARS-COLD.json \
  --ape-heap-exhaustion workloads/evidence/S04-APE-HEAP-EXHAUSTION-SCALARS-INCREMENTAL.json \
  --ape-heap-exhaustion workloads/evidence/S04-APE-HEAP-EXHAUSTION-UNICODE-COLD.json \
  --ape-heap-exhaustion workloads/evidence/S04-APE-HEAP-EXHAUSTION-UNICODE-INCREMENTAL.json \
  --output workloads/evidence/S04-PPE-INSTRUCTION-CURRENT-CHECKPOINT.json
```

The six Tree-sitter cached reports in this checkpoint were regenerated from
`workloads/results/s04-treesitter-current-20261012-issue5-refresh/` after the
dual-engine launch-race test changed the source manifest. Reproduce the target
reference and direct APE RTL run using a fresh output directory with:

```sh
python3 workloads/target/treesitter/execute/verify_rtl.py --case empty --case scalars --case unicode --kind cold_old --kind incremental --output workloads/results/s04-treesitter-current-20261012-issue5-refresh-reproduce
```

The source-bound completion audit now verifies each original criterion:
actual APE/PPE execution and independent oracle checks; ordering, atomics,
forwarding, replay and precise-fault regressions; full queue/cache/fabric
occupancy with conflict, reorder, reset and drain witnesses; bounded formal
checks under explicit assumptions; and matched-input counter/design-point
reports with the external service model stated explicitly. The remaining items
are claim boundaries rather than unfulfilled S04 acceptance criteria: the
ownership contract is exclusive clean/invalidate handoff rather than general
coherence; proofs are bounded/per-module rather than unbounded full-chip proofs;
resource observations are not worst-case bounds; and external line timing is
behavioral, not measured HBM/LPDDR performance. No hardware PMU result is
claimed. The issue will be closed only after the implementation/evidence commit
is pushed and these completion records are attached to the issue.

The refreshed [APE instruction/cache increment](../evidence/S04-INSTRUCTION-INCREMENT.json)
uses the current source-bound [48-image APE memory gate](../../hardware/spinal/build/s04/ape-memory-1791747405365193000/gate.json),
the replay-retirement race fix, and its [8-step/31-assertion bounded LSQ proof](../../hardware/spinal/build/s04/formal/ape-lsq-steps8-1791743951548405000/validation.json).
It also binds one real Tree-sitter case through APE LSQ plus I/D-L1 RTL:
[Spike-matched parser trace, 4,842/4,842 lower-line completions, and byte-exact
16 MiB final RAM](../evidence/S04-APE-TOOL-CACHED-INCREMENT.json). The cache
case is a Spike-derived parser-entry warm start that skips only the redundant
BSS-clear loop; cold startup is separately checked by direct APE RTL.

This does not refresh or replace the broader PPE execution, shared ownership,
design-point, or all-application acceptance gates below. Those remain separate
partial evidence and must be rerun/rebound against the current APE source before
Issue #5 closure. The checkpoint intentionally leaves `S04_complete: false`.

### Current-source dual-engine and formal refresh (2026-10-12)

The refreshed source-current ownership gate is
`hardware/spinal/build/s04/ownership-1791747469703725000/gate.json`. It passes
the controller protocol test and actual APE/PPE shared-memory RTL program with
75/75 line requests completed, four maximum outstanding lower transactions,
52 backpressure cycles and three response reorderings. The integrated run
rechecks 32 PPE application groups, 608 architectural accesses, the independent
2 KiB output oracle, an out-of-permission no-mutation fault, APE byte alias and
set-conflict refills, two quiescent resets/readbacks, bilateral ownership
handoffs, fences/barrier, and sequential APE/PPE atomic visibility. This is
exclusive sequential ownership, not general coherence or simultaneous
cross-engine atomic arbitration.

Fresh bounded proofs are
`hardware/spinal/build/s04/formal/ape-lsq-steps8-1791744415336260000/validation.json`
(31 checks/step plus allocation, multi-lease and replay reachability) and
`hardware/spinal/build/s04/formal/ownership-steps12-1791747486623044000/validation.json`
(7 checks/step plus request, outstanding, completion and stale-reply
reachability). The updated partial checkpoint is
[`S04-PPE-INSTRUCTION-INCREMENT.json`](../evidence/S04-PPE-INSTRUCTION-INCREMENT.json).
The refreshed current-source checkpoint above includes replacement APE
cached-application and Tree-sitter records. Earlier reports remain preserved
separately. S04 remains incomplete.

The ownership and LSQ proof drivers now compile with the pinned sbt wrapper and
invoke the generated test main directly from sbt's exported test classpath. This
avoids sbt's background `runMain` classpath copy, which failed under the full
filesystem. The generated RTL, toolchain identity and source hashes remain in
the normal gate records; no prior S03 or accepted S04 evidence is deleted.

The latest verified increment exercises a system-level APE/PPE shared-memory
tile, bilateral clean/invalidate ownership handoffs, clean-and-ack ordinary-RAM
fences, and bounded internal-invariant proofs for the actual generated L1 and
APE LSQ. The
original component and single-engine increments below are preserved historical
checkpoints, not current-source proof after subsequent source changes.

The latest source-bound ownership run is
`hardware/spinal/build/s04/ownership-1791740838300260000/gate.json`. Its actual
dual-engine RTL program checks PPE AMOADD 43→48, clean/invalidate handoffs,
APE's load of 48 and AMOADD old value 48, and final clean value 51. It preserves
lower-interface backpressure (52 cycles), four outstanding lower requests, and
three response reorderings. Four APE loads hit distinct lines mapping to
D-L1 set 0; their retirement and refills are checked. An APE byte-store/load
alias returns 42, and clean preserves the dirty word value 10752. The first
APE→PPE handoff is requested with live traffic and waits for 325 aggregate drain
cycles across the ownership transitions. After a quiescent reset/readback, the
combined tile first faults an out-of-range PPE output store without changing
the output bytes, then runs the source-bound PPE delimiter application: 32
groups, 608 architectural accesses, 34 lower-line requests for the successful
application, followed by a PPE→APE clean
handoff and exact 2 KiB output match. Before the valid groups, the same task is
run with its output outside the launch permission range: the fault is returned,
one store attempt is rejected, and all 256 output bytes remain unchanged.
A second reset is asserted only after
that clean handoff and all accepted lines drain; a relaunch reads the original
shared word back from the source-bound PPE memory image. The reported 75/75
line accounting passes. The measured output SHA-256 matches the independent
PPE oracle. This is host-sequenced execution under exclusive
ownership, not simultaneous cross-engine atomic arbitration or general
coherence. The refreshed bounded line-ledger proof is
`hardware/spinal/build/s04/formal/ownership-steps12-1791740861002479000/validation.json`:
12 steps, seven assertions per step, with active request/reply traffic, arbitrary
lower backpressure, and delayed/reordered/stale/malformed responses. Handoffs
and maintenance responses are excluded from this proof and remain covered by
the separate ownership-state proof and integrated simulation. Separate bounded
reachability queries require accepted traffic, at least two simultaneous lower
transactions, a completed response, and a rejected stale response; the
checkpoint refuses a line-traffic proof without those witnesses.

An additional source-bound application trace study is recorded in
[`S04-APE-APPLICATION-TRACE-DESIGN-POINTS.json`](../evidence/S04-APE-APPLICATION-TRACE-DESIGN-POINTS.json).
It starts from the actual APE RTL `repo_source_edit` memory trace (2,776 events),
whose architectural trace and byte-exact final memory are checked by the current
144-run Spike/application gate. That identical trace is replayed through actual
L1 RTL at 8/2, 16/4 and 32/8 set/MSHR points; each clean returns a final memory
identical to the application result.

| Sets / MSHRs | Replay RTL cycles | Hits / misses | Refills | Writebacks |
| ---: | ---: | ---: | ---: | ---: |
| 8 / 2 | 23,083 | 1,242 / 1,534 | 1,534 | 160 |
| 16 / 4 | 22,357 | 1,295 / 1,481 | 1,481 | 140 |
| 32 / 8 | 9,719 | 2,523 / 253 | 253 | 128 |

This trace replay has since been complemented by full execution of the same
`repo_source_edit` application inside the actual APE+LSQ+D-L1 and APE+LSQ+I/D-L1
RTL at 8/2, 16/4 and 32/8 points. All six runs match the direct APE retirement
and architectural memory-event sequences and the byte-exact final memory after
clean. See [`S04-APE-CACHED-APPLICATION.json`](../evidence/S04-APE-CACHED-APPLICATION.json).
Integrated RTL cycles and line traffic differ across these configurations, but
the randomized host line service is behavioral, not calibrated DRAM/HBM/LPDDR
latency or bandwidth. One application across three parameter points does not
support a general cache recommendation or silicon performance claim.

| Path | Sets / MSHRs | Integrated RTL cycles | Lower line requests | I-cache misses / fetch words | Peak D-cache / fabric outstanding | Response reorderings |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| D-L1 | 8 / 2 | 38,114 | 1,710 | — | 2 / 0 | 16 |
| D-L1 | 16 / 4 | 37,488 | 1,641 | — | 3 / 0 | 10 |
| D-L1 | 32 / 8 | 26,319 | 399 | — | 3 / 0 | 5 |
| I/D-L1 | 8 / 2 | 49,249 | 1,835 | 127 / 8,738 | 2 / 3 | 22 |
| I/D-L1 | 16 / 4 | 49,005 | 1,734 | 93 / 8,742 | 2 / 3 | 10 |
| I/D-L1 | 32 / 8 | 42,634 | 448 | 47 / 8,704 | 2 / 2 | 7 |

The I/D-L1 runs fetch actual application instructions through I-L1 and the
shared fabric; the obsolete programming port is poisoned. D-only runs retain
program RAM as a comparison. Both execute actual APE ROB/LSQ and D-L1, and PPE
is not part of these application runs. The line service is a deterministic-
seeded behavioral model with ready stalls and response reordering, not an RTL
lower cache/controller.

## Implemented and executed

### Earlier focused PPE application baseline (2026-10-12)

After the PPE ISA/core edits in the active worktree, the actual
`PpeCachedDataTile` RTL was re-elaborated and simulated for the 32-group
delimiter task through both I-L1 and D-L1 using the preserved source-bound
fixture. All 32 groups completed; 1,056 instructions retired, 352 loads and
256 stores were observed, 44/44 external line requests drained, and the
byte-exact full output memory matched the independent oracle
(`75636dc4…f1cfbd7`). The run used 32 sets and 8 MSHRs, with a behavioral
variable-latency/backpressured line service. It does not cover the full PPE
ISA/cache matrix, concurrent miss/reorder or full-MSHR behavior, scratchpad
stress, or calibrated external-memory bandwidth. The source/input-bound run
record is [`S04-PPE-CURRENT-SOURCE-APPLICATION.json`](../evidence/S04-PPE-CURRENT-SOURCE-APPLICATION.json);
it leaves `S04_complete: false`.

### Expanded source-current PPE application matrix (2026-10-12)

The latest source-bound PPE gate is
[`ppe-memory-1791750201180159000/gate.json`](../../hardware/spinal/build/s04/ppe-memory-1791750201180159000/gate.json).
It executes both the delimiter prefilter and the 256-element signed-int32
residual+bias+ReLU epilogue as 32-group applications through actual I-L1/D-L1.
For the vector workload, 608 loads and 256 stores complete; the full 4 KiB
memory image matches an independent element-wise oracle and preserves canaries.
At 32 sets/8 MSHRs, all 134 lower-line requests drain. This same application
pair is rerun at each matched I/D-L1 point (8/2, 16/4 and 32/8), with identical
input and output hashes. The six-point PPE suite also completes 316 exact ISA
comparisons per point and reaches the configured MSHR capacity. The timing
service remains behavioral, and this evidence is not a physical bandwidth or
speedup claim.

The combined current checkpoint now also binds six actual APE heap-exhaustion
runs—empty, scalar-heavy and Unicode inputs, each cold-old and incremental—at
the 128-byte test heap. Each returns clean ENOMEM, matches Spike's architectural
trace and full final memory, leaves the output payload untouched, and drains
its accepted line traffic. These selected-case fault-path tests do not prove a
formal worst-case resource bound.

- A real nonblocking write-back/write-allocate L1, byte stores, per-index MSHR
  ownership, tagged/reordered refills and writebacks, maintenance and counters.
- A distinct D-L1 64-bit atomic-add transaction updates a cache word
  indivisibly and returns the prior value. APE now decodes RV64A AMOADD.D and
  carries it through the ROB, LSQ, and D-L1; three ordered AMOs return 10, 11,
  and 13, a following load sees 16, and clean publishes 16 to the modeled
  backing store. Unsupported AMOADD.W traps before cache acceptance. The
  APE RV64A AMOADD.D and the PPE scalar AMOADD extension now exercise their
  respective memory paths. The integrated ownership test sequences the PPE
  atomic (43→48), clean/invalidate handoff, APE observation, and APE atomic
  (48→51) through the combined RTL hierarchy. This validates visibility across
  *exclusive sequential ownership epochs*, not concurrent cross-engine atomic
  arbitration or hardware coherence. PPE AMOADD is specified in
  [PPE-S04-ATOMIC-EXTENSION.md](../../hardware/spinal/spec/PPE-S04-ATOMIC-EXTENSION.md).
  Concurrent cross-engine atomic serialization remains open.
- APE ROB-backed address/store buffering with eight independent transport
  leases, head-authorized stores, youngest-older-store byte forwarding, partial
  merge, speculative loads past unresolved ordinary-RAM stores, and precise
  replay after a later-resolved overlapping store; device/atomic/fence
  boundaries remain conservative.
- Actual selected APE ROB8/P48/W1 execution through the LSQ and data L1.
  Squashed read leases drain without updating a reused architectural owner.
- Independent byte/register retirement checks, store authorization checks at
  cache acceptance, whole backing-memory checks after clean, and pinned external
  Spike comparison of **RTL-observed** architectural events.

The current integrated profile uses physical addresses and exclusive ownership
of a whole-line-aligned cacheable RAM region. In this profile, APE `FENCE` and
PPE `FENCE`/`BARRIER` wait for a clean-only D-L1 maintenance acknowledgement;
tests check that accepted stores are visible in modeled backing memory before
the fence retires. This does not invalidate I-cache lines or provide concurrent
cross-engine coherence. Sequential atomic visibility is tested only because
ownership transfer drains and cleans the old owner's cache before admitting the
new owner; simultaneous atomic requests from both engines are not supported or
claimed. It does not claim hardware-coherent shared virtual memory. The APE cached wrapper now has an optional
uncached device aperture and external request/response boundary. A device access
waits for older APE memory effects, cleans D-L1, then issues one serialized
request; it never enters the line cache. Device apertures are 64-bit-word
aligned, and responses must match both transaction ID and epoch. A malformed
identity is held off rather than delivered to the LSQ. I/O semantics and
latency are represented by the testbench service, not a hardware peripheral.
The combined tile exposes separate APE and PPE device request/response ports.
The PPE I/D wrapper cleans D-L1, serializes configured device transactions
outside the line cache, and rejects response-ID/epoch mismatches. Current PPE
I/D RTL evidence covers a cacheable store followed by device store/load traffic
and checks that the cached store is visible before each device request. Device
semantics and latency are still supplied by a behavioral testbench service;
shared atomics and independent system-wide I/O-ordering litmus tests remain
open. `forbiddenRegions` remains an assertion-only negative guard for reserved
APE apertures.

## Reproducible gates

From `hardware/spinal`, using Python 3.10 or newer and the existing pinned local
Scala/Verilator/LLVM/Spike dependencies:

```sh
python3 tools/verify_memory_l1.py
python3 tools/verify_ape_memory.py --instructions
python3 tools/verify_ppe_memory.py --instructions
python3 tools/verify_ownership.py --ppe-application-dir build/s04/ppe-memory-<ppe-run-id>/cached/delimiter_256_g0
python3 formal/verify_ownership_formal.py --gate build/s04/ownership-<run-id>/gate.json --steps 12
python3 formal/verify_l1_formal.py --gate build/s04/l1-<run-id>/gate.json --steps 8
python3 formal/verify_ape_lsq_formal.py --steps 8
```

Both drivers create fresh, timestamped directories under `build/s04`. They hash
sources, tools and actual generated RTL; the APE driver rebuilds program inputs,
runs real RTL, and compares observed traces against pinned upstream Spike.
The APE gate preserves a source archive and reruns both standard and recovery
tests for the accepted S03 profile. These tests do not rerun the full S03 tools
or physical-design studies.

Initial passing runs (2026-10-10; preserved with their exact source identities):

| Gate | Local evidence | Result and scope |
| --- | --- | --- |
| Nonblocking L1 | `hardware/spinal/build/s04/l1-1791620334992468000/gate.json` | 3 configurations; 9,344 accepted/completed word requests |
| APE LSQ/I-D L1 (source-current) | `hardware/spinal/build/s04/ape-memory-1791622652960313000/gate.json` | 58 cached executions, 58 selected-profile direct-memory regression invocations; 220 exact Spike matches and 8 explicit profile differences; source-bound APE I/D path |
| PPE I/D hierarchy (source-current) | `hardware/spinal/build/s04/ppe-memory-1791623226325837000/gate.json` | Historical pre-expansion gate: 244 I/D comparisons, 244 data-only regressions, 224 serial regressions |
| APE/PPE ownership integration (source-current) | `hardware/spinal/build/s04/ownership-1791623328783950000/gate.json` | Actual controller RTL and dual-engine tile; four distinct APE cold-read lines stress concurrent MSHRs; 2 handoffs, values 42→43→43; 17/17 line completions, max 4 outstanding, observed response reorders and backpressure |
| Ownership bounded formal (rebound) | `hardware/spinal/build/s04/formal/ownership-steps12-1791623348970956000/validation.json` | 12-step ownership-state safety proof tied to current integration RTL; seven assertions per step; line traffic is constrained inactive |
| Generated L1 bounded formal | `hardware/spinal/build/s04/formal/l1-4mshrs-steps8-1791621860419000000/validation.json` | Actual 4-MSHR generated RTL; 8-step bounded proof of 23 embedded assertions per step with unconstrained external inputs; no functional-refinement or unbounded claim |
| APE LSQ bounded formal | `hardware/spinal/build/s04/formal/ape-lsq-steps8-1791622358926597000/validation.json` | Actual ROB8/P48, 8-lease queue top; 8-step proof of 31 internal assertions/step; assumes row identity slot equals physical ROB index as wired by ApeCore; other inputs unconstrained |
| APE device-aperture negative control | `hardware/spinal/build/s04/device-region-negative/device-region-negative-control.json` | Actual APE RTL request overlapping configured `[0x1f000,0x20000)` is rejected by the cache-edge assertion; current-source APE gate also passes |
| APE uncached device path | `hardware/spinal/build/s04/ape-device/validation.json` | Focused simulation passed in both D-only and I/D profiles (6 requests); this run predates the final source-bound integration gate and is retained as diagnostic evidence, not current-source proof. Behavioral device model, not a hardware peripheral |

Latest refreshed source-bound gates (2026-10-12):

| Gate | Local evidence | Result and scope |
| --- | --- | --- |
| Nonblocking L1 + atomic-add primitive | `hardware/spinal/build/s04/l1-1791728490584960000/gate.json` | Three configurations pass; each records four committed atomic adds and rejects a partial-width atomic without changing memory |
| APE I/D L1, publication and device path | `hardware/spinal/build/s04/ape-memory-1791728574078536000/gate.json` | 228 comparisons: 220 exact Spike matches and 8 explicit profile differences; source-current after the cache transaction interface change |
| PPE I/D hierarchy and device path | `hardware/spinal/build/s04/ppe-memory-1791737020208626000/gate.json` | Current-source 16/4 gate: 252 exact I/D comparisons and 252 D-only regressions, plus 224 serial comparisons; full 4-MSHR/line witness and complete PPE delimiter task oracle |
| APE/PPE ownership + PPE device integration | `hardware/spinal/build/s04/ownership-1791728777211901000/gate.json` | Gate requires PPE device counts, backpressure, clean-before-I/O and returned data; two handoffs, 18/18 line completions, three concurrent lower transactions, reordered responses and backpressure |
| Bounded ownership proof | `hardware/spinal/build/s04/formal/ownership-steps12-1791728791855985000/validation.json` | 12-step bounded proof, seven assertion checks per step; rebound to the latest ownership gate |
| Generated L1 bounded formal | `hardware/spinal/build/s04/formal/l1-4mshrs-steps8-1791738811978403000/validation.json` | 8-step bounded proof of 23 generated-L1 assertions plus lower miss, multiple outstanding, refill and stale-reply reachability witnesses; not functional refinement or unbounded proof |
| APE LSQ bounded formal | `hardware/spinal/build/s04/formal/ape-lsq-steps8-1791728804388949000/validation.json` | 8-step bounded proof of 31 LSQ assertions; regenerated after the cache request interface change |
| Matched PPE cache design points | `workloads/s04/PPE-DESIGN-POINTS.json` | Six same-source/tool gates: D-L1 and I/D-L1 at 8/2, 16/4, 32/8; 316 exact comparisons per point, full 2/4/8 MSHR and line occupancy; I/D points bind the same 32-group delimiter task and 32-group vector epilogue |
| APE application-derived L1 design points | `workloads/evidence/S04-APE-APPLICATION-TRACE-DESIGN-POINTS.json` | One 2,776-event actual APE application trace replayed through three isolated L1 RTL points; identical final memory |
| APE cache-integrated application matrix | `workloads/evidence/S04-APE-CACHED-APPLICATION.json` | 40 source-bound runs across 12 real diff-workload input fixtures; full 3×3 set×MSHR factorial in D-L1 and I/D-L1 for `repo_source_edit`, plus D-L1/I-D-L1 16/4 regressions for the other 11 inputs; cache counters and every retirement trace and cleaned final memory match direct APE |
| Current partial checkpoint | `workloads/evidence/S04-PPE-INSTRUCTION-INCREMENT.json` | Source-bound APE/PPE, ownership, formal, generated PPE and application-derived APE cache evidence; S04 remains incomplete |

The current matched PPE cache matrix uses six gates with one source/tool
identity and byte-identical inputs within each execution mode. Each point
passes 316 architectural comparisons and reaches its configured 2/4/8 MSHR and
lower-line occupancy. In addition to ISA and protocol fixtures, every I/D-L1
point executes two full 32-group workloads through actual PPE RTL, I-L1, D-L1
and the shared line fabric:

- The delimiter-candidate task processes 256 bytes. All groups complete; 1,056
  instructions retire, with 352 loads and 256 stores. Its independent byte
  oracle and canaries match. It is a delimiter prefilter, not a JSON parser.
- A HATS-authored integer vector inference epilogue applies bias/residual add
  followed by ReLU to 256 signed 32-bit elements. Each group has 16 retired
  instructions, 27 lane events and 15 global memory words, checked against an
  independent PPE-ISA reference and final-memory oracle. This is a focused
  kernel, not a port of an external AI framework or a complete inference
  runtime.

Both applications execute groups sequentially (`max_outstanding=1`); separate
matrix fixtures provide concurrent-miss/reorder witnesses. The expanded suite
is broader, but it does not satisfy the roadmap's representative multi-workload
capacity/bandwidth study. External line service remains behaviorally modeled,
not HBM/LPDDR timing or measured bandwidth.

Latest APE atomic refresh (2026-10-11):

| Gate | Local evidence | Result and scope |
| --- | --- | --- |
| APE I/D hierarchy + AMOADD.D | `hardware/spinal/build/s04/ape-memory-1791729375675611000/gate.json` | 220 exact Spike matches, 8 checked profile differences, and actual AMOADD.D → LSQ → D-L1 RTL execution. Three atomic operations return the prior values (10, 11, 13), a load observes 16, clean writes back 16, and unsupported AMOADD.W is rejected before cache acceptance. Backing memory is modeled; PPE/cross-engine atomicity is not covered. |
| L1 component replay | `hardware/spinal/build/s04/l1-1791729438617336000/gate.json` | Source-bound 3-configuration L1 matrix, refreshed after the APE atomic interface change. |
| Partial APE checkpoint | `workloads/evidence/S04-INSTRUCTION-INCREMENT.json` | Binds the refreshed L1 and APE gates and includes the atomic result; does not include current PPE, ownership, or formal gates, so it is not a whole-S04 checkpoint. |

The broader current-source evidence bundle, including the PPE I/D hierarchy,
both APE and PPE atomic instruction tests, dual-engine ownership, three bounded
formal runs, generated PPE design points, and the APE application-derived L1
trace sweep, is
`workloads/evidence/S04-PPE-INSTRUCTION-INCREMENT.json`. It also includes the
APE AMOADD.D and PPE AMOADD RTL results. It is still explicitly partial:
concurrent cross-engine atomic arbitration, broader reset/drain stress, and
representative application-trace sizing remain open. APE dependence replay is
now implemented and covered by the overlapping ordinary-RAM store/load test,
but adversarial replay/reset coverage remains open.

The expanded [APE/PPE/ownership checkpoint](../evidence/S04-PPE-INSTRUCTION-INCREMENT.json)
binds the fresh APE, PPE, ownership, bounded-proof and matched-input design-point
runs together, including the sequential cross-engine atomic handoff witness.
These remain partial S04 results, not issue completion.

### 2026-10-12 replay refresh

The current replay-enabled APE LSQ and paired I/D hierarchy pass 58 actual RTL
executions, including the unresolved-store overlap/replay witness. The combined
APE/PPE top now also demonstrates the specified safe warm-reset boundary:
finish clean/drain, reset the system, relaunch APE, and read the persisted final
shared value (51) back through the RTL cache. This does not claim safe reset
with live external transactions; the memory service must first be quiescent.
The
source-bound APE gate records 220 exact Spike matches and eight documented
profile differences. Current PPE and dual-engine integration gates also pass;
all three correctly retain `S04_complete: false` because remaining system
coverage is not yet satisfied.

| Gate | Evidence | Result and scope |
| --- | --- | --- |
| APE LSQ/I-D L1 + selected S03 regressions | `hardware/spinal/build/s04/ape-memory-1791735383410473000/gate.json` | 58 actual RTL executions; 220 exact Spike comparisons and 8 documented profile differences; overlapping-store replay witness; partial integration |
| Integrated APE application design points | `hardware/spinal/build/s04/cached-app-1791739708920660000/gate.json` | 28 runs across all 12 S03 diff input fixtures; six representative D-L1/I-D-L1 design points plus 16/4 dual-cache-mode regression for the remaining 11; all architectural traces and cleaned memories match direct APE |
| PPE I/D hierarchy | `hardware/spinal/build/s04/ppe-memory-1791737896156617000/gate.json` | Current-source 32/8 gate: 316 I/D comparisons, 316 D-only regressions, 288 serial regressions; full 8-MSHR occupancy, delimiter-task oracle and vector-epilogue oracle |
| APE/PPE ownership and dual-engine top | `hardware/spinal/build/s04/ownership-1791740838300260000/gate.json` | 75/75 line completions, four outstanding peak, 52 backpressure cycles and 3 reorders; APE set conflicts/byte alias; live-traffic drain; one integrated PPE permission-fault/no-output-mutation case followed by the full 32-group application, 608 accesses and exact 2 KiB post-clean oracle match; two quiescent resets and post-PPE reset readback; host-sequenced exclusive ownership |
| Matched PPE hierarchy matrix | `workloads/s04/PPE-DESIGN-POINTS.json` | Six same-source/tool points across D-L1 and I/D-L1 at 8/2, 16/4 and 32/8; 316 exact comparisons each; I/D points execute both 32-group task oracles |
| Bounded generated L1 safety | `hardware/spinal/build/s04/formal/l1-4mshrs-steps8-1791738811978403000/validation.json` | 8-step proof, 23 internal assertion checks/step; reachability witnesses for lower miss, two outstanding lines, refill and stale-reply rejection; external data correctness is not formally proven |
| Bounded APE LSQ safety | `hardware/spinal/build/s04/formal/ape-lsq-steps8-1791739008413055000/validation.json` | 8-step proof, 31 internal assertion checks/step; reachability witnesses for lease allocation, two outstanding leases and dependence replay under fixed ROB row-slot identity |
| Bounded ownership-state safety | `hardware/spinal/build/s04/formal/ownership-steps12-1791737298170552000/validation.json` | 12-step handoff-state proof, 7 checks/step; line traffic constrained inactive |
| Bounded ownership line-ledger safety | `hardware/spinal/build/s04/formal/ownership-steps12-1791740861002479000/validation.json` | 12-step proof, 7 checks/step; active lower request/reply traffic with backpressure and reordered/stale/malformed replies; four non-vacuity witnesses; handoffs excluded |

The current-source device gate initially exposed a testbench assertion scoped
to the wrong profile: the D-only case was required to observe the epoch-mismatch
rejection that is intentionally injected only in I/D mode. The assertion now
checks each profile's own malformed-response case and separately requires both
at the end. This was a verification-harness correction; no RTL assertion was
weakened. The full APE gate now passes. Current-source PPE and ownership gates
also pass and are recorded above.

The latest combined partial checkpoint, including PPE device transactions and
the matched D-cache design-point report, is
`workloads/evidence/S04-APE-PPE-OWNERSHIP-INCREMENT.json`.

The ownership gate synthesizes both engines and the combined tile, then runs
actual APE and PPE programs through their RTL caches. The APE task cold-reads
four distinct data lines before its shared store; the modeled lower service
deliberately completes later requests first. The latest integrated run observes
three simultaneous lower transactions, response reordering, backpressure, and
exact accepted/completed accounting. Both private I/D-cache
pairs are clean-invalidated before ownership changes. The external line service
models memory acceptance and variable latency; this is not DRAM/HBM timing.
Controller simulation covers held results, failed maintenance, both handoff
directions, rejection of delayed prior-generation responses, and the combined
tile's clean/quiescent warm-reset and persisted-value readback. The atomic
witness is sequential across exclusive ownership epochs; this is not general
coherence, concurrent cross-engine atomic arbitration, or full S04 acceptance.

The L1 configurations are `(sets, line bytes, MSHRs) = (4,16,2), (8,32,4),
(16,64,8)`. Each reaches full MSHR occupancy and exercises request/response stalls,
reordered responses, hits under misses, four request faults, eight maintenance
operations, one failed clean and a clean/quiescent reset. Wrong-generation and
wrong-phase responses are rejected, and counters match public-port events.

APE tests require observed witnesses, not just named fixtures: eight occupied
LSQ leases, four active cache transactions, younger load completion, full and
partial byte forwarding, youngest-store priority, unknown-store stalls, a local
fence interlock, two discarded late wrong-path responses (including a fault),
and precise older faults. The directed APE FENCE case additionally checks that
its dirty line is visible below D-L1 at the fence's retirement point. PPE cached
cases exercise both FENCE and BARRIER and check the same property for all
accepted store bytes. Transaction counts reconcile allocation, local forwarding
and cache acceptance. Stores are checked when accepted, not only by their final
bytes.

Across the cached and legacy paths, 164 Spike comparisons match exactly.
Six runs retain two explicitly reviewed S03 profile differences: unsupported
FENCE.I and misaligned launch policy. The cached path accounts for 56 exact
matches and two such differences; the direct path has 108 exact matches and four
differences. No mismatch is silently skipped.

Report-logic negative controls (not hardware evidence), from the repository root:

```sh
python3 -m unittest discover -s workloads/s04 -p 'test_*.py' -v
python3 workloads/s04/checkpoint.py \
  --l1 hardware/spinal/build/s04/l1-1791616149851589000/gate.json \
  --ape hardware/spinal/build/s04/ape-memory-1791616762654285000/gate.json
```

The checkpoint rehashes evidence and recomputes trace comparison decisions before
writing [the partial increment record](../evidence/S04-MEMORY-INCREMENT.json).
It cannot report S04 completion.

The current combined APE/PPE/ownership checkpoint is reproduced from the repo
root with:

```sh
python3 workloads/s04/checkpoint.py --instructions \
  --l1 hardware/spinal/build/s04/l1-1791728490584960000/gate.json \
  --ape hardware/spinal/build/s04/ape-memory-1791735383410473000/gate.json \
  --ppe hardware/spinal/build/s04/ppe-memory-1791737896156617000/gate.json \
  --ownership hardware/spinal/build/s04/ownership-1791740838300260000/gate.json \
  --ownership-formal hardware/spinal/build/s04/formal/ownership-steps12-1791740861002479000/validation.json \
  --l1-formal hardware/spinal/build/s04/formal/l1-4mshrs-steps8-1791738811978403000/validation.json \
  --ape-lsq-formal hardware/spinal/build/s04/formal/ape-lsq-steps8-1791739008413055000/validation.json \
  --design-points workloads/s04/PPE-DESIGN-POINTS.json \
  --ape-trace-design-points workloads/evidence/S04-APE-APPLICATION-TRACE-DESIGN-POINTS.json \
  --ape-cached-application workloads/evidence/S04-APE-CACHED-APPLICATION.json
```

The latest point also includes one upstream Tree-sitter case executed by the
actual APE through its LSQ and I/D-L1 RTL, checked against the direct APE/Spike
parser-phase architectural trace and the byte-exact full 16 MiB final RAM:

```sh
python3 workloads/s04/checkpoint.py --instructions \
  --l1 hardware/spinal/build/s04/l1-1791728490584960000/gate.json \
  --ape hardware/spinal/build/s04/ape-memory-1791743834115814000/gate.json \
  --ppe hardware/spinal/build/s04/ppe-memory-1791737896156617000/gate.json \
  --ownership hardware/spinal/build/s04/ownership-1791740838300260000/gate.json \
  --ownership-formal hardware/spinal/build/s04/formal/ownership-steps12-1791740861002479000/validation.json \
  --l1-formal hardware/spinal/build/s04/formal/l1-4mshrs-steps8-1791738811978403000/validation.json \
  --ape-lsq-formal hardware/spinal/build/s04/formal/ape-lsq-steps8-1791739008413055000/validation.json \
  --design-points workloads/s04/PPE-DESIGN-POINTS.json \
  --ape-trace-design-points workloads/evidence/S04-APE-APPLICATION-TRACE-DESIGN-POINTS.json \
  --ape-cached-application workloads/evidence/S04-APE-CACHED-APPLICATION.json \
  --ape-tool-cached workloads/evidence/S04-APE-TOOL-CACHED-INCREMENT.json
```

The Tree-sitter cache case uses a Spike-derived parser-entry RAM image and skips
only the already-validated BSS-clear loop; startup stack setup and parser code
execute on APE RTL. Its cold-start path remains covered by the separate direct
APE/Spike run. This is one case, not the complete upstream tool matrix or S04
closure. See [`S04-APE-TOOL-CACHED-INCREMENT.json`](../evidence/S04-APE-TOOL-CACHED-INCREMENT.json).

To regenerate the cache-integrated APE application evidence from its bound
144-run direct APE/Spike gate, run `python3 tools/verify_ape_cached_application.py`
from `hardware/spinal` (SpinalSim/Verilator required).

## Regression and bring-up notes

## Matched PPE cache design points

The 316-comparison PPE cached matrix was rerun at three D-L1 and three I/D-L1
configurations. Inputs match byte-for-byte within each path; the paths use
separate manifests because instruction-cache mode changes clock contracts. Each
point matches all 316 independent architectural comparisons and reaches its
configured MSHR and lower-line occupancy. The I/D-L1 points include both the
delimiter-prefilter application and HATS-authored vector inference epilogue:

| Path | Sets × 32-byte lines | MSHRs | Aggregate RTL cycles | Global words | D-L1 hits / misses | Writebacks | Peak MSHRs / lower lines |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| D-L1 | 8 × 32 B | 2 | 82,607 | 796 | 416 / 380 | 166 | 2 / 2 |
| D-L1 | 16 × 32 B | 4 | 84,867 | 796 | 416 / 380 | 166 | 4 / 4 |
| D-L1 | 32 × 32 B | 8 | 89,227 | 796 | 416 / 380 | 166 | 8 / 8 |
| I/D-L1 | 8 × 32 B | 2 | 117,327 | 796 | 416 / 380 | 166 | 2 / 2 |
| I/D-L1 | 16 × 32 B | 4 | 121,692 | 796 | 416 / 380 | 166 | 4 / 4 |
| I/D-L1 | 32 × 32 B | 8 | 129,977 | 796 | 416 / 380 | 166 | 8 / 8 |

These results do not show a monotonic cycle benefit from increasing MSHRs:
the same workload produced the same cache hit/miss and line traffic counts,
while total modeled RTL cycles increased across these three points. Set count
and MSHR count were changed together, so this experiment cannot attribute a
causal effect to either parameter independently. External line service is a
behavioral testbench model; these cycles are not DRAM/HBM/LPDDR latency,
achieved bandwidth, silicon frequency, or a speedup claim. Source-bound gates
and the normalized comparison report are recorded in
[PPE-DESIGN-POINTS.json](PPE-DESIGN-POINTS.json).

Reproduce the six current-source gates and matched-input comparison from the
repository root (Python 3.10+):

```sh
python3 hardware/spinal/tools/verify_ppe_memory.py --sets 8 --mshrs 2
python3 hardware/spinal/tools/verify_ppe_memory.py --sets 16 --mshrs 4
python3 hardware/spinal/tools/verify_ppe_memory.py --sets 32 --mshrs 8
python3 workloads/s04/compare_ppe_design_points.py \
  <D-L1-8x2-gate> <D-L1-16x4-gate> <D-L1-32x8-gate> \
  <I-D-L1-8x2-gate> <I-D-L1-16x4-gate> <I-D-L1-32x8-gate>
```

The immutable S03 baseline is commit
`3b2d7e977a8b47386421830126ce32a70ffa8978`; its closure record and preserved source
archive are unchanged. Current APE source extends that baseline; earlier S03
timing/tool reports are not relabeled as measurements of this cache-equipped RTL.

A manual recovery probe initially paired ROB8 with the older ROB16-oriented
recovery programs and failed its early-target timing witness. The passing gate
builds the previously accepted `workloads/s03/profile_recovery.S` ROB8 inputs in
its own directory, without relaxing the recovery assertions or overwriting
earlier evidence. Initial cache bring-up failures and earlier successful run
directories remain local for diagnosis.

## Remaining original work

1. Re-run the complete accepted S03 real-tool suite on the integrated APE
   hierarchy and audit direct-memory versus cached architectural/measurement
   comparability. One actual application now runs through APE+LSQ+D-L1; the
   current 228-run Spike matrix remains selected-profile evidence, not a full
   app-suite cache-integrated run.
2. PPE coalescing, scratch banking, concurrent misses and individual I/D cache
   execution now have current-source gates; the integrated suite still needs
   broader end-to-end stress and full S04 acceptance review.
3. Complete system device/MMIO semantics: broader error and fence/handoff
   ordering plus a linearizable shared-atomic service with independent litmus
   tests. Selected APE and PPE device transactions now pass through RTL wrappers
   to behavioral services; that is not yet a complete system-wide contract.
4. Expand integrated replay, alias, fault, resource-full and reset/drain
   coverage; the integrated PPE bounds-fault case is one directed point, not
   broad adversarial APE/PPE fault/replay stress. Prove additional queue and
   protocol invariants with explicit assumptions.
5. Matched-input PPE generated-case points, isolated APE trace replay, and a
   cache-integrated APE matrix across 12 diff-workload inputs now pass. The
   `repo_source_edit` workload runs at 8/2, 16/4 and 32/8 in both D-L1 and I/D-L1;
   the other inputs run at matched 16/4 points in both modes. Broader PPE
   application traces, independent parameter sweeps and measured or explicitly
   calibrated memory service are still needed; current behavioral service
   cycles are not bandwidth measurements.

Unknown-store dependence replay now has a passing directed RTL witness, but
the test is not a full adversarial replay/reset campaign. Ownership integration
tests one shared data word across two transfers, including a handoff requested
with live external line traffic and measured drain-before-ack behavior; it is
not the full adversarial system suite. The isolated cache-point trace replay
still covers one diff workload; the cache-integrated APE runner covers all 12
accepted diff input fixtures.
External line-service latency is modeled, not HBM/LPDDR performance.
There is no physical-clock, energy, speedup, OS, coherence, whole-core formal or
full Issue #5 completion claim in this increment. Issue #5 stays open.
