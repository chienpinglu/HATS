# S04 PPE coalesced data hierarchy increment

Status: this historical data-path increment is partial on its own. The combined source-bound S04 completion audit is recorded in [README](README.md) and `../evidence/S04-PPE-INSTRUCTION-CURRENT-CHECKPOINT.json`.
This adds an actual PPE data path to the existing APE I/D hierarchy; it does not
close the original [S04 acceptance criteria](../../ROADMAP.md).

## Implemented and executed

The PPE executes original PPE-ISA programs through a lane-aware word coalescer,
a real nonblocking D-L1 and four independently accessed scratch banks. Masks,
address checks, precise load commit, partial-store faults, word poison, queues,
bank arbitration, cache tags/data, refill and writeback execute in generated RTL.
Only external byte storage and service timing are behaviorally modeled.

| Checked path | ISA-model exact | Decode/launch checks | Clock-protocol checks | Total |
| --- | ---: | ---: | ---: | ---: |
| PPE coalescer + banked scratch + D-L1 | 208 | 38 | 6 | 252 |
| PPE original serial configuration | 180 | 38 | 6 | 224 |

The ISA checks compare every retired full register/predicate/mask/stack-depth
snapshot, ordered lane memory event, completion and final global/scratch byte.
No normal ISA case is excluded. Programs cover all 37 opcode encodings, real
delimiter-kernel groups, random instruction streams, masks, faults and added
strided/alias/partial-word cases. Each case runs twice without core reset.

Separate directed clock tests use explicit profile-specific contracts. The
serial profile drains one offered lane store; the coalesced profile drains its
already offered eight-byte group. An unresponsive cached load stays busy after
expiry, cannot retire or complete, and eventually drains a supplied late reply
without reset or register commit. These are known-answer protocol tests, not
claims that the ISA oracle predicts microarchitectural cycle timing.

Observed mechanism witnesses include:

- Four simultaneous lower-level misses and four live L1 MSHRs, with reordered
  responses. Cold strided reads are required to witness this, not just warm hits.
- Four scratch banks accepting requests in one cycle.
- Sixteen logical lane accesses becoming two word requests in same-word alias
  and partial-byte store/load tests, while exact independent results match.
- Stable stalled lower requests, rejected stale generations, complete accepted
  versus returned line accounting, and byte-enable permission checks.
- Word-local poison preserves the healthy prefix of a faulting vector access;
  poison survives writeback of a dirty healthy neighbour.
- Completion acknowledgements are held before reuse. Clean+invalidate publishes
  final bytes between invocations, and object padding remains unmodified.

## Previously accepted source-bound evidence

- PPE: `hardware/spinal/build/s04/ppe-memory-1791618314743596000/gate.json`.
- Shared L1 regression and poison: `hardware/spinal/build/s04/l1-1791618158753113000/gate.json`.
- APE I/D, data-only and selected S03 regressions:
  `hardware/spinal/build/s04/ape-memory-1791618273349163000/gate.json`.

The L1 regression executes 9,344 requests in three cache configurations plus a
12-request word-poison test with six request faults, a failed clean and successful
retry. APE revalidation preserves 220 exact Spike matches and eight narrowly
checked pre-existing profile differences across 228 executions, plus its separate
instruction-publication protocol test. This is not a rerun of the full S03
real-tool performance/PPA study.

The PPE gate binds inputs, model, RTL, testbench, tools, generated Verilog and
observed traces by SHA-256; its source archive preserves the tested implementation.
The combined [increment record](../evidence/S04-PPE-DATA-INCREMENT.json) rechecks
all identities, source-archive contents, and actual comparison decisions.
Earlier successful and failed runs remain intact. Bring-up found an address
width elaboration error and an initially missing cold-miss witness; both were
fixed without weakening the gate. A synthetic report-test fixture decoding
error was also corrected; report tests are not RTL evidence.

Reproduce from `hardware/spinal`, using Python 3.10+ and existing dependencies:

```sh
python3 tools/verify_ppe_memory.py
python3 tools/verify_memory_l1.py
python3 tools/verify_ape_memory.py --instructions
```

Revalidate this recorded increment from the repository root:

```sh
python3 -m unittest discover -s workloads/s04 -p 'test_*.py' -v
python3 workloads/s04/checkpoint.py --instructions \
  --l1 hardware/spinal/build/s04/l1-1791618158753113000/gate.json \
  --ape hardware/spinal/build/s04/ape-memory-1791618273349163000/gate.json \
  --ppe hardware/spinal/build/s04/ppe-memory-1791618314743596000/gate.json
```

This older checkpoint is superseded by the current-source S04 completion audit.
Latest current-source PPE I/D gate:
`hardware/spinal/build/s04/ppe-memory-1791733549048868000/gate.json`. It passes
252 I/D comparisons, 252 D-only regressions and 224 serial regressions, plus
the actual PPE I/D uncached-device program. The device service remains a
testbench model. The fresh combined APE/PPE/ownership checkpoint is
`workloads/evidence/S04-APE-PPE-OWNERSHIP-INCREMENT.json`; that historical
increment remains partial.

## Still required

The later PPE I/D increment adds instruction-cache/fabric integration, and the
latest ownership increment adds a selected bilateral handoff gate. Remaining
gaps include system atomics and PPE device rules, system-wide ordering, broader
reset/drain/replay coverage, full real-tool execution and representative
trace-based capacity/bandwidth studies. APE's unknown-store dependence
interlock is not speculative dependence replay. No speedup, achieved clock,
physical SRAM quality, energy, coherent virtual memory, OS support or measured
HBM/LPDDR claim follows from these increments.

The target-fidelity checks for this historical increment were deliberately
partial. The prior S03 archives and unrelated local changes have been preserved.
