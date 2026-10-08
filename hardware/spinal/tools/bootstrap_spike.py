#!/usr/bin/env python3
"""Build pinned upstream Spike and the original APE environment adapter locally."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "tools/spike.lock.json"
SOURCE = ROOT / ".tools/spike-src"
BUILD = ROOT / ".tools/spike-build"
ADAPTER = ROOT / "tools/spike_adapter.cc"
STAMP = BUILD / "ape-build.json"
BINARY = BUILD / "ape-spike"
LIBRARIES = [f"lib{n}.a" for n in ("riscv", "disasm", "softfloat", "fesvr", "fdt")]
FLAGS = ["--without-boost", "--without-boost-asio", "--without-boost-regex",
         "CXX=clang++", "CC=clang", "CXXFLAGS=-O1 -g0"]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_check(lock):
    revision = subprocess.check_output(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(SOURCE), "status", "--porcelain", "--untracked-files=all"], text=True)
    if revision != lock["revision"] or dirty:
        raise RuntimeError("Spike source is not the pinned unmodified checkout; inspect it, do not overwrite it")
    if digest(SOURCE / "LICENSE") != lock["license_sha256"]:
        raise RuntimeError("Spike license identity mismatch")


def check():
    lock = json.loads(LOCK.read_text())
    source_check(lock)
    stamp = json.loads(STAMP.read_text())
    if stamp.get("status") != "passed" or stamp["revision"] != lock["revision"]:
        raise RuntimeError("No valid pinned Spike build")
    if stamp["lock_sha256"] != digest(LOCK) or stamp["adapter_sha256"] != digest(ADAPTER):
        raise RuntimeError("Spike adapter/lock changed; rebuild with bootstrap_spike.py")
    if stamp["configure_flags"] != FLAGS:
        raise RuntimeError("Spike build flags mismatch")
    for name, sha in stamp["artifacts"].items():
        if digest(BUILD / name) != sha:
            raise RuntimeError(f"Spike build artifact changed: {name}")
    if set(stamp["artifacts"]) != set(LIBRARIES + ["ape-spike", "config.h", "Makefile"]):
        raise RuntimeError("Incomplete Spike build evidence")
    return stamp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Offline identity check; no build/download")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.check:
        check()
        print("Pinned Spike source, adapter and build identities verified")
        return
    if not 1 <= args.jobs <= 16:
        raise ValueError("Use 1 to 16 build jobs")
    lock = json.loads(LOCK.read_text())
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    for tool in ("git", "make", "clang", "clang++", "dtc"):
        if not shutil.which(tool, path=env["PATH"]):
            raise RuntimeError(f"Install missing Spike build dependency: {tool}")
    if not SOURCE.exists():
        SOURCE.mkdir(parents=True)
        subprocess.run(["git", "init", str(SOURCE)], check=True, env=env)
        subprocess.run(["git", "-C", str(SOURCE), "fetch", "--depth", "1", lock["repository"], lock["revision"]],
                       check=True, env=env, timeout=180)
        subprocess.run(["git", "-C", str(SOURCE), "checkout", "--detach", "FETCH_HEAD"], check=True, env=env)
    source_check(lock)
    BUILD.mkdir(parents=True, exist_ok=True)
    stamp = {"status": "running", "revision": lock["revision"], "lock_sha256": digest(LOCK),
             "adapter_sha256": digest(ADAPTER), "configure_flags": FLAGS,
             "started_utc": datetime.now(timezone.utc).isoformat()}
    STAMP.write_text(json.dumps(stamp, indent=2) + "\n")
    try:
        stamp["compiler"] = subprocess.check_output(["clang++", "--version"], env=env, text=True).splitlines()[0]
        with (BUILD / "configure.log").open("w") as log:
            subprocess.run([str(SOURCE / "configure")] + FLAGS, cwd=BUILD, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        with (BUILD / "build.log").open("w") as log:
            subprocess.run(["make", f"-j{args.jobs}"] + LIBRARIES, cwd=BUILD, env=env,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        include_dirs = [BUILD, SOURCE] + [SOURCE / d for d in ("riscv", "disasm", "fesvr", "softfloat")]
        command = ["clang++", "-std=c++20", "-O1", "-g0"] + [f"-I{d}" for d in include_dirs]
        command += [str(ADAPTER)] + [str(BUILD / n) for n in LIBRARIES] + ["-lpthread", "-o", str(BINARY)]
        subprocess.run(command, env=env, check=True, timeout=180)
        source_check(lock)
        if digest(ADAPTER) != stamp["adapter_sha256"] or digest(LOCK) != stamp["lock_sha256"]:
            raise RuntimeError("Adapter or lock changed while building")
        stamp["artifacts"] = {n: digest(BUILD / n) for n in LIBRARIES + ["ape-spike", "config.h", "Makefile"]}
        stamp["status"] = "passed"
    except Exception as e:
        stamp["status"] = "failed"
        stamp["error"] = str(e)
        raise
    finally:
        stamp["finished_utc"] = datetime.now(timezone.utc).isoformat()
        STAMP.write_text(json.dumps(stamp, indent=2) + "\n")
    print("Built pinned Spike adapter; upstream instruction semantics unchanged")


if __name__ == "__main__":
    main()
