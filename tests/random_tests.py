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
                       "ldrand", "br", "loop", "jal", "csr", "ill", "clc", "csc", "cjalr", "divw", "mulw", "cinvoke", "user", "bpat", "call", "vmulx", "nest", "perm4", "amo", "word"],
                      [18, 12, 12, 3, 7, 3, 7, 6, 4, 4, 2, 6, 2, 2, 2, 1, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 4, 4])[0]
        if not allow_ctrl and k in ("br", "loop", "jal", "cjalr", "cinvoke", "user", "bpat", "call", "nest"):
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
                           "divu": "remu", "remu": "divu", "mulw": "mul", "mulwu": "mulw",
                           "divw": "remw", "remw": "div"}[f]
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
        elif k == "vmulx":          # v4 shared multiplier array: lane-edge vmul next to scalar mul passes
            lanes = [0, 1, 0x7F, 0x80, 0xFF, 0x7FFF, 0x8000, 0xFFFF, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF]
            def lanev():
                w = r.choice([8, 16, 32])
                return sum((r.choice(lanes + [r.getrandbits(w)]) & ((1 << w) - 1)) << (w * j) for j in range(128 // w))
            ra, rb = self.dst(), self.dst()
            if ra == rb or 0 in (ra, rb):
                return
            self.emit(f"li r{ra}, {lanev()}")
            self.emit(f"li r{rb}, {lanev() if r.random() < 0.7 else self.val()}")
            seq = r.choice([["v", "m"], ["m", "v"], ["v", "m", "v"], ["m", "v", "m"], ["v", "v"]])
            last = None
            for op in seq:
                x, y = r.choice([(ra, rb), (rb, ra), (ra, ra)] + ([(last, rb), (ra, last)] if last else []))
                d = self.dst()
                if op == "v":
                    self.emit(f"vmul.{r.choice('bhw')} r{d}, r{x}, r{y}")
                else:
                    self.emit(f"{r.choice(['mul', 'mulhu'])} r{d}, r{x}, r{y}")
                last = d if d else None
        elif k == "cap":
            f = r.choice([c for c in CAP_FUNCS if c not in ("cjalr", "cinvoke")] +
                         ["cincaddri", "csetbndi", "cseal", "cseal", "cunseal", "csealentry", "cmove", "cmove"])
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
            elif c < 0.4:
                self.emit("csealentry r57, r57")     # sentry call: unsealed on entry, link is a sentry
                if r.random() < 0.4:
                    self.emit("cmove r57, r57" if r.random() < 0.3 else f"cmove r{self.dst()}, r57")   # v6: copies keep the seal
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
        elif k == "amo":            # v4 atomics: lr/sc pairs (+ disturbances), AMOs, faults, capability swaps
            if allow_ctrl:          # (inside fetch-fault regions r57 could be stale -> base registers only)
                c = r.random()
                off = r.randrange(0, 1024, 16) if c < 0.9 else r.choice([8, 4, 1, 1024, 1040])   # (never below data: code)
                if r.random() < 0.5:
                    self.emit(f"addi r57, r3, {off}")          # untagged (hybrid) address
                else:
                    self.emit(f"cincaddri r57, r60, {off}")       # through the data capability
                base = 57 if r.random() > 0.03 else 52           # (MMIO -> access fault)
            else:
                base = r.choice([3, 60])
            c = r.random()
            if c < 0.45:
                self.emit(f"lr r{self.dst()}, (r{base})")
                for _ in range(r.choice([0, 0, 1, 2])):
                    if r.random() < 0.2:
                        self.emit(f"sq r{self.src()}, {r.randrange(0, 1024, 16)}(r3)")   # clears the reservation
                    else:
                        self.one(allow_ctrl=False)
                self.emit(f"sc r{self.dst()}, r{self.src()}, (r{base if r.random() < 0.85 else 3})")
                if r.random() < 0.3:
                    self.emit(f"sc r{self.dst()}, r{self.src()}, (r{base})")             # second sc fails
            else:
                fn = r.choice(["amoswap", "amoswap", "amoadd", "amoand", "amoor", "amoxor"])
                data = r.choice([self.src(), self.src(), 58, 60, 63])                   # sometimes a capability
                self.emit(f"{fn} r{self.dst()}, r{data}, (r{base})")
        elif k == "perm4":          # v4 GLOBAL / LOAD_MUTABLE / STORE_LOCAL: derive a data cap with chosen perms
            mask = r.choice([0x77F, 0x6FF, 0x3FF, 0x37F, 0x5FF, 0x7FF, 0x59B, 0x41B, 0x19B, r.getrandbits(11)])
            self.emit(f"li r57, {mask}")
            self.emit("candperm r58, r60, r57")
            off = r.randrange(0, 1024, 16)
            c = r.random()
            # inside PCC-bounded regions any instruction (the candperm too) may be skipped by a fetch fault,
            # leaving a stale untagged r58: never store through r58 there (it could hit code)
            sb = 58 if allow_ctrl else 60
            if c < 0.35:            # store the (possibly local) cap through r60 / itself / an untagged pointer
                self.emit(f"csc r58, {off}(r{r.choice([60, sb, 3])})")
            elif c < 0.6:           # store any register through it
                self.emit(f"csc r{self.src()}, {off}(r{sb})")
            elif c < 0.9:           # load through it (LOAD_MUTABLE attenuation), maybe follow the loaded cap
                d = self.dst()
                self.emit(f"clc r{d}, {off}(r58)")
                if d and r.random() < 0.5:
                    self.emit(f"cgetperm r{self.dst()}, r{d}")
                    self.emit(f"clc r{self.dst()}, {r.randrange(0, 64, 16)}(r{d})")
            else:
                self.emit(f"cgetperm r{self.dst()}, r58")
        elif k == "cinvoke":        # CInvoke-style domain call: sealed code + data pair, return sentry
            Lp, Lr, Lt, Le, La = (self.label() for _ in range(5))
            self.emit(f"la r57, {Lt}")
            self.emit("csetaddr r57, rc, r57")
            self.emit(f"csetbndi r57, r57, {Le} - {Lt} + 4")
            if r.random() < 0.12:
                self.emit("addi r59, r0, 0x5FF")                          # v4: code without PERMIT_CINVOKE
                self.emit("candperm r57, r57, r59")
            c = r.random()
            self.emit(f"cseal r57, r57, r{55 if c > 0.05 else 63}")        # sealed code (root: bad otype)
            if c < 0.1:
                self.emit("csealentry r57, r57")                          # (fails: already sealed / untagged)
            c2 = r.random()
            if c2 < 0.1:                                                  # data sealed with otype+1 -> mismatch
                self.emit("cincaddri r59, r55, 1")
                self.emit("cseal r59, r60, r59")
            else:
                self.emit(f"cseal r59, r{60 if c2 > 0.17 else 63}, r55")  # sealed data (rc has EXEC -> fault)
            if r.random() < 0.05:
                self.emit("cunseal r59, r59, r55")                        # unsealed data -> cap-sealed
            self.out.append(f"{Lp}:")
            self.emit("cgetpcc r56")
            self.emit(f"cincaddri r56, r56, {Lr} - {Lp}")
            if r.random() < 0.8:
                self.emit("csealentry r56, r56")                          # return sentry
            self.emit(f"cinvoke r58, r57, r59")
            self.out.append(f"{Lr}:")
            self.emit(f"j {La}")
            self.out.append(f"{Lt}:")
            for _ in range(r.randint(1, 6)):
                if r.random() < 0.25:
                    self.emit(f"{r.choice(['lq', 'ld', 'clc'])} r{self.dst()}, {r.randrange(0, 1024, 16)}(r58)")
                else:
                    self.one(allow_ctrl=False)
            self.out.append(f"{Le}:")
            self.emit("cjalr r0, r56")
            self.out.append(f"{La}:")
        elif k == "user":           # drop to user mode for a block, come back with ecall
            Lu = self.label()
            self.emit("csrr r57, status")
            self.emit("andi r57, r57, -2")             # IE off first: an interrupt here would clobber epc
            self.emit("ori r57, r57, 16")              # PU
            if r.random() < 0.5:
                self.emit("ori r57, r57, 2")           # PIE: interrupts enabled again in user mode
            self.emit("csrw status, r57")
            self.emit(f"la r57, {Lu}")
            self.emit("csrw epc, r57")
            self.emit("csetepcc rc")
            self.emit("eret")
            self.out.append(f"{Lu}:")
            for _ in range(r.randint(1, 10)):
                c = r.random()
                if c < 0.12:                           # privileged instruction -> privilege-violation
                    self.emit(r.choice(["csrr r57, status", "csrw scratch, r57", "eret", "halt zero",
                                        "csetepcc rc", "csrw status, r0"]))
                elif c < 0.3:                          # hybrid access around the user window
                    f = r.choice(["lq", "ld", "lbu", "sq", "sd", "sb"])
                    if f[0] == "s":
                        self.emit(f"{f} r{self.src()}, {r.randrange(0, 1100, 8)}(r3)")   # never below data (code)
                    else:
                        self.emit(f"{f} r{self.dst()}, {r.randrange(-64, 1100, 8)}(r3)")
                elif c < 0.36:
                    self.emit(f"{r.choice(['lq', 'sb'])} r{self.src()}, {r.choice([0, 0x30, 0x10])}(r52)")  # MMIO
                else:
                    self.one(allow_ctrl=False)
            self.emit("ecall")
        elif k == "bpat":           # loop with a data-dependent inner branch (exercises the 2-bit counters)
            L, Ls = self.label(), self.label()
            self.emit(f"li r61, {r.randint(2, 12)}")
            self.out.append(f"{L}:")
            self.emit(f"andi r57, r61, {r.choice([1, 2, 3, 4, 7])}")
            self.emit(f"{r.choice(['beqz', 'bnez'])} r57, {Ls}")
            for _ in range(r.randint(0, 2)):
                self.one(allow_ctrl=False)
            self.out.append(f"{Ls}:")
            self.one(allow_ctrl=False)
            self.emit("addi r61, r61, -1")
            self.emit(f"bnez r61, {L}")
        elif k == "call":           # shared subroutines called from many sites: stale BTB return targets
            self.emit(f"jal r1, SUB{r.randint(0, 1)}")
        elif k == "nest":           # v4 RAS: enter a 9-deep call chain at a random depth (8-entry RAS overflows)
            self.emit(f"jal r1, NEST{r.randint(0, 8)}")
        elif k == "csr":
            if r.random() < 0.5:
                self.emit(f"csrw scratch, r{self.src()}")
            self.emit(f"csrr r{self.dst()}, {r.choice(['scratch', 'cause', 'tval', 'epc', 'tvec', 'status'])}")
            if self.irqs and r.random() < 0.2:      # toggle interrupt enables
                self.emit(f"li r51, {r.choice([0, 1, 4, 5, 5, 7])}")
                self.emit("csrw status, r51")
            if r.random() < 0.3:                    # read the timer registers
                self.emit(f"{r.choice(['lq', 'ld', 'lw', 'lbu'])} r{self.dst()}, {r.choice([0x30, 0x40])}(r52)")
        elif k == "word":           # v5 32-bit word ops on word-edge operands, dependent chains, imm forms
            edge = [0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, M, 1 << 31 | 1 << 100, r.getrandbits(32)]
            ra, rb = self.dst(), self.dst()
            if ra == rb or 0 in (ra, rb):
                return
            self.emit(f"li r{ra}, {r.choice(edge + [self.val()])}")
            self.emit(f"li r{rb}, {r.choice(edge + [r.randint(0, 40), self.val()])}")
            src = ra
            for _ in range(r.randint(1, 4)):
                d = self.dst()
                c = r.random()
                if c < 0.45:
                    f = r.choice(["addw", "subw", "sllw", "srlw", "sraw", "addwu", "subwu", "sllwu"])
                    self.emit(f"{f} r{d}, r{src}, r{rb}")
                elif c < 0.75:
                    f = r.choice(["addiw", "addiwu", "slliw", "srliw", "sraiw", "slliwu"])
                    imm = r.randint(0, 31) if "l" in f[1:] or "ra" in f else r.choice([-1, 1, -8192, 8191, r.randint(-8192, 8191)])
                    self.emit(f"{f} r{d}, r{src}, {imm}")
                else:
                    self.emit(f"{r.choice(['mulw', 'mulwu', 'divw', 'remw', 'mul', 'div'])} r{d}, r{src}, r{rb}")
                if d:
                    src = d
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
        g.emit(f"li r6, {r.choice([0x203, 0x303, 0x283, 3])}")   # sometimes a no-EXEC data cap (+CINVOKE/LM/GLOBAL mix)
        g.emit(f"candperm r60, r60, r{r.choice([6, 5])}")
    elif r.random() < 0.3:
        g.emit(f"li r6, {r.choice([0x20F, 0x217, 0x39B, 0x309, 0x20D, 0x519, 0x0F, 0x29B])}")   # drop STORE_CAP / LOAD_CAP / LOAD / STORE (v4: + G/LM/CI/SL mix)
        g.emit("candperm r60, r60, r6")
    g.emit("li r54, 0x60")                  # sealing authority (SEAL|UNSEAL), cursor = small otype
    g.emit("candperm r55, rc, r54")
    g.emit(f"li r54, {r.choice([0, 1, 1, 2, 3, 3, 0x10000])}")
    g.emit("csetaddr r55, r55, r54")
    g.emit("li r52, -0x10000")              # MMIO base (timer registers at +0x30 / +0x40)
    g.emit(f"addi r57, r3, {r.randrange(-64, 700, 16)}")      # user-mode window for untagged accesses
    g.emit("csrw ubase, r57")
    g.emit(f"addi r57, r57, {r.randrange(0, 600, 8)}")
    g.emit("csrw ubound, r57")
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
    for k in range(2):                      # shared subroutines for the "call" stream
        g.out.append(f"SUB{k}:")
        for _ in range(r.randint(1, 3)):
            g.one(allow_ctrl=False)
        g.emit("jalr r0, r1, 0")
    for k in range(9):                      # nested call chain for the "nest" stream (ra saved in r41..r49)
        g.out.append(f"NEST{k}:")
        g.emit(f"addi r{41 + k}, r1, 0")
        for _ in range(r.randint(0, 2)):
            g.one(allow_ctrl=False)
        if k < 8:
            g.emit(f"jal r1, NEST{k + 1}")
            if r.random() < 0.3:
                g.one(allow_ctrl=False)
        g.emit(f"addi r1, r{41 + k}, 0")
        g.emit("jalr r0, r1, 0")
    g.out.append("handler:")
    g.emit("csrr r62, cause")
    g.emit("bltz r62, Hirq")
    g.emit("li r59, 8")
    g.emit("bne r62, r59, Hnotecall")
    g.emit("csrr r59, status")             # ecall: return to supervisor mode
    g.emit("andi r59, r59, -17")
    g.emit("csrw status, r59")
    g.out.append("Hnotecall:")
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
