"""Real local tools driven by fixed edits; no model, remote API, or HATS backend."""
import hashlib
import json
import resource
import subprocess
import time


CATEGORIES = ("inference", "tool", "compilation", "tests", "orchestration", "network_wait")


def account(events, elapsed):
    """The experiment deliberately serializes work. Attribute every gap explicitly.

    Child CPU may exceed wall time (compiler threads). Never sum it into the
    critical path. No overlapping tasks are permitted by this accounting model.
    """
    totals = {category: 0 for category in CATEGORIES}
    end = 0
    for i, event in enumerate(events):
        if event["category"] not in CATEGORIES or event["start_ns"] < end or event["end_ns"] < event["start_ns"]:
            raise ValueError("Unknown phase or nonserial/negative trace")
        if event["depends_on"] != ([] if i == 0 else [i - 1]):
            raise ValueError("Broken serial dependency chain")
        totals["orchestration"] += event["start_ns"] - end
        totals[event["category"]] += event["end_ns"] - event["start_ns"]
        end = event["end_ns"]
    if not events or elapsed < end: raise ValueError("Incomplete trace span")
    totals["orchestration"] += elapsed - end
    assert sum(totals.values()) == elapsed
    return {"critical_path_ns": elapsed, "phase_ns": totals,
            "method": "serial event chain; controller gaps attributed to orchestration, subprocess wait belongs to its called phase",
            "unexercised": ["inference", "network_wait"]}


def run_workflow(e, native):
    origin = time.perf_counter_ns()
    events, outcomes, commands = [], [], []
    build_commands_start = len(e.report["commands"])

    def event(name, category, fn):
        child = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = time.process_time_ns()
        started = time.perf_counter_ns()
        value = fn()
        stopped = time.perf_counter_ns()
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        events.append({"id": len(events), "name": name, "category": category,
                       "start_ns": started - origin, "end_ns": stopped - origin,
                       "depends_on": [len(events) - 1] if events else [],
                       "controller_cpu_ns": time.process_time_ns() - cpu,
                       "child_cpu_ns": round(((after.ru_utime + after.ru_stime) - (child.ru_utime + child.ru_stime)) * 1e9)})
        return value

    def command(cmd, cwd=None, allowed=(0,)):
        p = subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, timeout=180,
                           env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin", "LC_ALL": "C",
                                "GIT_CEILING_DIRECTORIES": str(e.out)})
        commands.append({"argv": [str(c).replace(str(e.out), "${RESULT}").replace(str(native.WORKLOADS.parent), "${HATS_ROOT}") for c in cmd],
                         "cwd": str(cwd).replace(str(e.out), "${RESULT}") if cwd else None,
                         "exit_code": p.returncode, "stdout_sha256": hashlib.sha256(p.stdout.encode()).hexdigest(),
                         "stderr_sha256": hashlib.sha256(p.stderr.encode()).hexdigest()})
        if p.returncode not in allowed: raise RuntimeError(f"Unexpected command failure: {cmd}\n{p.stderr[-4000:]}")
        return p

    # This event includes actual upstream C compilation, not just a cached link.
    binary = event("initial-unmodified-runtime-and-grammar-build", "compilation", lambda: e.build("workflow"))
    base = (native.ROOT / "baseline.c").read_text()
    candidates = {
        "chunk512": base.replace("#define CHUNK 256u", "#define CHUNK 512u").replace("unique_256b_chunks", "unique_chunk_count"),
        "chunk128": base.replace("#define CHUNK 256u", "#define CHUNK 128u").replace("unique_256b_chunks", "unique_chunk_count"),
        "wrong-depth": base.replace("depth + !wrapper, count", "depth, count"),
        "syntax-error": base + "\n#error intentional S01 rejection fixture\n",
    }
    for name, text in candidates.items():
        folder = binary.parent / name; folder.mkdir()
        before, after, work = [folder / s for s in ("before", "after", "work")]
        for d in (before, after, work): d.mkdir()
        def edit():
            (before / "baseline.c").write_text(base)
            (after / "baseline.c").write_text(text)
            (work / "baseline.c").write_text(base)
        event(name + ":edit", "orchestration", edit)
        patch = event(name + ":diff", "tool", lambda: command(["git", "diff", "--no-index", "--", "before/baseline.c", "after/baseline.c"], cwd=folder, allowed=(1,)))
        patch_path = folder / "candidate.patch"; patch_path.write_text(patch.stdout)
        def apply():
            command(["git", "apply", "--check", "-p2", str(patch_path)], cwd=work)
            command(["git", "apply", "-p2", str(patch_path)], cwd=work)
            if (work / "baseline.c").read_text() != text: raise ValueError("Patch round trip failed")
        event(name + ":apply", "tool", apply)
        obj = work / "baseline.o"
        compiled = event(name + ":compile", "compilation", lambda: command(e.common + ["-c", str(work / "baseline.c"), "-o", str(obj)], allowed=(0, 1)))
        outcome = {"candidate": name, "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                   "patch_sha256": native.sha(patch_path), "compile_exit": compiled.returncode, "checks": []}
        if name == "syntax-error":
            if compiled.returncode == 0 or "intentional S01 rejection fixture" not in compiled.stderr:
                raise ValueError("Intentional compile rejection was not observed")
            outcome["decision"] = "rejected_compile"
        else:
            if compiled.returncode: raise ValueError("Unexpected candidate compile failure")
            exe = work / "candidate"
            event(name + ":link", "compilation", lambda: command([e.cc, str(obj)] + [str(binary.parent / f"{s}.o") for s in ("runtime", "grammar", "profile")] + ["-o", str(exe)]))
            failures = 0
            for fixture, old, new in native.cases():
                for kind, args, raw in [("cold_old", [e.inputs / f"{fixture}.old"], old),
                                        ("cold_new", [e.inputs / f"{fixture}.new"], new),
                                        ("incremental", [e.inputs / f"{fixture}.old", e.inputs / f"{fixture}.new"], new)]:
                    def test():
                        p = command([str(exe)] + [str(p) for p in args])
                        parsed = json.loads(p.stdout)
                        try:
                            checked = native.check_output(raw, parsed)
                            return {"fixture": fixture, "kind": kind, "passed": True, "oracle": checked}
                        except ValueError as error:
                            return {"fixture": fixture, "kind": kind, "passed": False, "error": str(error)}
                    check = event(name + ":" + fixture + ":" + kind, "tests", test)
                    outcome["checks"].append(check)
                    failures += not check["passed"]
            if name == "wrong-depth":
                if not failures: raise ValueError("Semantic mutation escaped independent oracle")
                outcome["decision"] = "rejected_oracle"
            else:
                if failures: raise ValueError("Valid candidate failed oracle")
                outcome["decision"] = "accepted"
        outcomes.append(outcome)
    elapsed = time.perf_counter_ns() - origin
    return {"status": "passed", "hats_execution": False, "model_generated_candidates": False,
            "events": events, "accounting": account(events, elapsed), "outcomes": outcomes,
            "commands": commands, "initial_build_commands": e.report["commands"][build_commands_start:],
            "subprocesses": len(commands) + len(e.report["commands"]) - build_commands_start,
            "synchronization": "Serial parent subprocess launch/wait. No concurrency, shared-tree contention, CP execution or network delay measured.",
            "file_services": "Local source/patch writes, git read/diff/apply, compiler header/object/executable IO, JSON input reads and captured stdout/stderr. Not a syscall-count trace."}
