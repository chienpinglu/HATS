#!/usr/bin/env python3
"""Pinned CPU-side workload components. No model calls or HATS emulation."""
import argparse
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import random
import re
import resource
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "sources.lock.json"
CACHE = ROOT / "cache"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def manifest():
    value = json.loads(LOCK.read_text())
    seen = set()
    for source in value["sources"]:
        if not re.fullmatch(r"[a-z0-9-]+", source["id"]) or source["id"] in seen:
            raise ValueError("Invalid or duplicate source id")
        seen.add(source["id"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", source["repo"]):
            raise ValueError("Invalid GitHub repository")
        if not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
            raise ValueError("Source must be pinned to a full commit")
        if source["license"] not in ("MIT", "Apache-2.0"):
            raise ValueError("Non-permissive source requires separate review")
        paths = set()
        for entry in source["files"]:
            path = PurePosixPath(entry["path"])
            if path.is_absolute() or ".." in path.parts or "\\" in str(path) or str(path) in paths:
                raise ValueError("Unsafe or duplicate source path")
            paths.add(str(path))
            if not re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]):
                raise ValueError("Missing file checksum")
    return value


def source_path(source, entry):
    path = CACHE / source["id"] / source["commit"] / entry["path"]
    if not path.resolve().is_relative_to(CACHE.resolve()):
        raise ValueError("Source path escapes cache")
    return path


def verified_bytes(source, entry):
    data = source_path(source, entry).read_bytes()
    if len(data) != entry["bytes"] or digest(data) != entry["sha256"]:
        raise ValueError(f"Source integrity failure: {source['id']}/{entry['path']}")
    return data


def fetch(check=False):
    count = 0
    for source in manifest()["sources"]:
        for entry in source["files"]:
            path = source_path(source, entry)
            if path.exists():
                verified_bytes(source, entry)  # Never overwrite a mismatch.
            elif check:
                raise FileNotFoundError(f"Missing {source['id']}/{entry['path']}; run fetch")
            else:
                url = f"https://raw.githubusercontent.com/{source['repo']}/{source['commit']}/{entry['path']}"
                with urllib.request.urlopen(url, timeout=30) as response:
                    data = response.read(entry["bytes"] + 1)
                if len(data) != entry["bytes"] or digest(data) != entry["sha256"]:
                    raise ValueError(f"Download integrity failure: {url}")
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as output:
                    output.write(data)
            count += 1
    return count


def source_by_id(source_id):
    return next(s for s in manifest()["sources"] if s["id"] == source_id)


def load_module(source_id, filename):
    source = source_by_id(source_id)
    entry = next(e for e in source["files"] if e["path"] == filename)
    # Compile the verified bytes, not a second unchecked file read.
    code = compile(verified_bytes(source, entry), filename, "exec")
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("hats_workload", loader=None))
    exec(code, module.__dict__)
    return module


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def ace_functions():
    """Exact upstream function bodies, excluding unrelated model initialization.

    This is a component extraction, not a full ACE package import or agent run.
    No function bodies or results are replaced. The only dependency is the
    genuine upstream get_section_slug function plus Python's json/re modules.
    """
    source = source_by_id("ace")
    namespace = {"json": json, "re": re}
    for filename, names in [("utils.py", {"get_section_slug"}), ("playbook_utils.py", None)]:
        entry = next(e for e in source["files"] if e["path"] == filename)
        tree = ast.parse(verified_bytes(source, entry), filename=filename)
        definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                       and (names is None or node.name in names)]
        require(bool(definitions), "Missing pinned ACE functions")
        exec(compile(ast.Module(body=definitions, type_ignores=[]), filename, "exec"), namespace)
    from types import SimpleNamespace
    return SimpleNamespace(**namespace)


