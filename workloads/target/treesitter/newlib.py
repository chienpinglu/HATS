"""Local-only, pinned Newlib RV64I build; does not install into the system."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
WORKLOADS = ROOT.parents[1]
CACHE = WORKLOADS / "cache"
LOCK = ROOT / "newlib.lock.json"
BUILD = CACHE / "newlib-rv64i-build"
FLAGS = ["--target=riscv64-unknown-elf", "--disable-multilib", "--disable-libgloss",
         "--disable-shared", "--disable-nls", "--disable-newlib-supplied-syscalls",
         "--disable-newlib-multithread", "--disable-newlib-io-float"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tool(name):
    for prefix in ("/opt/homebrew/opt/llvm/bin", "/opt/homebrew/opt/lld/bin"):
        if (Path(prefix) / name).is_file(): return str(Path(prefix) / name)
    result = shutil.which(name)
    if not result: raise RuntimeError(f"Missing required tool: {name}")
    return result


def source(fetch=False):
    lock = json.loads(LOCK.read_text())
    if lock["release"] != "newlib-4.5.0.20241231" or lock["url"] != "https://sourceware.org/pub/newlib/" + lock["release"] + ".tar.gz":
        raise ValueError("Unexpected Newlib source identity")
    archive = CACHE / (lock["release"] + ".tar.gz")
    if not archive.exists() and fetch:
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(lock["url"], timeout=90) as stream:
            raw = stream.read(16 * 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != lock["archive_sha256"]:
            raise ValueError("Newlib download digest mismatch")
        with archive.open("xb") as out: out.write(raw)
    if sha(archive) != lock["archive_sha256"]: raise ValueError("Newlib archive changed")
    src = CACHE / lock["release"]
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        for m in members:
            path = PurePosixPath(m.name)
            if path.is_absolute() or ".." in path.parts or path.parts[0] != lock["release"] or not (m.isfile() or m.isdir()):
                raise ValueError("Unsafe archive member")
        if not src.exists(): tar.extractall(CACHE, filter="data")
        expected = {m.name for m in members if m.isfile()}
        actual = {str(p.relative_to(CACHE)) for p in src.rglob("*") if p.is_file() or p.is_symlink()}
        if actual != expected: raise ValueError("Unexpected or missing Newlib source files")
        # Verify the complete extracted tree against the locked archive; never overwrite edits.
        for m in members:
            p = CACHE / m.name
            if p.is_symlink() or not p.resolve().is_relative_to(src.resolve()):
                raise ValueError("Source path escapes extraction root")
            if m.isfile():
                if not p.is_file() or sha(p) != hashlib.sha256(tar.extractfile(m).read()).hexdigest():
                    raise ValueError(f"Newlib source changed: {m.name}")
    if sha(src / "COPYING.NEWLIB") != lock["license_sha256"]:
        raise ValueError("Newlib license identity mismatch")
    return src


def configuration():
    cc = tool("clang") + " --target=riscv64-unknown-elf -march=rv64i -mabi=lp64 -mno-relax"
    variables = {"CC_FOR_TARGET": cc, "GCC_FOR_TARGET": cc,
                 "AR_FOR_TARGET": tool("llvm-ar"), "RANLIB_FOR_TARGET": tool("llvm-ranlib"),
                 "LD_FOR_TARGET": tool("ld.lld"), "NM_FOR_TARGET": tool("llvm-nm"),
                 "AS_FOR_TARGET": cc, "OBJDUMP_FOR_TARGET": tool("llvm-objdump"),
                 "READELF_FOR_TARGET": tool("llvm-readelf"),
                 "CFLAGS_FOR_TARGET": "-O2 -g0 -ffunction-sections -fdata-sections -fno-stack-protector -msmall-data-limit=0"}
    return variables


def check():
    source()
    stamp = json.loads((BUILD / "hats-build.json").read_text())
    if stamp.get("status") != "passed" or stamp["lock_sha256"] != sha(LOCK) or stamp["builder_sha256"] != sha(__file__):
        raise ValueError("Missing or stale Newlib build evidence")
    if stamp["flags"] != FLAGS or stamp["variables"] != configuration():
        raise ValueError("Newlib configuration changed")
    if stamp["compiler"] != subprocess.check_output([tool("clang"), "--version"], text=True).splitlines()[0]:
        raise ValueError("Compiler identity changed; rebuild Newlib")
    if set(stamp["artifacts"]) != {str(p.relative_to(BUILD)) for p in artifacts()}:
        raise ValueError("Incomplete Newlib artifact manifest")
    for p, digest in stamp["artifacts"].items():
        if sha(BUILD / p) != digest: raise ValueError(f"Newlib artifact changed: {p}")
    return stamp


def artifacts():
    return [BUILD / "riscv64-unknown-elf/newlib/libc.a", BUILD / "riscv64-unknown-elf/newlib/newlib.h"] + sorted(
        p for p in (BUILD / "riscv64-unknown-elf/newlib/targ-include").rglob("*") if p.is_file())


def build(jobs, rebuild=False):
    src = source()
    BUILD.mkdir(parents=True, exist_ok=True)
    if (BUILD / "hats-build.json").exists():
        previous = json.loads((BUILD / "hats-build.json").read_text())
        if rebuild and (previous.get("variables") != configuration() or previous.get("flags") != FLAGS):
            raise ValueError("Changed compiler flags need a fresh build directory, not mixed cached objects")
        if previous.get("status") == "passed" and not rebuild:
            check(); print("Verified existing Newlib build"); return
    variables = configuration()
    env = {"PATH": "/opt/homebrew/opt/llvm/bin:/opt/homebrew/opt/lld/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin", "LC_ALL": "C"}
    (BUILD / "tmp").mkdir(exist_ok=True)
    env["TMPDIR"] = str(BUILD / "tmp")
    env.update(variables)
    config = [str(src / "configure"), *FLAGS, "--prefix=" + str(BUILD / "unused-install")]
    make = ["make", f"-j{jobs}", "all-target-newlib", "MAKEINFO=true"]
    stamp = {"schema": 1, "status": "running", "lock_sha256": sha(LOCK), "builder_sha256": sha(__file__),
             "flags": FLAGS, "variables": variables, "commands": [config, make],
             "compiler": subprocess.check_output([tool("clang"), "--version"], text=True).splitlines()[0]}
    stamp_path = BUILD / "hats-build.json"
    try:
        for name, command, timeout in (("configure", config, 180), ("build", make, 600)):
            print(f"Newlib {name}; log {BUILD / (name + '.log')}", flush=True)
            with (BUILD / (name + ".log")).open("w") as log:
                subprocess.run(command, cwd=BUILD, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=timeout)
        source()
        stamp["artifacts"] = {str(p.relative_to(BUILD)): sha(p) for p in artifacts()}
        stamp["status"] = "passed"
    except Exception as exc:
        stamp.update(status="failed", error=str(exc)); raise
    finally:
        stamp_path.write_text(json.dumps(stamp, indent=2) + "\n")
    print("Pinned RV64I Newlib libc built locally; no target application executed")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("command", choices=("fetch", "check", "build"))
    p.add_argument("--jobs", type=int, default=4)
    p.add_argument("--rebuild", action="store_true", help="Rerun unchanged compiler configuration and refresh evidence")
    a = p.parse_args()
    if not 1 <= a.jobs <= 8: p.error("Use 1 to 8 build jobs")
    if a.command == "fetch": source(True); print("Verified Newlib source archive/tree")
    elif a.command == "check": check(); print("Verified pinned Newlib build")
    else: build(a.jobs, a.rebuild)
