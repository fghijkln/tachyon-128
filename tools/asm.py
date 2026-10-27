#!/usr/bin/env python3
"""TACHYON-128 two-pass assembler.

Usage: asm.py prog.s -o prog.bin [--hex prog.hex] [--lst prog.lst]

Syntax summary (see SPEC.md section 6):
  label:            labels (also numeric expressions with labels, + - * / << >> & | ~ ( ))
  # or ;            comments
  .org N  .align N  .space N  .equ NAME, EXPR
  .byte .half .word .dword .quad (128-bit)  .ascii "..."  .asciz "..."
Pseudo-ops: nop li la mv cmove not neg j call ret jr beqz bnez bltz bgez bgtz blez
            bgt ble bgtu bleu seqz snez halt
"""
import ast
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from isa import *  # noqa: E402,F401,F403


class AsmError(Exception):
    pass


def parse_reg(tok):
    t = tok.strip().lower()
    if t in REG_ALIAS:
        return REG_ALIAS[t]
    m = re.fullmatch(r"r(\d+)", t)
    if m and int(m.group(1)) < NREGS:
        return int(m.group(1))
    raise AsmError(f"bad register '{tok}'")


_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
           ast.FloorDiv: lambda a, b: a // b, ast.Div: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
           ast.LShift: lambda a, b: a << b, ast.RShift: lambda a, b: a >> b,
           ast.BitAnd: lambda a, b: a & b, ast.BitOr: lambda a, b: a | b, ast.BitXor: lambda a, b: a ^ b,
           ast.Pow: lambda a, b: a ** b}


def eval_expr(s, syms):
    s = s.strip()
    # character literal
    s = re.sub(r"'(\\?.)'", lambda m: str(ord(bytes(m.group(1), "utf-8").decode("unicode_escape"))), s)
    try:
        tree = ast.parse(s, mode="eval")
    except SyntaxError:
        raise AsmError(f"bad expression '{s}'")

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, int):
            return n.value
        if isinstance(n, ast.Name):
            if n.id in syms:
                return syms[n.id]
            raise KeyError(n.id)
        if isinstance(n, ast.BinOp) and type(n.op) in _BINOPS:
            return _BINOPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp):
            v = ev(n.operand)
            if isinstance(n.op, ast.USub):
                return -v
            if isinstance(n.op, ast.UAdd):
                return v
            if isinstance(n.op, ast.Invert):
                return ~v
        raise AsmError(f"unsupported expression '{s}'")
    return ev(tree)


def split_operands(s):
    out, cur, depth, q = [], "", 0, False
    for ch in s:
        if ch == '"':
            q = not q
        if not q and ch == "(":
            depth += 1
        if not q and ch == ")":
            depth -= 1
        if ch == "," and depth == 0 and not q:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def li_sequence(rd, value):
    """Shortest sequence materialising a 128-bit constant (wide-immediate 'constant fusion').
    Returns list of (kind, args) where kind in {'addi','wli','wins'}."""
    v = value & MASK
    sv = to_signed(v)
    if -8192 <= sv < 8192:
        return [("addi", (rd, 0, sv))]
    halves = [(v >> (16 * i)) & 0xFFFF for i in range(8)]
    cands = []
    # base 0 via wli of the first non-zero slot
    nz = [i for i in range(8) if halves[i]]
    seq = [("wli", (rd, halves[nz[0]], nz[0], 0))] + [("wins", (rd, halves[i], i, 1)) for i in nz[1:]]
    cands.append(seq)
    # base = sign-extended simm14 (all-ones, or the constant's own low 14 bits), then patch slots
    for base in (-1, sext(v, 14)):
        bh = [((base & MASK) >> (16 * i)) & 0xFFFF for i in range(8)]
        seq = [("addi", (rd, 0, base))] + [("wins", (rd, halves[i], i, 1)) for i in range(8) if halves[i] != bh[i]]
        cands.append(seq)
    return min(cands, key=len)


