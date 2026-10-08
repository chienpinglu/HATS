"""Strict architectural-event comparison; no instruction execution semantics."""
import json
from pathlib import Path


class Divergence(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Divergence(f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def validate(events):
    if not events or len(events) > 500000:
        raise Divergence("Empty or excessive architectural trace")
    fields = {"retire": {"kind", "pc", "instruction", "writes", "rd", "value", "next"},
              "memory": {"kind", "address", "bytes", "write", "data", "error"},
              "trap": {"kind", "pc", "cause", "value"}}
    for i, event in enumerate(events):
        if not isinstance(event, dict) or event.get("kind") not in fields:
            raise Divergence(f"Unknown event at {i}")
        kind = event["kind"]
        if set(event) != fields[kind]:
            raise Divergence(f"Wrong fields at {i}")
        for name in ("pc", "next", "value", "address", "data"):
            if name in event:
                v = event[name]
                if not isinstance(v, str) or not v.isascii() or not v.isdigit() or str(int(v)) != v or not 0 <= int(v) < 2**64:
                    raise Divergence(f"Noncanonical uint64 at {i}/{name}")
        for name in ("writes", "write", "error"):
            if name in event and type(event[name]) is not bool:
                raise Divergence(f"Invalid boolean at {i}/{name}")
        if kind == "retire":
            if type(event["instruction"]) is not int or not 0 <= event["instruction"] < 2**32:
                raise Divergence("Invalid instruction")
            if type(event["rd"]) is not int or not 0 <= event["rd"] < 32:
                raise Divergence("Invalid destination")
            if event["writes"] != (event["rd"] != 0) or (not event["writes"] and event["value"] != "0"):
                raise Divergence("Invalid destination normalization")
        if kind == "memory":
            if type(event["bytes"]) is not int or event["bytes"] not in (1, 2, 4, 8):
                raise Divergence("Invalid access width")
            if int(event["data"]) >= 2**(8*event["bytes"]):
                raise Divergence("Memory data exceeds access width")
        if kind == "trap":
            if type(event["cause"]) is not int or not 0 <= event["cause"] < 64 or i != len(events)-1:
                raise Divergence("Invalid or nonterminal trap")
    if events[-1]["kind"] != "trap":
        raise Divergence("Trace missing terminal trap")


def read_trace(path):
    events = [json.loads(line, object_pairs_hook=unique_object) for line in Path(path).read_text().splitlines()]
    validate(events)
    return events


def equal_events(rtl, spike):
    if len(rtl) != len(spike):
        raise Divergence(f"Event count differs: RTL={len(rtl)}, Spike={len(spike)}")
    for i, (actual, expected) in enumerate(zip(rtl, spike)):
        if actual != expected:
            raise Divergence(f"Event {i} differs: RTL={actual}; Spike={expected}")


def compare(rtl, spike, profile="shared"):
    validate(rtl)
    validate(spike)
    if profile == "shared":
        equal_events(rtl, spike)
        return {"status": "matched", "events": len(rtl),
                "retirements": sum(e["kind"] == "retire" for e in rtl),
                "memory_events": sum(e["kind"] == "memory" for e in rtl)}
    if profile == "fence_i_gap":
        # Exact, reviewed boundary, not a general permission to ignore mismatches.
        if len(rtl) != 2 or len(spike) != 3:
            raise Divergence("FENCE.I profile shape changed")
        equal_events(rtl[:1], spike[:1])
        equal_events(rtl[-1:], [{"kind": "trap", "pc": "4", "cause": 2, "value": "42"}])
        equal_events(spike[1:], [
            {"kind": "retire", "pc": "4", "instruction": 0x100f, "writes": False, "rd": 0, "value": "0", "next": "8"},
            {"kind": "trap", "pc": "8", "cause": 3, "value": "42"}])
        return {"status": "expected_profile_difference", "matched_prefix_retirements": 1,
                "reason": "Spike implicitly supports Zifencei; APE does not"}
    if profile == "launch_alignment_gap":
        equal_events(rtl, [{"kind": "trap", "pc": "2", "cause": 0, "value": "0"}])
        equal_events(spike, [{"kind": "trap", "pc": "0", "cause": 2, "value": "0"}])
        return {"status": "expected_profile_difference", "matched_prefix_retirements": 0,
                "reason": "APE launch validation is not Spike instruction execution; injected PC=2 is outside normal entry contract"}
    raise Divergence(f"Unknown comparison profile: {profile}")
