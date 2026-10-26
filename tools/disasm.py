#!/usr/bin/env python3
"""TACHYON-128 disassembler.  Usage: disasm.py prog.bin [--base 0] [--count N]"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isa import *  # noqa: E402,F401,F403

_INV_I = {v: k for k, v in I_OPS.items()}
_INV_L = {v[0]: k for k, v in LOAD_OPS.items()}
_INV_L.update({v: k for k, v in CAP_LOAD_OPS.items()})
_INV_S = {v[0]: k for k, v in STORE_OPS.items()}
_INV_S.update({v: k for k, v in CAP_STORE_OPS.items()})
_INV_B = {v: k for k, v in BRANCH_OPS.items()}
_INV_CSR = {v: k for k, v in CSR_NAMES.items()}
_INV_LANE = {v: k for k, v in LANE_SUFFIX.items()}


def decode(w):
    """Return (mnemonic, kind) or None when the word is not a legal instruction.
    Mirrors the legality rules the simulator and RTL use."""
    f = fields(w)
    op, func = f["op"], f["func"]
    if op == OP_ALU:
        return ("r", ALU_FUNCS[func]) if func < len(ALU_FUNCS) else None
    if op == OP_MULDIV:
        return ("r", MULDIV_FUNCS[func]) if func < len(MULDIV_FUNCS) else None
    if op == OP_SIMD:
        sop, lw = func >> 2, func & 3
        if sop >= len(SIMD_FUNCS) or (SIMD_FUNCS[sop] == "vmul" and lw == 3):
            return None
        return ("v", SIMD_FUNCS[sop] + "." + _INV_LANE[lw])
    if op == OP_CAP:
        return ("r", CAP_FUNCS[func]) if func < len(CAP_FUNCS) else None
    if op in _INV_I:
        return ("i", _INV_I[op])
    if op == OP_WIDE:
        return ("k", "wins" if f["keep"] else "wli")
    if op in _INV_L:
        return ("l", _INV_L[op])
    if op in _INV_S:
        return ("s", _INV_S[op])
    if op in _INV_B:
        return ("b", _INV_B[op])
    if op == OP_JAL:
        return ("j", "jal")
    if op == OP_JALR:
        return ("i", "jalr")
    if op == OP_HALT:
        return ("halt", "halt")
    if op == OP_CSRR:
        return ("csrr", "csrr") if f["uimm14"] < NUM_CSRS else None
    if op == OP_CSRW:
        return ("csrw", "csrw") if f["uimm14"] < NUM_CSRS else None
    if op == OP_ERET:
        return ("eret", "eret")
    return None


def disasm(w, pc=0):
    d = decode(w)
    if d is None:
        return f".word 0x{w:08x}  # illegal"
    kind, mn = d
    f = fields(w)
    rn = reg_name
    rd, rs1, rs2 = rn(f["rd"]), rn(f["rs1"]), rn(f["rs2"])
    if kind in ("r", "v"):
        base = mn.split(".")[0]
        if base in ALU_UNARY or base in SIMD_UNARY or base in CAP_UNARY:
            return f"{mn} {rd}, {rs1}"
        return f"{mn} {rd}, {rs1}, {rs2}"
    if kind == "i":
        imm = f["uimm14"] if mn == "csetbndi" else (f["uimm14"] & 127 if mn in ("slli", "srli", "srai") else f["imm14"])
        return f"{mn} {rd}, {rs1}, {imm}"
    if kind == "k":
        return f"{mn} {rd}, 0x{f['imm16']:04x}, {f['slot']}"
    if kind == "l":
        return f"{mn} {rd}, {f['imm14']}({rs1})"
    if kind == "s":
        return f"{mn} {rd}, {f['imm14']}({rs1})"
    if kind == "b":
        return f"{mn} {rs1}, {rd}, 0x{(pc + 4 * f['imm14']) & MASK:x}"
    if kind == "j":
        return f"jal {rd}, 0x{(pc + 4 * f['imm20']) & MASK:x}"
    if kind == "halt":
        return f"halt {rs1}"
    if kind == "csrr":
        return f"csrr {rd}, {_INV_CSR[f['uimm14']]}"
    if kind == "csrw":
        return f"csrw {_INV_CSR[f['uimm14']]}, {rs1}"
    return "eret"


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("bin")
    ap.add_argument("--base", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--count", type=int, default=None)
    a = ap.parse_args()
    data = open(a.bin, "rb").read()
    n = len(data) // 4 if a.count is None else a.count
    for i in range(n):
        w = struct.unpack_from("<I", data, 4 * i)[0]
        pc = a.base + 4 * i
        print(f"{pc:08x}  {w:08x}  {disasm(w, pc)}")


if __name__ == "__main__":
    main()
