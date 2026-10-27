"""AST -> linear IR over virtual registers.

Values are kept in *canonical form*: an integer of C type T (width w < 128) lives in a 128-bit
register sign-extended (signed T) or zero-extended (unsigned T / pointers) from w bits.
Every operation that can leave a non-canonical value re-normalises with an 'ext'."""
from . import ctype as T
from .ctype import wrap
from .lexer import error_at

# physical registers used directly in IR
ZERO, RA, SP = 0, 1, 2
A0 = 4
NARGREG = 8
FRAME = -1      # pseudo base: start of the local-variable area
INCOMING = -2   # pseudo base: caller's sp (incoming stack args at +0, va save area at -128)
VREG0 = 64

BR_CC = {"eq": "beq", "ne": "bne", "lt": "blt", "ge": "bge", "ltu": "bltu", "geu": "bgeu"}
NEG_CC = {"eq": "ne", "ne": "eq", "lt": "ge", "ge": "lt", "ltu": "geu", "geu": "ltu"}


class Ins:
    __slots__ = ("op", "d", "a", "b", "imm", "sym", "sz", "sign", "cc", "label", "nargs", "extra")

    def __init__(self, op, d=None, a=None, b=None, imm=None, sym=None, sz=None, sign=None, cc=None,
                 label=None, nargs=0, extra=None):
        self.op, self.d, self.a, self.b, self.imm, self.sym = op, d, a, b, imm, sym
        self.sz, self.sign, self.cc, self.label, self.nargs, self.extra = sz, sign, cc, label, nargs, extra

    def uses(self):
        op = self.op
        if op in ("bin", "bcc"):
            r = [self.a]
            if self.b is not None:
                r.append(self.b)
            return r
        if op in ("mov", "ext", "ld", "jt"):
            return [self.a] if self.a is not None else []
        if op == "st":
            return [self.a, self.b]
        if op == "call":
            return [self.a] if self.a is not None else []
        return []

    def defs(self):
        if self.op in ("li", "la", "mov", "bin", "ext", "ld", "faddr"):
            return [self.d]
        return []

    def __repr__(self):
        f = [self.op]
        for k in ("d", "a", "b", "imm", "sym", "sz", "sign", "cc", "label"):
            v = getattr(self, k)
            if v is not None:
                f.append(f"{k}={v}")
        return " ".join(f)


class LV:
    """An lvalue: kind 'reg' (promoted local in a vreg), 'mem' (base reg + offset) or 'bit'."""
    __slots__ = ("kind", "reg", "off", "mem")

    def __init__(self, kind, reg, off=0, mem=None):
        self.kind, self.reg, self.off, self.mem = kind, reg, off, mem


def fits14(v):
    return -8192 <= v < 8192


def needs_ext(src, dst):
    """Does converting canonical value of type src to dst need re-normalisation?"""
    if dst.kind == "bool":
        return False   # handled separately
    if dst.kind == "void":
        return False
    db = 128 if dst.kind == "ptr" else dst.size * 8
    if db >= 128:
        return False
    sb = 128 if src.kind == "ptr" else src.size * 8
    du = dst.unsigned or dst.kind == "ptr"
    su = src.unsigned or src.kind == "ptr" or src.kind == "bool"
    if db > sb:
        return (not su) and du
    if db == sb:
        return su != du
    return True


