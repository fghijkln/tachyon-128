"""Random instruction-stream generator for golden-vs-RTL differential testing.

Each program: random register init (128-bit values via li/wide immediates), a trap handler
that skips faulting instructions and services deterministic timer interrupts (re-arming mtimecmp
= mtime + delta; mtime counts retired instructions, so golden and RTL agree on every delivery point), then a weighted random mix of every instruction class:
ALU (R/I), SIMD (all lanes), MUL/DIV, capability ops, wide immediates, loads/stores of all
sizes (through an untagged base, a bounded capability, and random bases -> faults), capability
sealing/unsealing (cseal/cunseal with a sealing authority, sealed-use faults), spills/reloads (clc/csc, incl. tag clearing by data stores and LOAD_CAP/STORE_CAP checks), forward
branches, counted backward loops, JAL, calls into PCC-bounded code regions through cjalr (incl.
short bounds -> fetch faults, missing EXEC, untagged targets), CSR traffic and illegal words.  Sources are biased
toward recently written registers to stress forwarding and interlocks.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from isa import (ALU_FUNCS, ALU_UNARY, MULDIV_FUNCS, SIMD_FUNCS, SIMD_UNARY, LANE_SUFFIX,  # noqa: E402
                 CAP_FUNCS, CAP_UNARY, CAP_RD_ONLY, CAP_RS1_ONLY, LOAD_OPS, STORE_OPS, BRANCH_OPS)

POOL = list(range(4, 41))
M = (1 << 128) - 1


class Gen:
    def __init__(self, seed):
        self.r = random.Random(seed)
        self.out = []
        self.recent = []
        self.lbl = 0
        self.cslots = []
        self.irqs = False

    def val(self):
        r = self.r
        c = r.random()
        if c < 0.3:
            return r.getrandbits(128)
        if c < 0.5:
            return r.getrandbits(r.randint(1, 128))
        if c < 0.7:
            return r.choice([0, 1, 2, 3, M, M - 1, 1 << 127, (1 << 127) - 1, 0x80, 0xFF, 1 << 64, 16, 7])
        return r.randint(-5000, 5000) & M

    def src(self):
        r = self.r
        if self.recent and r.random() < 0.55:
            return r.choice(self.recent[-3:])
        return r.choice(POOL + [0])

    def dst(self):
        d = self.r.choice(POOL) if self.r.random() > 0.03 else 0
        self.recent.append(d)
        return d

    def label(self):
        self.lbl += 1
        return f"L{self.lbl}"

    def emit(self, s):
        self.out.append("        " + s)

    def one(self, allow_ctrl=True):
        r = self.r
        k = r.choices(["alu", "alui", "simd", "md", "cap", "wide", "ld", "st", "ldcap", "stcap",
                       "ldrand", "br", "loop", "jal", "csr", "ill", "clc", "csc", "cjalr", "divw", "mulw"],
                      [18, 12, 12, 3, 7, 3, 7, 6, 4, 4, 2, 6, 2, 2, 2, 1, 3, 3, 2, 2, 2])[0]
        if not allow_ctrl and k in ("br", "loop", "jal", "cjalr"):
            k = "alu"
        if k == "alu":
            f = r.choice(ALU_FUNCS)
            if f in ALU_UNARY:
                self.emit(f"{f} r{self.dst()}, r{self.src()}")
            else:
                self.emit(f"{f} r{self.dst()}, r{self.src()}, r{self.src()}")
        elif k == "alui":
            f = r.choice(["addi", "andi", "ori", "xori", "slti", "sltiu", "slli", "srli", "srai"])
            imm = r.randint(0, 127) if f in ("slli", "srli", "srai") else r.randint(-8192, 8191)
            self.emit(f"{f} r{self.dst()}, r{self.src()}, {imm}")
        elif k == "simd":
            f = r.choice(SIMD_FUNCS)
            suf = r.choice("bhwd" if f != "vmul" else "bhw")
            if f in SIMD_UNARY:
                self.emit(f"{f}.{suf} r{self.dst()}, r{self.src()}")
            else:
                self.emit(f"{f}.{suf} r{self.dst()}, r{self.src()}, r{self.src()}")
        elif k == "md":
            f = r.choice(MULDIV_FUNCS)
            a, b = self.src(), self.src()
            d = self.dst()
            self.emit(f"{f} r{d}, r{a}, r{b}")
            if r.random() < 0.4:       # partner op on same operands (result cache)
                partner = {"mul": "mulhu", "mulhu": "mul", "div": "rem", "rem": "div",
                           "divu": "remu", "remu": "divu"}[f]
                if d not in (a, b):
                    self.emit(f"{partner} r{self.dst()}, r{a}, r{b}")
        elif k == "divw":           # divider early termination: operands of chosen significant widths
            wa, wb = r.randint(0, 128), r.randint(1, 128)
            a = r.getrandbits(wa) | (1 << (wa - 1) if wa else 0)
            b = r.getrandbits(wb) | (1 << (wb - 1))
            if r.random() < 0.3:
                a = (-a) & M
            ra, rb = self.dst(), self.dst()
            if ra == rb or 0 in (ra, rb):
                return
            self.emit(f"li r{ra}, {a}")
            self.emit(f"li r{rb}, {b}")
            self.emit(f"{r.choice(['div', 'divu', 'rem', 'remu'])} r{self.dst()}, r{ra}, r{rb}")
        elif k == "mulw":           # multiplier passes: 32-bit chunks of edge patterns, chained products
            ch = [0, 1, 0xFFFFFFFF, 0x80000000]
            a = r.choice([self.val(), sum(r.choice(ch + [r.getrandbits(32)]) << (32 * j) for j in range(4))])
            b = sum(r.choice(ch + [r.getrandbits(32)]) << (32 * j) for j in range(4))
            ra, rb = self.dst(), self.dst()
            if ra == rb or 0 in (ra, rb):
                return
            self.emit(f"li r{ra}, {a}")
            self.emit(f"li r{rb}, {b}")
            d = self.dst()
            self.emit(f"{r.choice(['mul', 'mulhu'])} r{d}, r{ra}, r{rb}")
            if r.random() < 0.5:
                self.emit(f"{r.choice(['mul', 'mulhu'])} r{self.dst()}, r{d}, r{r.choice([ra, rb, d])}")
        elif k == "cap":
            f = r.choice([c for c in CAP_FUNCS if c != "cjalr"] + ["cincaddri", "csetbndi", "cseal", "cseal", "cunseal"])
            s1 = r.choice([60, 63, self.src(), self.src()])
            if f in CAP_RD_ONLY:
                self.emit(f"{f} r{self.dst()}")
            elif f in CAP_RS1_ONLY:
                self.emit(f"{f} r{s1}")
            elif f in ("cseal", "cunseal"):
                auth = r.choice([55, 55, 55, 63, self.src()])
                self.emit(f"{f} r{self.dst()}, r{s1 if r.random() < 0.6 else self.src()}, r{auth}")
            elif f in CAP_UNARY:
                self.emit(f"{f} r{self.dst()}, r{s1}")
            elif f == "cincaddri":
                self.emit(f"cincaddri r{self.dst()}, r{s1}, {r.randint(-64, 64)}")
            elif f == "csetbndi":
                self.emit(f"csetbndi r{self.dst()}, r{s1}, {r.randint(0, 300)}")
            else:
                self.emit(f"{f} r{self.dst()}, r{s1}, r{self.src()}")
        elif k == "wide":
            self.emit(f"{r.choice(['wli', 'wins'])} r{self.dst()}, {r.getrandbits(16)}, {r.randint(0, 7)}")
        elif k in ("ld", "ldcap"):
            f = r.choice(list(LOAD_OPS))
            size = LOAD_OPS[f][1]
            off = r.randrange(0, 1024, size) if r.random() < 0.9 else r.randrange(0, 1024)
            base = 3 if k == "ld" else 60
            if k == "ldcap" and r.random() < 0.15:
                off = r.choice([1024, 1024 - size + 1, -size]) if r.random() < 0.7 else off
            self.emit(f"{f} r{self.dst()}, {off}(r{base})")
        elif k in ("st", "stcap"):
            f = r.choice(list(STORE_OPS))
            size = STORE_OPS[f][1]
            off = r.randrange(0, 1024, size) if r.random() < 0.9 else r.randrange(0, 1024)
            base = 3 if k == "st" else 60
            if k == "stcap" and r.random() < 0.15:
                off = r.choice([1024, -size, 2000])
            self.emit(f"{f} r{self.src()}, {off}(r{base})")
        elif k in ("clc", "csc"):     # tagged memory: granule-aligned mostly, via r3 (unchecked) or r60 (cap)
            base = r.choice([3, 60])
            off = r.randrange(0, 1024, 16) if r.random() < 0.9 else r.choice([8, 4] + ([1024, -16] if base == 60 else []))
            if k == "csc" and off % 16 == 0 and 0 <= off < 1024:
                self.cslots.append(off)
            if k == "clc" and self.cslots and r.random() < 0.7:
                off = r.choice(self.cslots[-4:])          # reload a recently spilled granule
            if k == "clc":
                self.emit(f"clc r{self.dst()}, {off}(r{base})")
            else:
                data = r.choice([60, 63, self.src(), self.src()])
                self.emit(f"csc r{data}, {off}(r{base})")
        elif k == "ldrand":         # random base: mostly access/align/cap faults, never a store
            f = r.choice(list(LOAD_OPS))
            self.emit(f"{f} r{self.dst()}, {r.randint(-64, 64)}(r{self.src()})")
        elif k == "br":
            f = r.choice(list(BRANCH_OPS) + ["beqz", "bnez"])
            L = self.label()
            if f in ("beqz", "bnez"):
                self.emit(f"{f} r{self.src()}, {L}")
            else:
                self.emit(f"{f} r{self.src()}, r{self.src()}, {L}")
            for _ in range(r.randint(0, 4)):
                self.one(allow_ctrl=False)
            self.out.append(f"{L}:")
        elif k == "loop":
            L = self.label()
            self.emit(f"li r61, {r.randint(1, 6)}")
            self.out.append(f"{L}:")
            for _ in range(r.randint(1, 6)):
                self.one(allow_ctrl=False)
            self.emit("addi r61, r61, -1")
            self.emit(f"bnez r61, {L}")
        elif k == "jal":
            L = self.label()
            self.emit(f"jal r{self.dst()}, {L}")
            for _ in range(r.randint(0, 3)):
                self.one(allow_ctrl=False)
            self.out.append(f"{L}:")
        elif k == "cjalr":          # call a PCC-bounded region through a code capability, return via link cap
            Lt, Le, La = self.label(), self.label(), self.label()
            self.emit(f"la r57, {Lt}")
            self.emit("csetaddr r57, rc, r57")
            size = f"{Le} - {Lt} + 4" if r.random() < 0.75 else f"({Le} - {Lt}) // 2"   # short -> fetch fault
            self.emit(f"csetbndi r57, r57, {size}")
            c = r.random()
            if c < 0.1:
                self.emit("li r56, 0x1B")            # no EXEC -> cap-permission at the cjalr
                self.emit("candperm r57, r57, r56")
            self.emit("cjalr r56, r0" if c > 0.93 else "cjalr r56, r57")   # untagged -> cap-tag
            self.emit(f"j {La}")
            self.out.append(f"{Lt}:")
            for _ in range(r.randint(1, 8)):
                self.one(allow_ctrl=False)
            if r.random() < 0.3:
                self.emit(f"cgetpcc r{self.dst()}")
            self.out.append(f"{Le}:")
            self.emit("cjalr r0, r56")
            self.out.append(f"{La}:")
        elif k == "csr":
            if r.random() < 0.5:
                self.emit(f"csrw scratch, r{self.src()}")
            self.emit(f"csrr r{self.dst()}, {r.choice(['scratch', 'cause', 'tval', 'epc', 'tvec', 'status'])}")
            if self.irqs and r.random() < 0.2:      # toggle interrupt enables
                self.emit(f"li r51, {r.choice([0, 1, 4, 5, 5, 7])}")
                self.emit("csrw status, r51")
            if r.random() < 0.3:                    # read the timer registers
                self.emit(f"{r.choice(['lq', 'ld', 'lw', 'lbu'])} r{self.dst()}, {r.choice([0x30, 0x40])}(r52)")
        elif k == "ill":
            self.emit(f".word 0x{r.choice([0, 0xff000001, 0x37000003, 0x00000007, 0x0080003d]):08x}")


def gen_program(seed, n=None):
    g = Gen(seed)
    r = g.r
    n = n or r.randint(120, 320)
    g.out.append("        .org 0")
    g.emit("la r4, handler")
    g.emit("csrw tvec, r4")
    g.emit("la r3, data")
    g.emit("li r5, 1024")
    g.emit("csetaddr r60, rc, r3")
    g.emit("csetbnd r60, r60, r5")
    if r.random() < 0.5:
        g.emit("li r6, 3")              # sometimes a read-only data capability
        g.emit(f"candperm r60, r60, r{r.choice([6, 5])}")
    elif r.random() < 0.3:
        g.emit(f"li r6, {r.choice([0x0F, 0x17, 0x1B])}")   # drop LOAD_CAP or STORE_CAP or LOAD
        g.emit("candperm r60, r60, r6")
    g.emit("li r54, 0x60")                  # sealing authority (SEAL|UNSEAL), cursor = small otype
    g.emit("candperm r55, rc, r54")
    g.emit(f"li r54, {r.choice([0, 1, 1, 2, 3, 3, 0x10000])}")
    g.emit("csetaddr r55, r55, r54")
    g.emit("li r52, -0x10000")              # MMIO base (timer registers at +0x30 / +0x40)
    for reg in POOL:
        if r.random() < 0.8:
            g.emit(f"li r{reg}, {g.val()}")
    irqs = r.random() < 0.6
    delta = r.randint(8, 80)              # > handler length, so the mainline always progresses
    if irqs:                                # deterministic timer interrupts (mtime = retired count)
        g.irqs = True
        g.emit(f"li r51, {r.randint(5, 200)}")
        g.emit("sq r51, 0x40(r52)")
        g.emit(f"li r51, {r.choice([5, 5, 5, 7, 1])}")
        g.emit("csrw status, r51")
    for _ in range(n):
        g.one()
    g.emit("halt zero")
    g.out.append("handler:")
    g.emit("csrr r62, cause")
    g.emit("bltz r62, Hirq")
    g.emit("csrr r59, epc")
    g.emit("csrr r58, tval")
    g.emit("bne r58, r59, Hskip")
    g.emit("csetepcc rc")             # fetch fault (tval == epc): resume under the root PCC
    g.out.append("Hskip:")
    g.emit("addi r59, r59, 4")
    g.emit("csrw epc, r59")
    g.emit("eret")
    g.out.append("Hirq:")                   # timer interrupt: re-arm mtimecmp = mtime + delta, resume at epc
    g.emit("addi r50, r50, 1")
    g.emit("lq r51, 0x30(r52)")
    g.emit(f"addi r51, r51, {delta}")
    g.emit("sq r51, 0x40(r52)")
    g.emit("eret")
    g.out.append("        .align 16")
    g.out.append("data:")
    for _ in range(64):
        g.out.append(f"        .quad {r.getrandbits(128)}")
    return "\n".join(g.out) + "\n"


if __name__ == "__main__":
    print(gen_program(int(sys.argv[1]) if len(sys.argv) > 1 else 1))
