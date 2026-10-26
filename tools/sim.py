#!/usr/bin/env python3
"""TACHYON-128 reference ISA simulator (golden model).

Usage: sim.py prog.bin [--trace out.trace] [--max N] [--quiet] [--regs]

Architectural state: 64 x (128-bit value + capability tag + perms/base/top), 128-bit PC,
CSRs tvec/epc/cause/tval/scratch, RAM_BYTES of RAM at 0, MMIO page at the top of the space.
Writes a commit trace (one line per retired instruction, one 'T' line per trap) that the RTL
testbench reproduces bit-for-bit.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isa import *  # noqa: E402,F401,F403


class Trap(Exception):
    def __init__(self, cause, tval):
        self.cause, self.tval = cause, tval & MASK


class Halt(Exception):
    def __init__(self, code):
        self.code = code


def clz(v):
    return XLEN - v.bit_length()


def ctz(v):
    return XLEN if v == 0 else (v & -v).bit_length() - 1


def lanes(v, w):
    return [(v >> (i * w)) & ((1 << w) - 1) for i in range(XLEN // w)]


def pack(ls, w):
    m = (1 << w) - 1
    r = 0
    for i, x in enumerate(ls):
        r |= (x & m) << (i * w)
    return r


def simd(op, w, a, b):
    la, lb = lanes(a, w), lanes(b, w)
    m = (1 << w) - 1
    smin, smax = -(1 << (w - 1)), (1 << (w - 1)) - 1
    S = lambda x: sext(x, w)  # noqa: E731
    clamp = lambda x, lo, hi: max(lo, min(hi, x))  # noqa: E731
    sh = b & (w - 1)
    if op == "vsum":
        return sum(la) & MASK
    if op == "vsplat":
        return pack([la[0]] * len(la), w)
    f = {
        "vadd": lambda x, y: x + y,
        "vsub": lambda x, y: x - y,
        "vaddss": lambda x, y: clamp(S(x) + S(y), smin, smax),
        "vaddus": lambda x, y: min(x + y, m),
        "vsubss": lambda x, y: clamp(S(x) - S(y), smin, smax),
        "vsubus": lambda x, y: max(x - y, 0),
        "vmins": lambda x, y: min(S(x), S(y)),
        "vminu": lambda x, y: min(x, y),
        "vmaxs": lambda x, y: max(S(x), S(y)),
        "vmaxu": lambda x, y: max(x, y),
        "vcmpeq": lambda x, y: m if x == y else 0,
        "vcmpgts": lambda x, y: m if S(x) > S(y) else 0,
        "vcmpgtu": lambda x, y: m if x > y else 0,
        "vmul": lambda x, y: x * y,
        "vsll": lambda x, y: x << sh,
        "vsrl": lambda x, y: x >> sh,
        "vsra": lambda x, y: S(x) >> sh,
    }[op]
    return pack([f(x, y) for x, y in zip(la, lb)], w)


def divs(a, b, signed, want_rem):
    """RISC-V style division semantics on 128-bit values."""
    if b == 0:
        return a if want_rem else MASK
    if not signed:
        return a % b if want_rem else a // b
    sa, sb = to_signed(a), to_signed(b)
    if sa == -(1 << 127) and sb == -1:
        return 0 if want_rem else a
    q = abs(sa) // abs(sb)
    if (sa < 0) != (sb < 0):
        q = -q
    r = sa - q * sb
    return (r if want_rem else q) & MASK


class Machine:
    def __init__(self, binary, ram_bytes=RAM_BYTES):
        self.ram = bytearray(ram_bytes)
        self.ram[:len(binary)] = binary
        self.val = [0] * NREGS
        self.tag = [0] * NREGS
        self.meta = [NULL_META] * NREGS          # (perm, base, top, otype)
        # root capability lives in r63 (rc) at reset: all permissions over the whole space
        self.val[63], self.tag[63], self.meta[63] = 0, 1, ROOT_META
        self.pc = 0
        self.csr = [0] * NUM_CSRS
        self.pcc = ROOT_META                 # program-counter capability (always tagged, never sealed)
        self.epcc = ROOT_META                # PCC saved on trap, restored by eret
        self.mtag = {}              # shadow tag memory: granule index -> (perm, base, top) when tagged
        self.console = bytearray()
        self.trace = []
        self.retired = 0
        self.halted = None          # ('exit', code) | ('trap', cause)
        self.exit_code = 0

    # ---------------------------------------------------------------- register helpers
    def rd_write(self, rd, v, tag=0, meta=NULL_META):
        if rd == 0:
            return None
        self.val[rd] = v & MASK
        self.tag[rd] = tag
        self.meta[rd] = meta if tag else NULL_META
        return rd

    # ---------------------------------------------------------------- memory
    def check_access(self, rs1, ea, size, is_store, store_cap=False):
        if self.tag[rs1]:
            perm, base, top, otype = self.meta[rs1]
            if otype:
                raise Trap(CAUSE_CAP_SEALED, ea)
            need = PERM_STORE if is_store else PERM_LOAD
            if not perm & need:
                raise Trap(CAUSE_CAP_PERM, ea)
            if store_cap and not perm & PERM_STORE_CAP:
                raise Trap(CAUSE_CAP_PERM, ea)
            if ea < base or ea + size > top:
                raise Trap(CAUSE_CAP_BOUNDS, ea)
        if ea % size:
            raise Trap(CAUSE_ALIGN, ea)
        if ea + size <= len(self.ram):
            return "ram"
        if ea >= MMIO_BASE:
            return "mmio"
        raise Trap(CAUSE_ACCESS, ea)

    def load(self, rs1, ea, size, signed):
        kind = self.check_access(rs1, ea, size, False)
        if kind == "mmio":
            return 0
        v = int.from_bytes(self.ram[ea:ea + size], "little")
        return sext(v, 8 * size) & MASK if signed else v

    def store(self, rs1, ea, size, v):
        kind = self.check_access(rs1, ea, size, True)
        v &= (1 << (8 * size)) - 1
        if kind == "mmio":
            if ea == MMIO_CONSOLE:
                self.console.append(v & 0xFF)
            elif ea == MMIO_HEXOUT:
                self.console += f"{v:032x}\n".encode()
            elif ea == MMIO_EXIT:
                raise Halt(v & 0xFFFFFFFF)
            return
        self.ram[ea:ea + size] = v.to_bytes(size, "little")
        self.mtag.pop(ea // GRANULE, None)     # any data store clears the granule's tag

    def load_cap(self, rs1, ea):
        """clc: 128-bit value + tag/metadata from the shadow memory. Returns (value, tag, meta)."""
        kind = self.check_access(rs1, ea, 16, False)
        if kind == "mmio":
            return 0, 0, NULL_META
        v = int.from_bytes(self.ram[ea:ea + 16], "little")
        g = ea // GRANULE
        if g in self.mtag and (not self.tag[rs1] or self.meta[rs1][0] & PERM_LOAD_CAP):
            return v, 1, self.mtag[g]
        return v, 0, NULL_META

    def store_cap(self, rs1, ea, A):
        """csc: store register A's value and (if tagged) its capability metadata."""
        kind = self.check_access(rs1, ea, 16, True, store_cap=bool(self.tag[A]))
        if kind == "mmio":
            self.store(rs1, ea, 16, self.val[A])
            return
        self.ram[ea:ea + 16] = self.val[A].to_bytes(16, "little")
        if self.tag[A]:
            self.mtag[ea // GRANULE] = self.meta[A]
        else:
            self.mtag.pop(ea // GRANULE, None)

    # ---------------------------------------------------------------- one instruction
    def step(self):
        pc = self.pc
        pperm, pbase, ptop, _ = self.pcc
        if not pperm & PERM_EXEC:
            raise Trap(CAUSE_CAP_PERM, pc)
        if pc < pbase or pc + 4 > ptop:
            raise Trap(CAUSE_CAP_BOUNDS, pc)
        if pc + 4 > len(self.ram):
            raise Trap(CAUSE_ACCESS, pc)
        w = struct.unpack_from("<I", self.ram, pc)[0]
        f = fields(w)
        op, rd, rs1, rs2, func = f["op"], f["rd"], f["rs1"], f["rs2"], f["func"]
        A = f["rd"]                       # field A (store data / branch rs2 / wins source)
        x1, x2 = self.val[rs1], self.val[rs2]
        npc = (pc + 4) & MASK
        wrote = None
        self._halt = None
        self._new_pcc = self._new_epcc = None

        if op == OP_ALU:
            if func >= len(ALU_FUNCS):
                raise Trap(CAUSE_ILLEGAL, w)
            fn = ALU_FUNCS[func]
            s1, s2 = to_signed(x1), to_signed(x2)
            sh = x2 & 127
            r = {
                "add": lambda: x1 + x2, "sub": lambda: x1 - x2, "and": lambda: x1 & x2,
                "or": lambda: x1 | x2, "xor": lambda: x1 ^ x2, "sll": lambda: x1 << sh,
                "srl": lambda: x1 >> sh, "sra": lambda: s1 >> sh, "slt": lambda: int(s1 < s2),
                "sltu": lambda: int(x1 < x2), "min": lambda: min(s1, s2), "max": lambda: max(s1, s2),
                "minu": lambda: min(x1, x2), "maxu": lambda: max(x1, x2), "andn": lambda: x1 & ~x2,
                "seq": lambda: int(x1 == x2), "clz": lambda: clz(x1), "ctz": lambda: ctz(x1),
                "popcnt": lambda: bin(x1).count("1"),
            }[fn]()
            wrote = self.rd_write(rd, r)
        elif op == OP_MULDIV:
            if func >= len(MULDIV_FUNCS):
                raise Trap(CAUSE_ILLEGAL, w)
            fn = MULDIV_FUNCS[func]
            if fn == "mul":
                r = x1 * x2
            elif fn == "mulhu":
                r = (x1 * x2) >> 128
            else:
                r = divs(x1, x2, fn in ("div", "rem"), fn.startswith("rem"))
            wrote = self.rd_write(rd, r)
        elif op == OP_SIMD:
            sop, lw = func >> 2, func & 3
            if sop >= len(SIMD_FUNCS) or (SIMD_FUNCS[sop] == "vmul" and lw == 3):
                raise Trap(CAUSE_ILLEGAL, w)
            wrote = self.rd_write(rd, simd(SIMD_FUNCS[sop], LANE_BITS[lw], x1, x2))
        elif op == OP_CAP:
            if func >= len(CAP_FUNCS):
                raise Trap(CAUSE_ILLEGAL, w)
            fn = CAP_FUNCS[func]
            if fn == "cgetpcc":
                wrote = self.rd_write(rd, pc, 1, self.pcc)
            elif fn == "csetepcc":
                if not self.tag[rs1]:
                    raise Trap(CAUSE_CAP_TAG, x1)
                if self.meta[rs1][3]:
                    raise Trap(CAUSE_CAP_SEALED, x1)
                self._new_epcc = self.meta[rs1]
            elif fn == "cjalr":
                if not self.tag[rs1]:
                    raise Trap(CAUSE_CAP_TAG, x1)
                if self.meta[rs1][3]:
                    raise Trap(CAUSE_CAP_SEALED, x1)
                if not self.meta[rs1][0] & PERM_EXEC:
                    raise Trap(CAUSE_CAP_PERM, x1)
                npc = x1 & ~3
                self._new_pcc = self.meta[rs1]
                wrote = self.rd_write(rd, pc + 4, 1, self.pcc)    # link = PCC with cursor pc+4
            elif fn in ("cseal", "cunseal"):
                wrote = self.seal_op(fn, rd, rs1, rs2)
            else:
                wrote = self.cap_op(fn, rd, rs1, x2)
        elif op in I_OPS.values():
            imm = f["imm14"]
            ui = imm & MASK
            s1 = to_signed(x1)
            sh = f["uimm14"] & 127
            if op == OP_ADDI:
                wrote = self.rd_write(rd, x1 + imm)
            elif op == OP_ANDI:
                wrote = self.rd_write(rd, x1 & ui)
            elif op == OP_ORI:
                wrote = self.rd_write(rd, x1 | ui)
            elif op == OP_XORI:
                wrote = self.rd_write(rd, x1 ^ ui)
            elif op == OP_SLTI:
                wrote = self.rd_write(rd, int(s1 < imm))
            elif op == OP_SLTIU:
                wrote = self.rd_write(rd, int(x1 < ui))
            elif op == OP_SLLI:
                wrote = self.rd_write(rd, x1 << sh)
            elif op == OP_SRLI:
                wrote = self.rd_write(rd, x1 >> sh)
            elif op == OP_SRAI:
                wrote = self.rd_write(rd, s1 >> sh)
            elif op == OP_CINCADDRI:
                wrote = self.cap_op("cincaddr", rd, rs1, ui)
            elif op == OP_CSETBNDI:
                wrote = self.cap_op("csetbnd", rd, rs1, f["uimm14"])
        elif op == OP_WIDE:
            sh = 16 * f["slot"]
            ins = f["imm16"] << sh
            if f["keep"]:
                ins |= self.val[rd] & ~(0xFFFF << sh) & MASK
            wrote = self.rd_write(rd, ins)
        elif OP_LB <= op <= OP_LDU:
            _, size, signed = [v for v in LOAD_OPS.values() if v[0] == op][0]
            ea = (x1 + f["imm14"]) & MASK
            wrote = self.rd_write(rd, self.load(rs1, ea, size, signed))
        elif op == OP_CLC:
            ea = (x1 + f["imm14"]) & MASK
            v, t, m = self.load_cap(rs1, ea)
            wrote = self.rd_write(rd, v, t, m)
        elif op == OP_CSC:
            self.store_cap(rs1, (x1 + f["imm14"]) & MASK, A)
        elif OP_SB <= op <= OP_SQ:
            size = [v[1] for v in STORE_OPS.values() if v[0] == op][0]
            ea = (x1 + f["imm14"]) & MASK
            self.store(rs1, ea, size, self.val[A])
        elif OP_BEQ <= op <= OP_BGEU:
            a, b = x1, self.val[A]
            sa, sb = to_signed(a), to_signed(b)
            t = {OP_BEQ: a == b, OP_BNE: a != b, OP_BLT: sa < sb, OP_BGE: sa >= sb,
                 OP_BLTU: a < b, OP_BGEU: a >= b}[op]
            if t:
                npc = (pc + 4 * f["imm14"]) & MASK
        elif op == OP_JAL:
            wrote = self.rd_write(rd, pc + 4)
            npc = (pc + 4 * f["imm20"]) & MASK
        elif op == OP_JALR:
            npc = (x1 + f["imm14"]) & MASK & ~3
            wrote = self.rd_write(rd, pc + 4)
        elif op == OP_HALT:
            self._halt = x1 & 0xFFFFFFFF
        elif op == OP_CSRR:
            if f["uimm14"] >= NUM_CSRS:
                raise Trap(CAUSE_ILLEGAL, w)
            wrote = self.rd_write(rd, self.csr[f["uimm14"]])
        elif op == OP_CSRW:
            if f["uimm14"] >= NUM_CSRS:
                raise Trap(CAUSE_ILLEGAL, w)
            self.csr[f["uimm14"]] = x1
        elif op == OP_ERET:
            npc = self.csr[1] & ~3
            self._new_pcc = self.epcc
        else:
            raise Trap(CAUSE_ILLEGAL, w)
        return pc, npc, wrote

    def seal_op(self, fn, rd, rs1, rs2):
        a, t1, (p1, b1, top1, ot1) = self.val[rs1], self.tag[rs1], self.meta[rs1]
        k, t2, (p2, b2, top2, ot2) = self.val[rs2], self.tag[rs2], self.meta[rs2]
        if not t1:
            raise Trap(CAUSE_CAP_TAG, a)
        if not t2:
            raise Trap(CAUSE_CAP_TAG, k)
        if fn == "cseal":
            if ot1:
                raise Trap(CAUSE_CAP_SEALED, a)
            if ot2:
                raise Trap(CAUSE_CAP_SEALED, k)
            if not p2 & PERM_SEAL:
                raise Trap(CAUSE_CAP_PERM, k)
            if k < b2 or k >= top2 or k == 0 or k > OTYPE_MAX:
                raise Trap(CAUSE_CAP_BOUNDS, k)
            return self.rd_write(rd, a, 1, (p1, b1, top1, k))
        if not ot1:
            raise Trap(CAUSE_CAP_SEALED, a)
        if ot2:
            raise Trap(CAUSE_CAP_SEALED, k)
        if not p2 & PERM_UNSEAL:
            raise Trap(CAUSE_CAP_PERM, k)
        if k < b2 or k >= top2:
            raise Trap(CAUSE_CAP_BOUNDS, k)
        if k != ot1:
            raise Trap(CAUSE_CAP_SEALED, k)
        return self.rd_write(rd, a, 1, (p1, b1, top1, 0))

    def cap_op(self, fn, rd, rs1, x2):
        t, (perm, base, top, otype), a = self.tag[rs1], self.meta[rs1], self.val[rs1]
        if t and otype and fn in ("csetaddr", "cincaddr", "csetbnd", "candperm"):
            raise Trap(CAUSE_CAP_SEALED, a)     # sealed capabilities are immutable
        if fn == "csetaddr":
            return self.rd_write(rd, x2, t, (perm, base, top, 0))
        if fn == "cincaddr":
            return self.rd_write(rd, a + x2, t, (perm, base, top, 0))
        if fn == "csetbnd":
            if not t:
                raise Trap(CAUSE_CAP_TAG, a)
            ntop = a + x2
            if a < base or ntop > top:
                raise Trap(CAUSE_CAP_BOUNDS, a)
            return self.rd_write(rd, a, 1, (perm, a, ntop, 0))
        if fn == "candperm":
            return self.rd_write(rd, a, t, (perm & x2 & PERM_ALL, base, top, 0))
        if fn == "cgettype":
            return self.rd_write(rd, otype)
        if fn == "cgetbase":
            return self.rd_write(rd, base)
        if fn == "cgetlen":
            return self.rd_write(rd, min(top - base, MASK))
        if fn == "cgetperm":
            return self.rd_write(rd, perm)
        if fn == "cgettag":
            return self.rd_write(rd, t)
        if fn == "cclrtag":
            return self.rd_write(rd, a)
        raise AssertionError(fn)

    # ---------------------------------------------------------------- run loop
    def trace_line(self, pc, rd):
        if rd is None:
            return f"{pc:x} 0 0 0"
        line = f"{pc:x} {rd} {self.val[rd]:x} {self.tag[rd]}"
        if self.tag[rd]:
            p, b, t, o = self.meta[rd]
            line += f" {p} {b:x} {t:x} {o:x}"
        return line

    def run(self, max_steps=5_000_000):
        while self.halted is None and self.retired < max_steps:
            try:
                pc, npc, wrote = self.step()
            except Trap as tr:
                self.csr[1], self.csr[2], self.csr[3] = self.pc, tr.cause, tr.tval
                self.epcc, self.pcc = self.pcc, ROOT_META   # handler runs with the root PCC
                self.trace.append(f"T {tr.cause} {self.pc:x} {tr.tval:x}")
                if self.csr[0] == 0:
                    self.halted = ("trap", tr.cause)
                else:
                    self.pc = self.csr[0] & MASK & ~3
                continue
            except Halt as h:
                # MMIO exit store retires, then the machine stops
                self.trace.append(self.trace_line(self.pc, None))
                self.retired += 1
                self.halted, self.exit_code = ("exit", h.code), h.code
                break
            self.trace.append(self.trace_line(pc, wrote))
            self.retired += 1
            self.pc = npc
            if self._new_pcc is not None:
                self.pcc = self._new_pcc
            if self._new_epcc is not None:
                self.epcc = self._new_epcc
            if self._halt is not None:
                self.halted, self.exit_code = ("exit", self._halt), self._halt
        if self.halted is None:
            self.halted = ("timeout", 0)
        return self

    def tagdump(self):
        """Shadow tag memory as lines 'granule perm base top otype' (tagged granules only, ascending)."""
        return [f"{g:x} {p} {b:x} {t:x} {o:x}" for g, (p, b, t, o) in sorted(self.mtag.items())]

    def regdump(self):
        out = []
        for i in range(NREGS):
            s = f"r{i:<2} {self.val[i]:032x} tag={self.tag[i]}"
            if self.tag[i]:
                p, b, t, o = self.meta[i]
                s += f" perm={p} base={b:x} top={t:x} otype={o:x}"
            out.append(s)
        return "\n".join(out)


def main():
    import argparse
    ap = argparse.ArgumentParser(description="TACHYON-128 golden ISA simulator")
    ap.add_argument("bin")
    ap.add_argument("--trace")
    ap.add_argument("--max", type=int, default=5_000_000)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--regs", action="store_true")
    a = ap.parse_args()
    m = Machine(open(a.bin, "rb").read()).run(a.max)
    if a.trace:
        with open(a.trace, "w") as f:
            f.write("\n".join(m.trace) + "\n")
    if not a.quiet:
        sys.stdout.write(m.console.decode("latin-1"))
        print(f"--- {m.halted[0]} code={m.halted[1]} retired={m.retired}", file=sys.stderr)
    if a.regs:
        print(m.regdump())
    sys.exit(0 if m.halted[0] == "exit" else 1)


if __name__ == "__main__":
    main()
