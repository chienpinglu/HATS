"""Validate device-produced edit scripts by applying them and checking minimum cost."""
import struct


def lines(text):
    parts = text.split(b"\n")
    return [p + b"\n" for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def check_output(memory, old, new, expected_status):
    if len(memory) != 65536:
        raise ValueError("Wrong memory image size")
    status, count, cost, n, m = struct.unpack_from("<5I", memory, 0x8000)
    if status != expected_status or count > 64:
        raise ValueError("Wrong application status or output length")
    if status:
        if (count, cost, n, m) != (0, 0, 0, 0):
            raise ValueError("Rejected input published partial output")
        return dict(status=status, edits=0, cost=0)
    a, b = lines(old), lines(new)
    if (n, m) != (len(a), len(b)):
        raise ValueError("Wrong line counts")
    i = j = actual_cost = 0
    rebuilt = []
    for index in range(count):
        kind, ai, bj = struct.unpack_from("<3I", memory, 0x8014 + index * 12)
        if (ai, bj) != (i, j):
            raise ValueError("Nonsequential edit coordinates")
        if kind == 0 and i < n and j < m and a[i] == b[j]:
            rebuilt.append(a[i]); i += 1; j += 1
        elif kind == 1 and i < n:
            i += 1; actual_cost += 1
        elif kind == 2 and j < m:
            rebuilt.append(b[j]); j += 1; actual_cost += 1
        else:
            raise ValueError("Invalid edit operation")
    if (i, j) != (n, m) or b"".join(rebuilt) != new or actual_cost != cost:
        raise ValueError("Edit script does not reproduce target")
    # Independent prefix edit-distance recurrence; no target LCS table or output
    # is used to compute the expected minimum insertion/deletion count.
    previous = list(range(m + 1))
    for ai, av in enumerate(a, 1):
        row = [ai]
        for bj, bv in enumerate(b, 1):
            row.append(previous[bj-1] if av == bv else min(previous[bj], row[-1]) + 1)
        previous = row
    if cost != previous[m]:
        raise ValueError("Edit script is not minimum cost")
    return dict(status=0, edits=count, cost=cost)
