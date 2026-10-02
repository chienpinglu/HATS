"""Shared Java discovery for the build wrapper and verification manifest."""
import os
from pathlib import Path
import shutil

def java_path():
    override = os.environ.get("HATS_JAVA")
    if override:
        return override
    candidates = []
    if os.environ.get("JAVA_HOME"):
        candidates.append(Path(os.environ["JAVA_HOME"]) / "bin/java")
    candidates.append(Path("/opt/homebrew/opt/openjdk/bin/java"))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    found = shutil.which("java")
    if not found:
        raise RuntimeError("Install a JDK or set HATS_JAVA to its java executable")
    return found

if __name__ == "__main__":
    print(java_path())
