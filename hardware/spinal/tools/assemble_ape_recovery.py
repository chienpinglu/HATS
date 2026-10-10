#!/usr/bin/env python3
"""Assemble the original early-recovery witnesses; keep the standard suite intact."""
import hashlib
import json
from pathlib import Path
import subprocess
from assemble_ape import ROOT, find_tool, extract

OUT = ROOT / "build/ape_recovery/programs"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    clang = find_tool("HATS_RV_CLANG", ["/opt/homebrew/opt/llvm/bin/clang", "clang"])
    linker = find_tool("HATS_RV_LD", ["/opt/homebrew/opt/lld/bin/ld.lld", "ld.lld"])
    source = ROOT / "examples/ape_recovery/programs.S"
    manifest = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "programs": {}}
    for i in range(6):
        name = f"recovery{i}"
        obj, elf, image = [OUT / (name + ext) for ext in (".o", ".elf", ".hex")]
        subprocess.run([clang, "--target=riscv64-unknown-elf", "-march=rv64i", "-mabi=lp64", "-mno-relax",
                        f"-DAPE_RECOVERY_TEST={i}", "-c", str(source), "-o", str(obj)], check=True)
        subprocess.run([linker, "--no-relax", "-T", str(ROOT / "examples/ape/link.ld"), str(obj), "-o", str(elf)], check=True)
        image.write_text("".join(f"{w:08x}\n" for w in extract(elf)))
        manifest["programs"][name] = {"elf_sha256": hashlib.sha256(elf.read_bytes()).hexdigest(),
                                      "image_sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Built six real RV64I recovery witness images")


if __name__ == "__main__":
    main()