class FuncGen:
    def __init__(self, fn, unit):
        self.fn = fn
        self.unit = unit
        self.code = []
        self.nv = VREG0
        self.var_reg = {}       # Obj -> vreg (promoted)
        self.var_off = {}       # Obj -> frame offset
        self.var_ptr = {}       # Obj -> vreg holding address (struct params)
        self.frame_size = 0     # local area bytes
        self.out_area = 0       # outgoing stack-arg area bytes
        self.labels = {}
        self.nlabel = 0
        self.retlabel = self.new_label()
        self.sret = None
        self.has_call = False
        self.data = []          # extra data (jump tables)
        self.pc = getattr(unit, "purecap", False)   # -mpurecap: pointers are capabilities
        self.slots = []         # (offset, size) of every frame object, for capability bounds

    # --------------------------------------------------------- helpers
    def vreg(self):
        self.nv += 1
        return self.nv - 1

    def emit(self, *a, **k):
        i = Ins(*a, **k)
        self.code.append(i)
        return i

    def new_label(self):
        self.nlabel += 1
        return f"__L{self.unit.uid}_{self.unit.fnid}_{self.nlabel}"

    def ast_label(self, n):
        if n not in self.labels:
            self.labels[n] = self.new_label()
        return self.labels[n]

    def alloc_slot(self, size, align):
        align = max(align, 1)
        self.frame_size = T.align_to(self.frame_size, align)
        off = self.frame_size
        self.frame_size += max(size, 1)
        self.slots.append((off, max(size, 1)))
        return off

    def li(self, v):
        r = self.vreg()
        self.emit("li", d=r, imm=v & T.MASK if hasattr(T, "MASK") else v)
        return r

    def const(self, v):
        r = self.vreg()
        self.emit("li", d=r, imm=v)
        return r

    def bin(self, op, a, b):
        r = self.vreg()
        self.emit("bin", d=r, a=a, b=b, cc=op)
        return r

    def bini(self, op, a, imm):
        r = self.vreg()
        self.emit("bin", d=r, a=a, b=None, imm=imm, cc=op)
        return r

    # pointer + integer: cincaddr in purecap (keeps the tag; the pointer must be the first operand)
    def padd(self, p, off):
        return self.bin("cadd" if self.pc else "add", p, off)

    def paddi(self, p, imm):
        return self.bini("cadd" if self.pc else "add", p, imm)

    def faddr(self, d, off):
        """Address of frame offset off; purecap bounds it to the frame object containing off."""
        i = self.emit("faddr", d=d, imm=off)
        if self.pc:
            for so, sz in self.slots:
                if so <= off < so + sz:
                    i.sz, i.extra = sz, so
        return i

    def gaddr(self, o):
        """Address of a global object or function (purecap: bounded capability, see backend.i_la)."""
        r = self.vreg()
        sz = o.ty.size if not o.is_func and o.ty.size > 0 else 0
        self.emit("la", d=r, sym=o.asm_name, imm=0, sz=sz, extra="func" if o.is_func else None)
        return r

    def ext(self, r, ty):
        """Normalise r to canonical form of ty (if ty narrower than 128 bits)."""
        if ty.kind == "ptr" or ty.size >= 16 or ty.kind == "void":
            return r
        if ty.kind == "bool":
            return r
        d = self.vreg()
        self.emit("ext", d=d, a=r, sz=ty.size * 8, sign=not ty.unsigned)
        return d

    def mov(self, d, a):
        self.emit("mov", d=d, a=a)

    # --------------------------------------------------------- function
    def gen(self):
        fn = self.fn
        # decide which locals live in registers
        for o in fn.locals:
            if self.promotable(o):
                self.var_reg[o] = self.vreg()
        params = list(fn.params)
        regi = 0
        if fn.ty.ret.is_struct():
            self.sret = self.vreg()
            self.mov(self.sret, A0)
            regi = 1
        stack_i = 0
        for p in params:
            if regi < NARGREG:
                src = A0 + regi
                regi += 1
                loc = ("reg", src)
            else:
                loc = ("stack", 16 * stack_i)
                stack_i += 1
            if p.ty.is_struct():
                pr = self.vreg()
                if loc[0] == "reg":
                    self.mov(pr, loc[1])
                else:
                    self.emit("ld", d=pr, a=INCOMING, imm=loc[1], sz=16, sign=False)
                self.var_ptr[p] = pr
                continue
            if loc[0] == "reg":
                v = loc[1]
            else:
                v = self.vreg()
                self.emit("ld", d=v, a=INCOMING, imm=loc[1], sz=16, sign=False)
            if p in self.var_reg:
                self.mov(self.var_reg[p], v)
            else:
                off = self.local_off(p)
                self.emit("st", a=v, b=FRAME, imm=off, sz=self.store_size(p.ty))
        if fn.va_save:
            for i in range(NARGREG):
                self.emit("st", a=A0 + i, b=INCOMING, imm=-128 + 16 * i, sz=16)
            self.va_first = (-128 + 16 * regi) if regi < NARGREG else 16 * stack_i
        self.stmt(fn.body)
        if fn.name == "main":
            self.mov(A0, ZERO)
        self.emit("label", label=self.retlabel)
        self.emit("ret")
        return self

    def store_size(self, ty):
        return 16 if ty.kind == "ptr" else ty.size

    def promotable(self, o):
        return (o.ty.is_scalar() and not o.addr_taken and not o.volatile)

    def local_off(self, o):
        if o not in self.var_off:
            al = max(o.ty.align, getattr(o, "align", 1) or 1)
            self.var_off[o] = self.alloc_slot(o.ty.size, al)
        return self.var_off[o]

    # --------------------------------------------------------- statements
    def stmt(self, n):
        k = n.kind
        if k == "block":
            for s in n.body:
                self.stmt(s)
        elif k == "expr":
            self.expr(n.expr, discard=True)
        elif k == "init":
            self.gen_init(n.var, n.init)
        elif k == "return":
            if n.expr is not None:
                if self.fn.ty.ret.is_struct():
                    src = self.expr(n.expr)
                    self.copy_mem(self.sret, 0, src, 0, self.fn.ty.ret.size, self.fn.ty.ret.align)
                    self.mov(A0, self.sret)
                else:
                    v = self.expr(n.expr)
                    self.mov(A0, v)
            self.emit("br", label=self.retlabel)
        elif k == "if":
            lt, lf, le = self.new_label(), self.new_label(), self.new_label()
            self.cond(n.cond, lt, lf)
            self.emit("label", label=lt)
            self.stmt(n.then)
            if n.els is not None:
                self.emit("br", label=le)
                self.emit("label", label=lf)
                self.stmt(n.els)
                self.emit("label", label=le)
            else:
                self.emit("label", label=lf)
        elif k == "for":
            brk, cnt = self.ast_label(n.brk), self.ast_label(n.cnt)
            top, body = self.new_label(), self.new_label()
            if n.init is not None:
                self.stmt(n.init)
            # loop rotation: test at the bottom
            if n.cond is not None:
                self.cond(n.cond, body, brk)
            self.emit("label", label=body)
            self.stmt(n.body)
            self.emit("label", label=cnt)
            if n.inc is not None:
                self.expr(n.inc, discard=True)
            if n.cond is not None:
                self.cond(n.cond, body, brk)
            else:
                self.emit("br", label=body)
            self.emit("label", label=brk)
        elif k == "do":
            brk, cnt = self.ast_label(n.brk), self.ast_label(n.cnt)
            top = self.new_label()
            self.emit("label", label=top)
            self.stmt(n.body)
            self.emit("label", label=cnt)
            self.cond(n.cond, top, brk)
            self.emit("label", label=brk)
        elif k == "switch":
            self.switch(n)
        elif k == "label":
            self.emit("label", label=self.ast_label(n.label))
            self.stmt(n.body)
        elif k == "goto":
            self.emit("br", label=self.ast_label(n.label))
        else:
            error_at(n.tok, f"internal: unknown statement {k}")

    def switch(self, n):
        v = self.expr(n.cond)
        brk = self.ast_label(n.brk)
        dflt = self.ast_label(n.default) if n.default is not None else brk
        cases = [(lo, hi, self.ast_label(l)) for lo, hi, l in n.cases]
        singles = [(lo, l) for lo, hi, l in cases if lo == hi]
        ranges = [(lo, hi, l) for lo, hi, l in cases if lo != hi]
        for lo, hi, l in ranges:
            nxt = self.new_label()
            t = self.bini("add", v, -lo) if fits14(-lo) else self.bin("sub", v, self.const(lo))
            t = self.ext(t, T.UINT128)
            self.emit("bcc", a=self.const(hi - lo), b=t, cc="ltu", label=nxt)
            self.emit("br", label=l)
            self.emit("label", label=nxt)
        if len(singles) >= 6:
            vals = sorted(x[0] for x in singles)
            lo, hi = vals[0], vals[-1]
            span = hi - lo + 1
            if span <= 3 * len(singles) and span <= 1024:
                table = {}
                for val, l in singles:
                    table.setdefault(val, l)
                t = self.bini("add", v, -lo) if fits14(-lo) else self.bin("sub", v, self.const(lo))
                self.emit("bcc", a=t, b=self.const(span), cc="geu", label=dflt)
                tl = self.new_label()
                self.data.append((tl, [table.get(lo + i, dflt) for i in range(span)]))
                self.emit("jt", a=t, sym=tl, extra=[table.get(lo + i, dflt) for i in range(span)] + [dflt])
                self.stmt(n.body)
                self.emit("label", label=brk)
                return
        if len(singles) >= 8:
            self.bsearch(v, sorted(singles), dflt)
        else:
            for val, l in singles:
                if val == 0:
                    self.emit("bcc", a=v, b=ZERO, cc="eq", label=l)
                else:
                    self.emit("bcc", a=v, b=self.const(val), cc="eq", label=l)
            self.emit("br", label=dflt)
        self.stmt(n.body)
        self.emit("label", label=brk)

    def bsearch(self, v, cases, dflt):
        signed = True
        if len(cases) <= 4:
            for val, l in cases:
                self.emit("bcc", a=v, b=self.const(val) if val else ZERO, cc="eq", label=l)
            self.emit("br", label=dflt)
            return
        mid = len(cases) // 2
        mv, ml = cases[mid]
        right = self.new_label()
        c = self.const(mv)
        self.emit("bcc", a=v, b=c, cc="eq", label=ml)
        self.emit("bcc", a=c, b=v, cc="lt", label=right)
        self.bsearch(v, cases[:mid], dflt)
        self.emit("label", label=right)
        self.bsearch(v, cases[mid + 1:], dflt)

    # --------------------------------------------------------- initialisers
    def gen_init(self, var, init):
        if var in self.var_reg:
            e = init.expr
            if e is None and init.elems:
                e = init.elems[0].expr
            v = self.expr(e) if e is not None else ZERO
            self.mov(self.var_reg[var], v)
            return
        off = self.local_off(var)
        base = self.vreg()
        self.faddr(base, off)
        ty = var.ty
        if ty.is_scalar():
            v = self.expr(init.expr) if init.expr is not None else ZERO
            self.emit("st", a=v, b=base, imm=0, sz=self.store_size(ty))
            return
        if ty.is_struct() and init.expr is not None:
            src = self.expr(init.expr)
            self.copy_mem(base, 0, src, 0, ty.size, ty.align)
            return
        # zero the whole object, then store the explicit elements
        self.zero_mem(base, 0, ty.size, ty.align)
        self.init_elems(base, 0, ty, init)

    def init_elems(self, base, off, ty, init):
        if init.expr is not None and not ty.is_array():
            if ty.is_struct():
                src = self.expr(init.expr)
                self.copy_mem(base, off, src, 0, ty.size, ty.align)
                return
            if init.expr.kind == "num" and init.expr.val == 0:
                return
            v = self.expr(init.expr)
            self.store_at(base, off, v, ty)
            return
        if not init.elems:
            return
        if ty.is_array():
            for i in sorted(init.elems):
                self.init_elems(base, off + i * ty.base.size, ty.base, init.elems[i])
        else:
            for i in sorted(init.elems):
                m = ty.members[i]
                c = init.elems[i]
                if m.bit_width is not None:
                    if c.expr is None:
                        continue
                    v = self.expr(c.expr)
                    self.store_bitfield(base, off + m.offset, m, v)
                    continue
                self.init_elems(base, off + m.offset, m.ty, c)

    def addr_of(self, base, off):
        if off == 0:
            return base, 0
        if fits14(off):
            return base, off
        r = self.padd(base, self.const(off))
        return r, 0

    def store_at(self, base, off, v, ty):
        b, o = self.addr_of(base, off)
        self.emit("st", a=v, b=b, imm=o, sz=self.store_size(ty))

    def zero_mem(self, base, off, size, align):
        self.fill_copy(base, off, None, 0, size, align)

    def copy_mem(self, dst, doff, src, soff, size, align):
        self.fill_copy(dst, doff, src, soff, size, align)

    def fill_copy(self, dst, doff, src, soff, size, align):
        unit = 16
        while unit > align:
            unit //= 2
        n = size // unit
        if n > 16:
            # loop
            cnt = self.const(n)
            d = self.vreg()
            s = self.vreg()
            self.mov(d, dst)
            pa = "cadd" if self.pc else "add"
            if doff:
                self.emit("bin", d=d, a=d, b=self.const(doff), cc=pa)
            if src is not None:
                self.mov(s, src)
                if soff:
                    self.emit("bin", d=s, a=s, b=self.const(soff), cc=pa)
            c = self.vreg()
            self.mov(c, cnt)
            top = self.new_label()
            self.emit("label", label=top)
            if src is not None:
                t = self.vreg()
                self.emit("ld", d=t, a=s, imm=0, sz=unit, sign=False)
                self.emit("st", a=t, b=d, imm=0, sz=unit)
                self.emit("bin", d=s, a=s, b=None, imm=unit, cc=pa)
            else:
                self.emit("st", a=ZERO, b=d, imm=0, sz=unit)
            self.emit("bin", d=d, a=d, b=None, imm=unit, cc=pa)
            self.emit("bin", d=c, a=c, b=None, imm=-1, cc="add")
            self.emit("bcc", a=c, b=ZERO, cc="ne", label=top)
            rest = size - n * unit
            doff2 = 0
            soff2 = 0
            if rest:
                self.fill_copy_tail(d, doff2, s if src is not None else None, soff2, rest)
            return
        for i in range(n):
            self._copy_unit(dst, doff + i * unit, src, soff + i * unit, unit)
        rest = size - n * unit
        if rest:
            self.fill_copy_tail(dst, doff + n * unit, src, soff + n * unit if src is not None else 0, rest)

    def fill_copy_tail(self, dst, doff, src, soff, rest):
        o = 0
        for u in (8, 4, 2, 1):
            while rest >= u:
                self._copy_unit(dst, doff + o, src, soff + o, u)
                o += u
                rest -= u

    def _copy_unit(self, dst, doff, src, soff, unit):
        b, o = self.addr_of(dst, doff)
        if src is None:
            self.emit("st", a=ZERO, b=b, imm=o, sz=unit)
        else:
            sb, so = self.addr_of(src, soff)
            t = self.vreg()
            self.emit("ld", d=t, a=sb, imm=so, sz=unit, sign=False)
            self.emit("st", a=t, b=b, imm=o, sz=unit)

    # --------------------------------------------------------- lvalues
    def lval(self, n):
        k = n.kind
        if k == "var":
            o = n.var
            if o in self.var_reg:
                return LV("reg", self.var_reg[o])
            if o.is_local:
                if o in self.var_ptr:
                    return LV("mem", self.var_ptr[o], 0)
                return LV("mem", FRAME, self.local_off(o))
            return LV("mem", self.gaddr(o), 0)
        if k == "deref":
            p = n.lhs
            if p.kind in ("add", "sub") and p.ty.is_ptr() and p.rhs.kind == "num":
                off = wrap(p.rhs.val, T.INT128)
                if p.kind == "sub":
                    off = -off
                base = self.expr(p.lhs)
                if fits14(off):
                    return LV("mem", base, off)
                return LV("mem", self.padd(base, self.const(off)), 0)
            return LV("mem", self.expr(p), 0)
        if k == "member":
            m = n.mem
            lv = self.lval_struct(n.lhs)
            off = lv.off + m.offset
            base = lv.reg
            if not fits14(off + 16):
                base = self.padd(self.base_reg(lv), self.const(off))
                off = 0
            if m.bit_width is not None:
                return LV("bit", base, off, m)
            return LV("mem", base, off)
        if k == "cliteral":
            self.gen_init(n.var, n.init)
            return LV("mem", FRAME, self.local_off(n.var))
        if k == "call" or k == "cond" or k == "comma" or k == "assign" or k == "stmtexpr":
            if n.ty.is_struct():
                r = self.expr(n)
                return LV("mem", r, 0)
        error_at(n.tok, f"internal: not an lvalue ({k})")

    def lval_struct(self, n):
        lv = self.lval(n)
        if lv.kind != "mem":
            error_at(n.tok, "internal: struct not in memory")
        return lv

    def base_reg(self, lv):
        if lv.reg == FRAME:
            r = self.vreg()
            self.faddr(r, lv.off)
            lv.reg, lv.off = r, 0
            return r
        return lv.reg

    def addr_reg(self, lv):
        """Materialise the address of a memory lvalue in a register."""
        if lv.reg == FRAME:
            r = self.vreg()
            self.faddr(r, lv.off)
            return r
        if lv.off == 0:
            return lv.reg
        return self.paddi(lv.reg, lv.off)

    def load(self, lv, ty):
        if lv.kind == "reg":
            return lv.reg
        if lv.kind == "bit":
            return self.load_bitfield(lv)
        if ty.is_aggregate() or ty.is_func():
            return self.addr_reg(lv)
        r = self.vreg()
        sz = 16 if ty.kind == "ptr" else ty.size
        self.emit("ld", d=r, a=lv.reg, imm=lv.off, sz=sz, sign=not (ty.unsigned or ty.kind == "ptr"))
        return r

    def store(self, lv, v, ty):
        if lv.kind == "reg":
            self.mov(lv.reg, v)
            return
        if lv.kind == "bit":
            self.store_bitfield(lv.reg, lv.off, lv.mem, v)
            return
        if ty.is_struct():
            dst = self.addr_reg(lv)
            self.copy_mem(dst, 0, v, 0, ty.size, ty.align)
            return
        self.emit("st", a=v, b=lv.reg, imm=lv.off, sz=self.store_size(ty))

    def load_bitfield(self, lv):
        m = lv.mem
        u = self.vreg()
        self.emit("ld", d=u, a=lv.reg, imm=lv.off, sz=m.ty.size, sign=False)
        sh = 128 - m.bit_offset - m.bit_width
        t = self.bini("sll", u, sh) if sh else u
        return self.bini("srl" if m.ty.unsigned else "sra", t, 128 - m.bit_width)

    def store_bitfield(self, base, off, m, v):
        if base == FRAME:
            b = self.vreg()
            self.faddr(b, off)
            base, off = b, 0
        u = self.vreg()
        self.emit("ld", d=u, a=base, imm=off, sz=m.ty.size, sign=False)
        mask = ((1 << m.bit_width) - 1) << m.bit_offset
        cleared = self.bin("and", u, self.const(~mask & T.MASK128))
        sh = self.bini("sll", v, m.bit_offset) if m.bit_offset else v
        ins = self.bin("and", sh, self.const(mask))
        nw = self.bin("or", cleared, ins)
        self.emit("st", a=nw, b=base, imm=off, sz=m.ty.size)

    def bitfield_value(self, m, v):
        """Value of v after truncation to the bit-field width (result of an assignment)."""
        t = self.bini("sll", v, 128 - m.bit_width)
        return self.bini("srl" if m.ty.unsigned else "sra", t, 128 - m.bit_width)

    # --------------------------------------------------------- conditions
    def cond(self, n, lt, lf):
        """Branch to lt if n is true else lf."""
        k = n.kind
        if k == "num":
            self.emit("br", label=lt if n.val else lf)
            return
        if k == "lnot":
            self.cond(n.lhs, lf, lt)
            return
        if k == "logand":
            mid = self.new_label()
            self.cond(n.lhs, mid, lf)
            self.emit("label", label=mid)
            self.cond(n.rhs, lt, lf)
            return
        if k == "logor":
            mid = self.new_label()
            self.cond(n.lhs, lt, mid)
            self.emit("label", label=mid)
            self.cond(n.rhs, lt, lf)
            return
        if k in ("eq", "ne", "lt", "le"):
            u = n.cmpty.unsigned or n.cmpty.kind == "ptr"
            a = self.expr_or_zero(n.lhs)
            b = self.expr_or_zero(n.rhs)
            if k == "eq":
                self.emit("bcc", a=a, b=b, cc="eq", label=lt)
            elif k == "ne":
                self.emit("bcc", a=a, b=b, cc="ne", label=lt)
            elif k == "lt":
                self.emit("bcc", a=a, b=b, cc="ltu" if u else "lt", label=lt)
            else:
                self.emit("bcc", a=b, b=a, cc="geu" if u else "ge", label=lt)
            self.emit("br", label=lf)
            return
        if k == "cast" and n.lhs.ty.is_scalar() and n.ty.is_scalar() and not needs_trunc_for_bool(n):
            self.cond(n.lhs, lt, lf)
            return
        v = self.expr(n)
        self.emit("bcc", a=v, b=ZERO, cc="ne", label=lt)
        self.emit("br", label=lf)

    def expr_or_zero(self, n):
        if n.kind == "num" and n.val == 0:
            return ZERO
        return self.expr(n)

    # --------------------------------------------------------- expressions
    def expr(self, n, discard=False):
        k = n.kind
        m = getattr(self, "e_" + k, None)
        if m is None:
            error_at(n.tok, f"internal: unknown expression {k}")
        if discard and k in ("incdec",):
            return self.e_incdec(n, discard=True)
        return m(n)

    def e_num(self, n):
        if n.val == 0:
            return ZERO
        return self.const(wrap(n.val, n.ty) & T.MASK128)

    def e_var(self, n):
        return self.load(self.lval(n), n.ty)

    e_deref = e_var
    e_member = e_var

    def e_cliteral(self, n):
        return self.load(self.lval(n), n.ty)

    def e_addr(self, n):
        e = n.lhs
        if e.kind == "var" and e.var.is_func if hasattr(e, "var") else False:
            return self.gaddr(e.var)
        if e.kind == "deref":
            return self.expr(e.lhs)
        lv = self.lval(e)
        if lv.kind == "reg":
            error_at(n.tok, "internal: address of register variable")
        return self.addr_reg(lv)

    def e_cast(self, n):
        src = n.lhs.ty
        dst = n.ty
        v = self.expr(n.lhs)
        if dst.kind == "void":
            return ZERO
        if dst.kind == "bool":
            if src.kind == "bool":
                return v
            return self.bin("sltu", ZERO, v)
        if src.is_aggregate() or src.is_func():
            return v
        if needs_ext(src, dst):
            return self.ext(v, dst)
        return v

    def arith(self, op, a, b, ty):
        r = self.arith0(op, a, b, ty)
        if ty.kind != "ptr" and ty.size == 4:
            for i in reversed(self.code):       # mark the 32-bit C operation (opt.fuse_word_ops)
                if i.op == "bin":
                    i.extra = "w32"
                    break
        return r

    def arith0(self, op, a, b, ty):
        if self.pc and ty.kind == "ptr" and op in ("add", "sub"):
            return self.padd(a, b if op == "add" else self.bin("sub", ZERO, b))
        if op == "add":
            r = self.bin("add", a, b)
        elif op == "sub":
            r = self.bin("sub", a, b)
        elif op == "mul":
            r = self.bin("mul", a, b)
        elif op == "div":
            r = self.bin("divu" if ty.unsigned or ty.kind == "ptr" else "div", a, b)
            return r if ty.unsigned or ty.size >= 16 else self.ext(r, ty)
        elif op == "mod":
            return self.bin("remu" if ty.unsigned or ty.kind == "ptr" else "rem", a, b)
        elif op == "band":
            return self.bin("and", a, b)
        elif op == "bor":
            return self.bin("or", a, b)
        elif op == "bxor":
            return self.bin("xor", a, b)
        elif op == "shl":
            r = self.bin("sll", a, b)
        elif op == "shr":
            return self.bin("srl" if ty.unsigned else "sra", a, b)
        else:
            raise AssertionError(op)
        return self.ext(r, ty)

    def binop(self, n):
        a = self.expr(n.lhs)
        b = self.expr(n.rhs)
        return self.arith(n.kind, a, b, n.ty)

    e_add = e_sub = e_mul = e_div = e_mod = e_band = e_bor = e_bxor = e_shl = e_shr = binop

    def e_neg(self, n):
        v = self.expr(n.lhs)
        return self.ext(self.bin("sub", ZERO, v), n.ty)

    def e_bnot(self, n):
        v = self.expr(n.lhs)
        r = self.bini("xor", v, -1)
        return self.ext(r, n.ty) if n.ty.unsigned else r

    def e_lnot(self, n):
        v = self.expr(n.lhs)
        return self.bini("sltu", v, 1)

    def cmp_value(self, n):
        u = n.cmpty.unsigned or n.cmpty.kind == "ptr"
        a = self.expr_or_zero(n.lhs)
        b = self.expr_or_zero(n.rhs)
        k = n.kind
        if k == "eq":
            return self.bin("seq", a, b)
        if k == "ne":
            if b == ZERO:
                return self.bin("sltu", ZERO, a)
            if a == ZERO:
                return self.bin("sltu", ZERO, b)
            return self.bin("sltu", ZERO, self.bin("xor", a, b))
        if k == "lt":
            return self.bin("sltu" if u else "slt", a, b)
        r = self.bin("sltu" if u else "slt", b, a)
        return self.bini("xor", r, 1)

    e_eq = e_ne = e_lt = e_le = cmp_value

    def logic_value(self, n):
        r = self.vreg()
        lt, lf, le = self.new_label(), self.new_label(), self.new_label()
        self.cond(n, lt, lf)
        self.emit("label", label=lt)
        self.emit("li", d=r, imm=1)
        self.emit("br", label=le)
        self.emit("label", label=lf)
        self.emit("li", d=r, imm=0)
        self.emit("label", label=le)
        return r

    e_logand = e_logor = logic_value

    def e_cond(self, n):
        lt, lf, le = self.new_label(), self.new_label(), self.new_label()
        self.cond(n.cond, lt, lf)
        r = self.vreg()
        self.emit("label", label=lt)
        if n.ty.is_void():
            self.expr(n.then, discard=True)
        else:
            self.mov(r, self.expr(n.then))
        self.emit("br", label=le)
        self.emit("label", label=lf)
        if n.ty.is_void():
            self.expr(n.els, discard=True)
        else:
            self.mov(r, self.expr(n.els))
        self.emit("label", label=le)
        return r

    def e_comma(self, n):
        self.expr(n.lhs, discard=True)
        return self.expr(n.rhs)

    def e_assign(self, n):
        lv = self.lval(n.lhs)
        v = self.expr(n.rhs)
        if n.ty.is_struct():
            dst = self.addr_reg(lv)
            self.copy_mem(dst, 0, v, 0, n.ty.size, n.ty.align)
            return dst
        self.store(lv, v, n.ty)
        if lv.kind == "bit":
            return self.bitfield_value(lv.mem, v)
        return v

    def e_opassign(self, n):
        lv = self.lval(n.lhs)
        if lv.kind == "mem" and lv.reg == FRAME:
            pass
        cur = self.load(lv, n.ty)
        lt = n.lhs.ty
        opty = n.opty
        if lt.kind == "ptr":
            rhs = self.expr(n.rhs)
            r = self.padd(cur, rhs if n.op == "add" else self.bin("sub", ZERO, rhs)) if self.pc \
                else self.bin("add" if n.op == "add" else "sub", cur, rhs)
        else:
            c = cur if not needs_ext(lt, opty) else self.ext(cur, opty)
            rhs = self.expr(n.rhs)
            r = self.arith(n.op, c, rhs, opty)
            if needs_ext(opty, lt):
                r = self.ext(r, lt)
            if lt.kind == "bool":
                r = self.bin("sltu", ZERO, r)
        self.store(lv, r, lt)
        if lv.kind == "bit":
            return self.bitfield_value(lv.mem, r)
        return r

    def e_incdec(self, n, discard=False):
        lv = self.lval(n.lhs)
        ty = n.ty
        cur = self.load(lv, ty)
        if ty.kind == "bool":
            nv = self.const(1) if n.delta > 0 else self.bini("xor", cur, 1)
        else:
            if self.pc and ty.kind == "ptr":
                nv = self.paddi(cur, n.delta) if fits14(n.delta) else self.padd(cur, self.const(n.delta))
            else:
                nv = self.bini("add", cur, n.delta) if fits14(n.delta) else self.bin("add", cur, self.const(n.delta))
            nv = self.ext(nv, ty)
        if n.post and not discard:
            old = self.vreg()
            self.mov(old, cur)
            self.store(lv, nv, ty)
            return old
        self.store(lv, nv, ty)
        if lv.kind == "bit":
            return self.bitfield_value(lv.mem, nv)
        return nv

    def e_stmtexpr(self, n):
        body = n.body.body
        for s in body[:-1]:
            self.stmt(s)
        if body and body[-1].kind == "expr":
            return self.expr(body[-1].expr)
        if body:
            self.stmt(body[-1])
        return ZERO

    def e_cheri(self, n):
        """__builtin_cheri_*: capability intrinsics (no-ops / plain values in hybrid mode)."""
        a = self.expr(n.args[0])
        b = self.expr(n.args[1]) if len(n.args) > 1 else None
        op = n.op
        if op in ("bounds_set", "perms_and") and not self.pc:
            return a                      # hybrid pointers are untagged: nothing to narrow
        if op == "address_set" and not self.pc:
            return b
        cc = {"bounds_set": "csetbnd", "address_set": "csetaddr", "perms_and": "candperm",
              "tag_get": "cgettag", "length_get": "cgetlen", "base_get": "cgetbase", "perms_get": "cgetperm"}[op]
        r = self.vreg()
        self.emit("bin", d=r, a=a, b=b, cc=cc)
        return r

    def e_va_start(self, n):
        lv = self.lval(n.ap)
        r = self.vreg()
        self.emit("faddr", d=r, imm=self.va_first, sym="INCOMING")
        self.store(lv, r, n.ap.ty)
        return ZERO

    def e_va_arg(self, n):
        lv = self.lval(n.ap)
        ap0 = self.load(lv, n.ap.ty)
        ap = self.vreg()
        self.mov(ap, ap0)
        nxt = self.paddi(ap, 16)
        self.store(lv, nxt, n.ap.ty)
        ty = n.ty
        r = self.vreg()
        self.emit("ld", d=r, a=ap, imm=0, sz=16 if ty.kind == "ptr" else ty.size,
                  sign=not (ty.unsigned or ty.kind == "ptr"))
        return r

    def e_call(self, n):
        fty = n.fty
        # builtins
        if n.fname in ("__builtin_halt",):
            pass
        args = []
        sret_slot = None
        if fty.ret.is_struct():
            sret_slot = self.alloc_slot(fty.ret.size, fty.ret.align)
            r = self.vreg()
            self.faddr(r, sret_slot)
            args.append(r)
        for a in n.args:
            if a.ty.is_struct():
                src = self.expr(a)
                off = self.alloc_slot(a.ty.size, max(a.ty.align, 16))
                d = self.vreg()
                self.faddr(d, off)
                self.copy_mem(d, 0, src, 0, a.ty.size, a.ty.align)
                args.append(d)
            else:
                args.append(self.expr_or_zero(a))
        target = None
        sym = None
        fn = n.fn
        if fn.kind == "addr" and fn.lhs.kind == "var" and fn.lhs.var.is_func:
            sym = fn.lhs.var.asm_name
            fn.lhs.var.referenced = True
        else:
            target = self.expr(fn)
        nstack = max(0, len(args) - NARGREG)
        self.out_area = max(self.out_area, 16 * nstack)
        for i, a in enumerate(args[NARGREG:]):
            self.emit("st", a=a, b=SP, imm=16 * i, sz=16)
        for i, a in enumerate(args[:NARGREG]):
            self.mov(A0 + i, a)
        self.has_call = True
        self.emit("call", a=target, sym=sym, nargs=min(len(args), NARGREG))
        if fty.ret.is_void():
            return ZERO
        r = self.vreg()
        self.mov(r, A0)
        if fty.ret.is_struct():
            return r
        return r


def needs_trunc_for_bool(n):
    """A cast used as a condition can be skipped unless it narrows (truncation changes truthiness)."""
    src, dst = n.lhs.ty, n.ty
    if dst.kind == "bool":
        return False
    db = 128 if dst.kind == "ptr" else dst.size * 8
    sb = 128 if src.kind == "ptr" else src.size * 8
    return db < sb


T.MASK128 = (1 << 128) - 1
T.MASK = T.MASK128
