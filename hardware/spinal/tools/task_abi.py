"""HATS-TASK-0.1 byte-layout checker; not a CP, runtime or security boundary."""
import struct

VERSION = (0, 1)
APE, PPE = 1, 2
# Explicit little-endian fields, no host-native alignment or pointers.
FIELDS = [
    ("major", "H"), ("minor", "H"), ("bytes", "H"), ("kind", "B"), ("flags", "B"),
    ("task_id", "Q"), ("parent_id", "Q"), ("engine_class", "I"), ("domain_mask", "I"),
    ("code_handle", "Q"), ("argument_address", "Q"), ("argument_bytes", "Q"),
    ("capability_set", "Q"), ("dependencies_address", "Q"), ("dependency_count", "I"),
    ("priority", "I"), ("completion_cookie", "Q"), ("budget_ticks", "Q"),
    ("group_count", "I"), ("waves_per_group", "H"), ("logical_width", "H"),
    ("scratch_bytes_per_group", "Q"), ("address_space", "I"), ("address_generation", "I"),
    ("reserved", "Q"),
]
WIRE = struct.Struct("<" + "".join(kind for _, kind in FIELDS))
OFFSETS = {name: struct.calcsize("<" + "".join(k for _, k in FIELDS[:i]))
           for i, (name, _) in enumerate(FIELDS)}
COMPLETION_FIELDS = [
    ("major", "H"), ("minor", "H"), ("bytes", "H"), ("status", "H"),
    ("task_id", "Q"), ("sequence", "Q"), ("value", "Q"),
    ("fault_address", "Q"), ("fault_pc", "Q"), ("cause", "I"),
    ("engine_id", "I"), ("fault_lane_mask", "Q"),
]
COMPLETION = struct.Struct("<" + "".join(kind for _, kind in COMPLETION_FIELDS))


def span(address, size):
    if not 0 <= address < 1 << 64 or not 0 <= size < 1 << 64 or address + size > 1 << 64:
        raise ValueError("Address range wraps or is not unsigned 64-bit")


def validate(d):
    if set(d) != {name for name, _ in FIELDS}:
        raise ValueError("Missing or unknown descriptor field")
    for name, kind in FIELDS:
        bits = struct.calcsize("<" + kind) * 8
        if type(d[name]) is not int or not 0 <= d[name] < 1 << bits:
            raise ValueError(f"Invalid unsigned field: {name}")
    if (d["major"], d["minor"]) != VERSION or d["bytes"] != 128:
        raise ValueError("Unsupported ABI version/length")
    if d["kind"] != 1 or d["flags"] or d["reserved"]:
        raise ValueError("Unsupported kind, flags or reserved fields")
    if d["engine_class"] not in (APE, PPE):
        raise ValueError("Unsupported engine class")
    if not d["domain_mask"] or d["domain_mask"] & ~15:
        raise ValueError("Invalid four-domain affinity")
    if not all(d[k] for k in ("task_id", "code_handle", "capability_set", "budget_ticks", "group_count", "waves_per_group", "logical_width")):
        raise ValueError("Required nonzero field")
    if d["task_id"] == d["parent_id"] or d["dependency_count"] > 8 or d["priority"] > 3:
        raise ValueError("Invalid parent, dependency count or priority")
    span(d["argument_address"], d["argument_bytes"])
    span(d["dependencies_address"], 16 * d["dependency_count"])
    if bool(d["dependency_count"]) != bool(d["dependencies_address"]) or d["dependencies_address"] % 16:
        raise ValueError("Invalid dependency list address")
    if d["scratch_bytes_per_group"] % 16:
        raise ValueError("Scratch size must be 16-byte aligned")
    span(0, d["scratch_bytes_per_group"] * d["group_count"])
    if d["engine_class"] == APE and (d["group_count"], d["waves_per_group"], d["logical_width"], d["scratch_bytes_per_group"]) != (1, 1, 1, 0):
        raise ValueError("APE does not use PPE geometry")
    if d["engine_class"] == PPE and d["logical_width"] > 64:
        raise ValueError("Lane mask is at most 64 bits")