def component(case):
    if case.startswith("gepa."):
        m = load_module("gepa", "src/gepa/gepa_utils.py")
        if case == "gepa.pareto":
            fronts = {i: {i % 32, 32} for i in range(512)}
            result = m.remove_dominated_programs(fronts, dict.fromkeys(range(33), 1))
            require(all(f == {32} for f in result.values()), "Pareto coverage mismatch")
            rng = random.Random(17)
            require(all(m.select_program_candidate_from_pareto_front(result, [1] * 33, rng) == 32
                        for _ in range(32)), "Invalid selected candidate")
            return {"validation_items": 512, "candidates": 33}
        obj = {i: ("trace", {"score": i / 16}) for i in range(256)}
        result = m.try_json_serialize(obj)
        require(json.loads(json.dumps(result))["16"] == ["trace", {"score": 1.0}], "JSON mismatch")
        return {"records": 256}
    if case.startswith("ace."):
        m = ace_functions()
        text = "## GENERAL\n" + "\n".join(m.format_playbook_line(f"gen-{i:05d}", 0, 0, f"Rule {i}")
                                              for i in range(1, 257))
        if case == "ace.counter-update":
            result = m.update_bullet_counts(text, [{"id": f"gen-{i:05d}", "tag": "helpful"} for i in range(1, 257)])
            stats = m.get_playbook_stats(result)
            require(stats["total_bullets"] == 256 and stats["by_section"]["GENERAL"]["helpful"] == 256,
                    "Lost counter update")
        elif case == "ace.curator-add":
            result, next_id = m.apply_curator_operations(text, [{"type": "ADD", "section": "general", "content": "New rule"}], 257)
            require(next_id == 258 and m.get_playbook_stats(result)["total_bullets"] == 257, "Lost curator edit")
        else:
            for i in range(128):
                obj = {"id": i, "trace": {"text": 'braces { } and "quotes"', "ok": True}}
                require(m.extract_json_from_text("Result:\n```json\n" + json.dumps(obj) + "\n```") == obj,
                        "Structured output extraction failed")
        return {"bullets": 256, "extraction": "upstream function bodies; no model initialization"}
    if case == "dgm.edit":
        m = load_module("dgm", "tools/edit.py")
        with tempfile.TemporaryDirectory(prefix="hats-edit-") as tmp:
            path = Path(tmp) / "candidate.py"
            require(m.tool_function("create", str(path), "x = 1\n").startswith("File created"), "Create failed")
            require(m.tool_function("create", str(path), "x = 9\n").startswith("Error:"), "Duplicate create accepted")
            require(path.read_text() == "x = 1\n", "Duplicate create changed file")
            m.tool_function("edit", str(path), "x = 2\n")
            require(path.read_text() == "x = 2\n" and "x = 2" in m.tool_function("view", str(path)), "Edit/view failed")
            require(m.tool_function("edit", str(Path(tmp) / "missing"), "x").startswith("Error:"), "Missing edit accepted")
        return {"operations": 5}
    if case == "stop.maxcut":
        m = load_module("stop", "tasks/maxcut/seed_algorithm.py")
        n = 32
        graph = [[int((i < n // 2) != (j < n // 2)) for j in range(n)] for i in range(n)]
        result = m.algorithm(graph)
        require(len(result) == n and set(result) <= {0, 1}, "Invalid partition")
        score = sum(graph[i][j] for i in range(n) for j in range(i) if result[i] != result[j])
        require(score == 256, "Incorrect known bipartite cut")
        return {"nodes": n, "cut_weight": score, "optimum_for_this_fixture": 256}
    if case == "stop.sat":
        m = load_module("stop", "tasks/three_sat/seed_algorithm.py")
        random.seed(17)
        formula = [[i, i, i] for i in range(1, 25)]
        result = m.algorithm(formula)
        require(result is not None and all(any(result[abs(l)] == (l > 0) for l in c) for c in formula), "Unsatisfied formula")
        require(m.algorithm([[1, 1, 1], [-1, -1, -1]]) is None, "Contradictory formula accepted")
        return {"variables": 24, "satisfiable_and_contradictory_cases": 2}
    raise ValueError(f"Unknown component {case}")


def corpus(source_id, operation):
    source = source_by_id(source_id)
    entries = [e for e in source["files"] if e["path"].endswith((".py", ".go"))]
    if operation == "python-compile":
        entries = [e for e in entries if e["path"].endswith(".py")]
        require(bool(entries), "Empty Python corpus")
        nodes = 0
        for entry in entries:
            data = verified_bytes(source, entry)
            tree = ast.parse(data, filename=entry["path"])
            nodes += sum(1 for _ in ast.walk(tree))
            compile(tree, entry["path"], "exec")  # Bytecode compilation, not module execution.
        return {"files": len(entries), "ast_nodes": nodes, "compiler": "CPython AST-to-bytecode"}
    with tempfile.TemporaryDirectory(prefix="hats-diff-") as tmp:
        tmp = Path(tmp)
        for algorithm in ("myers", "patience", "histogram"):
            for entry in entries:
                original = verified_bytes(source, entry)
                prefix = b"#" if entry["path"].endswith(".py") else b"//"
                # Deliberately synthetic edits on genuine source, not an agent trace.
                lines = original.splitlines(keepends=True)
                lines.insert(len(lines) // 2, prefix + b" HATS deterministic edit fixture\n")
                changed = b"".join(lines) + b"\n" + prefix + b" end fixture\n"
                (tmp / "old").write_bytes(original)
                (tmp / "new").write_bytes(changed)
                diff = subprocess.run(["git", "diff", "--no-index", "--no-ext-diff", "--no-textconv",
                                       f"--diff-algorithm={algorithm}", "--", "old", "new"],
                                      cwd=tmp, capture_output=True, check=False, timeout=10)
                require(diff.returncode == 1, "Diff failed or fixture made no change")
                # Apply to the disposable new path initialized to the old content.
                (tmp / "new").write_bytes(original)
                subprocess.run(["git", "apply", "--no-index", "-"], input=diff.stdout,
                               cwd=tmp, capture_output=True, check=True, timeout=10)
                require((tmp / "new").read_bytes() == changed, "Patch round-trip mismatch")
        return {"files": len(entries), "algorithms": 3, "round_trips": len(entries) * 3,
                "input_class": "upstream source with synthetic edits"}


def cases():
    result = {name: {"kind": "upstream_component", "source": name.split('.')[0]}
              for name in ["gepa.pareto", "gepa.trace-json", "ace.counter-update", "ace.curator-add",
                           "ace.json-extract", "dgm.edit", "stop.maxcut", "stop.sat"]}
    for source in manifest()["sources"]:
        for operation in ["diff-patch"] + (["python-compile"] if source["id"] != "gascity" else []):
            result[f"{source['id']}.{operation}"] = {"kind": "source_corpus", "source": source["id"]}
    return result


def worker(case):
    started = time.perf_counter()
    cpu_started = time.process_time()
    with contextlib.redirect_stdout(io.StringIO()):
        if cases()[case]["kind"] == "upstream_component":
            details = component(case)
        else:
            source_id, operation = case.split(".", 1)
            details = corpus(source_id, operation)
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"wall_seconds": time.perf_counter() - started,
            "worker_cpu_seconds": time.process_time() - cpu_started,
            "child_cpu_seconds": sum(resource.getrusage(resource.RUSAGE_CHILDREN)[:2]),
            "worker_peak_rss_bytes": usage.ru_maxrss * (1 if sys.platform == "darwin" else 1024),
            "details": details}


def isolated_worker(case, timeout):
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "PYTHONHASHSEED": "0",
           "PYTHONDONTWRITEBYTECODE": "1", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "_worker", case],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                               start_new_session=True, cwd=ROOT)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise TimeoutError(f"{case} exceeded {timeout}s")
    if process.returncode:
        raise RuntimeError(stderr.decode(errors="replace")[-2000:])
    return json.loads(stdout)


def run(selected, repeat, timeout, backend):
    report = {"schema_version": 1, "claim_class": "host_component_baseline", "backend": backend,
              "hats_execution": False, "full_agent_experiment": False, "status": "running",
              "python": platform.python_version(), "machine": platform.machine(), "system": platform.system(),
              "lock_sha256": digest(LOCK.read_bytes()), "runner_sha256": digest(Path(__file__).read_bytes()),
              "sources": {s["id"]: s["commit"] for s in manifest()["sources"]}, "cases": []}
    outdir = ROOT / "results"
    outdir.mkdir(exist_ok=True)
    path = outdir / f"run-{time.time_ns()}.json"
    try:
        if backend != "host":
            raise RuntimeError("HATS RTL backend unavailable: ABI, ISA, runtime and OS-service support are missing")
        if "ahe.python-compile" in selected and sys.version_info < (3, 12):
            raise RuntimeError("Pinned AHE source requires Python 3.12+; use a newer interpreter for the full suite")
        fetch(check=True)
        for case in selected:
            item = {"id": case, **cases()[case], "status": "failed", "samples": []}
            try:
                for _ in range(repeat):
                    item["samples"].append(isolated_worker(case, timeout))
                item["median_wall_seconds"] = statistics.median(s["wall_seconds"] for s in item["samples"])
                item["status"] = "passed"
            except Exception as error:
                item["error"] = str(error)
            report["cases"].append(item)
            print(f"{item['status'].upper()}: {case}", flush=True)
        report["status"] = "passed" if all(c["status"] == "passed" for c in report["cases"]) else "failed"
    except Exception as error:
        report.update(status="blocked", error=str(error))
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"Report: {path}")
    return 0 if report["status"] == "passed" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument("--check", action="store_true")
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--case", action="append", choices=sorted(cases()))
    run_parser.add_argument("--repeat", type=int, default=1)
    run_parser.add_argument("--timeout", type=float, default=30)
    run_parser.add_argument("--backend", choices=["host", "hats-rtl"], default="host")
    worker_parser = sub.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("case", choices=sorted(cases()))
    args = parser.parse_args()
    if args.command == "list":
        print(json.dumps(cases(), indent=2))
    elif args.command == "fetch":
        print(f"Verified {fetch(args.check)} pinned files")
    elif args.command == "_worker":
        print(json.dumps(worker(args.case)))
    else:
        if args.repeat < 1 or args.timeout <= 0:
            parser.error("repeat and timeout must be positive")
        return run(args.case or list(cases()), args.repeat, args.timeout, args.backend)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        sys.exit(str(error))
