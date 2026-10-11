"""Original PPE programs shared as binary fixtures, not execution-model logic."""
from ppe_isa import assemble


def delimiter_candidates():
    """Mark bytes in b'{}[]:,' including inside strings: a prefilter, NOT parsing.

    S0 points to three little-endian u64 words: input address, output address,
    input length. Each group handles eight byte positions with an explicit tail
    mask. Output is one 0/1 byte per input byte; no inter-group synchronization.
    """
    items = [("LOAD", {"d": 8, "a": 0}), ("LOAD", {"d": 9, "a": 0, "imm": 8}),
             ("LOAD", {"d": 10, "a": 0, "imm": 16}), ("MOVI", {"d": 11, "imm": 3}),
             ("SHL", {"d": 12, "a": 2, "b": 11}),
             ("VADD", {"d": 2, "a": 0, "b": 12, "flags": 2}),
             ("VMOVI", {"d": 4, "imm": 0}), ("VMOVI", {"d": 5, "imm": 1})]
    for register, byte in enumerate(b"{}[]:,", 13):
        items.append(("MOVI", {"d": register, "imm": byte}))
    items += [("VCMPLTU", {"d": 0, "a": 2, "b": 10, "flags": 2}),
              ("SPLIT", {"p": 0, "other": "join", "join": "join"}),
              ("VLOAD", {"d": 3, "a": 8, "b": 2, "width": 0})]
    for register in range(13, 19):
        items += [("VCMPEQ", {"d": 1, "a": 3, "b": register, "flags": 2}),
                  ("SELECT", {"d": 4, "a": 5, "b": 4, "p": 1})]
    items += [("VSTORE", {"d": 4, "a": 9, "b": 2, "width": 0}),
              ("JMP", {"target": "join"}), "join:", ("JOIN", {}), ("RETURN", {"a": 19})]
    return assemble(items)


def vector_relu_epilogue():
    """HATS-authored fused vector residual/bias + ReLU memory kernel.

    This is a generic AI inference microkernel, not copied from an external
    repository. The descriptor holds three u64 addresses: input A, input B,
    and output. Each PPE group processes eight signed int32 elements.
    """
    items = [
        ("LOAD", {"d": 8, "a": 0}), ("LOAD", {"d": 9, "a": 0, "imm": 8}),
        ("LOAD", {"d": 10, "a": 0, "imm": 16}), ("MOVI", {"d": 11, "imm": 2}),
        ("VSHL", {"d": 12, "a": 1, "b": 11, "width": 3, "flags": 2}),
        ("MOVI", {"d": 13, "imm": 5}), ("SHL", {"d": 14, "a": 2, "b": 13}),
        ("VADD", {"d": 12, "a": 12, "b": 14, "width": 3, "flags": 2}),
        ("VLOAD", {"d": 2, "a": 8, "b": 12, "width": 2}),
        ("VLOAD", {"d": 3, "a": 9, "b": 12, "width": 2}),
        ("VADD", {"d": 4, "a": 2, "b": 3, "width": 2}),
        ("VMOVI", {"d": 5, "imm": 0, "width": 2}),
        ("VCMPLT", {"d": 0, "a": 4, "b": 5, "width": 2}),
        ("SELECT", {"d": 6, "a": 5, "b": 4, "p": 0, "width": 2}),
        ("VSTORE", {"d": 6, "a": 10, "b": 12, "width": 2}),
        ("RETURN", {})]
    return assemble(items)
