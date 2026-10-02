#!/usr/bin/env python3
"""Fetch only the pinned public sbt launcher, with a fixed SHA-256 check."""
from pathlib import Path
import argparse
import hashlib
import urllib.request

URL = "https://repo.maven.apache.org/maven2/org/scala-sbt/sbt-launch/1.10.7/sbt-launch-1.10.7.jar"
SHA256 = "3cca02818047327a83efde776103a1ef92f76f72c062badbbb062499a3270c07"
DEST = Path(__file__).resolve().parents[1] / ".tools/sbt-launch-1.10.7.jar"

def valid(path):
    return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == SHA256

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Verify only; no network or writes")
    args = parser.parse_args()
    if valid(DEST):
        return
    if args.check:
        raise SystemExit("Missing or invalid sbt launcher; run python3 tools/bootstrap.py")
    if DEST.exists():
        raise SystemExit("Existing sbt launcher has a checksum mismatch; inspect it before replacing")
    DEST.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit("Downloaded sbt launcher failed SHA-256 verification")
    with DEST.open("xb") as output:
        output.write(data)
    print("Installed verified sbt launcher 1.10.7")

if __name__ == "__main__":
    main()
