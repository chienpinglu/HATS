# S04: APE/PPE memory-execution architecture

Status: implementation in progress; not S04 acceptance.
Scope: [issue #5](https://github.com/chienpinglu/HATS/issues/5), all original
work packages and acceptance criteria in [ROADMAP](../../../ROADMAP.md).

## Execution path and regression boundary

Both engines must execute their actual programs through the RTL hierarchy. The
S03 commit `3b2d7e977a8b47386421830126ce32a70ffa8978`, closure record and preserved
source archives are regression anchors. The selected APE profile is ROB8/P48/W1;
optional W2 remains a correctness configuration. The existing serial PPE path
and direct APE transport remain reference configurations, not substitutes for
S04 execution. Independent architectural comparison must observe retired memory
effects, not assume that speculative/cache-line requests have architectural order.

The intended path is APE instruction fetch and LSQ, or PPE instruction fetch and
masked/coalesced lane requests, through instruction/data L1 controllers to a
tagged shared lower-level interface. Banked scratchpad is separate from global
cache storage. External memory service may be behaviorally modeled; cache tags,
data, queues, MSHRs, forwarding, arbitration and ownership must execute in RTL.

## Initial memory model and ownership

The first integrated profile uses physical addresses and explicit exclusive
ownership of cacheable regions. It does not claim hardware-coherent shared
virtual memory. A region cannot change owner until both engines have drained all
operations and both private I/D-cache pairs have successfully
cleaned/invalidated. The controller performs bilateral maintenance before
incrementing the ownership generation. Failure leaves ownership with the old
owner. Code publication similarly requires
completed data writes/clean and instruction-cache invalidation before execution.
`MemoryOwnershipController` and `ApePpeSharedMemoryTile` enforce this exclusive
boundary in RTL. The source-bound gate tests actual APE/PPE programs, both
handoff directions, delayed-generation rejection and shared 42→43→43 data
visibility. This is not general coherence and still needs adversarial stress and
formal proof.

Shared synchronization words and device memory require a separate uncached,
ordered path. The APE wrapper routes configured 64-bit-word-aligned apertures
around D-L1, performs clean-only maintenance, then issues one serialized device
request and returns its response/error to the APE LSQ. The PPE I/D wrapper
provides the analogous D-L1 clean and serialized request path for configured
apertures. Both accept responses only when transaction ID and epoch match the
held request; malformed responses are backpressured. The combined APE/PPE tile
exposes separate ports for both boundaries. Current PPE SpinalSim coverage
executes a real instruction stream through I-L1/fabric and D-L1, verifies a
dirty cached store is visible before device store/load operations, and rejects
malformed response ID/epoch. Device behavior and latency remain an external
testbench service, not a peripheral implementation. Exclusive ownership and
idle-drained handoff prevent the non-owner engine from running during a device
operation, but independent system-wide I/O-ordering litmus tests remain open.
The scoped PPE scalar AMOADD extension is specified in
[`PPE-S04-ATOMIC-EXTENSION.md`](PPE-S04-ATOMIC-EXTENSION.md). APE AMOADD.D and
PPE AMOADD each execute through their own LSQ/coalescer and private D-L1 and
return the old value. The exclusive ownership controller prevents concurrent
engine ownership during a handoff, but does not provide a system-wide shared
atomic serialization point for concurrent requesters. Cross-engine litmus
tests, device interaction, and formal atomic-order proofs remain outstanding.

APE stores, device accesses and atomics become externally visible only with
architectural authorization. Speculative ordinary loads may fill owned cache
lines but must not publish register/fault state after squash. LSQ generations
must survive accepted transactions until their responses drain; a ROB slot cannot
be used as an unqualified external transaction ID. Dependence resolution must
forward the youngest older store's covered bytes, wait on unknown older addresses
or replay a bypassed load, and suppress younger irreversible effects on faults.

PPE lane masks apply before requests are generated. Coalescing may combine only
compatible accesses within a line, with defined same-address store-lane order.
Returned words must be demultiplexed to the correct lane and instruction epoch.
Load destinations commit together only when the instruction's required accesses
succeed. The existing explicit partial-store fault contract must remain visible.

## Tagged word and line interfaces

The first controller component, `NonBlockingL1`, uses an aligned 64-bit word
client port with byte write enables and whole-line lower-level transfers.
`MemoryHierarchyConfig` fixes line size, direct-mapped set count, MSHR capacity,
client ID width and transaction generation width. A line is at least two words.
The lower interface is a defined cache-facing transfer contract, not an HBM,
LPDDR or AXI PHY claim; a burst adapter can later implement it.

- An accepted client `(id, epoch)` has exactly one response. The caller keeps
  that identity unique while outstanding. Misaligned client word addresses fault
  without a lower-level request or cache mutation.
- Each active MSHR owns one cache index until its response is consumed. Different
  indices can miss concurrently; hits at unreserved indices can proceed under
  misses. Same-index aliases serialize, including replacement and partial stores.
- Every lower request carries an MSHR slot, generation and read/write phase.
  Responses may reorder. Only a matching live waiting phase may update state;
  stale/unmatched replies are consumed and counted without publishing effects.
- Lower requests and client responses retain stable payloads under backpressure.
  Each accepted lower request returns once, no earlier than the following cycle.
  Generation reuse relies on that no-duplicate-response fabric contract after a
  completed transaction. Arbitrarily delayed duplicates across generation wrap
  are not made safe by a finite counter alone.
- A dirty victim is written back before replacement refill. Failed writeback
  has no external mutation and preserves the dirty resident line. Failed refill
  installs no line. The requesting access receives a fault. Previously completed
  stores remain owned cache state; a clean failure prevents ownership transfer.
- Cacheable RAM permits line-wide reads within its region. Protection/range
  checks precede caching; sub-line protected/device regions cannot use this path.
- `drain` prevents new client admission; `idle` requires all client responses and
  lower transactions drained. `clean` separately reports absence of dirty data.
  A lossless warm reset requires successful clean, drain and fabric quiescence;
  idle alone is insufficient. Cold reset that discards owned memory requires
  coordinated system reinitialization. A timeout never fabricates completion.
- Clean/invalidate maintenance stops admission, waits for drain, writes every
  dirty line, and acknowledges only after completion. A failure preserves the
  failing line and reports failure; the owner cannot be released.
- `CacheWordRequest.atomicAdd` is a distinct, aligned 64-bit read-modify-write:
  the request carries the addend, the response returns the old word, and the
  cache installs the sum before releasing the line's MSHR. A partial-width or
  malformed atomic faults without modifying data. This primitive is covered on
  hit and refill paths. The selected APE RV64A `AMOADD.D` path and PPE scalar
  `AMOADD` extension issue it through their respective memory engines and
  private D-L1s. The combined APE/PPE test checks sequential visibility across
  explicit clean/invalidate ownership handoffs. Concurrent cross-engine atomic
  arbitration, hardware cache coherence and simultaneous shared-memory access
  are not implemented or claimed; the owner controller enforces exclusive
  engine ownership instead.

This component initially stores data in explicit RTL registers. SRAM mapping,
bank ports and physical timing/area remain separate measured design choices.
Capacity or simulated service delay is not measured HBM/LPDDR performance.

### Optional word-granular poison

`wordPoison = true` adds one poison bit per 64-bit word to successful line
responses, resident lines and writeback requests. This is a reported-data-error
contract, not an ECC implementation. A poisoned word returns a client error;
neighbouring healthy words remain usable. A store cannot repair a poisoned word
or dirty it accidentally, including on a refill. Healthy-word stores preserve
the poison mask on eviction/clean. A failed writeback preserves both dirty data
and poison. Owner-side repair requires explicit invalidation before reuse.

The existing line `error` is separate: it rejects the entire transfer, preserving
the original failed-refill/writeback rules. Without this optional metadata the
original interface and cache behavior are unchanged. PPE uses word poison so a
fault at byte address 8 does not incorrectly turn the preceding healthy lane at
address 0 into a fault merely because both share a cache line. Sub-word failure
granularity is not claimed.

## PPE coalesced data-path implementation increment

`PpeConfig.memoryHierarchy = Some(m)` replaces the serial memory-instruction
path with `PpeMemoryEngine` and four independently addressed scratch banks.
`PpeCachedDataTile` connects the real PPE word port to a 16-set, 32-byte-line,
four-MSHR D-L1. Its data-only regression profile still fetches instructions from
loader RAM; the full instruction-cache profile below removes that RAM.

- Before grouping, the core computes lane addresses with overflow, alignment,
  object bounds and write-permission checks. Masked lanes cannot issue or fault.
  No lane after the first known address-validation fault is issued.
- Ordinary loads sharing a 64-bit word coalesce, including nonadjacent active
  lanes. Distinct word groups may overlap. The L1 serializes cache-index aliases;
  it reuses resident lines and overlaps misses at different indices.
- Stores coalesce only consecutive active lanes within a word. Later lanes win
  on colliding byte enables. Exactly one irreversible store group can be in
  flight; a failing group prevents all later groups. This preserves the existing
  ordered partial-store fault prefix.
- Returned word data is routed to its group using a live `(leader lane, epoch)`
  lease. Public access observations remain lane-ordered. Loads buffer results
  and commit destination registers only if the entire instruction succeeds.
  An early read error waits for other accepted reads to drain before completion.
- The scratchpad has four 64-bit banks, interleaved by word address, each with
  128 rows and independent request/response flow control. Loads to distinct
  banks can proceed together; conflicts queue in the memory engine. Stores keep
  the same precise-prefix grouping rules. Launch clear writes all four banks
  per row and requires 128 rows, not the serial profile's 512 word cycles.
- A cycle-budget expiration prevents new offers but never withdraws an offered
  request. Already offered/accepted groups drain, including a multi-lane store
  group, before fault completion. Missing service prevents completion/reuse;
  the tested recovery supplies the late response and drains it without reset.
  The cached clock-protocol fixtures use a separate explicit group contract;
  they do not reuse the serial profile's one-lane timeout expectation.
- In the hierarchy profile, APE `FENCE` and PPE `FENCE`/`BARRIER` wait for prior
  operations and a clean-only D-L1 maintenance acknowledgement before retiring.
  The directed RTL checks observe dirty bytes in backing line memory at the
  retirement point. This is ordinary cacheable-RAM writeback, not invalidation,
  MMIO ordering, atomic serialization, or concurrent cross-engine coherence.

Standalone per-engine wrappers rely on the caller's exclusive ownership of
complete cache lines. The integrated `ApePpeSharedMemoryTile` gates both engines
through the system ownership controller. A byte-granular object may occupy a fraction of a padded owned line;
the padding is ordinary accessible RAM, not another owner or device. Store byte
enables may not escape the object's permissions. Launch cannot overlap cache
maintenance. Clean+invalidate between tested invocations publishes memory and
prevents stale lines from leaking between owners. The integrated controller
enforces bilateral clean+invalidate before changing owner; standalone cache
wrappers do not enforce system ownership on their own.

See [PPE data-path evidence](../../../workloads/s04/PPE-DATA-PROGRESS.md) for exact
ISA-versus-protocol counts, tested source identities and outstanding requirements.

### PPE instruction/data hierarchy and publication

`PpeConfig.instructionCache = true` uses `CachedInstructionFetch` and I-L1 instead
of a program RAM. The per-engine wrapper merges I-L1 (source 0) and D-L1 (source 1) through
the same `CacheLineFabric` contract used by APE. The integrated
`ApePpeSharedMemoryTile` connects both wrappers to one ownership-enforced
line-service boundary. A source is part of every line
transaction's identity, in addition to slot, generation and phase.

Both host launch ports are ready/valid `Stream`s. A producer must hold `valid`
and its payload stable until `ready` is asserted; a request from the non-owner
is backpressured, not rejected or discarded. It may handshake only after the
requested engine owns memory and the controller is in RUN. The source-bound
integration test presents APE and PPE launches together, then holds each
non-owner request across the handoff that makes it eligible. This contract
prevents a transient readiness sample from being misreported as request denial.

The current code window is a configured, 128-byte-aligned physical region at
`instructionBase` (default `0x100000`); each logical PPE byte PC is added to this
base. The wrapper's 1,024-word profile reserves 8 KiB. The launch's `codeWords`
still bounds legal instruction PCs. Invalid launches/falloff never authorize an
out-of-range fetch. The code region and any modified executable data must be
ordinary exclusively owned RAM, not device registers.

PPE does not speculate instruction fetch across execution in this profile. It
keeps one buffered word and one outstanding fetch lease. A transport or word-
poison fault on a demanded instruction reports cause 4, the faulting logical
byte PC, the physical instruction address and lane mask zero; that instruction
does not retire. A branch that skips a poisoned word does not fault merely
because another healthy instruction shares its line.

An offered fetch remains live after clock-budget expiry. The core enters DRAIN,
keeps launch/completion blocked until the response returns, and discards the
late fetch data/error. Cause 5 remains the timeout result; a later code fetch
error cannot replace it. Local buffer invalidation and launch require drained
fetch state. This is not page-fault replay, prefetch speculation or an instruction
throughput improvement claim.

Publication has the same ordered steps as APE: quiesce, clean D-L1 (optionally
invalidate D), invalidate I-L1, clear the frontend buffer, then hold the result
until consumed. A failed data writeback retains dirty ownership and does not
invalidate the old I-cache or report successful publication. A successful retry
permits the PPE to execute an instruction it previously wrote through D-L1.
This explicit tile command does not add a new PPE ISA instruction or turn local
FENCE/BARRIER into system coherence.

See [PPE instruction-path evidence](../../../workloads/s04/PPE-INSTRUCTION-PROGRESS.md).

## APE data-path implementation increment

`ApeLoadStoreQueue` uses ROB-backed address/data rows plus eight independent
transport leases. The selected `ApeCachedDataTile` executes the ROB8/P48/W1
engine through this queue and a real data L1 (8 sets, 32-byte lines, 4 MSHRs).
The original head-only profile remains `ApeConfig.memoryHierarchy = None`.

- Stores become cache requests only from the architectural head. Older buffered
  stores can forward to younger loads before the stores become visible.
- Each requested byte comes from the youngest covering older store. Fully
  covered loads complete locally; partially covered loads merge their captured
  forwarded bytes with the returned cache word. Other loads can overlap misses.
- Unknown older store addresses/data conservatively block a load. This is a
  dependence interlock, **not** speculative dependence prediction or replay.
- A live older FENCE prevents younger load admission. At the head, the system
  fence request waits for the data hierarchy to drain, cleans dirty D-L1 lines,
  and retires only after a successful lower-memory completion. Device requests
  are serialized behind older APE memory operations, clean D-L1 before issue,
  and block younger memory operations until the response returns. System-wide
  system-wide device ordering and atomic ordering remain open. Selected APE
  and PPE device paths are exercised through RTL wrappers against behavioral
  services, not a specified physical peripheral or end-to-end I/O model.
- Cache requests keep `(lease slot, epoch)` ownership through response. An
  offered load is irrevocable even after squash. Its ROB slot cannot be reused
  while the lease survives; returned data/fault state is published only to a
  matching live ROB generation and physical destination.
- Halt and relaunch wait for all memory leases to drain. Maintenance and new
  launches are interlocked in the wrapper. The data-only regression profile
  retains program RAM; the full instruction-cache profile below removes it.
- `memoryRetired` reports architectural accesses separately from speculative
  transport. Independent Spike comparisons consume this RTL port and retirement
  ports, not values reconstructed by the local sequential oracle.

The current wrapper requires an exclusively owned, whole-line-aligned physical
RAM region and does not itself contain the system ownership controller.
Optional `forbiddenRegions` define half-open physical apertures that the APE
cached wrapper assertion-checks against the actual byte mask before cache
admission. Separately, `deviceRegions` configure word-aligned apertures routed
through a serialized uncached port. The wrapper waits for D-L1 clean before
issue; the environment supplies the device response, including error status.
The combined tile forwards both engine device ports and includes their active
transactions in handoff quiescence. The APE SpinalSim test covers clean-before-I/O,
read/write traffic, malformed response ID/epoch rejection and backpressure in
D-only and I/D profiles. A separate PPE I/D RTL program covers cached-store
cleaning, device read/write, malformed ID/epoch rejection and drain. Both use
behavioral device services. Neither defines a physical peripheral protocol;
broader system I/O litmus tests remain open. See
[S04 progress](../../../workloads/s04/README.md) for evidence.

## APE instruction/data hierarchy and publication increment

`ApeConfig.instructionCache = true` removes the internal instruction RAM and
feeds the frontend from `CachedInstructionFetch` through a real I-L1.
`ApeCachedDataTile(..., instructionCache = true)` connects that I-L1 and the
LSQ-backed D-L1 to `CacheLineFabric`. I/D caches use the same configurable line
contract. The initial frontend keeps one 64-bit word and one outstanding fetch;
it is not a wide or multi-miss instruction frontend.

The fabric tags every request with its source cache. Its identity is
`(source, slot, generation, phase)`, so equal MSHR IDs from different caches do
not alias. Round-robin arbitration locks while stalled; replies can reorder.
A per-source ledger tracks ownership through matching responses and keeps
unmatched replies from falsely satisfying drain. The existing once-only fabric
contract still applies across finite generation wrap.

An offered fetch cannot be canceled by a branch. Its response drains; the
frontend accepts data/fault only if its requested word is still the demanded
word. Branch recovery and precise retirement also suppress younger buffered
instruction faults. A bad entry alignment/range never sends an I-L1 request.
Halt/relaunch includes fetch drain, and instruction-buffer invalidation requires
quiescence. The obsolete programming port does not supply instructions in this
profile; tests poison it while the external line service provides the real code.

The tile maintenance command now performs, in order:

1. Wait for the engine and line hierarchy to drain and block new launches.
2. Clean D-L1, optionally invalidating its lines. On failure, retain ownership
   and dirty state; return failure without advancing to I-cache invalidation.
3. Invalidate I-L1 and the frontend word buffer.
4. Hold the result stable until acknowledged; only then admit a new launch.

This is explicit tile-level code publication, **not** an implemented FENCE.I ISA
extension or an inter-engine ownership controller. Tests use the actual APE to
store a new instruction through D-L1: I-L1 remains stale before publication, a
failed clean prevents success, and retry exposes the new instruction without a
processor reset. The same tests cover precise fetch faults, wrong-path faults
before/after redirect, source-tagged response reordering and unmatched replies.
See [instruction evidence](../../../workloads/s04/INSTRUCTION-PROGRESS.md).

## Full issue acceptance map

| Original work package | Required integrated evidence | Current status |
| --- | --- | --- |
| WP1: APE memory execution | LSQ, store buffer, forwarding/dependence and multiple outstanding accesses; precise retirement and independent real-tool regression | LSQ/D-L1 instruction tests include selected dependence replay and Spike comparison; 12 diff fixtures run through cached D-L1 and I/D-L1, plus three Tree-sitter input classes × cold-old/incremental through cached I/D-L1; broader independent compiler/runtime/tool coverage pending |
| WP2: PPE memory execution | Actual masked coalescing, scratch banking and concurrent misses with full-state oracle | PPE coalescer, four-bank scratchpad, concurrent reads and I/D-L1 execute through RTL; 316 cached comparisons pass per matched design point across six configurations; broader application/runtime scheduling coverage pending |
| WP3: cache hierarchy | Real I/D L1, MSHRs, refill/writeback and tagged lower interface in both engine paths | APE and PPE I/D-L1 paths and source-tagged shared fabric pass selected configuration, full-resource integrated stress, conflict/reorder/reset/drain checks, and matched PPE design points; broader application-derived sizing is outside this acceptance boundary |
| WP4: sharing/ordering | Enforced ownership or coherence boundary, atomics, fences and ordered device path; independent litmus tests | Bilateral exclusive ownership and selected dual-engine visibility pass; cacheable-RAM clean-and-ack fences pass; serialized APE and PPE device RTL paths pass against modeled services; APE RV64A AMOADD.D and PPE scalar AMOADD execute through their memory engines and private D-L1; a dual-engine RTL litmus verifies PPE AMOADD (43→48), clean/invalidate handoff, APE observation and AMOADD (48→51). General coherent sharing, concurrent cross-engine atomic arbitration, physical device protocol, broad system-wide I/O litmus coverage, and formal atomic-order proofs are not claimed |
| WP5: adversarial behavior | Replay, aliases, partial accesses, stalls, reordered replies, faults, code publication and wrong-path suppression | Selected dependence replay, aliases, partial accesses, stalls, reordering, faults, publication and wrong-path suppression tests pass; L1, APE-LSQ, and shared line-ledger assertions have bounded proofs under documented assumptions. Proofs are scoped and bounded, not unbounded whole-core verification |
| WP6: measured choices | Cache/memory counters and matched-real-input capacity/bandwidth comparisons | PPE generated workloads and real APE application traces are compared at matched points with event counters and exact final-state checks; service timing is behavioral, not calibrated. Broader application surveys, calibrated service assumptions, and physical bandwidth measurements are not claimed |

The source-bound completion audit in
`workloads/evidence/S04-PPE-INSTRUCTION-CURRENT-CHECKPOINT.json` records AC1–AC5
as passed and binds the current implementation, tests, formal runs, workload
design points, and these specification bytes. Its explicit limitations define
the claim boundary: behavioral external service rather than physical HBM/LPDDR,
bounded selected formal properties rather than unbounded full-chip proof, and
exclusive clean/invalidate ownership rather than general coherence.

## Implementation sequence

1. Establish and stress the tagged nonblocking L1 and maintenance contracts.
2. Implement the APE LSQ and cached instruction/data path with precise recovery.
3. Implement PPE coalescing, scratch banking and cached instruction/data paths.
4. Enforce shared ownership, atomic/fence/device and instruction-publication rules.
5. Run independent architectural/full-state regressions, protocol stress and
   selected formal properties; preserve intermediate source-bound checkpoints.
6. Measure matched-real-workload design points, complete the original acceptance
   audit, and only then commit/push the accepted stage and resolve issue #5.
