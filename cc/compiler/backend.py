"""Register allocation (linear scan over liveness-derived intervals) and TACHYON-128
assembly emission."""
from .ir import A0, FRAME, INCOMING, NARGREG, SP, VREG0, ZERO, fits14

CALLER_SAVED = list(range(12, 28)) + list(range(54, 59))     # t0-t15, t16-t20
CALLEE_SAVED = list(range(28, 54))                            # s0-s15, s16-s25
SCR_ADDR, SCR_A, SCR_B, SCR_D = 59, 60, 61, 62
REGNAME = {0: "zero", 1: "ra", 2: "sp", 3: "gp"}
for _i in range(8):
    REGNAME[4 + _i] = f"a{_i}"
for _i in range(16):
    REGNAME[12 + _i] = f"t{_i}"
    REGNAME[28 + _i] = f"s{_i}"
for _i in range(44, 64):
    REGNAME[_i] = f"r{_i}"


def rn(r):
    return REGNAME[r]


class Block:
    __slots__ = ("start", "end", "succ", "use", "defs", "live_in", "live_out", "label")

    def __init__(self, start):
        self.start, self.end = start, start
        self.succ = []
        self.use = 0
        self.defs = 0
        self.live_in = 0
        self.live_out = 0
        self.label = None


def build_blocks(code):
    blocks = []
    cur = None
    label_block = {}
    for k, i in enumerate(code):
        if i.op == "label":
            if cur is not None and cur.end >= cur.start and k > cur.start:
                cur.end = k - 1
                blocks.append(cur)
            cur = Block(k)
            label_block[i.label] = cur
            continue
        if cur is None:
            cur = Block(k)
        if i.op in ("br", "bcc", "ret", "jt"):
            cur.end = k
            blocks.append(cur)
            cur = None
    if cur is not None:
        cur.end = len(code) - 1
        blocks.append(cur)
    for n, b in enumerate(blocks):
        last = code[b.end]
        nxt = blocks[n + 1] if n + 1 < len(blocks) else None
        if last.op == "br":
            b.succ = [label_block[last.label]]
        elif last.op == "bcc":
            b.succ = [label_block[last.label]] + ([nxt] if nxt else [])
        elif last.op == "jt":
            b.succ = [label_block[l] for l in set(last.extra)]
        elif last.op == "ret":
            b.succ = []
        else:
            b.succ = [nxt] if nxt else []
    return blocks


def liveness(code, blocks):
    for b in blocks:
        use = 0
        dfs = 0
        for k in range(b.start, b.end + 1):
            i = code[k]
            for u in i.uses():
                if u is not None and u >= VREG0:
                    bit = 1 << (u - VREG0)
                    if not dfs & bit:
                        use |= bit
            for d in i.defs():
                if d >= VREG0:
                    dfs |= 1 << (d - VREG0)
        b.use, b.defs = use, dfs
    changed = True
    while changed:
        changed = False
        for b in reversed(blocks):
            out = 0
            for s in b.succ:
                out |= s.live_in
            inn = b.use | (out & ~b.defs)
            if out != b.live_out or inn != b.live_in:
                b.live_out, b.live_in = out, inn
                changed = True


def bits_of(x):
    while x:
        low = x & -x
        yield low.bit_length() - 1
        x ^= low


class Allocation:
    def __init__(self):
        self.reg = {}         # vreg -> phys
        self.spill = {}       # vreg -> spill slot index
        self.used_callee = set()


