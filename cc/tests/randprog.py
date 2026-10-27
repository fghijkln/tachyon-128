#!/usr/bin/env python3
"""Small csmith-style random C program generator for differential testing (tcc128 vs host gcc).

Programs are free of undefined behaviour under the documented host flags (-fwrapv, signed char):
  * division/remainder go through safe_* helpers (divisor 0 or MIN/-1 -> dividend),
  * shift counts are masked to the promoted width, left operands of shifts are made unsigned,
  * expressions are side-effect free (calls and assignments only appear as statements), so the
    result never depends on the order of evaluation,
  * array indices are masked to the array length, loops have constant trip counts.
At exit every global is printed, so any miscompilation that changes state is observable.
"""
import random
import sys

INT_TYPES = [
    ("signed char", 8, True), ("unsigned char", 8, False), ("short", 16, True),
    ("unsigned short", 16, False), ("int", 32, True), ("unsigned int", 32, False),
    ("long", 64, True), ("unsigned long", 64, False), ("long long", 64, True),
    ("unsigned long long", 64, False), ("__int128", 128, True), ("unsigned __int128", 128, False),
]
TINFO = {n: (b, s) for n, b, s in INT_TYPES}
RANK = {"signed char": 1, "unsigned char": 1, "short": 2, "unsigned short": 2, "int": 3, "unsigned int": 3,
        "long": 4, "unsigned long": 4, "long long": 5, "unsigned long long": 5, "__int128": 6,
        "unsigned __int128": 6}
UNSIGNED_OF = {"int": "unsigned int", "long": "unsigned long", "long long": "unsigned long long",
               "__int128": "unsigned __int128"}


def promote(t):
    return "int" if TINFO[t][0] < 32 else t


def usual(a, b):
    a, b = promote(a), promote(b)
    if a == b:
        return a
    (ab, asg), (bb, bsg) = TINFO[a], TINFO[b]
    if asg == bsg:
        return a if RANK[a] > RANK[b] else b
    u, s = (a, b) if not asg else (b, a)
    if RANK[u] >= RANK[s]:
        return u
    if TINFO[s][0] > TINFO[u][0]:
        return s
    return UNSIGNED_OF[s]


def wrap(v, t):
    b, s = TINFO[t]
    v &= (1 << b) - 1
    if s and v >> (b - 1):
        v -= 1 << b
    return v


