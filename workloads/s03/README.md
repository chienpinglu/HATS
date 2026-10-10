# S03 performance-core evidence

The S03 gate implements the original issue #4 criteria. Historical increment
collectors and the final acceptance collector have different scopes:

- `evidence.py` preserves execution/rename/recovery/formal compatibility
  increments. Its output is always `S03_complete: false`.
- `multi_evidence.py` preserves the focused dual-lane and controlled smoke
  increment. Its output is always `S03_complete: false`.
- `closure_evidence.py` requires current-source full compatibility, all focused
  and selected formal gates, all 108 controlled workload runs, all nine verified
  physical design points, a measured performance report and a reviewed design
  selection. Only that complete acceptance collector can emit `S03_complete: true`.

Use the project's Python 3.12+ environment (`hashlib.file_digest` is required), the documented
Spinal/Verilator toolchain, and the pinned local workload/reference dependencies.
On the development Mac, `/opt/homebrew/bin/python3` selects the supported Python;
the system `python3` may be older. Run commands from the repository root.

```sh
python3 -m unittest discover -s workloads/s03 -p 'test_*.py' -v
python3 workloads/s03/compare.py
```

The collector tests validate report/rejection logic, not hardware.

## Controlled memory-service component

`service_schedule.h` supplies request acceptance and response delays indexed by
transaction ordinal and a fixed seed. Acceptance delay is measured from first
presentation, response delay from acceptance. Changing processor arrival cycles
or holding a ready response does not change the realized service sequence.
The one-outstanding profile matches the current APE transport contract; a future
multi-outstanding LSU requires a separate service/ordering model.

The service is integrated into the actual Verilator real-tool runner through
the explicit `HATS_S03` build option used by `compare.py`. Ordinary compatibility
runs retain their cycle-dependent randomized service and are not used to claim
controlled architecture speedups. The native test below is service-component
evidence only, not APE execution or HATS performance:

```sh
mkdir -p hardware/spinal/build/ape_service_schedule
clang++ -std=c++20 -Wall -Wextra -Werror -fsanitize=address,undefined \
  workloads/s03/check_service_schedule.cc \
  -o hardware/spinal/build/ape_service_schedule/check
hardware/spinal/build/ape_service_schedule/check
```

The test checks 120,000 transactions across three abstract response-base profiles
and four processor-arrival patterns, including held responses and illegal
handshakes. Base delays 2/8/32 plus 0–7-cycle jitter are experimental parameters,
not claims about HBM, LPDDR or a physical memory system.

The actual RTL study uses response bases 2 and 16 with 0–7-cycle jitter, the same
compiled images, full architectural digests and output comparison. It varies
issue width, ROB/fused-reservation capacity, physical registers and prediction.
`--smoke` covers only two widths and small inputs; it cannot close S03.

## Complete evidence path

1. Run the semantic, rename, recovery, registered-execution and dual-lane RTL
   gates in `hardware/spinal/tools/verify_ape_*.py`, followed by both selected
   bounded formal gates. Their exact scope is documented in the associated
   [microarchitecture specifications](../../hardware/spinal/spec/APE-VERIFICATION.md).
2. Run `python3 workloads/s02/run_all.py --output <fresh-compatibility.json>`
   for fresh real-tool, ISA, PPE, bounded-diff and legacy compatibility.
3. Run the complete `compare.py` study and the
   [technology study](../../hardware/spinal/spec/APE-TECHNOLOGY-STUDY.md).
4. After both studies finish, use `report_designs.py --study <study.json>
   --technology <technology.json> --output workloads/S03-DESIGN-STUDY.md`.
   Review the measured choices in `workloads/s03/design-selection.json` and
   the original acceptance rows in `workloads/S03-COMPLETION.md`.
5. Run `closure_evidence.py --compatibility <compatibility.json>
   --study <study.json> --technology <technology.json> --output <fresh-final.json>`.
   It revalidates the actual artifacts and rejects stale sources, mixed revisions,
   incomplete matrices, altered counters and a report inconsistent with the data.

For a PRF48 selection, first run `verify_profile.py --study <study.json>
--bulk <full-bulk-validation.json>`. It reuses the hash-verified measured RTL
executable and pinned reference inputs, but executes all 42 tool cases again on
the candidate; it also runs 100 standard and 12 recovery ISA invocations at
ROB8/P48/one lane. Add `--profile <profile-validation.json>` to the final collector.
The generic `ApeConfig` fallback remains P64; a selected explicit P48 profile is
not inferred from P64 integration evidence. No candidate is selected until its
measurements, physical results and full-profile gate have been reviewed together.

The selected profile's six recovery programs are in `profile_recovery.S`. They
fit ROB8 while preserving the unchanged harness's timing/pressure assertions;
the general ROB16/P36 programs remain unchanged. ISA runs use a fresh fork working
directory, leaving earlier reports intact. To continue after an orchestration or
ISA-stage failure with all 42 tool executions already complete, supply both
`--resume-tools <preserved-report.json>` and `--original-driver <verify_profile.py.original>`.
The driver verifies the exact previous driver snapshot and unchanged hardware,
harness, inputs, executable and every DUT output. It reuses only those actual
tool executions and runs all ISA/recovery tests afresh. The final report binds the
prior attempt; failed ISA results never enter the accepted comparison count.

Reports are bound to their source and generated-artifact hashes. Preserve prior
checkpoints; do not overwrite them with a new implementation. Paths in angle
brackets refer to actual fresh reports returned by the drivers. Tool setup,
synthetic collector tests and a successful individual matrix row are not final
hardware acceptance. See the [full closure plan](../../hardware/spinal/spec/S03-CLOSURE-PLAN.md).