def allocate(code):
    blocks = build_blocks(code)
    liveness(code, blocks)
    start = {}
    end = {}

    def touch(v, p):
        if v not in start or p < start[v]:
            start[v] = p
        if v not in end or p > end[v]:
            end[v] = p
    for k, i in enumerate(code):
        for u in i.uses():
            if u is not None and u >= VREG0:
                touch(u, k)
        for d in i.defs():
            if d >= VREG0:
                touch(d, k)
    for b in blocks:
        for v in bits_of(b.live_in):
            touch(v + VREG0, b.start)
        for v in bits_of(b.live_out):
            touch(v + VREG0, b.end)
    calls = [k for k, i in enumerate(code) if i.op == "call"]
    # vregs actually live across some call (precise, unlike the interval test): only these
    # need a callee-saved register; values merely spanning a call inside a lifetime hole
    # can live in caller-saved registers.
    across = 0
    block_of = [0] * len(code)
    for bn, b in enumerate(blocks):
        live = b.live_out
        for k in range(b.end, b.start - 1, -1):
            block_of[k] = bn
            i = code[k]
            for d in i.defs():
                if d >= VREG0:
                    live &= ~(1 << (d - VREG0))
            if i.op == "call":
                across |= live
            for u in i.uses():
                if u is not None and u >= VREG0:
                    live |= 1 << (u - VREG0)
    intervals = sorted(start, key=lambda v: (start[v], end[v]))
    alloc = Allocation()
    fixed = argreg_coalesce(code, start, end, block_of, calls)
    free_caller = list(CALLER_SAVED)
    free_callee = list(CALLEE_SAVED)
    active = []   # (end, vreg)
    hint = {}
    for k, i in enumerate(code):
        if i.op == "mov" and i.d is not None and i.d >= VREG0 and i.a is not None and i.a >= VREG0:
            hint.setdefault(i.d, i.a)

    def crosses(v):
        return bool(across >> (v - VREG0) & 1)

    nspill = 0
    for v in intervals:
        if v in fixed:
            alloc.reg[v] = fixed[v]
            continue
        s = start[v]
        # expire
        keep = []
        for (e, w) in active:
            if e <= s:
                r = alloc.reg[w]
                (free_callee if r in CALLEE_SAVED else free_caller).append(r)
            else:
                keep.append((e, w))
        active = keep
        cross = crosses(v)
        pool_order = [free_callee] if cross else [free_caller, free_callee]
        r = None
        h = hint.get(v)
        if h is not None and h in alloc.reg:
            hr = alloc.reg[h]
            for pool in pool_order:
                if hr in pool:
                    pool.remove(hr)
                    r = hr
                    break
        if r is None:
            for pool in pool_order:
                if pool:
                    r = pool.pop(0) if pool is free_caller else pool.pop()
                    break
        if r is None:
            # spill: furthest-ending active interval whose register class fits
            cands = [(e, w) for (e, w) in active if (not cross or alloc.reg[w] in CALLEE_SAVED)]
            if cands:
                e, w = max(cands)
                if e > end[v]:
                    r = alloc.reg.pop(w)
                    alloc.spill[w] = nspill
                    nspill += 1
                    active.remove((e, w))
            if r is None:
                alloc.spill[v] = nspill
                nspill += 1
                continue
        alloc.reg[v] = r
        if r in CALLEE_SAVED:
            alloc.used_callee.add(r)
        active.append((end[v], v))
    alloc.nspill = nspill
    return alloc


def phys_refs(i):
    """Physical argument registers read / written by an IR instruction (incl. implicit)."""
    rd = [u for u in i.uses() if u is not None and A0 <= u < A0 + NARGREG]
    wr = [d for d in i.defs() if A0 <= d < A0 + NARGREG]
    if i.op == "call":
        rd += [A0 + k for k in range(i.nargs)]
        wr += list(range(A0, A0 + NARGREG))
    elif i.op == "ret":
        rd.append(A0)
    return rd, wr


def argreg_coalesce(code, start, end, block_of, calls):
    """Give a vreg the argument register it is copied to / from when its whole lifetime sits in
    one basic block, contains no call, and that register is untouched meanwhile:
      v = ...; ...; mov aK, v      (v dies at the mov)        -> v lives in aK
      mov v, aK; ...                (v born from aK)          -> v lives in aK
    A call inside the checked range writes every argument register, so it disqualifies too.
    The copy then disappears in the emitter."""
    fixed = {}
    taken = {}   # phys -> list of (s, e)
    for k, i in enumerate(code):
        if i.op != "mov" or i.d is None or i.a is None:
            continue
        if A0 <= i.d < A0 + NARGREG and i.a >= VREG0 and end.get(i.a) == k:
            v, p = i.a, i.d
            s, e = start[v], k
            lo, hi = s, e          # p must be untouched in [s, e)
        elif A0 <= i.a < A0 + NARGREG and i.d >= VREG0 and start.get(i.d) == k:
            v, p = i.d, i.a
            s, e = k, end[v]
            lo, hi = s + 1, e + 1  # p must be untouched in (s, e]
        else:
            continue
        if v in fixed or block_of[s] != block_of[e]:
            continue
        bad = False
        for j in range(lo, hi):
            rd, wr = phys_refs(code[j])
            if p in rd or p in wr:
                bad = True
                break
        if bad:
            continue
        if any(not (e < ts or te < s) for ts, te in taken.get(p, [])):
            continue
        fixed[v] = p
        taken.setdefault(p, []).append((s, e))
    return fixed


