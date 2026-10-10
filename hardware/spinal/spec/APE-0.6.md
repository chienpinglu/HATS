# APE-0.6: optional dual-lane issue candidate

Status: focused RTL/Spike, full controlled workload study, P64 compatibility,
nine-point technology study and selected PRF48 profile gates passed.
See the [original S03 acceptance review](../../../workloads/S03-COMPLETION.md).

## Hardware scope

`ApeConfig.issueWidth` selects one or two actual `ApeExecute` pipelines. Default
remains one based on the completed design study. Both lanes execute the supported
integer, branch and address-generation semantics. This is **not** two-wide
dispatch/retirement or a claim of twice the performance: dispatch, completion/CDB,
architectural retirement and external memory remain single-wide.

`ApeIssueScheduler` selects the oldest ready live/unissued reservation rows,
relative to the circular ROB head. A blocked lane reserves nothing; the next
available lane takes the oldest remaining row. Grants denote accepted issues,
not requests held through input backpressure. `ApeExecute.request.ready` is
independent of request valid, which is a required interface contract. Each row
can issue to at most one lane per edge. Reservation operands are still stored
alongside ROB rows; separate queue capacities are not implemented by this change.

Two result ports share a round-robin arbiter. A selected result is locked while
stalled so its Stream payload remains stable. Memory responses retain priority
over this shared completion port. Losing lane results remain registered and
cannot write the PRF, wake consumers, redirect control or alter ROB completion.

The completion guard inventories **every stage of every lane**. Dispatch excludes
a `(slot, next generation)` pair still resident anywhere in those pipelines.
Accepted results must match the live owner's slot, generation and physical tag,
and the owner must be issued but not already complete/address-prepared.
Selective branch recovery can leave killed tokens in either lane; they drain
through the arbiter but cannot change architectural or renamed state. Older
live tokens survive. Full fault/retirement recovery and relaunch clear both lanes
and the arbiter's held selection. External memory remains head-only.

## Observation contract

- `issues(lane)` publishes every accepted issue with PC and full completion identity.
- Legacy `issued` aliases **lane zero only**. It remains complete for width one;
  wider observers must use `issues`, not mistake `issued` for the aggregate.
- `issueCount` is accepted operations on this edge; `readyCount` is currently
  ready reservation rows, including when issue is disabled by recovery.
- `completionBlocked` means at least one valid lane result cannot advance.
- `executionBlocked` means active eligible ready work exists but no lane accepts.
- `robBlocked` means dispatch is ROB-capacity blocked outside a recovery edge.

These overlap; adding stall counters does not partition total execution time.
`ApeCoreSim` follows all lane identities, independently records squash history,
rejects duplicate issue and checks completion age/ownership at the public ports.

## Verification and performance path

Run `python3 hardware/spinal/tools/verify_ape_multi.py` from the repo root. It
freshly exercises scheduler selection, four standard core configurations, six
dual-lane recovery configurations, and independent Spike comparisons. Required
witnesses include simultaneous issue, shared-completion backpressure, PRF
pressure and rejected late results after earlier-edge ROB-slot reuse. Existing
precise-fault, wrong-path effect, nested recovery and concurrent older-retirement
checks remain enabled. Two unchanged architectural-profile exclusions apply
only to the standard matrix; recovery must match exactly.

The nested recovery fixture retains three non-allocating older NOPs so that
an older retirement can overlap the outer branch's recovery under dual-lane
completion arbitration. The gate requires that overlap as an observed coverage
witness, in addition to architectural correctness. Both narrow and wide recovery
gates passed: 108 narrow and 72 wide invocations, all exactly matched to Spike.

The complete multi-issue gate passed 472 invocations: 456 exact Spike matches
and 16 unchanged standard-profile differences. Its deep dual-lane case observed
28 rejected results after earlier-edge slot reuse; ROB16/P36 observed 72,269
rename-stall cycles. These are correctness/pressure witnesses, not speedup metrics.

`workloads/s03/compare.py` builds one set of actual upstream tool binaries, runs
independent Spike references, and executes the same images/inputs on each RTL
design point. `--smoke` selects only two widths and small inputs; it is explicitly
not the complete design study. The full matrix varies ROB/reservation capacity,
PRF capacity, issue width and predictor choice. Its abstract memory service is
indexed by architectural transaction ordinal, with realized acceptance/response
wait checks. Complete architectural digests and output images must agree before
cycle ratios are calculated. The ordinary compatibility service is unchanged.

The initial controlled smoke passed eight actual-RTL runs. At the same
transaction service (response base two plus 0..7 cycles), the results were:

| Real program/input | Narrow cycles | Dual-lane cycles | Dual-lane cycle increase |
| --- | ---: | ---: | ---: |
| Integer helper vectors | 1,159,169 | 1,252,055 | 8.01% |
| Runtime self-tests | 127,220 | 127,341 | 0.095% |
| Tree-sitter empty edit | 269,601 | 271,790 | 0.812% |
| Tree-sitter scalar edit | 835,876 | 842,781 | 0.826% |

Every retirement/memory stream and output matched Spike; realized per-transaction
service was checked in the RTL runner. This candidate did **not** improve these
simulated cycle counts. Completion arbitration and the single dispatch/retire/
memory interfaces are possible bottlenecks, not a proven causal decomposition.
No technology-based frequency or energy result follows. The full 108-run
controlled workload matrix has since passed. The dual candidate is slower in
every pair, by 0.040%–8.013% (equal-case geometric mean +1.685%). The complete
[measured report](../../../workloads/S03-DESIGN-STUDY.md) also includes all nine
physical points. The selected application profile is ROB8/P48/one lane/bimodal16,
with full independent tool/ISA/recovery evidence; the generic P64 fallback remains.

## Acceptance and remaining system scope

Preserve the verified APE-0.5 checkpoint as historical evidence. The wider
candidate has its focused gate, complete controlled workload study, full
current-source P64 integration, synthesis/timing comparisons and separate selected-
profile acceptance. The [semantic boundary](APE-SEMANTIC-BOUNDARY.md)
now separates RISC-V frontend/profile policy from reusable execution, rename,
checkpoint and predictor interfaces. Its component gate and the selected
checkpoint/rename formal gates pass on the same current source. Those proofs
retain their documented bounded, restricted scope. All nine technology points miss
the 1,000 ps mapping target. No achieved clock, physical energy, cache,
MMU/OS, compiler execution, Python execution or end-to-end agent speedup is
claimed here. See [the full closure plan](S03-CLOSURE-PLAN.md).
