# Agent workload suite

This suite starts measuring CPU-side work that HATS aims to execute. It draws
from public projects covered in the RSI survey: GEPA, ACE, AFlow, DGM, STOP,
AHE and Gas City. It provides runnable component tests and source-processing
workloads, not complete reproductions of those agents or papers.

All execution currently uses the host. None of these workloads runs on HATS RTL
yet. The [coverage map](COVERAGE.md) identifies the missing processor/runtime
capabilities and the requirements for full upstream experiments.

## Run locally

Requirements: Python 3.12 or newer for the full suite, Git, and macOS or Linux. No pip packages,
model credentials, Docker, model downloads or GPU are required for these cases.
From the HATS repository root:

```sh
python3 workloads/suite.py fetch
python3 workloads/suite.py fetch --check
python3 workloads/suite.py list
python3 workloads/suite.py run --repeat 3
python3 -m unittest discover -s workloads -p 'test_*.py' -v
```

On the development Mac, use `/opt/homebrew/bin/python3` if the older framework
Python has a broken certificate store or cannot parse the pinned AHE source.
That source requires Python 3.12+ f-string syntax. Never disable TLS verification. Downloads
use immutable commits and SHA-256/length checks; subsequent runs are offline.

Select one case:

```sh
python3 workloads/suite.py run --case dgm.edit --repeat 5 --timeout 30
```

`--backend hats-rtl` deliberately produces a blocked report and a nonzero exit:
there is no silent host fallback. Missing/corrupt sources also block the run.
Individual execution failures and timeouts remain failures in the report.

## Included cases

| Source | Executed upstream component | Other local workloads |
| --- | --- | --- |
| GEPA | Pareto coverage pruning/selection; trace JSON conversion | Diff/patch and Python compilation |
| ACE | Playbook counter updates, curator ADD, JSON extraction | Diff/patch and Python compilation |
| DGM | File create/edit/view, including rejected operations | Diff/patch and Python compilation |
| STOP | Max-cut seed and random-walk SAT seed | Diff/patch and Python compilation |
| AFlow | None yet | Diff/patch and Python compilation of selected sources |
| AHE | None yet | Diff/patch and Python compilation of selected sources |
| Gas City | None yet | Diff/patch of Go event-processing sources |

There are 21 cases: eight component cases, seven diff/patch cases and six Python
compilation cases. Every diff case uses Git's Myers, patience and histogram
algorithms and verifies patch application reconstructs the expected bytes.
Inputs are pinned upstream files with deterministic **synthetic edits**, not
recorded agent trajectories. Temporary files are separate from the source cache.

ACE's component adapter extracts the unchanged top-level functions from
`playbook_utils.py` and `get_section_slug` from `utils.py` using Python's AST.
It supplies the standard `json` and `re` modules. This omits unrelated model,
tokenizer and dotenv initialization; it is not a full ACE import. GEPA, DGM and
STOP component modules are executed from verified upstream bytes. Test inputs
and correctness checks are original HATS fixtures, not paper datasets.

The compiler cases parse actual Python source to AST and compile it to CPython
bytecode without importing it. They do not run Clang/LLVM, compile native
machine code, or execute the full source program. The STOP checks cover known
small fixtures; they do not measure general optimization quality or RSI.

## Evidence and safety

Unique JSON reports are written under ignored `results/`. They record source
commits, lockfile and runner hashes, per-repeat wall/CPU time, worker peak RSS,
correctness results and backend identity. Wall time includes module loading and
the component operation, but excludes worker startup and source downloads.
Worker and child CPU times are separate. Worker RSS excludes child processes;
neither RSS nor these timings describe HATS memory traffic or energy.

These fixed, small cases are correctness and instrumentation baselines, not
representative application benchmarks. Repeat counts do not increase workload
diversity. Architectural sizing needs larger inputs, concurrency sweeps, real
traces, cold/warm separation and end-to-end measurements. No speedup is claimed.

Workers receive a small environment without inherited model credentials. They
have process-group timeouts. This is **not a security sandbox**: only reviewed,
pinned components are executed. Do not feed generated/untrusted code into this
runner. Full agents and candidate evaluators require isolated execution and
explicit model/data/compute budgets before enabling them.

## Provenance

[sources.lock.json](sources.lock.json) pins 28 selected files from seven projects,
including their licenses and upstream READMEs. `fetch` downloads them to ignored
`cache/`; it does not vendor third-party code into HATS. Upstream authors retain
ownership and their licenses apply independently of HATS. The runner, fixtures
and coverage documents are original HATS work developed with AI assistance.

HyperAgents is listed as a reference but excluded from downloads because the
reviewed revision uses CC BY-NC-SA 4.0, rather than the MIT/Apache licenses used
by the default set. SIFT, Self-Harness and AI4AI-Bench remain reference-only until
their official runnable artifacts, licensing and environment are integrated.
We have not substituted unrelated repositories with similar project names.

## Validation snapshot

On 2026-10-04 the 21 host cases passed three repetitions each on macOS arm64 with
Homebrew Python 3.14.3. Seven independent harness tests also passed. Regenerate local
reports with the commands above; machine-specific reports remain ignored.
Full upstream agent experiments and all HATS workload execution remain untested.