class Assembler:
    def __init__(self):
        self.syms = {}
        self.lines = []

    # ------------------------------------------------------------ helpers
    def ev(self, s, final):
        try:
            return eval_expr(s, self.syms)
        except KeyError as e:
            if final:
                raise AsmError(f"undefined symbol {e}")
            return 0

    def mem_operand(self, s, final):
        m = re.fullmatch(r"(.*)\((\s*\w+\s*)\)", s.strip())
        if not m:
            raise AsmError(f"bad memory operand '{s}'")
        off = m.group(1).strip()
        return (self.ev(off, final) if off else 0), parse_reg(m.group(2))

    # ------------------------------------------------------------ instruction expansion
    def expand(self, mn, ops, pc, final):
        """Return list of 32-bit words for one source instruction (or pseudo-op)."""
        R = parse_reg
        E = lambda s: self.ev(s, final)  # noqa: E731
        n = len(ops)

        def need(k):
            if n != k:
                raise AsmError(f"'{mn}' expects {k} operands, got {n}")

        def imm14(v, signed=True):
            if signed and not -8192 <= v < 8192:
                raise AsmError(f"immediate {v} out of simm14 range")
            if not signed and not 0 <= v < 16384:
                raise AsmError(f"immediate {v} out of uimm14 range")
            return v

        def boff(target, bits):
            d = target - pc
            if d % 4:
                raise AsmError("branch target not word aligned")
            d //= 4
            lim = 1 << (bits - 1)
            if final and not -lim <= d < lim:
                raise AsmError(f"branch target out of range ({d} words)")
            return d

        # ---- real instructions
        if mn in ALU_FUNCS:
            if mn in ALU_UNARY:
                need(2)
                return [enc_r(OP_ALU, R(ops[0]), R(ops[1]), 0, ALU_FUNCS.index(mn))]
            need(3)
            return [enc_r(OP_ALU, R(ops[0]), R(ops[1]), R(ops[2]), ALU_FUNCS.index(mn))]
        if mn in MULDIV_FUNCS:
            need(3)
            return [enc_r(OP_MULDIV, R(ops[0]), R(ops[1]), R(ops[2]), MULDIV_FUNCS.index(mn))]
        if "." in mn and mn.split(".")[0] in SIMD_FUNCS:
            base, suf = mn.split(".", 1)
            if suf not in LANE_SUFFIX:
                raise AsmError(f"bad lane suffix '.{suf}'")
            if base == "vmul" and suf == "d":
                raise AsmError("vmul.d is not defined (64-bit lane multiply)")
            func = SIMD_FUNCS.index(base) << 2 | LANE_SUFFIX[suf]
            if base in SIMD_UNARY:
                need(2)
                return [enc_r(OP_SIMD, R(ops[0]), R(ops[1]), 0, func)]
            need(3)
            return [enc_r(OP_SIMD, R(ops[0]), R(ops[1]), R(ops[2]), func)]
        if mn in AMO_FUNCS:
            def amo_addr(s):
                off, reg = self.mem_operand(s, final)
                if off:
                    raise AsmError("atomics take no offset: use (rs1)")
                return reg
            if mn == "lr":
                need(2)
                return [enc_r(OP_AMO, R(ops[0]), amo_addr(ops[1]), 0, 0)]
            need(3)
            return [enc_r(OP_AMO, R(ops[0]), amo_addr(ops[2]), R(ops[1]), AMO_FUNCS.index(mn))]
        if mn in CAP_RD_ONLY:
            need(1)
            return [enc_r(OP_CAP, R(ops[0]), 0, 0, CAP_FUNCS.index(mn))]
        if mn in CAP_RS1_ONLY:
            need(1)
            return [enc_r(OP_CAP, 0, R(ops[0]), 0, CAP_FUNCS.index(mn))]
        if mn in CAP_FUNCS:
            if mn in CAP_UNARY:
                need(2)
                return [enc_r(OP_CAP, R(ops[0]), R(ops[1]), 0, CAP_FUNCS.index(mn))]
            need(3)
            return [enc_r(OP_CAP, R(ops[0]), R(ops[1]), R(ops[2]), CAP_FUNCS.index(mn))]
        if mn in I_OPS:
            need(3)
            v = E(ops[2])
            if mn in ("slli", "srli", "srai"):
                if not 0 <= v < 128:
                    raise AsmError("shift amount out of range")
            elif mn == "csetbndi":
                imm14(v, signed=False)
            else:
                imm14(v)
            return [enc_i(I_OPS[mn], R(ops[0]), R(ops[1]), v)]
        if mn in LOAD_OPS or mn in CAP_LOAD_OPS:
            need(2)
            off, base = self.mem_operand(ops[1], final)
            op = LOAD_OPS[mn][0] if mn in LOAD_OPS else CAP_LOAD_OPS[mn]
            return [enc_i(op, R(ops[0]), base, imm14(off))]
        if mn in STORE_OPS or mn in CAP_STORE_OPS:
            need(2)
            off, base = self.mem_operand(ops[1], final)
            op = STORE_OPS[mn][0] if mn in STORE_OPS else CAP_STORE_OPS[mn]
            return [enc_i(op, R(ops[0]), base, imm14(off))]
        if mn in BRANCH_OPS:
            need(3)
            # enc: field A = rs2, rs1 field = rs1
            return [enc_i(BRANCH_OPS[mn], R(ops[1]), R(ops[0]), boff(E(ops[2]), 14))]
        if mn == "jal":
            if n == 1:
                return [enc_j(OP_JAL, 1, boff(E(ops[0]), 20))]
            need(2)
            return [enc_j(OP_JAL, R(ops[0]), boff(E(ops[1]), 20))]
        if mn == "jalr":
            if n == 2:
                off, base = self.mem_operand(ops[1], final) if "(" in ops[1] else (0, R(ops[1]))
                return [enc_i(OP_JALR, R(ops[0]), base, imm14(off))]
            need(3)
            return [enc_i(OP_JALR, R(ops[0]), R(ops[1]), imm14(E(ops[2])))]
        if mn in ("wli", "wins"):
            need(3)
            v, slot = E(ops[1]), E(ops[2])
            if not 0 <= v < 65536 or not 0 <= slot < 8:
                raise AsmError("wli/wins: imm16 0..65535, slot 0..7")
            return [enc_k(R(ops[0]), v, slot, 1 if mn == "wins" else 0)]
        if mn == "halt":
            return [enc_i(OP_HALT, 0, R(ops[0]) if n else 0, 0)]
        if mn == "csrr":
            need(2)
            return [enc_i(OP_CSRR, R(ops[0]), 0, self.csr(ops[1], final))]
        if mn == "csrw":
            need(2)
            return [enc_i(OP_CSRW, 0, R(ops[1]), self.csr(ops[0], final))]
        if mn == "eret":
            need(0)
            return [enc_i(OP_ERET, 0, 0, 0)]
        if mn == "ecall":
            need(0)
            return [enc_i(OP_ECALL, 0, 0, 0)]

        # ---- pseudo-ops
        if mn == "nop":
            return [enc_i(OP_ADDI, 0, 0, 0)]
        if mn == "li":
            need(2)
            try:
                v = eval_expr(ops[1], self.syms)
            except KeyError:
                raise AsmError("li needs a constant known at that point (use 'la' for labels)")
            out = []
            for kind, a in li_sequence(R(ops[0]), v):
                if kind == "addi":
                    out.append(enc_i(OP_ADDI, a[0], a[1], a[2]))
                else:
                    out.append(enc_k(*a))
            return out
        if mn == "la":   # fixed 2-instruction form, address < 2^32
            need(2)
            v = E(ops[1])
            if final and not 0 <= v < (1 << 32):
                raise AsmError("la: address must be < 2^32")
            rd = R(ops[0])
            return [enc_k(rd, v & 0xFFFF, 0, 0), enc_k(rd, (v >> 16) & 0xFFFF, 1, 1)]
        if mn == "mv":
            need(2)
            return [enc_i(OP_ADDI, R(ops[0]), R(ops[1]), 0)]
        if mn == "cmove":
            need(2)
            return [enc_i(OP_CINCADDRI, R(ops[0]), R(ops[1]), 0)]
        if mn == "not":
            need(2)
            return [enc_i(OP_XORI, R(ops[0]), R(ops[1]), -1)]
        if mn == "neg":
            need(2)
            return [enc_r(OP_ALU, R(ops[0]), 0, R(ops[1]), ALU_FUNCS.index("sub"))]
        if mn == "seqz":
            need(2)
            return [enc_i(OP_SLTIU, R(ops[0]), R(ops[1]), 1)]
        if mn == "snez":
            need(2)
            return [enc_r(OP_ALU, R(ops[0]), 0, R(ops[1]), ALU_FUNCS.index("sltu"))]
        if mn == "j":
            need(1)
            return [enc_j(OP_JAL, 0, boff(E(ops[0]), 20))]
        if mn == "call":
            need(1)
            return [enc_j(OP_JAL, 1, boff(E(ops[0]), 20))]
        if mn == "ret":
            return [enc_i(OP_JALR, 0, 1, 0)]
        if mn == "jr":
            need(1)
            return [enc_i(OP_JALR, 0, R(ops[0]), 0)]
        zb = {"beqz": "beq", "bnez": "bne", "bltz": "blt", "bgez": "bge"}
        if mn in zb:
            need(2)
            return [enc_i(BRANCH_OPS[zb[mn]], 0, R(ops[0]), boff(E(ops[1]), 14))]
        if mn in ("bgtz", "blez"):   # 0 < rs  /  0 >= rs
            need(2)
            op = OP_BLT if mn == "bgtz" else OP_BGE
            return [enc_i(op, R(ops[0]), 0, boff(E(ops[1]), 14))]
        sw = {"bgt": "blt", "ble": "bge", "bgtu": "bltu", "bleu": "bgeu"}
        if mn in sw:
            need(3)
            return [enc_i(BRANCH_OPS[sw[mn]], R(ops[0]), R(ops[1]), boff(E(ops[2]), 14))]
        raise AsmError(f"unknown mnemonic '{mn}'")

    def csr(self, s, final):
        s = s.strip().lower()
        if s in CSR_NAMES:
            return CSR_NAMES[s]
        v = self.ev(s, final)
        if not 0 <= v < NUM_CSRS:
            raise AsmError(f"bad csr '{s}'")
        return v

    # ------------------------------------------------------------ data directives
    def directive(self, d, args, pc, final):
        """Return bytes emitted (or new pc for .org via ('org', addr))."""
        ops = split_operands(args) if args else []
        if d == ".org":
            return ("org", self.ev(ops[0], True))
        if d == ".align":
            a = self.ev(ops[0], True)
            return bytes((-pc) % a)
        if d == ".space":
            return bytes(self.ev(ops[0], True))
        if d == ".equ" or d == ".set":
            self.syms[ops[0]] = self.ev(ops[1], final)
            return b""
        if d in (".text", ".data", ".global", ".globl", ".section"):
            return b""
        sizes = {".byte": 1, ".half": 2, ".word": 4, ".dword": 8, ".quad": 16}
        if d in sizes:
            sz = sizes[d]
            out = b""
            for o in ops:
                v = self.ev(o, final) & ((1 << (8 * sz)) - 1)
                out += v.to_bytes(sz, "little")
            return out
        if d in (".ascii", ".asciz", ".string"):
            out = b""
            for o in ops:
                o = o.strip()
                if not (o.startswith('"') and o.endswith('"')):
                    raise AsmError("string expected")
                out += bytes(o[1:-1], "utf-8").decode("unicode_escape").encode("latin-1")
                if d != ".ascii":
                    out += b"\0"
            return out
        raise AsmError(f"unknown directive '{d}'")

    # ------------------------------------------------------------ passes
    def run_pass(self, src, final):
        image = {}
        listing = []
        pc = 0
        for lineno, raw in enumerate(src.splitlines(), 1):
            line = re.split(r"[#;]", raw, 1)[0] if '"' not in raw else self.strip_comment(raw)
            line = line.strip()
            try:
                while True:
                    m = re.match(r"^([A-Za-z_.$][\w.$]*):", line)
                    if not m:
                        break
                    name = m.group(1)
                    if not final and name in self.syms and self.defined.get(name):
                        raise AsmError(f"duplicate label '{name}'")
                    self.syms[name] = pc
                    self.defined[name] = True
                    line = line[m.end():].strip()
                if not line:
                    continue
                parts = line.split(None, 1)
                mn = parts[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                if mn.startswith("."):
                    r = self.directive(mn, args, pc, final)
                    if isinstance(r, tuple):
                        pc = r[1]
                        continue
                    for i, b in enumerate(r):
                        image[pc + i] = b
                    if r:
                        listing.append((pc, None, raw.strip()))
                    pc += len(r)
                    continue
                if pc % 4:
                    raise AsmError("instruction not word aligned (use .align 4)")
                words = self.expand(mn, split_operands(args), pc, final)
                for i, w in enumerate(words):
                    for k, b in enumerate(struct.pack("<I", w)):
                        image[pc + 4 * i + k] = b
                    listing.append((pc + 4 * i, w, raw.strip() if i == 0 else ""))
                pc += 4 * len(words)
            except AsmError as e:
                raise AsmError(f"line {lineno}: {e}\n    {raw.strip()}")
        return image, listing

    @staticmethod
    def strip_comment(raw):
        q = False
        for i, ch in enumerate(raw):
            if ch == '"':
                q = not q
            elif ch in "#;" and not q:
                return raw[:i]
        return raw

    def assemble(self, src):
        self.defined = {}
        self.run_pass(src, False)
        self.defined = {}
        image, listing = self.run_pass(src, True)
        size = (max(image) + 1) if image else 0
        buf = bytearray(size)
        for a, b in image.items():
            buf[a] = b
        return bytes(buf), listing


def preprocess(path, seen=None):
    """Expand `.include "file"` (relative to the including file)."""
    seen = seen or set()
    path = os.path.abspath(path)
    if path in seen:
        raise AsmError(f"recursive include of {path}")
    out = []
    for line in open(path):
        m = re.match(r'\s*\.include\s+"([^"]+)"', line)
        if m:
            out.append(preprocess(os.path.join(os.path.dirname(path), m.group(1)), seen | {path}))
        else:
            out.append(line.rstrip("\n"))
    return "\n".join(out)


def assemble_file(path):
    return Assembler().assemble(preprocess(path))


def write_hex128(binary, path):
    """$readmemh image: one 128-bit little-endian word per line."""
    b = binary + bytes((-len(binary)) % 16)
    with open(path, "w") as f:
        for i in range(0, len(b), 16):
            f.write(f"{int.from_bytes(b[i:i+16], 'little'):032x}\n")


def main():
    import argparse
    from disasm import disasm
    ap = argparse.ArgumentParser(description="TACHYON-128 assembler")
    ap.add_argument("src")
    ap.add_argument("-o", "--out")
    ap.add_argument("--hex")
    ap.add_argument("--lst")
    a = ap.parse_args()
    try:
        binary, listing = assemble_file(a.src)
    except AsmError as e:
        sys.exit(f"{a.src}: {e}")
    out = a.out or os.path.splitext(a.src)[0] + ".bin"
    with open(out, "wb") as f:
        f.write(binary)
    if a.hex:
        write_hex128(binary, a.hex)
    if a.lst:
        with open(a.lst, "w") as f:
            for pc, w, src in listing:
                if w is None:
                    f.write(f"{pc:08x}            {src}\n")
                else:
                    f.write(f"{pc:08x}  {w:08x}  {disasm(w, pc):32s} {src}\n")
    print(f"{out}: {len(binary)} bytes")


if __name__ == "__main__":
    main()
