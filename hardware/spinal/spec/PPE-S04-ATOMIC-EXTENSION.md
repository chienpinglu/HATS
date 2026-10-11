# PPE S04 scalar atomic-add extension

Status: implemented in selected PPE RTL paths. A dual-engine litmus verifies
sequential visibility across exclusive ownership handoff; concurrent
cross-engine atomic arbitration and whole-system litmus acceptance remain open.

This is an S04 extension to the PPE-ISA-0.1 operation set. Existing opcodes
1–37 and the code-object header are unchanged. Opcode 38 is `AMOADD`:

| Field | Meaning |
| --- | --- |
| `d` | Scalar register receiving the old 64-bit memory value |
| `a` | Scalar base register |
| `b` | Scalar 64-bit addend register |
| `imm` | Signed 32-bit byte displacement added to `S[a]` |
| `width` | Must be 3 (8 bytes) |
| `flags` | Must be zero; scratch and vector forms are illegal |

The operation requires a uniform full-wave execution context, a naturally
aligned global address, and both read and write permission for the full word.
It produces one memory request with `write=1`, `atomicAdd=1`, and an all-byte
mask. D-L1 returns the old value and commits `(old + S[b]) mod 2^64` as one
cache-side transaction. The PPE writes the returned old value to `S[d]` only
after the matching response succeeds. Faults do not publish the destination.
The ordinary PPE memory engine cannot split, coalesce, or reorder this scalar
operation with lane requests; it drains the response before instruction retire.

Scratch and configured device/MMIO apertures are not atomic targets. The
exclusive owner controller permits one engine to execute against a region at
a time; clean/invalidate handoff transfers the resulting value between private
caches. The dual-engine test establishes sequential visibility across these
exclusive ownership epochs (PPE 43→48; APE observes 48 and updates it to 51).
This is not simultaneous arbitration, general coherence, or a system-wide
ordering guarantee outside that ownership protocol. Independent concurrent
requesters, device interaction, and broader litmus tests remain required.

Evidence is source-bound by `verify_ppe_memory.py` and its `PpeAtomicAddSim`
run. It checks three ordered operations (old values 10, 11, 13), a following
load and fence-visible backing value of 16, and an independent Python
functional-model oracle. Its backing line service is behavioral, not DRAM RTL.
