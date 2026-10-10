#!/usr/bin/env python3
"""Pinned local research-library and native ABC tools for early S03 timing.

Downloads stay ignored. No system installation or manufacturing-PDK claim.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request

HW = Path(__file__).resolve().parents[1]
OUT = HW / ".tools/s03-timing"
ORFS_REVISION = "ef421749a1050a8e9a197e7dfcd05396807f889d"
ABC_REVISION = "a3001b72edc5de22442e942165487fddf150e3d0"
LIBRARY_SHA = "8d540a4d4cf6d09d27c87ad067857a9c0c2eeb023ab7a56e058cd3113db4e9b1"
LICENSE_SHA = "0d542e0c8804e39aa7f37eb00da5a762149dc682d7829451287e11b938e94594"
ARCHIVE_SHA = "25539755a180775d0db33f377301cbbf6c4d2dfdb561efec091158b2974e3b57"
LIBRARY = OUT / "nangate45/NangateOpenCellLibrary_typical.lib"
ABC_SOURCE = OUT / ("abc-" + ABC_REVISION)
ABC = ABC_SOURCE / "abc"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def source_hashes():
    # Only upstream build/source inputs, not mutable object/dependency files.
    paths = [p for p in ABC_SOURCE.rglob("*") if p.is_file() and
             (p.suffix in (".c", ".cc", ".cpp", ".h", ".hpp", ".mk") or
              p.name in ("Makefile", "copyright.txt", ".gitcommit", "depends.sh"))]
    return {str(p.relative_to(ABC_SOURCE)): sha(p) for p in sorted(paths)}


def fetch(url, path, digest):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with urllib.request.urlopen(url, timeout=120) as response:
            path.write_bytes(response.read())
    require(sha(path) == digest, "Downloaded/local artifact differs from lock: " + str(path))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    base = f"https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD-flow-scripts/{ORFS_REVISION}/flow/platforms/nangate45/"
    fetch(base + "lib/" + LIBRARY.name, LIBRARY, LIBRARY_SHA)
    fetch(base + "LICENSE", LIBRARY.parent / "LICENSE", LICENSE_SHA)
    archive = OUT / "abc-a3001b7.tar.gz"
    fetch(f"https://codeload.github.com/berkeley-abc/abc/tar.gz/{ABC_REVISION}", archive, ARCHIVE_SHA)
    with tarfile.open(archive, "r:gz") as source:
        # Extraction is fresh-only; never overwrite an existing local checkout.
        if not ABC_SOURCE.exists():
            source.extractall(OUT, filter="data")
        for member in source.getmembers():
            require(member.name == ABC_SOURCE.name or member.name.startswith(ABC_SOURCE.name + "/"), "Unexpected archive root")
            if member.isfile():
                path = OUT / member.name
                require(path.resolve().is_relative_to(ABC_SOURCE.resolve()), "Archive traversal")
                require(path.is_file() and sha(path) == hashlib.sha256(source.extractfile(member).read()).hexdigest(),
                        "Local ABC source differs from pinned archive: " + member.name)
    before = source_hashes()
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    command = ["make", "-j4", "ABC_USE_NO_READLINE=1"]
    with (OUT / "abc-build.log").open("w") as log:
        subprocess.run(command, cwd=ABC_SOURCE, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    require(before == source_hashes() and ABC.is_file(), "ABC build changed source or did not produce executable")
    report = {"schema": 1, "status": "built", "abc_revision": ABC_REVISION,
              "abc_archive_sha256": ARCHIVE_SHA, "abc_source_sha256": before,
              "abc_executable_sha256": sha(ABC), "command": command,
              "compiler": subprocess.check_output(["cc", "--version"], text=True).splitlines()[0],
              "orfs_revision": ORFS_REVISION, "liberty_sha256": LIBRARY_SHA,
              "license_sha256": LICENSE_SHA,
              "limits": ["Nangate45 is a non-manufacturable generic research library",
                         "Native ABC is an analysis tool, not processor RTL or licensed manufacturing IP"]}
    (OUT / "tools.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Pinned local timing tools ready: " + str(OUT / "tools.json"))


if __name__ == "__main__":
    main()