LOADS = {(1, True): "lb", (2, True): "lh", (4, True): "lw", (8, True): "ld", (16, True): "lq",
         (1, False): "lbu", (2, False): "lhu", (4, False): "lwu", (8, False): "ldu", (16, False): "lq"}
STORES = {1: "sb", 2: "sh", 4: "sw", 8: "sd", 16: "sq"}
IMM_FORM = {"add": "addi", "and": "andi", "or": "ori", "xor": "xori", "slt": "slti", "sltu": "sltiu",
            "sll": "slli", "srl": "srli", "sra": "srai",
            "addw": "addiw", "addwu": "addiwu", "sllw": "slliw", "sllwu": "slliwu", "cadd": "cincaddri", "csetbnd": "csetbndi"}
CAP_UNARY_OPS = {"cgettag", "cgetlen", "cgetbase", "cgetperm"}
PC_MEM = {"lq": "clc", "sq": "csc"}      # purecap: every 16-byte access moves the tag too
BR = {"eq": "beq", "ne": "bne", "lt": "blt", "ge": "bge", "ltu": "bltu", "geu": "bgeu"}
NEG = {"eq": "bne", "ne": "beq", "lt": "bge", "ge": "blt", "ltu": "bgeu", "geu": "bltu"}


class Emitter:
    def __init__(self, fg, code, alloc, name):
        self.fg, self.code, self.alloc, self.name = fg, code, alloc, name
        self.out = []
        saves = sorted(alloc.used_callee)
        self.has_call = any(i.op == "call" for i in code)
        out_area = fg.out_area
        local = (fg.frame_size + 15) // 16 * 16
        self.local_base = out_area
        self.spill_base = out_area + local
        self.save_base = self.spill_base + 16 * alloc.nspill
        self.saves = saves + ([1] if self.has_call else [])
        self.pc = getattr(fg, "pc", False)
        # purecap + bounded stack: a variadic function keeps its bounded va capability in a 16-byte slot
        # below the 128-byte save area (built in the prologue from the caller's stack-argument byte count)
        self.vacap = self.pc and getattr(fg, "stackb", False) and fg.fn.va_save
        va = (144 if self.vacap else 128) if fg.fn.va_save else 0
        self.frame = self.save_base + 16 * len(self.saves) + va
        self.frame = (self.frame + 15) // 16 * 16
        self.long_branches = len(code) > 6000
        self.pc = getattr(fg, "pc", False)

    def e(self, s):
        self.out.append("        " + s)

    # operand mapping -------------------------------------------------
    def src(self, r, scratch):
        if r is None:
            return None
        if r < VREG0:
            return r
        if r in self.alloc.reg:
            return self.alloc.reg[r]
        slot = self.alloc.spill[r]
        self.mem("lq", scratch, SP, self.spill_base + 16 * slot)
        return scratch

    def dst(self, r):
        if r < VREG0:
            return r, None
        if r in self.alloc.reg:
            return self.alloc.reg[r], None
        return SCR_D, self.alloc.spill[r]

    def finish_dst(self, slot):
        if slot is not None:
            self.mem("sq", SCR_D, SP, self.spill_base + 16 * slot)

    def mem(self, op, r, base, off):
        if self.pc:
            op = PC_MEM.get(op, op)
        if fits14(off):
            self.e(f"{op} {rn(r)}, {off}({rn(base)})")
        else:
            self.e(f"li {rn(SCR_ADDR)}, {off}")
            self.e(f"{'cincaddr' if self.pc else 'add'} {rn(SCR_ADDR)}, {rn(base)}, {rn(SCR_ADDR)}")
            self.e(f"{op} {rn(r)}, 0({rn(SCR_ADDR)})")

    def addi(self, d, a, imm):
        """d = a + imm for addresses (sp, frame objects): cincaddr(i) in purecap."""
        if fits14(imm):
            if imm == 0 and d == a:
                return
            self.e(f"{'cincaddri' if self.pc else 'addi'} {rn(d)}, {rn(a)}, {imm}")
        else:
            self.e(f"li {rn(SCR_ADDR)}, {imm}")
            self.e(f"{'cincaddr' if self.pc else 'add'} {rn(d)}, {rn(a)}, {rn(SCR_ADDR)}")

    def setbounds(self, d, size):
        if size < (1 << 14):
            self.e(f"csetbndi {rn(d)}, {rn(d)}, {size}")
        else:
            self.e(f"li {rn(SCR_ADDR)}, {size}")
            self.e(f"csetbnd {rn(d)}, {rn(d)}, {rn(SCR_ADDR)}")

    def base_off(self, base, off):
        if base == FRAME:
            return SP, self.local_base + off
        if base == INCOMING:
            return SP, self.frame + off
        return base, off

    # ------------------------------------------------------------------
    def emit(self):
        self.out.append(f"{self.name}:")
        if self.frame:
            self.addi(SP, SP, -self.frame)
        for k, r in enumerate(self.saves):
            self.mem("sq", r, SP, self.save_base + 16 * k)
        if self.vacap:
            # va capability = [save area, incoming sp + stack-argument bytes); the caller put that byte
            # count in SCR_D (r62) right before the call and nothing above has touched r62 yet
            self.addi(SCR_A, SP, self.frame - 128)
            self.e(f"addi {rn(SCR_D)}, {rn(SCR_D)}, 128")
            self.e(f"csetbnd {rn(SCR_A)}, {rn(SCR_A)}, {rn(SCR_D)}")
            self.mem("sq", SCR_A, SP, self.frame - 144)
        for i in self.code:
            getattr(self, "i_" + i.op)(i)
        return self.out

    def epilogue(self):
        for k, r in enumerate(self.saves):
            self.mem("lq", r, SP, self.save_base + 16 * k)
        if self.frame:
            self.addi(SP, SP, self.frame)
        self.e("ret")

    def i_label(self, i):
        self.out.append(f"{i.label}:")

    def i_ret(self, i):
        self.epilogue()

    def i_br(self, i):
        self.e(f"j {i.label}")

    def i_bcc(self, i):
        a = self.src(i.a, SCR_A)
        b = self.src(i.b, SCR_B)
        if self.long_branches:
            skip = f"{i.label}_s{id(i)}"
            self.e(f"{NEG[i.cc]} {rn(a)}, {rn(b)}, {skip}")
            self.e(f"j {i.label}")
            self.out.append(f"{skip}:")
        else:
            self.e(f"{BR[i.cc]} {rn(a)}, {rn(b)}, {i.label}")

    def i_li(self, i):
        d, slot = self.dst(i.d)
        v = i.imm & ((1 << 128) - 1)
        if v >> 127:
            v -= 1 << 128
        self.e(f"li {rn(d)}, {v}")
        self.finish_dst(slot)

    def i_la(self, i):
        d, slot = self.dst(i.d)
        if not self.pc:
            self.e(f"la {rn(d)}, {i.sym}" + (f"+{i.imm}" if i.imm else ""))
        elif i.extra == "func":       # code pointer: derived from the PCC
            self.e(f"la {rn(SCR_ADDR)}, {i.sym}")
            self.e(f"cgetpcc {rn(d)}")
            self.e(f"csetaddr {rn(d)}, {rn(d)}, {rn(SCR_ADDR)}")
        else:                         # data: derived from gp (RAM capability), bounded to the object
            self.e(f"la {rn(SCR_ADDR)}, {i.sym}")
            self.e(f"csetaddr {rn(d)}, gp, {rn(SCR_ADDR)}")
            if i.sz:
                self.setbounds(d, i.sz)
        if self.pc and i.imm:
            self.addi(d, d, i.imm)
        self.finish_dst(slot)

    def i_faddr(self, i):
        d, slot = self.dst(i.d)
        if i.sym == "INCOMING" and self.vacap:     # va_start: cursor into the bounded va capability
            self.mem("lq", d, SP, self.frame - 144)
            self.addi(d, d, i.imm + 128)
        elif i.sym == "INCOMING":
            self.addi(d, SP, self.frame + i.imm)
        elif self.pc and i.sz:        # bounded to the frame object [start, start + size)
            self.addi(d, SP, self.local_base + i.extra)
            self.setbounds(d, i.sz)
            self.addi(d, d, i.imm - i.extra)
        else:
            self.addi(d, SP, self.local_base + i.imm)
        self.finish_dst(slot)

    def i_mov(self, i):
        a = self.src(i.a, SCR_A)
        d, slot = self.dst(i.d)
        if slot is not None:
            self.mem("sq", a, SP, self.spill_base + 16 * slot)
            return
        if a != d:
            self.e(f"{'cmove' if self.pc else 'mv'} {rn(d)}, {rn(a)}")

    def i_bin(self, i):
        a = self.src(i.a, SCR_A)
        if i.cc in CAP_UNARY_OPS:
            d, slot = self.dst(i.d)
            self.e(f"{i.cc} {rn(d)}, {rn(a)}")
            self.finish_dst(slot)
            return
        if i.cc == "cadd" and i.b is not None:
            b = self.src(i.b, SCR_B)
            d, slot = self.dst(i.d)
            self.e(f"cincaddr {rn(d)}, {rn(a)}, {rn(b)}")
            self.finish_dst(slot)
            return
        if i.b is None:
            d, slot = self.dst(i.d)
            imm = i.imm
            if i.cc in ("sll", "srl", "sra"):
                self.e(f"{IMM_FORM[i.cc]} {rn(d)}, {rn(a)}, {imm & 127}")
            elif i.cc in ("sllw", "sllwu"):
                self.e(f"{IMM_FORM[i.cc]} {rn(d)}, {rn(a)}, {imm & 31}")
            elif i.cc in IMM_FORM and fits14(imm):
                self.e(f"{IMM_FORM[i.cc]} {rn(d)}, {rn(a)}, {imm}")
            else:
                self.e(f"li {rn(SCR_B)}, {imm}")
                self.e(f"{'cincaddr' if i.cc == 'cadd' else i.cc} {rn(d)}, {rn(a)}, {rn(SCR_B)}")
            self.finish_dst(slot)
            return
        b = self.src(i.b, SCR_B)
        d, slot = self.dst(i.d)
        self.e(f"{i.cc} {rn(d)}, {rn(a)}, {rn(b)}")
        self.finish_dst(slot)

    def i_ext(self, i):
        a = self.src(i.a, SCR_A)
        d, slot = self.dst(i.d)
        sh = 128 - i.sz
        if not i.sign and i.sz == 8:
            self.e(f"andi {rn(d)}, {rn(a)}, 255")
        elif i.sz == 32:                                   # v5: sext.w / zext.w
            self.e(f"{'addiw' if i.sign else 'addiwu'} {rn(d)}, {rn(a)}, 0")
        else:
            self.e(f"slli {rn(d)}, {rn(a)}, {sh}")
            self.e(f"{'srai' if i.sign else 'srli'} {rn(d)}, {rn(d)}, {sh}")
        self.finish_dst(slot)

    def i_ld(self, i):
        base, off = self.base_off(i.a, i.imm)
        b = self.src(base, SCR_A)
        d, slot = self.dst(i.d)
        self.mem(LOADS[(i.sz, bool(i.sign))], d, b, off)
        self.finish_dst(slot)

    def i_st(self, i):
        v = self.src(i.a, SCR_A)
        base, off = self.base_off(i.b, i.imm)
        if base == SP and i.b == SP:
            off = i.imm
        b = self.src(base, SCR_B)
        self.mem(STORES[i.sz], v, b, off)

    def i_call(self, i):
        t = None if i.sym else self.src(i.a, SCR_A)
        if i.extra == "va":           # purecap: stack-argument bytes for the variadic callee's va bounds
            self.e(f"li {rn(SCR_D)}, {i.imm}")
        if i.sym:
            self.e(f"call {i.sym}")
        else:
            self.e(f"jalr ra, {rn(t)}, 0")

    def i_jt(self, i):
        a = self.src(i.a, SCR_A)
        self.e(f"slli {rn(SCR_ADDR)}, {rn(a)}, 4")
        self.e(f"la {rn(SCR_B)}, {i.sym}")
        if self.pc:     # table read through a capability bounded to the table
            self.e(f"csetaddr {rn(SCR_B)}, gp, {rn(SCR_B)}")
            self.e(f"csetbndi {rn(SCR_B)}, {rn(SCR_B)}, {16 * (len(i.extra) - 1)}")
            self.e(f"cincaddr {rn(SCR_ADDR)}, {rn(SCR_B)}, {rn(SCR_ADDR)}")
        else:
            self.e(f"add {rn(SCR_ADDR)}, {rn(SCR_ADDR)}, {rn(SCR_B)}")
        self.e(f"lq {rn(SCR_ADDR)}, 0({rn(SCR_ADDR)})")
        self.e(f"jr {rn(SCR_ADDR)}")
