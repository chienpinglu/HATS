"""Build a real freestanding LP64 diff executable and byte-exact input cases."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess

from assemble_ape import find_tool
from ape_app_image import decode_elf, DATA_BASE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/ape_app"
SRC = ROOT / "examples/ape_app"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    clang = find_tool("HATS_RV_CLANG", ["/opt/homebrew/opt/llvm/bin/clang", "clang"])
    ld = find_tool("HATS_RV_LD", ["/opt/homebrew/opt/llvm/bin/ld.lld", "/opt/homebrew/opt/lld/bin/ld.lld", "ld.lld"])
    common = [clang, "--target=riscv64-unknown-elf", "-march=rv64i", "-mabi=lp64", "-mno-relax",
              "-O2", "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-pic", "-msmall-data-limit=0"]
    commands = []
    for source in ("start.S", "diff.c"):
        command = common + ["-c", str(SRC / source), "-o", str(OUT / (source + ".o"))]
        commands.append(command)
        subprocess.run(command, check=True, timeout=60)
    command = [ld, "--no-relax", "--no-undefined", "-T", str(SRC / "link.ld"),
               str(OUT / "start.S.o"), str(OUT / "diff.c.o"), "-o", str(OUT / "diff.elf")]
    commands.append(command)
    subprocess.run(command, check=True, timeout=60)
    code, initial, profile = decode_elf((OUT / "diff.elf").read_bytes())
    (OUT / "code.hex").write_text("".join(f"{v:08x}\n" for v in struct.unpack("<1024I", code)))
    # Deliberately poison BSS after the standard ELF zero-fill. Target startup,
    # not a host cleanup, must reinitialize it on each invocation.
    start, end = (profile["symbols"][k] for k in ("__bss_start", "__bss_end"))
    initial[start-DATA_BASE:end-DATA_BASE] = b"\xa5" * (end-start)
    original = (ROOT / "examples/ape/kernel.c").read_bytes()
    assert b"value & 1" in original
    cases = [
        ("empty", b"", b"", 0),
        ("insert", b"", b"int x;\nreturn x;\n", 0),
        ("delete", b"old\nline\n", b"", 0),
        ("replace", b"a\nb\nc\n", b"a\nnew\nc\n", 0),
        ("duplicate_tie", b"a\nb\na\n", b"b\na\nb\n", 0),
        ("line_endings", b"a\r\nb\n", b"a\nb", 0),
        ("binary_bytes", b"a\0b\n\xff\n", b"a\0c\n\xff\n", 0),
        ("repo_source_edit", original, original.replace(b"value & 1", b"value & 3"), 0),
        ("max_lines", b"x\n" * 32, b"x\n" * 31 + b"z\n", 0),
        ("max_bytes", b"a" * 511 + b"\n", b"a" * 510 + b"b\n", 0),
        ("too_many_lines", b"x\n" * 33, b"", 2),
        ("too_many_bytes", b"x" * 513, b"", 1),
    ]
    manifest = {"profile": profile, "commands": commands,
                "clang": subprocess.check_output([clang, "--version"], text=True).splitlines()[0],
                "linker": subprocess.check_output([ld, "--version"], text=True).strip(), "cases": []}
    for name, old, new, status in cases:
        image = bytearray(initial)
        struct.pack_into("<QQ", image, 0x6000, len(old), len(new))
        image[0x6010:0x6010+min(512, len(old))] = old[:512]
        image[0x6210:0x6210+min(512, len(new))] = new[:512]
        image[0x8000:0x9000] = b"\xcc" * 4096
        (OUT / f"{name}.bin").write_bytes(image)
        (OUT / f"{name}.old").write_bytes(old)
        (OUT / f"{name}.new").write_bytes(new)
        manifest["cases"].append({"name": name, "expected_status": status,
                                  "input_sha256": sha(OUT / f"{name}.bin"),
                                  "old_sha256": sha(OUT / f"{name}.old"), "new_sha256": sha(OUT / f"{name}.new")})
    (OUT / "cases.txt").write_text("".join(c["name"] + "\n" for c in manifest["cases"]))
    (OUT / "runtime.properties").write_text(f"exit_pc={profile['symbols']['ape_exit']}\nwritable_start={profile['writable_start']}\nbss_end={end}\n")
    manifest["elf_sha256"] = sha(OUT / "diff.elf")
    manifest["code_sha256"] = sha(OUT / "code.hex")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built LP64 diff executable: {profile['code_bytes']} code bytes, {len(cases)} application cases")


if __name__ == "__main__":
    main()