def descriptor(**overrides):
    d = {name: 0 for name, _ in FIELDS}
    d.update(major=0, minor=1, bytes=128, kind=1, task_id=1, engine_class=APE,
             domain_mask=1, code_handle=1, capability_set=1, budget_ticks=100000,
             group_count=1, waves_per_group=1, logical_width=1)
    d.update(overrides)
    validate(d)
    return d


def pack(d):
    validate(d)
    return WIRE.pack(*(d[name] for name, _ in FIELDS))


def unpack(raw):
    if len(raw) != WIRE.size:
        raise ValueError("Descriptor must be exactly 128 bytes")
    d = dict(zip((name for name, _ in FIELDS), WIRE.unpack(raw)))
    validate(d)
    return d


def validate_initial_profile(d):
    """Proposed single-domain S02 adapter; permissions still need separate checks."""
    validate(d)
    if any(d[k] for k in ("parent_id", "dependency_count", "address_space", "address_generation", "priority")) or d["domain_mask"] != 1:
        raise ValueError("Not supported by initial single-domain profile")
    if d["engine_class"] == PPE and (d["waves_per_group"] != 1 or d["logical_width"] != 8 or d["scratch_bytes_per_group"] > 4096):
        raise ValueError("Unsupported initial PPE resources")


def completion_validate(d):
    if set(d) != {name for name, _ in COMPLETION_FIELDS}:
        raise ValueError("Missing or unknown completion field")
    for name, kind in COMPLETION_FIELDS:
        if type(d[name]) is not int or not 0 <= d[name] < 1 << (struct.calcsize("<" + kind) * 8):
            raise ValueError(f"Invalid unsigned completion field: {name}")
    if (d["major"], d["minor"], d["bytes"]) != (0, 1, 64) or d["status"] not in (1, 2, 3, 4, 5):
        raise ValueError("Invalid completion version/status")
    engine_class = d["engine_id"] >> 16
    if engine_class not in (0, APE, PPE) or (not engine_class and d["engine_id"]):
        raise ValueError("Invalid assigned engine")
    if not 0 <= d["cause"] <= 9:
        raise ValueError("Unknown completion cause")
    if d["fault_lane_mask"] and (engine_class != PPE or d["status"] != 2):
        raise ValueError("Lane fault mask requires a PPE fault")
    if d["status"] == 1 and (not d["engine_id"] or d["cause"]):
        raise ValueError("Success requires an assigned engine and no cause")
    if d["status"] == 2 and (not d["engine_id"] or not d["cause"]):
        raise ValueError("Fault requires an assigned engine and cause")
    if d["status"] in (4, 5) and (d["engine_id"] or not d["cause"]):
        raise ValueError("Rejected/dependency-failed work has no engine and needs a cause")
    if d["status"] == 5 and d["cause"] != 9:
        raise ValueError("Dependency failure requires dependency/identity cause")
    if d["status"] != 2 and (d["fault_address"] or d["fault_pc"]):
        raise ValueError("Fault diagnostics require FAULT status")


def completion_pack(**values):
    d = {name: 0 for name, _ in COMPLETION_FIELDS}
    d.update(major=0, minor=1, bytes=64)
    if set(values) - set(d): raise ValueError("Unknown completion field")
    d.update(values)
    completion_validate(d)
    return COMPLETION.pack(*(d[name] for name, _ in COMPLETION_FIELDS))


def completion_unpack(raw):
    if len(raw) != COMPLETION.size:
        raise ValueError("Completion must be exactly 64 bytes")
    d = dict(zip((name for name, _ in COMPLETION_FIELDS), COMPLETION.unpack(raw)))
    completion_validate(d)
    return d
