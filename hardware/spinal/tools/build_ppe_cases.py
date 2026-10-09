"""Original PPE binaries/inputs and independent architectural reference traces."""
import argparse
import json
from pathlib import Path
import random
import struct
import ppe_isa as p
from ppe_programs import delimiter_candidates


def op(name, **fields): return name, fields


def split(cutoff, yes=None, no=None):
    return [op("MOVI", d=8, imm=cutoff), op("VCMPLTU", d=0, a=0, b=8, flags=2),
            op("SPLIT", p=0, other="else", join="join"), *(yes or [op("VMOVI", d=2, imm=10)]),
            op("JMP", target="join"), "else:", *(no or [op("VMOVI", d=2, imm=20)]),
            "join:", op("JOIN"), op("RETURN")]


def snapshot(wave, trace, instruction):
    return {"pc": trace["pc"], "next_pc": trace["next_pc"], "mask": trace["mask"],
            "active": wave.active, "depth": len(wave.stack), "instruction": str(instruction),
            "scalar": [str(v) for v in wave.scalar], "vector": [[str(v) for v in row] for row in wave.vector],
            "predicate": wave.predicate[:]}


def cases():
    result = []
    def add(name, instructions, scratch=0, data=bytes(4096), **settings):
        result.append((name, p.assemble(instructions, scratch), data, settings))
    add("return", [op("RETURN")])
    for width in (2, 3):
        for extension in (0, 1) if width == 2 else (0,):
            items = [op("MOVI", d=8, imm=-2), op("MOVI", d=9, imm=7)]
            for name in ("MOV", *sorted(p.SCALAR_BINARY)):
                fields = dict(d=10, a=8, width=width, flags=extension)
                if name != "MOV": fields["b"] = 9
                items.append(op(name, **fields))
            items += [op("VMOVI", d=2, imm=-2), op("VMOVI", d=3, imm=7)]
            for broadcast in (0, 2):
                items += [op("VMOV", d=4, a=8 if broadcast else 2, width=width, flags=broadcast|extension)]
                for name in sorted(p.VECTOR_BINARY):
                    items.append(op(name, d=4, a=2, b=9 if broadcast else 3, width=width, flags=broadcast|extension))
                for name in sorted(p.COMPARE):
                    items.append(op(name, d=1, a=2, b=9 if broadcast else 3, width=width, flags=broadcast))
                items.append(op("SELECT", d=5, a=0, b=4, p=1, width=width, flags=extension))
            items += [op("FENCE"), op("BARRIER"), op("RETURN", a=10)]
            add(f"arithmetic_w{width}_e{extension}", items)
    add("conditional_loop", [op("MOVI", d=8, imm=9), op("MOVI", d=9, imm=1), "loop:",
                              op("SUB", d=8, a=8, b=9), op("JNZ", a=8, target="loop"), op("RETURN", a=8)])
    for cutoff in (0, 3, 8): add(f"split_{cutoff}", split(cutoff))
    add("nested_mixed", [op("MOVI", d=8, imm=4), op("MOVI", d=9, imm=2),
        op("VCMPLTU", d=0, a=0, b=8, flags=2), op("VCMPLTU", d=1, a=0, b=9, flags=2), op("VCMPEQ", d=2, a=0, b=0),
        op("SPLIT", p=0, other="outer_else", join="outer_join"), op("VCMPLTU", d=2, a=0, b=0),
        op("SPLIT", p=1, other="inner_else", join="inner_join"), op("VMOVI", d=3, imm=10),
        op("JMP", target="inner_join"), "inner_else:", op("VMOVI", d=3, imm=20), "inner_join:", op("JOIN"),
        op("JMP", target="outer_join"), "outer_else:", op("VMOVI", d=3, imm=30), "outer_join:", op("JOIN"), op("RETURN")])
    add("empty_then", [op("MOVI", d=8, imm=4), op("VCMPLTU", d=0, a=0, b=8, flags=2),
        op("SPLIT", p=0, other="else", join="join"), op("JMP", target="join"), "else:",
        op("VMOVI", d=3, imm=7), "join:", op("JOIN"), op("RETURN")])
    add("empty_else", [op("MOVI", d=8, imm=4), op("VCMPLTU", d=0, a=0, b=8, flags=2),
                       op("SPLIT", p=0, other="join", join="join"), op("VMOVI", d=3, imm=7),
                       op("JMP", target="join"), "join:", op("JOIN"), op("RETURN")])
    def nested(depth):
        if not depth: return [op("VMOVI", d=2, imm=99)]
        return [op("SPLIT", p=0, other=f"e{depth}", join=f"j{depth}"), *nested(depth-1),
                op("JMP", target=f"j{depth}"), f"e{depth}:", f"j{depth}:", op("JOIN")]
    for depth in (8, 9): add(f"depth_{depth}", [op("VCMPEQ", d=0, a=0, b=0), *nested(depth), op("RETURN")])
    for name in ("MOVI", "LOAD", "STORE", "FENCE", "BARRIER", "RETURN"):
        instruction = op(name, d=9, imm=1) if name == "MOVI" else op(name)
        add("nonuniform_" + name.lower(), split(8, [instruction]))
    for space in (0, 2):
        for width in range(4):
            items = [op("MOVI", d=8, imm=128), op("MOVI", d=9, imm=-128),
                     op("STORE", d=9, a=8, width=width, flags=space),
                     op("LOAD", d=10, a=8, width=width, flags=space),
                     op("LOAD", d=11, a=8, width=width, flags=space | int(width < 3)),
                     op("MOVI", d=12, imm=width), op("VSHL", d=2, a=0, b=12, flags=2),
                     op("VMOVI", d=3, imm=-128), op("VSTORE", d=3, a=8, b=2, width=width, flags=space),
                     op("VLOAD", d=4, a=8, b=2, width=width, flags=space | int(width < 3)),
                     op("FENCE"), op("BARRIER"), op("RETURN", a=11)]
            add(f"memory_s{space}_w{width}", items, scratch=256 if space else 0)
    add("load_error", [op("VMOVI", d=2, imm=99), op("MOVI", d=8, imm=3),
                       op("VSHL", d=3, a=0, b=8, flags=2), op("VLOAD", d=2, a=0, b=3), op("RETURN")], fail=8)
    add("store_partial", [op("MOVI", d=8, imm=100), op("VADD", d=2, a=0, b=8, flags=2),
                          op("MOVI", d=9, imm=3), op("VSHL", d=3, a=0, b=9, flags=2),
                          op("VSTORE", d=2, a=0, b=3), op("RETURN")], fail=16)
    for name, instructions, settings in (
        ("alignment", [op("LOAD", d=8, imm=1), op("RETURN")], {}),
        ("readonly", [op("STORE", d=8), op("RETURN")], {"writable": 0}),
        ("range", [op("LOAD", d=8, imm=4096), op("RETURN")], {}),
        ("underflow", [op("LOAD", d=8, imm=-1, width=0), op("RETURN")], {}),
        ("overflow", [op("MOVI", d=8, imm=-1), op("LOAD", d=9, a=8, imm=1, width=0), op("RETURN")], {}),
        ("scratch_bounds", [op("LOAD", d=8, flags=2), op("RETURN")], {}),
        ("falloff", [op("VMOVI", d=2, imm=1)], {})):
        add(name, instructions, **settings)
    add("masked_invalid", [op("MOVI", d=9, imm=3), op("VSHL", d=4, a=0, b=9, flags=2)] +
        split(4, [op("VLOAD", d=2, a=0, b=4)]), data=struct.pack("<4Q", 11, 22, 33, 44))
    add("stale_reply", [op("LOAD", d=8), op("RETURN", a=8)], data=struct.pack("<Q", 1234), stale=1)
    # Raw decoder probes intentionally bypass the trusted code-object loader.
    for index, word in enumerate((0, 255, 37 | (1 << 30), 3, 3 | (3 << 26) | (2 << 28),
                                  23 | (8 << 8) | (3 << 26), 32 | (1 << 28), 37 | (1 << 32), 30 | (1 << 8))):
        add(f"raw_illegal_{index}", [op("RETURN")], kind=1, raw=word)
    for name, override, reason in (("code_empty", {"codeWords": 0}, 7), ("code_capacity", {"codeWords": 1025}, 7),
                                  ("scratch_capacity", {"scratchBytes": 4112}, 7), ("scratch_alignment", {"scratchBytes": 1}, 7),
                                  ("no_groups", {"groups": 0}, 8), ("group_bounds", {"group": 1}, 8),
                                  ("no_task", {"task": 0}, 8), ("no_budget", {"budget": 0}, 8),
                                  ("bad_range", {"limit": 0}, 8), ("argument_overflow", {"argument": p.MASK, "argumentBytes": 2}, 8)):
        add("reject_" + name, [op("RETURN")], kind=2, reason=reason, **override)
    for name, delay, ready in (("late_response", 80, 0), ("held_request", 2, 560)):
        add("budget_" + name, [op("MOVI", d=8, imm=99), op("VMOV", d=2, a=8, flags=2),
                              op("VSTORE", d=2, a=0, b=0, width=0), op("RETURN")],
            kind=3, budget=540, delay=delay, readyAfter=ready)
    add("never_responds", [op("LOAD", d=8), op("RETURN")], kind=4, budget=540)
    for size in (0, 1, 8, 9, 53, 256):
        data = bytearray(b"\xa5" * 2048)
        raw = bytes(range(256))[:size] if size != 53 else b'{"text":"literal { in string","values":[1,2,3]}'.ljust(53, b" ")
        assert len(raw) == size
        struct.pack_into("<3Q", data, 0, 256, 1024, len(raw)); data[256:256+len(raw)] = raw
        for group in range(max(1, (len(raw)+7)//8)):
            result.append((f"delimiter_{size}_g{group}", delimiter_candidates(), bytes(data),
                           {"argumentBytes": 24, "group": group, "groups": max(1, (len(raw)+7)//8)}))
    rng = random.Random(0x48415453)
    for sample in range(8):
        items = [op("MOVI", d=r, imm=rng.randrange(-(1 << 31), 1 << 31)) for r in range(8, 32)]
        items += [op("VMOV", d=r, a=r, flags=2) for r in range(8, 32)]
        for _ in range(64):
            name = rng.choice(sorted(p.SCALAR_BINARY | p.VECTOR_BINARY | p.COMPARE))
            width = rng.choice([2, 3]); flags = 0
            if name in p.VECTOR_BINARY | p.COMPARE: flags |= rng.choice([0, 2])
            if name not in p.COMPARE and width == 2: flags |= rng.randrange(2)
            items.append(op(name, d=rng.randrange(8) if name in p.COMPARE else rng.randrange(8, 32),
                            a=rng.randrange(8, 32), b=rng.randrange(8, 32), width=width, flags=flags))
        add(f"random_{sample}", items + [op("RETURN", a=8)])
    return result


def build(out):
    out.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name, raw, data, settings in cases():
        folder = out / name; folder.mkdir(exist_ok=True)
        code = p.Code.decode(raw)
        options = dict(task=7, epoch=11, addressSpace=2, generation=3, argument=0, argumentBytes=0,
                       group=0, groups=1, budget=1000000, base=0, limit=len(data), writable=1,
                       scratchBytes=code.scratch_bytes, codeWords=len(code.instructions), fail=-1, stale=0,
                       kind=0, delay=0, readyAfter=0)
        options.update(settings)
        (folder / "case.properties").write_text("".join(f"{k}={v}\n" for k, v in options.items()))
        words = [int.from_bytes(i.encode(), "little") for i in code.instructions]
        if options["kind"] == 1: words[0] = options["raw"]
        (folder / "code.hex").write_text("".join(f"{word:016x}\n" for word in words))
        (folder / "code.bin").write_bytes(raw[:p.HEADER.size] + b"".join(struct.pack("<Q", w) for w in words))
        (folder / "memory.bin").write_bytes(data)
        memory = p.Memory(data, base=options["base"], writable=bool(options["writable"]), fail_addresses=[options["fail"]])
        launch = dict(argument=options["argument"], argument_bytes=options["argumentBytes"],
                      group=options["group"], groups=options["groups"], task=options["task"])
        wave = p.Wave(raw, memory, **({} if options["kind"] == 2 else launch))
        if options["kind"] == 2:
            wave.scalar[:7] = [options["argument"], options["argumentBytes"], options["group"], options["groups"], 8, 0, options["task"]]
        snapshots, ordered_access = [], []
        for _ in range(10000 if options["kind"] == 0 else 2 if options["kind"] == 3 else 0):
            old_pc, old_count = wave.pc, len(wave.trace)
            old_global, old_scratch = len(memory.events), len(wave.scratch.events)
            wave.step()
            for is_scratch, events in ((False, memory.events[old_global:]), (True, wave.scratch.events[old_scratch:])):
                ordered_access += [dict(event, scratch=is_scratch, retirement_index=old_count) for event in events]
            if len(wave.trace) > old_count:
                snapshots.append(snapshot(wave, wave.trace[-1], int.from_bytes(code.instructions[old_pc].encode(), "little")))
            if wave.completion is not None: break
        if options["kind"] == 0 and wave.completion is None: raise ValueError("Reference did not terminate: " + name)
        if options["kind"] in (1, 2):
            wave.completion = {"status": "rejected" if options["kind"] == 2 else "fault",
                               "cause": options.get("reason", 1), "pc": 0, "address": 0, "lane_mask": 0}
        if options["kind"] == 3:
            # Clock-budget oracle: first store was offered before expiry and must
            # drain, but no subsequent lane may be issued and no store retires.
            memory.access(0, 1, store=True, value=99, lane=0)
            ordered_access.append(dict(memory.events[-1], scratch=False, retirement_index=2))
            wave.completion = {"status": "fault", "cause": 5, "pc": 16, "address": 0, "lane_mask": 0}
        if options["kind"] == 4: wave.completion = {"status": "quiescence_required"}
        completion = dict(wave.completion)
        if "value" in completion: completion["value"] = str(completion["value"])
        golden = {"kind": options["kind"], "trace": snapshots, "completion": completion, "ordered_access": ordered_access, "global": memory.events,
                  "scratch": wave.scratch.events, "scalar": [str(x) for x in wave.scalar],
                  "vector": [[str(x) for x in row] for row in wave.vector], "predicate": wave.predicate,
                  "active": wave.active, "depth": len(wave.stack)}
        (folder / "reference.json").write_text(json.dumps(golden) + "\n")
        (folder / "reference.memory.bin").write_bytes(memory.data)
        (folder / "reference.scratch.bin").write_bytes(wave.scratch.data + bytes(4096-len(wave.scratch.data)))
        manifest.append({"name": name, "kind": options["kind"], "instructions": len(code.instructions), "retired": len(snapshots),
                         "opcodes": sorted({i.op for i in code.instructions}), "status": completion["status"]})
    (out / "cases.txt").write_text("\n".join(r["name"] for r in manifest) + "\n")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "build/ppe/cases")
    args = parser.parse_args()
    print(f"Built {len(build(args.out))} independently executed PPE cases")