class Gen:
    def __init__(self, seed, use128=True):
        self.r = random.Random(seed)
        self.seed = seed
        self.types = [t for t in INT_TYPES if use128 or t[1] < 128]
        self.globals = []     # (name, type, arraylen or None)
        self.funcs = []       # (name, rettype, [param types])
        self.out = []

    def rtype(self):
        r = self.r.random()
        if r < 0.3:
            return "int"
        if r < 0.4:
            return "unsigned int"
        return self.r.choice(self.types)[0]

    def const(self, t):
        b, s = TINFO[t]
        r = self.r.random()
        if r < 0.3:
            v = self.r.randint(-10, 10)
        elif r < 0.5:
            v = self.r.choice([0, 1, -1, 127, 128, 255, 256, 32767, -32768, 65535, 2147483647, -2147483648,
                               4294967295, 0x7FFFFFFFFFFFFFFF, -(1 << 63)])
        else:
            v = self.r.getrandbits(min(b, 64))
        v = wrap(v, t)
        return self.lit(v, t), t

    def lit(self, v, t):
        b, s = TINFO[t]
        if b == 128:
            hi = (v >> 64) & ((1 << 64) - 1)
            lo = v & ((1 << 64) - 1)
            return f"(({t})(((unsigned __int128){hi:#x}ULL << 64) | {lo:#x}ULL))"
        if v < 0:
            if b <= 32:
                return f"(({t})({v + 1} - 1))"
            return f"(({t})({v + 1}LL - 1))"
        suf = "ULL" if b == 64 or v > 0x7FFFFFFF else ("U" if not s else "")
        return f"(({t}){v:#x}{suf})"

    # --------------------------------------------------------------- expressions
    def expr(self, scope, depth):
        """Returns (code, type)."""
        r = self.r.random()
        if depth <= 0 or r < 0.25:
            return self.leaf(scope)
        r = self.r.random()
        if r < 0.45:
            op = self.r.choice(["+", "-", "*", "&", "|", "^", "+", "-"])
            a, ta = self.expr(scope, depth - 1)
            b, tb = self.expr(scope, depth - 1)
            return f"({a} {op} {b})", usual(ta, tb)
        if r < 0.55:
            op = self.r.choice(["/", "%"])
            a, ta = self.expr(scope, depth - 1)
            b, tb = self.expr(scope, depth - 1)
            t = usual(ta, tb)
            fn = ("safe_div_" if op == "/" else "safe_mod_") + self.tname(t)
            self.need_safe.add(t)
            return f"{fn}({a}, {b})", t
        if r < 0.65:
            op = self.r.choice(["<<", ">>"])
            a, ta = self.expr(scope, depth - 1)
            b, tb = self.expr(scope, depth - 1)
            pa = promote(ta)
            w = TINFO[pa][0]
            if op == "<<" and TINFO[pa][1]:
                # make the left operand unsigned to avoid shifting into the sign bit
                pa = UNSIGNED_OF[pa]
                a = f"(({pa}){a})"
            return f"({a} {op} (({b}) & {w - 1}))", pa
        if r < 0.75:
            op = self.r.choice(["<", ">", "<=", ">=", "==", "!=", "&&", "||"])
            a, ta = self.expr(scope, depth - 1)
            b, tb = self.expr(scope, depth - 1)
            return f"({a} {op} {b})", "int"
        if r < 0.82:
            op = self.r.choice(["-", "~", "!", "+"])
            a, ta = self.expr(scope, depth - 1)
            return f"({op}{a})", ("int" if op == "!" else promote(ta))
        if r < 0.9:
            t = self.rtype()
            a, ta = self.expr(scope, depth - 1)
            return f"(({t}){a})", t
        c, tc = self.expr(scope, depth - 1)
        a, ta = self.expr(scope, depth - 1)
        b, tb = self.expr(scope, depth - 1)
        return f"({c} ? {a} : {b})", usual(ta, tb)

    def leaf(self, scope):
        r = self.r.random()
        if r < 0.3:
            return self.const(self.rtype())
        if r < 0.38 and self.fields:
            f = self.r.choice(self.fields)
            return f"s0.{f[0]}", f[1]
        if r < 0.43 and self.ptrs:
            n, t = self.r.choice(self.ptrs)
            return f"(*{n})", t
        if r < 0.47 and self.pures and self.pure_depth < 2:
            name, rt, pts = self.r.choice(self.pures)
            self.pure_depth += 1
            args = ", ".join(self.expr(scope, 1)[0] for _ in pts)
            self.pure_depth -= 1
            return f"{name}({args})", rt
        cands = list(scope) + [(n, t, a) for n, t, a in self.globals]
        n, t, alen = self.r.choice(cands)
        if alen:
            idx, ti = self.expr(scope, 0)
            return f"{n}[(unsigned)({idx}) % {alen}u]", t
        return n, t

    def tname(self, t):
        return t.replace(" ", "_")

    def lvalue(self, scope, scalar=False):
        cands = [c for c in scope if not c[0].startswith("i")] + [(n, t, a) for n, t, a in self.globals]
        if self.fields and self.r.random() < 0.15:
            f = self.r.choice(self.fields)
            return f"s0.{f[0]}", f[1]
        if self.ptrs and self.r.random() < 0.1:
            n, t = self.r.choice(self.ptrs)
            return f"(*{n})", t
        if scalar:
            cands = [c for c in cands if not c[2]] or [("i_tmp", "int", None)]
        n, t, alen = self.r.choice(cands)
        if alen:
            idx, ti = self.expr(scope, 1)
            return f"{n}[(unsigned)({idx}) % {alen}u]", t
        return n, t

    # --------------------------------------------------------------- statements
    def stmt(self, scope, depth, fidx, ind, loopvars):
        r = self.r.random()
        p = "    " * ind
        if depth > 0 and r < 0.12:
            c, _ = self.expr(scope, 2)
            self.out.append(f"{p}if ({c}) {{")
            self.block(scope, depth - 1, fidx, ind + 1, loopvars, self.r.randint(1, 3))
            if self.r.random() < 0.5:
                self.out.append(f"{p}}} else {{")
                self.block(scope, depth - 1, fidx, ind + 1, loopvars, self.r.randint(1, 3))
            self.out.append(f"{p}}}")
            return
        if depth > 0 and r < 0.22 and len(loopvars) < 3:
            lv = f"i{len(loopvars)}"
            n = self.r.randint(1, 4)
            kind = self.r.random()
            if kind < 0.6:
                self.out.append(f"{p}for ({lv} = 0; {lv} < {n}; {lv}++) {{")
            elif kind < 0.8:
                self.out.append(f"{p}{lv} = {n};")
                self.out.append(f"{p}while ({lv}-- > 0) {{")
            else:
                self.out.append(f"{p}{lv} = 0;")
                self.out.append(f"{p}do {{")
            scope2 = scope + [(lv, "int", None)]
            self.block(scope2, depth - 1, fidx, ind + 1, loopvars + [lv], self.r.randint(1, 4))
            if self.r.random() < 0.2:
                c, _ = self.expr(scope2, 1)
                self.out.append(f"{p}    if ({c}) {self.r.choice(['break', 'continue'])};")
            if kind >= 0.8:
                self.out.append(f"{p}}} while (++{lv} < {n});")
            else:
                self.out.append(f"{p}}}")
            return
        if depth > 0 and r < 0.28:
            c, t = self.expr(scope, 1)
            self.out.append(f"{p}switch ((int)({c}) & 7) {{")
            used = self.r.sample(range(8), self.r.randint(1, 4))
            for v in used:
                self.out.append(f"{p}case {v}:")
                self.block(scope, depth - 1, fidx, ind + 1, loopvars, self.r.randint(1, 2))
                if self.r.random() < 0.7:
                    self.out.append(f"{p}    break;")
            if self.r.random() < 0.5:
                self.out.append(f"{p}default:")
                self.block(scope, depth - 1, fidx, ind + 1, loopvars, 1)
            self.out.append(f"{p}}}")
            return
        if r < 0.36 and fidx + 1 < len(self.funcs) and len(loopvars) <= 1:
            j = self.r.randint(fidx + 1, len(self.funcs) - 1)
            name, rt, pts = self.funcs[j]
            args = ", ".join(self.expr(scope, 2)[0] for _ in pts)
            lv, lt = self.lvalue(scope, scalar=True)
            self.out.append(f"{p}{lv} = {name}({args});")
            return
        if r < 0.45:
            lv, lt = self.lvalue(scope)
            op = self.r.choice(["++", "--"])
            self.out.append(f"{p}{lv}{op};" if self.r.random() < 0.5 else f"{p}{op}{lv};")
            return
        if r < 0.6:
            lv, lt = self.lvalue(scope)
            op = self.r.choice(["+=", "-=", "*=", "&=", "|=", "^=", "<<=", ">>="])
            e, te = self.expr(scope, 2)
            if op in ("<<=", ">>="):
                w = TINFO[promote(lt)][0]
                if op == "<<=" and TINFO[promote(lt)][1]:
                    # avoid UB: do it unsigned
                    ut = UNSIGNED_OF[promote(lt)]
                    self.out.append(f"{p}{lv} = ({lt})(({ut}){lv} << (({e}) & {w - 1}));")
                    return
                self.out.append(f"{p}{lv} {op} (({e}) & {w - 1});")
                return
            self.out.append(f"{p}{lv} {op} {e};")
            return
        lv, lt = self.lvalue(scope)
        e, te = self.expr(scope, 3)
        self.out.append(f"{p}{lv} = {e};")

    def block(self, scope, depth, fidx, ind, loopvars, n):
        for _ in range(n):
            self.stmt(scope, depth, fidx, ind, loopvars)

    # --------------------------------------------------------------- program
    def program(self):
        self.need_safe = set()
        ng = self.r.randint(4, 9)
        for k in range(ng):
            t = self.rtype()
            alen = self.r.choice([None, None, None, 4, 8, 5])
            self.globals.append((f"g{k}", t, alen))
        # struct with bit-fields
        self.fields = []
        sdecl = ["struct S0 {"]
        for k in range(self.r.randint(0, 6)):
            t = self.r.choice(["int", "unsigned int", "signed char", "unsigned short", "long", "unsigned char"])
            if t in ("int", "unsigned int") and self.r.random() < 0.6:
                w = self.r.randint(1, 31)
                sdecl.append(f"    {t} f{k} : {w};")
                self.fields.append((f"f{k}", t, w))
            else:
                sdecl.append(f"    {t} f{k};")
                self.fields.append((f"f{k}", t, None))
        sdecl.append("};")
        # pointers to scalar globals
        self.ptrs = []
        pdecl = []
        scal = [(n, t) for n, t, a in self.globals if not a]
        for k in range(self.r.randint(0, 2) if scal else 0):
            n, t = self.r.choice(scal)
            pdecl.append(f"static {t} *ptr{k} = &{n};")
            self.ptrs.append((f"ptr{k}", t))
        # pure helpers (no global side effects) usable inside expressions
        self.pures = []
        self.pure_depth = 0
        pure_src = []
        for k in range(self.r.randint(0, 3)):
            rt = self.rtype()
            pts = [self.rtype() for _ in range(self.r.randint(1, 3))]
            params = [(f"a{i}", t, None) for i, t in enumerate(pts)]
            saved = self.pures, self.fields, self.ptrs, self.globals
            self.fields, self.ptrs, self.globals = [], [], []
            e, _ = self.expr(params, 3)
            self.pures, self.fields, self.ptrs, self.globals = saved
            sig = ", ".join(f"{t} {n}" for n, t, _ in params)
            pure_src.append(f"static {rt} pure_{k}({sig}) {{ return {e}; }}")
            self.pures.append((f"pure_{k}", rt, pts))
        nf = self.r.randint(2, 6)
        for k in range(nf):
            rt = self.rtype()
            pts = [self.rtype() for _ in range(self.r.choice([0, 1, 2, 3, 4, 5, 9, 11]))]
            self.funcs.append((f"func_{k}", rt, pts))
        body = []
        for k in range(nf - 1, -1, -1):
            name, rt, pts = self.funcs[k]
            self.out = []
            params = [(f"p{i}", t, None) for i, t in enumerate(pts)]
            locs = [(f"l{i}", self.rtype(), None) for i in range(self.r.randint(0, 4))]
            sig = ", ".join(f"{t} {n}" for n, t, _ in params) or "void"
            self.out.append(f"static {rt} {name}({sig}) {{")
            self.out.append("    int i0 = 0, i1 = 0, i2 = 0, i_tmp = 0;")
            for n, t, _ in locs:
                c, _ = self.const(t)
                self.out.append(f"    {t} {n} = {c};")
            self.block(params + locs, 3, k, 1, [], self.r.randint(3, 8))
            e, te = self.expr(params + locs, 3)
            self.out.append(f"    (void)i0; (void)i1; (void)i2; (void)i_tmp;")
            self.out.append(f"    return {e};")
            self.out.append("}")
            body.append("\n".join(self.out))
        body.reverse()
        hdr = ["/* random program, seed %d */" % self.seed, "#include <stdio.h>"]
        for n, t, alen in self.globals:
            if alen:
                init = ", ".join(self.const(t)[0] for _ in range(alen))
                hdr.append(f"static {t} {n}[{alen}] = {{{init}}};")
            else:
                hdr.append(f"static {t} {n} = {self.const(t)[0]};")
        if self.fields:
            hdr += sdecl
            init = ", ".join(str(self.r.randint(0, 1) if f[2] == 1 else self.r.randint(-5, 50)) for f in self.fields)
            hdr.append(f"static struct S0 s0 = {{{init}}};")
        hdr += pdecl
        safe = []
        for t in sorted(self.need_safe):
            tn = self.tname(t)
            b, s = TINFO[t]
            if s:
                mn = f"(({t})1 << {b - 1})"
                cond = f"b == 0 || (a == {mn} && b == -1)"
            else:
                cond = "b == 0"
            safe.append(f"static {t} safe_div_{tn}({t} a, {t} b) {{ return ({cond}) ? a : a / b; }}")
            safe.append(f"static {t} safe_mod_{tn}({t} a, {t} b) {{ return ({cond}) ? a : a % b; }}")
        main = ["int main(void) {"]
        name, rt, pts = self.funcs[0]
        args = ", ".join(self.const(t)[0] for t in pts)
        main.append(f"    {rt} r = {name}({args});")
        main.append("    print128(\"r\", (unsigned __int128)r);")
        for n, t, alen in self.globals:
            if alen:
                for i in range(alen):
                    main.append(f"    print128(\"{n}[{i}]\", (unsigned __int128){n}[{i}]);")
            else:
                main.append(f"    print128(\"{n}\", (unsigned __int128){n});")
        for f in self.fields:
            main.append(f"    print128(\"s0.{f[0]}\", (unsigned __int128)s0.{f[0]});")
        main.append("    return 0;\n}")
        helper = ("static void print128(const char *n, unsigned __int128 v) {\n"
                  "    printf(\"%s=%016llx%016llx\\n\", n, (unsigned long long)(v >> 64), (unsigned long long)v);\n}")
        protos = []
        for name, rt, pts in self.funcs:
            protos.append(f"static {rt} {name}({', '.join(pts) or 'void'});")
        return "\n".join(hdr + safe + [helper] + pure_src + protos + body + main) + "\n"


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    sys.stdout.write(Gen(seed).program())


if __name__ == "__main__":
    main()
