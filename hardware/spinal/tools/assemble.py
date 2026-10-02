#!/usr/bin/env python3
"""Extract fully resolved Clang A64 ELF sections into simulation program images."""
from pathlib import Path
import hashlib
import json
import struct
import subprocess

root = Path(__file__).resolve().parents[1]
out = root / "build" / "programs"
out.mkdir(parents=True, exist_ok=True)
source = root / "examples" / "workloads.s"
obj = out / "workloads.o"
subprocess.run(["clang", "-target", "aarch64-none-elf", "-c", str(source), "-o", str(obj)], check=True)
raw = obj.read_bytes()
assert raw[:6] == b"\x7fELF\x02\x01"
offset = struct.unpack_from("<Q", raw, 40)[0]
size, count, string_index = struct.unpack_from("<HHH", raw, 58)
headers = [struct.unpack_from("<IIQQQQIIQQ", raw, offset + i * size) for i in range(count)]
sh = headers[string_index]
names = raw[sh[4]:sh[4] + sh[5]]
manifest = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "programs": {}}
for h in headers:
    assert h[1] not in (4, 9) or h[5] == 0, "unresolved relocation"
    name = names[h[0]:].split(b"\0")[0].decode()
    if not name.startswith(".text."):
        continue
    data = raw[h[4]:h[4] + h[5]]
    assert len(data) % 4 == 0 and len(data) <= 1024
    words = struct.unpack("<" + "I" * (len(data) // 4), data)
    short = name.removeprefix(".text.")
    (out / (short + ".hex")).write_text("".join(f"{word:08x}\n" for word in words))
    manifest["programs"][short] = {"words": len(words), "sha256": hashlib.sha256(data).hexdigest()}
(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Assembled {len(manifest['programs'])} real A64 program images")
