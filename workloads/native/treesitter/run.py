#!/usr/bin/env python3
"""Pinned native Tree-sitter profiling; this is not an APE/PPE execution backend."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
WORKLOADS = ROOT.parents[1]
CACHE = WORKLOADS / "cache"
LOCK = ROOT / "sources.lock.json"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(fetch=False):
    items = json.loads(LOCK.read_text())["sources"]
    result = []
    for item in items:
        if not re.fullmatch(r"native-tree-sitter(?:-json)?", item["id"]) or not re.fullmatch(r"[0-9a-f]{40}", item["revision"]):
            raise ValueError("Invalid source identity")
        if item["repository"] != f"https://github.com/tree-sitter/{item['id'].removeprefix('native-')}.git":
            raise ValueError("Unexpected source repository")
        path = CACHE / item["id"] / item["revision"]
        if not path.exists() and fetch:
            path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", str(path)], check=True)
            subprocess.run(["git", "-C", str(path), "fetch", "--depth", "1", item["repository"], item["revision"]], check=True, timeout=180)
            subprocess.run(["git", "-C", str(path), "checkout", "--detach", "FETCH_HEAD"], check=True)
        rev = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        dirty = subprocess.check_output(["git", "-C", str(path), "status", "--porcelain", "--untracked-files=all"], text=True)
        if rev != item["revision"] or dirty or sha(path / "LICENSE") != item["license_sha256"]:
            raise ValueError(f"Source identity/integrity failure: {item['id']}; never overwrite it")
        for notice, expected in item.get("additional_notices", {}).items():
            if not (path / notice).resolve().is_relative_to(path.resolve()) or sha(path / notice) != expected:
                raise ValueError("Bundled license notice integrity failure")
        result.append(path)
    return result


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def cases():
    result = [("empty", b"{}", b'{"ready":true}'),
              ("scalars", b"[null,true,false,0,-12,3.25,1e4]", b"[null,false,true,7,-12,3.25,1e4]"),
              ("unicode", encode({"text": "alpha \u03b1 \U0001f680", "escape": 'a"b\\c\n'}),
               encode({"text": "alpha \u03b2 \U0001f680", "escape": 'a"b\\c\n'})),
              ("nested", b"[" * 48 + b"0" + b"]" * 48, b"[" * 48 + b"123" + b"]" * 48),
              ("trailing_comma", b'{"x":[1,2,]}', b'{"x":[1,2]}'),
              ("truncated", b'{"x":"unfinished', b'{"x":"finished"}')]
    for n in (16, 256, 2048):
        data = [{"id": i, "name": f"task-{i}", "ready": i % 3 == 0, "deps": [i - 1, i - 2]} for i in range(n)]
        old = encode(data)
        data[n // 2]["name"] = "edited-candidate"
        result.append((f"records_{n}", old, encode(data)))
    raw = (WORKLOADS / "sources.lock.json").read_bytes()
    value = json.loads(raw)
    value["scope"] = "HATS deterministic repository-lock edit fixture"
    result.append(("repository_lock", raw, encode(value)))
    return result


def fixture_manifest():
    return {"schema": 1, "input_class": "Original deterministic fixtures and one repository lockfile; not recorded agent trajectories",
            "cases": [{"id": name, "old_bytes": len(old), "new_bytes": len(new),
                       "old_sha256": hashlib.sha256(old).hexdigest(), "new_sha256": hashlib.sha256(new).hexdigest(),
                       "old_expected_sha256": expected_hash(old), "new_expected_sha256": expected_hash(new)}
                      for name, old, new in cases()]}


def expected_hash(raw):
    try:
        value = {"has_error": False, "nodes": expected_nodes(raw)}
    except (ValueError, UnicodeError):
        value = {"has_error": True}
    return hashlib.sha256(json.dumps(value, separators=(",", ":")).encode()).hexdigest()


def expected_nodes(raw):
    """Independent JSON syntax/span oracle, checked first by the standard decoder.

    The output is a preorder of JSON values and object-key strings; parser-specific
    document/pair/string-content wrappers are excluded on both sides.
    """
    text = raw.decode("utf-8")
    json.loads(text, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    offsets = [0]
    for char in text:
        offsets.append(offsets[-1] + len(char.encode("utf-8")))
    nodes = []
    token = re.compile(r'"(?:[^"\\]|\\.)*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|true|false|null')

    def skip(p):
        while p < len(text) and text[p] in " \t\r\n": p += 1
        return p

    def parse(p, depth):
        p = skip(p)
        start, slot = p, len(nodes)
        if text[p] in "[{":
            opener = text[p]
            closer = "]" if opener == "[" else "}"
            nodes.append(["array" if opener == "[" else "object", offsets[p], 0, depth])
            p = skip(p + 1)
            if text[p] != closer:
                while True:
                    if opener == "{":
                        if text[p] != '"': raise ValueError("Expected object key")
                        p = skip(parse(p, depth + 1))
                        if text[p] != ":": raise ValueError("Expected colon")
                        p += 1
                    p = skip(parse(p, depth + 1))
                    if text[p] == closer: break
                    if text[p] != ",": raise ValueError("Expected comma")
                    p = skip(p + 1)
            p += 1
            nodes[slot][2] = offsets[p]
            return p
        m = token.match(text, p)
        if not m: raise ValueError("Invalid scalar")
        value = m.group()
        kind = "string" if value.startswith('"') else value if value in ("true", "false", "null") else "number"
        nodes.append([kind, offsets[start], offsets[m.end()], depth])
        return m.end()

    end = skip(parse(0, 0))
    if end != len(text): raise ValueError("Trailing input")
    return nodes


def check_output(raw, result):
    if result.get("live_after_cleanup") != 0:
        raise ValueError("Tracked library allocations leaked")
    try:
        expected = expected_nodes(raw)
    except (ValueError, UnicodeError):
        if result.get("has_error") is not True:
            raise ValueError("Invalid JSON was not reported")
        return {"valid_json": False}
    if result.get("has_error") is not False or result.get("nodes") != expected:
        raise ValueError("Syntax tree differs from independent JSON span/structure oracle")
    return {"valid_json": True, "semantic_nodes": len(expected)}


def tool(name):
    candidate = Path("/opt/homebrew/opt/llvm/bin") / name
    found = str(candidate) if candidate.is_file() else shutil.which(name)
    if not found: raise RuntimeError(f"Missing {name}")
    return found


def run(repeat, sanitize):
    runtime, grammar = sources()
    fixture = fixture_manifest()
    if fixture != json.loads((ROOT / "cases.lock.json").read_text()):
        raise ValueError("Fixture identity changed; review and explicitly re-freeze it")
    out = WORKLOADS / "results" / f"treesitter-{time.time_ns()}"
    out.mkdir(parents=True)
    own = sorted(p for p in ROOT.iterdir() if p.is_file())
    hashes = {str(p.relative_to(WORKLOADS)): sha(p) for p in own}
    source_hashes = {}
    for base, dirs in ((runtime, ["lib/src", "lib/include"]), (grammar, ["src"])):
        for folder in dirs:
            for p in sorted((base / folder).rglob("*")):
                if p.is_file(): source_hashes[str(p.relative_to(CACHE))] = sha(p)
        source_hashes[str((base / "LICENSE").relative_to(CACHE))] = sha(base / "LICENSE")
    report = {"schema": 1, "status": "running", "claim_class": "host_native_tool_baseline",
              "hats_execution": False, "full_agent_experiment": False, "machine": platform.machine(),
              "system": platform.system(), "source_sha256": hashes, "upstream_sha256": source_hashes,
              "fixtures": fixture, "builds": {}, "runs": [],
              "limits": ["Host arm64/x86 measurements are not RISC-V code size, cycles or target performance",
                         "Allocator accounting covers requested Tree-sitter bytes, not libc metadata or all process memory",
                         "Instrumented edges/call-stack samples and input-read chunks are diagnostics, not PMU branch/cache counters",
                         "No model inference, compilation-on-target, full agent orchestration or network operation is measured"]}
    path = out / "validation.json"
    print(f"Report: {path}", flush=True)
    def save(): path.write_text(json.dumps(report, indent=2) + "\n")
    save()
    try:
        cc, size, nm = tool("clang"), tool("llvm-size"), tool("llvm-nm")
        report["compiler"] = subprocess.check_output([cc, "--version"], text=True).splitlines()[0]
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(ROOT), "-p", "test_*.py", "-v"], check=True, timeout=60)
        inputs = out / "inputs"; inputs.mkdir()
        for name, old, new in cases():
            (inputs / f"{name}.old.json").write_bytes(old)
            (inputs / f"{name}.new.json").write_bytes(new)
        modes = ["native", "instrumented"] + (["sanitized"] if sanitize else [])
        for mode in modes:
            build = out / mode; build.mkdir()
            common = [cc, "-std=c11", "-D_POSIX_C_SOURCE=200809L", "-O2", "-g", "-fno-omit-frame-pointer",
                      "-I" + str(runtime / "lib/include"), "-I" + str(runtime / "lib/src"), "-I" + str(grammar / "src")]
            checks = ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"] if mode == "sanitized" else []
            instrumentation = ["-fsanitize-coverage=trace-pc-guard", "-finstrument-functions"] if mode == "instrumented" else []
            commands = []
            for name, src, upstream in [("runtime", runtime / "lib/src/lib.c", True),
                                        ("grammar", grammar / "src/parser.c", True),
                                        ("baseline", ROOT / "baseline.c", False),
                                        ("profile", ROOT / "profile.c", False)]:
                cmd = common + checks + (instrumentation if upstream else []) + ["-c", str(src), "-o", str(build / f"{name}.o")]
                commands.append(cmd)
            binary = build / "ts-baseline"
            commands.append([cc] + checks + [str(build / f"{n}.o") for n in ("runtime", "grammar", "baseline", "profile")] + ["-o", str(binary)])
            started = time.perf_counter()
            with (build / "build.log").open("w") as log:
                for cmd in commands:
                    subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
            report["builds"][mode] = {"commands": commands, "host_build_seconds": time.perf_counter() - started,
                "executable_bytes": binary.stat().st_size, "executable_sha256": sha(binary),
                "section_sizes": subprocess.check_output([size, "--format=sysv", str(binary), str(build / "runtime.o"), str(build / "grammar.o")], text=True),
                "runtime_undefined_symbols": subprocess.check_output([nm, "--undefined-only", str(build / "runtime.o")], text=True)}
            for name, old, new in cases():
                for kind, args, raw in [("cold_old", [str(inputs / f"{name}.old.json")], old),
                                        ("cold_new", [str(inputs / f"{name}.new.json")], new),
                                        ("incremental", [str(inputs / f"{name}.old.json"), str(inputs / f"{name}.new.json")], new)]:
                    for sample in range(repeat if mode == "native" else 1):
                        proc = subprocess.run([str(binary)] + args, text=True, capture_output=True, check=True, timeout=30,
                                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"})
                        result = json.loads(proc.stdout)
                        checked = check_output(raw, result)
                        if mode == "instrumented" and not result["full_parse"]["edge_visits"]:
                            raise ValueError("Instrumentation did not execute")
                        artifact = build / f"{name}-{kind}-{sample}.json"
                        artifact.write_text(proc.stdout)
                        result.pop("nodes")
                        report["runs"].append({"case": name, "mode": mode, "kind": kind, "sample": sample,
                                              "output": str(artifact.relative_to(out)),
                                              "check": checked, "profile": result, "output_sha256": sha(artifact)})
                print(f"PASS {mode}: {name}", flush=True)
            save()
        if hashes != {str(p.relative_to(WORKLOADS)): sha(p) for p in own}:
            raise ValueError("Harness changed during run")
        sources()
        if any(sha(CACHE / p) != v for p, v in source_hashes.items()): raise ValueError("Upstream changed during run")
        for record in report["runs"]:
            if sha(out / record["output"]) != record["output_sha256"]:
                raise ValueError("Output artifact changed during run")
        if len(report["runs"]) != len(cases()) * 3 * (repeat + 1 + int(sanitize)):
            raise ValueError("Incomplete run matrix")
        report["status"] = "passed"
        report["runs_passed"] = len(report["runs"])
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        save()
    print(f"PASS: {report['runs_passed']} native/reference-checked runs; no HATS execution")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["fetch", "check", "fixtures", "run"])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--sanitize", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20: parser.error("repeat must be 1..20")
    if args.command == "fixtures": print(json.dumps(fixture_manifest(), indent=2))
    elif args.command in ("fetch", "check"):
        sources(args.command == "fetch"); print("Verified pinned clean sources and licenses")
    else: run(args.repeat, args.sanitize)
