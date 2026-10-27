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
        self.mtimecmp = MASK                 # timer compare register (MMIO), reset all ones
        self.mtag = {}              # shadow tag memory: granule index -> (perm, base, top) when tagged
        self.console = bytearray()
        self.trace = []
        self.retired = 0
        self.halted = None          # ('exit', code) | ('trap', cause)
        self.exit_code = 0
        self.resv = None            # v4: lr/sc reservation (granule index) or None

    @property
    def user(self):
        return bool(self.csr[CSR_STATUS] & ST_U)

    # ---------------------------------------------------------------- register helpers
    def rd_write(self, rd, v, tag=0, meta=NULL_META):
        if rd == 0:
            return None
        self.val[rd] = v & MASK
        self.tag[rd] = tag
        self.meta[rd] = meta if tag else NULL_META
        return rd

    # ---------------------------------------------------------------- memory
    def check_access(self, rs1, ea, size, is_store, store_cap=False, store_local=False, rmw=False, ram_only=False):
        if self.tag[rs1]:
            perm, base, top, otype = self.meta[rs1]
            if otype:
                raise Trap(CAUSE_CAP_SEALED, ea)
            need = PERM_STORE if is_store else PERM_LOAD
            if rmw:
                need = PERM_LOAD | PERM_STORE       # v4 AMOs read and write
            if perm & need != need:
                raise Trap(CAUSE_CAP_PERM, ea)
            if store_cap and not perm & PERM_STORE_CAP:
                raise Trap(CAUSE_CAP_PERM, ea)
            if store_local and not perm & PERM_STORE_LOCAL:
                raise Trap(CAUSE_CAP_PERM, ea)      # v4: a local capability needs STORE_LOCAL
            if ea < base or ea + size > top:
                raise Trap(CAUSE_CAP_BOUNDS, ea)
        elif self.user and not (self.csr[CSR_UBASE] <= ea and ea + size <= self.csr[CSR_UBOUND]):
            raise Trap(CAUSE_PRIV, ea)      # user-mode hybrid access outside [ubase, ubound)
        if ea % size:
            raise Trap(CAUSE_ALIGN, ea)
        if ea + size <= len(self.ram):
            return "ram"
        if ea >= MMIO_BASE and not ram_only:      # v4: atomics are RAM-only
            return "mmio"
        raise Trap(CAUSE_ACCESS, ea)

    def load(self, rs1, ea, size, signed):
        kind = self.check_access(rs1, ea, size, False)
        if kind == "mmio":
            v = (self.mmio_word(ea) >> (8 * (ea & 15))) & ((1 << (8 * size)) - 1)
        else:
            v = int.from_bytes(self.ram[ea:ea + size], "little")
        return sext(v, 8 * size) & MASK if signed else v

    def mmio_word(self, ea):
        """16-byte MMIO register containing ea (reads)."""
        base = ea & ~15
        if base == MMIO_MTIME:
            return self.retired             # instructions retired before this one
        if base == MMIO_MTIMECMP:
            return self.mtimecmp
        return 0

    def irq_pending(self):
        st = self.csr[CSR_STATUS]
        return bool(st & ST_IE) and bool(st & ST_TIE) and self.retired >= self.mtimecmp

    def store(self, rs1, ea, size, v):
        kind = self.check_access(rs1, ea, size, True)
        self.resv = None                       # v4: every completed store clears the reservation
        v &= (1 << (8 * size)) - 1
        if kind == "mmio":
            if ea == MMIO_CONSOLE:
                self.console.append(v & 0xFF)
            elif ea == MMIO_HEXOUT:
                self.console += f"{v:032x}\n".encode()
            elif ea == MMIO_EXIT:
                raise Halt(v & 0xFFFFFFFF)
            elif ea == MMIO_MTIMECMP:
                self.mtimecmp = v
            return
        self.ram[ea:ea + size] = v.to_bytes(size, "little")
        self.mtag.pop(ea // GRANULE, None)     # any data store clears the granule's tag

    def load_cap(self, rs1, ea, checked=False):
        """clc: 128-bit value + tag/metadata from the shadow memory. Returns (value, tag, meta).
        checked=True: the caller (lr / amoswap) already did the access checks (RAM only)."""
        kind = "ram" if checked else self.check_access(rs1, ea, 16, False)
        if kind == "mmio":
            return self.mmio_word(ea), 0, NULL_META
        v = int.from_bytes(self.ram[ea:ea + 16], "little")
        g = ea // GRANULE
        if g in self.mtag and (not self.tag[rs1] or self.meta[rs1][0] & PERM_LOAD_CAP):
            p, b, t, o = self.mtag[g]
            if self.tag[rs1] and not self.meta[rs1][0] & PERM_LOAD_MUTABLE and not o:
                p &= ~PERM_LM_STRIP     # v4: authority without LOAD_MUTABLE -> loaded cap is deeply immutable
            return v, 1, (p, b, t, o)
        return v, 0, NULL_META

    def store_cap(self, rs1, ea, A, checked=False, val=None, tag=None, meta=None):
        """csc: store register A's value and (if tagged) its capability metadata.
        checked=True (sc / amoswap): checks already done; val/tag/meta give the data (A may be overwritten)."""
        if val is None:
            val, tag, meta = self.val[A], self.tag[A], self.meta[A]
        kind = "ram" if checked else self.check_access(rs1, ea, 16, True, store_cap=bool(tag),
                                                       store_local=bool(tag) and not meta[0] & PERM_GLOBAL)
        self.resv = None
        if kind == "mmio":
            self.store(rs1, ea, 16, self.val[A])
            return
        self.ram[ea:ea + 16] = val.to_bytes(16, "little")
        if tag:
            self.mtag[ea // GRANULE] = meta
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
        if self.user and (op in (OP_ERET, OP_HALT) or (op in (OP_CSRR, OP_CSRW) and f["uimm14"] < NUM_CSRS)
                          or (op == OP_CAP and func < len(CAP_FUNCS) and CAP_FUNCS[func] in ("csetepcc", "cgetepcc"))):
            raise Trap(CAUSE_PRIV, w)       # privileged instruction in user mode
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
            if fn.endswith(("w", "wu")):            # v5 word ops
                wrote = self.rd_write(rd, word_op(fn, x1, x2))
                fn = None
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
            }[fn]() if fn else None
            if fn:
                wrote = self.rd_write(rd, r)
        elif op == OP_MULDIV:
            if func >= len(MULDIV_FUNCS):
                raise Trap(CAUSE_ILLEGAL, w)
            fn = MULDIV_FUNCS[func]
            if fn == "mul":
                r = x1 * x2
            elif fn == "mulhu":
                r = (x1 * x2) >> 128
            elif fn in ("mulw", "mulwu"):              # v5: low 32 bits of the product, extended
                r = wext(x1 * x2, fn == "mulwu")
            elif fn in ("divw", "remw"):               # v5: signed 32-bit operands, sign-extended result
                r = wext(divs(wext(x1) & MASK, wext(x2) & MASK, True, fn == "remw"))
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
            elif fn == "cgetepcc":                       # v4: read EPCC (cursor = epc), supervisor only
                wrote = self.rd_write(rd, self.csr[1], 1, self.epcc)
            elif fn == "cjalr":
                if not self.tag[rs1]:
                    raise Trap(CAUSE_CAP_TAG, x1)
                sentry = self.meta[rs1][3] == OTYPE_SENTRY
                if self.meta[rs1][3] and not sentry:
                    raise Trap(CAUSE_CAP_SEALED, x1)
                if not self.meta[rs1][0] & PERM_EXEC:
                    raise Trap(CAUSE_CAP_PERM, x1)
                npc = x1 & ~3
                p1, b1, t1, _ = self.meta[rs1]
                self._new_pcc = (p1, b1, t1, 0)                    # a sentry is unsealed by the jump
                lp, lb, lt, _ = self.pcc                            # link = PCC with cursor pc+4,
                wrote = self.rd_write(rd, pc + 4, 1, (lp, lb, lt, OTYPE_SENTRY if sentry else 0))  # sealed if sentry
            elif fn == "csealentry":
                p1, b1, t1, o1 = self.meta[rs1]
                if not self.tag[rs1]:
                    raise Trap(CAUSE_CAP_TAG, x1)
                if o1:
                    raise Trap(CAUSE_CAP_SEALED, x1)
                if not p1 & PERM_EXEC:
                    raise Trap(CAUSE_CAP_PERM, x1)
                wrote = self.rd_write(rd, x1, 1, (p1, b1, t1, OTYPE_SENTRY))
            elif fn == "cinvoke":
                (p1, b1, t1, o1), (p2, b2, t2, o2) = self.meta[rs1], self.meta[rs2]
                if not self.tag[rs1]:
                    raise Trap(CAUSE_CAP_TAG, x1)
                if not self.tag[rs2]:
                    raise Trap(CAUSE_CAP_TAG, x2)
                if o1 in (0, OTYPE_SENTRY):
                    raise Trap(CAUSE_CAP_SEALED, x1)
                if o2 in (0, OTYPE_SENTRY) or o2 != o1:
                    raise Trap(CAUSE_CAP_SEALED, x2)
                if not p1 & PERM_CINVOKE:               # v4: both halves need PERMIT_CINVOKE
                    raise Trap(CAUSE_CAP_PERM, x1)
                if not p2 & PERM_CINVOKE:
                    raise Trap(CAUSE_CAP_PERM, x2)
                if not p1 & PERM_EXEC:
                    raise Trap(CAUSE_CAP_PERM, x1)
                if p2 & PERM_EXEC:
                    raise Trap(CAUSE_CAP_PERM, x2)
                npc = x1 & ~3
                self._new_pcc = (p1, b1, t1, 0)
                wrote = self.rd_write(rd, x2, 1, (p2, b2, t2, 0))
            elif fn in ("cseal", "cunseal"):
                wrote = self.seal_op(fn, rd, rs1, rs2)
            else:
                wrote = self.cap_op(fn, rd, rs1, x2)
        elif op == OP_AMO:
            if func >= len(AMO_FUNCS):
                raise Trap(CAUSE_ILLEGAL, w)
            wrote = self.amo(AMO_FUNCS[func], rd, rs1, rs2)
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
            elif op in (OP_ADDIW, OP_ADDIWU):          # v5 word immediates
                wrote = self.rd_write(rd, wext(x1 + imm, op == OP_ADDIWU))
            elif op in (OP_SLLIW, OP_SRLIW, OP_SRAIW, OP_SLLIWU):
                fn = {OP_SLLIW: "sllw", OP_SRLIW: "srlw", OP_SRAIW: "sraw", OP_SLLIWU: "sllwu"}[op]
                wrote = self.rd_write(rd, word_op(fn, x1, f["uimm14"]))
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
        elif op == OP_ECALL:
            raise Trap(CAUSE_ECALL, 0)
        elif op == OP_CSRR:
            if f["uimm14"] >= NUM_CSRS:
                raise Trap(CAUSE_ILLEGAL, w)
            wrote = self.rd_write(rd, self.csr[f["uimm14"]])
        elif op == OP_CSRW:
            if f["uimm14"] >= NUM_CSRS:
                raise Trap(CAUSE_ILLEGAL, w)
            if f["uimm14"] == CSR_STATUS:     # U is read-only to csrw
                x1 = (x1 & STATUS_WMASK) | (self.csr[CSR_STATUS] & ST_U)
            self.csr[f["uimm14"]] = x1
        elif op == OP_ERET:
            npc = self.csr[1] & ~3
            self._new_pcc = self.epcc
            st = self.csr[CSR_STATUS]       # IE <- PIE, PIE <- 1, U <- PU, PU <- 0
            self.csr[CSR_STATUS] = (st & ST_TIE) | ST_PIE | (ST_IE if st & ST_PIE else 0) | (ST_U if st & ST_PU else 0)
        else:
            raise Trap(CAUSE_ILLEGAL, w)
        return pc, npc, wrote

    def amo(self, fn, rd, rs1, rs2):
        """v4 atomics: 128-bit, 16-byte aligned, RAM only; address = rs1 (no offset)."""
        ea = self.val[rs1]
        g = ea // GRANULE
        d_val, d_tag, d_meta = self.val[rs2], self.tag[rs2], self.meta[rs2]      # read before rd is written
        capst = fn in ("sc", "amoswap")
        local = bool(d_tag) and not d_meta[0] & PERM_GLOBAL
        if fn == "lr":
            self.check_access(rs1, ea, 16, False, ram_only=True)
            v, t, m = self.load_cap(rs1, ea, checked=True)
            self.resv = g
            return self.rd_write(rd, v, t, m)
        self.check_access(rs1, ea, 16, True, store_cap=capst and bool(d_tag), store_local=capst and local,
                          rmw=fn != "sc", ram_only=True)
        if fn == "sc":
            ok = self.resv == g
            self.resv = None
            if ok:
                self.store_cap(rs1, ea, rs2, checked=True, val=d_val, tag=d_tag, meta=d_meta)
            return self.rd_write(rd, 0 if ok else 1)
        if fn == "amoswap":
            v, t, m = self.load_cap(rs1, ea, checked=True)                       # old value, clc tag rules
            self.store_cap(rs1, ea, rs2, checked=True, val=d_val, tag=d_tag, meta=d_meta)
            return self.rd_write(rd, v, t, m)
        old = int.from_bytes(self.ram[ea:ea + 16], "little")
        new = {"amoadd": old + d_val, "amoand": old & d_val, "amoor": old | d_val, "amoxor": old ^ d_val}[fn] & MASK
        self.ram[ea:ea + 16] = new.to_bytes(16, "little")
        self.mtag.pop(g, None)                 # a data write: the granule's tag is cleared
        self.resv = None
        return self.rd_write(rd, old)

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
        if not ot1 or ot1 == OTYPE_SENTRY:          # sentries cannot be unsealed explicitly
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

    def enter_trap(self, cause, tval):
        """Common trap/interrupt entry: epc, cause, tval, EPCC, status.PIE <- IE, IE <- 0."""
        st = self.csr[CSR_STATUS]           # PU <- U, U <- 0 (traps enter supervisor mode)
        self.csr[CSR_STATUS] = (st & ST_TIE) | (ST_PIE if st & ST_IE else 0) | (ST_PU if st & ST_U else 0)
        self.csr[1], self.csr[2], self.csr[3] = self.pc, cause, tval
        self.epcc, self.pcc = self.pcc, ROOT_META   # handler runs with the root PCC
        self.resv = None                    # v4: traps and interrupts clear the lr/sc reservation
        if self.csr[0] == 0:
            self.halted = ("trap", cause)
        else:
            self.pc = self.csr[0] & MASK & ~3

    def run(self, max_steps=5_000_000):
        while self.halted is None and self.retired < max_steps:
            if self.irq_pending():
                # timer interrupt: taken before the next instruction (precise, epc = that instruction)
                self.trace.append(f"I {IRQ_TIMER} {self.pc:x}")
                self.enter_trap(IRQ_FLAG | IRQ_TIMER, 0)
                continue
            try:
                pc, npc, wrote = self.step()
            except Trap as tr:
                self.trace.append(f"T {tr.cause} {self.pc:x} {tr.tval:x}")
                self.enter_trap(tr.cause, tr.tval)
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
