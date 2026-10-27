"""Machine-independent IR clean-up: constant propagation into immediates, constant folding,
redundant-extension removal, copy propagation, retargeting and dead-code elimination."""
from .ir import VREG0, ZERO, Ins, fits14

M128 = (1 << 128) - 1
PURECAP = False      # set by the driver per unit: -mpurecap code (integer adds never feed a capability base)


def enabled(name):
    """v6 perf passes can be switched off individually for A/B measurements and bisecting:
    TCC128_DISABLE=name[,name...] (part of the libc cache key)."""
    import os
    return name not in os.environ.get("TCC128_DISABLE", "").split(",")
IMM_OPS = {"add", "and", "or", "xor", "slt", "sltu", "sll", "srl", "sra", "cadd"}
COMMUTATIVE = {"add", "and", "or", "xor", "mul", "seq", "min", "max", "minu", "maxu"}
PURE = {"li", "la", "mov", "bin", "ext", "ld", "faddr"}


def sx(v):
    v &= M128
    return v - (1 << 128) if v >> 127 else v


def fold(op, a, b):
    a &= M128
    b &= M128
    if op == "add":
        return a + b
    if op == "sub":
        return a - b
    if op == "and":
        return a & b
    if op == "or":
        return a | b
    if op == "xor":
        return a ^ b
    if op == "sll":
        return a << (b & 127)
    if op == "srl":
        return a >> (b & 127)
    if op == "sra":
        return sx(a) >> (b & 127)
    if op == "slt":
        return int(sx(a) < sx(b))
    if op == "sltu":
        return int(a < b)
    if op == "seq":
        return int(a == b)
    if op == "mul":
        return a * b
    if op in ("div", "divu", "rem", "remu"):
        if b == 0:
            return None
        if op == "divu":
            return a // b
        if op == "remu":
            return a % b
        sa, sb = sx(a), sx(b)
        q = abs(sa) // abs(sb)
        if (sa < 0) != (sb < 0):
            q = -q
        return q if op == "div" else sa - q * sb
    return None


def ext_val(v, bits, sign):
    v &= (1 << bits) - 1
    if sign and v >> (bits - 1):
        v -= 1 << bits
    return v & M128


def def_counts(code):
    cnt = {}
    for i in code:
        for d in i.defs():
            if d >= VREG0:
                cnt[d] = cnt.get(d, 0) + 1
    return cnt


def use_counts(code):
    cnt = {}
    for i in code:
        for u in i.uses():
            if u is not None and u >= VREG0:
                cnt[u] = cnt.get(u, 0) + 1
    return cnt


def canonical_for(ins, bits, sign):
    """Is the (single) value defined by ins already canonical for an ext(bits, sign)?"""
    if ins is None:
        return False
    if ins.op == "ld":
        lb = ins.sz * 8
        if lb > bits:
            return False
        if lb == bits:
            return ins.sign == sign
        return (not ins.sign) or sign      # zero-extended narrower is canonical for both
    if ins.op == "ext":
        if ins.sz == bits and ins.sign == sign:
            return True
        if ins.sz < bits:
            return (not ins.sign) or sign
        return False
    if ins.op == "li":
        return ext_val(ins.imm, bits, sign) == ins.imm & M128
    if ins.op == "bin" and ins.cc in ("slt", "sltu", "seq"):
        return True
    if ins.op == "bin" and ins.cc == "and" and ins.b is None and ins.imm is not None and ins.imm >= 0:
        return ins.imm < (1 << (bits - 1)) or (not sign and ins.imm < (1 << bits))
    if ins.op == "bin" and ins.cc == "srl" and ins.b is None and ins.imm is not None:
        w = 128 - (ins.imm & 127)
        return w < bits or (w == bits and not sign)
    if ins.op == "bin" and ins.cc == "sra" and ins.b is None and ins.imm is not None:
        w = 128 - (ins.imm & 127)
        return w <= bits and sign
    return False


def optimize(code):
    for rnd in range(4):
        changed = False
        if rnd == 0 and enabled("dupret"):
            code, changed = dup_returns(code)
        dc = def_counts(code)
        single = {}
        for i in code:
            for d in i.defs():
                if d >= VREG0 and dc.get(d) == 1:
                    single[d] = i

        def constval(r):
            if r == ZERO:
                return 0
            if r is None or r < VREG0:
                return None
            ins = single.get(r)
            if ins is not None and ins.op == "li":
                return ins.imm & M128
            return None

        out = []
        for i in code:
            op = i.op
            if op == "bin":
                ca, cb = constval(i.a), (constval(i.b) if i.b is not None else i.imm)
                if i.b is None and cb is not None:
                    cb &= M128
                if ca is not None and cb is not None:
                    v = fold(i.cc, ca, cb)
                    if v is not None:
                        i = Ins("li", d=i.d, imm=v & M128)
                        changed = True
                        out.append(i)
                        single[i.d] = i if dc.get(i.d) == 1 else single.get(i.d)
                        continue
                if i.b is not None:
                    if ca is not None and cb is None and i.cc in COMMUTATIVE:
                        i.a, i.b = i.b, i.a
                        ca, cb = cb, ca
                        changed = True
                    if cb is not None:
                        s = sx(cb)
                        if i.cc in ("sll", "srl", "sra"):
                            i.b, i.imm = None, cb & 127
                            changed = True
                        elif i.cc in IMM_OPS and fits14(s):
                            i.b, i.imm = None, s
                            changed = True
                        elif i.cc == "sub" and fits14(-s):
                            i.cc, i.b, i.imm = "add", None, -s
                            changed = True
                        elif cb == 0 and i.b != ZERO:
                            i.b = ZERO
                            changed = True
                        elif i.cc == "mul" and cb & (cb - 1) == 0 and cb:
                            i.cc, i.b, i.imm = "sll", None, cb.bit_length() - 1
                            changed = True
                        elif i.cc == "divu" and cb & (cb - 1) == 0 and cb:
                            i.cc, i.b, i.imm = "srl", None, cb.bit_length() - 1
                            changed = True
                        elif i.cc == "remu" and cb & (cb - 1) == 0 and cb and fits14(cb - 1):
                            i.cc, i.b, i.imm = "and", None, cb - 1
                            changed = True
                if i.b is None and i.imm is not None:
                    if (i.cc in ("add", "or", "xor", "sll", "srl", "sra", "cadd") and i.imm == 0):
                        i = Ins("mov", d=i.d, a=i.a)
                        changed = True
                    elif i.cc == "and" and sx(i.imm) == -1:
                        i = Ins("mov", d=i.d, a=i.a)
                        changed = True
                    elif ca == 0 and i.a != ZERO:
                        i.a = ZERO
                        changed = True
                elif ca == 0 and i.a != ZERO:
                    i.a = ZERO
                    changed = True
            elif op == "bcc":
                ca, cb = constval(i.a), constval(i.b)
                if ca == 0 and i.a != ZERO:
                    i.a = ZERO
                    changed = True
                if cb == 0 and i.b != ZERO:
                    i.b = ZERO
                    changed = True
                if ca is not None and cb is not None:
                    sa, sb = sx(ca), sx(cb)
                    t = {"eq": ca == cb, "ne": ca != cb, "lt": sa < sb, "ge": sa >= sb,
                         "ltu": ca < cb, "geu": ca >= cb}[i.cc]
                    if t:
                        i = Ins("br", label=i.label)
                    else:
                        changed = True
                        continue
                    changed = True
            elif op == "st":
                if constval(i.a) == 0 and i.a != ZERO:
                    i.a = ZERO
                    changed = True
            elif op == "mov":
                c = constval(i.a)
                if c is not None and i.a != ZERO and i.d >= VREG0:
                    i = Ins("li", d=i.d, imm=c)
                    changed = True
            elif op == "ext":
                src = single.get(i.a) if i.a is not None and i.a >= VREG0 else None
                c = constval(i.a)
                if c is not None:
                    i = Ins("li", d=i.d, imm=ext_val(c, i.sz, i.sign))
                    changed = True
                elif i.a == ZERO:
                    i = Ins("li", d=i.d, imm=0)
                    changed = True
                elif canonical_for(src, i.sz, i.sign):
                    i = Ins("mov", d=i.d, a=i.a)
                    changed = True
            out.append(i)
        code = out
        if demanded_bits(code):
            changed = True
        if enabled("basefold") and fold_bases(code):
            changed = True
        # copy propagation: single-def d = mov s (s single-def vreg or a never-redefined phys? no)
        dc = def_counts(code)
        rep = {}
        for i in code:
            if i.op == "mov" and i.d >= VREG0 and i.a is not None and i.a >= VREG0 and \
                    dc.get(i.d) == 1 and dc.get(i.a) == 1:
                rep[i.d] = i.a
        if rep:
            def R(r):
                seen = 0
                while r in rep and seen < 50:
                    r = rep[r]
                    seen += 1
                return r
            for i in code:
                if i.a is not None and i.a in rep:
                    i.a = R(i.a)
                if i.b is not None and i.b in rep:
                    i.b = R(i.b)
            changed = True
        if enabled("copyprop"):
            if local_copy_prop(code):
                changed = True
            code, d = live_dce(code)
            changed = changed or d
        # retarget: t = <op>; mov v, t  (t used once, defined right before) -> v = <op>
        uc = use_counts(code)
        dc = def_counts(code)
        out = []
        for i in code:
            if i.op == "mov" and out and i.a is not None and i.a >= VREG0 and uc.get(i.a) == 1 and \
                    dc.get(i.a) == 1 and out[-1].op in PURE and out[-1].d == i.a and i.d is not None and \
                    i.d >= VREG0:
                out[-1].d = i.d
                changed = True
                continue
            out.append(i)
        code = out
        # dead code
        while True:
            uc = use_counts(code)
            n0 = len(code)
            code = [i for i in code if not (i.op in PURE and i.d is not None and i.d >= VREG0 and
                                            uc.get(i.d, 0) == 0)]
            code = [i for i in code if not (i.op == "mov" and i.d == i.a)]
            if len(code) == n0:
                break
            changed = True
        code = jump_cleanup(code)
        if not changed:
            break
    return code


def fold_bases(code):
    """v6 base+offset folding (post-increment pointers): within a block, track y == x + k for
    y = mov x / y = add x, imm, and keep the relation when x itself steps (x = add x, c, or
    x = mov t with t == x + c).  A load/store through y then uses x with the offset adjusted,
    so `*d++ = *s++` becomes `lb t, -1(s); sb t, -1(d)` after the increments and the
    old-value copies die.  In purecap code only plain copies are tracked (an integer add drops
    the tag, so rebasing onto the tagged source would change which accesses trap)."""
    eq = {}           # y -> (x, k): y == x + k at this point
    did = False
    for i in code:
        op = i.op
        if op == "label":
            eq = {}
            continue
        if op == "ld" and i.a is not None and i.a in eq:
            x, k = eq[i.a]
            if fits14(i.imm + k):
                i.a, i.imm = x, i.imm + k
                did = True
        elif op == "st" and i.b is not None and i.b in eq:
            x, k = eq[i.b]
            if fits14(i.imm + k):
                i.b, i.imm = x, i.imm + k
                did = True
        if op == "call":
            continue
        for d in i.defs():
            if d is None:
                continue
            step = None
            if op == "bin" and i.cc == "add" and i.b is None and i.a == d and i.imm is not None:
                step = sx(i.imm)
            elif op == "mov" and i.a in eq and eq[i.a][0] == d:
                step = eq[i.a][1]
            eq.pop(d, None)
            if step is not None:
                eq = {y: ((x, k - step) if x == d else (x, k)) for y, (x, k) in eq.items()}
            else:
                eq = {y: v for y, v in eq.items() if v[0] != d}
            if d < VREG0:
                continue
            if op == "mov" and i.a is not None and i.a >= VREG0 and i.a != d:
                eq[d] = (i.a, 0)
            elif op == "bin" and i.cc == "add" and i.b is None and i.imm is not None and \
                    i.a is not None and i.a >= VREG0 and i.a != d and not PURECAP:
                eq[d] = (i.a, sx(i.imm))
    return did


def local_copy_prop(code):
    """v6 block-local copy propagation for multiply-defined vregs (the global pass only handles
    single-definition copies): after d = mov s, uses of d read s until either is redefined."""
    cp = {}
    did = False
    dc = def_counts(code)
    uc = use_counts(code)
    for i in code:
        if i.op == "label":
            cp = {}
            continue
        if cp:
            if i.a is not None and i.a in cp and i.op != "label":
                i.a = cp[i.a]
                did = True
            if i.b is not None and i.b in cp and i.op in ("bin", "bcc", "st"):
                i.b = cp[i.b]
                did = True
        for d in i.defs():
            if d is None:
                continue
            if cp:
                cp = {k: v for k, v in cp.items() if k != d and v != d}
            if i.op == "mov" and d >= VREG0 and i.a is not None and i.a >= VREG0 and i.a != d and \
                    not (dc.get(i.a) == 1 and uc.get(i.a) == 1):
                cp[d] = i.a     # (t = op; ...; d = mov t with t used once is left to retargeting)
    return did


def live_dce(code):
    """v6 liveness-based dead-code elimination: a pure definition (no loads) whose vreg is not
    live afterwards is removed even if the vreg is used elsewhere (other live ranges)."""
    from .backend import build_blocks, liveness
    blocks = build_blocks(code)
    liveness(code, blocks)
    dead = set()
    for b in blocks:
        live = b.live_out
        for k in range(b.end, b.start - 1, -1):
            i = code[k]
            ds = i.defs()
            if i.op in ("li", "la", "mov", "bin", "ext", "faddr") and ds and ds[0] is not None and \
                    ds[0] >= VREG0 and not (live >> (ds[0] - VREG0)) & 1:
                dead.add(k)
                continue
            for d in ds:
                if d is not None and d >= VREG0:
                    live &= ~(1 << (d - VREG0))
            for u in i.uses():
                if u is not None and u >= VREG0:
                    live |= 1 << (u - VREG0)
    if not dead:
        return code, False
    return [i for k, i in enumerate(code) if k not in dead], True


DUP_MAX = 4       # instructions (besides the ret) of a return block that may be copied
DUP_SITES = 8     # copies per return block


def dup_returns(code):
    """v6 return-block duplication: `br L` to a short block `L: <= 4 simple ops; ret` becomes a
    copy of that block, so each return path ends in its own ret (no jump to a shared exit; the
    epilogue sinks into each path, which also lets shrink-wrapping give an early exit no frame)."""
    import copy
    label_pos = {i.label: k for k, i in enumerate(code) if i.op == "label"}
    bodies = {}
    for l, k in label_pos.items():
        j = k + 1
        while j < len(code) and code[j].op == "label":
            j += 1
        body = []
        while j < len(code) and len(body) <= DUP_MAX and code[j].op in ("mov", "li", "bin", "ext", "la"):
            body.append(code[j])
            j += 1
        if j < len(code) and code[j].op == "ret" and len(body) <= DUP_MAX:
            bodies[l] = body + [code[j]]
    if not bodies:
        return code, False
    out = []
    count = {}
    did = False
    for i in code:
        if i.op == "br" and i.label in bodies and count.get(i.label, 0) < DUP_SITES:
            count[i.label] = count.get(i.label, 0) + 1
            out.extend(copy.copy(x) for x in bodies[i.label])
            did = True
            continue
        out.append(i)
    return out, did


def jump_cleanup(code):
    """Remove unreachable code after unconditional jumps, jumps to the next label, and
    thread jumps to jumps."""
    # label aliasing: label followed directly by 'br X'
    alias = {}
    for k, i in enumerate(code):
        if i.op == "label":
            j = k + 1
            while j < len(code) and code[j].op == "label":
                j += 1
            if j < len(code) and code[j].op == "br" and code[j].label != i.label:
                alias[i.label] = code[j].label

    def A(l):
        seen = set()
        while l in alias and l not in seen:
            seen.add(l)
            l = alias[l]
        return l
    for i in code:
        if i.op in ("br", "bcc") and i.label in alias:
            i.label = A(i.label)
        if i.op == "jt":
            i.extra = [A(l) for l in i.extra]
    out = []
    dead = False
    for i in code:
        if i.op == "label":
            dead = False
        if dead:
            continue
        out.append(i)
        if i.op in ("br", "ret", "jt"):
            dead = True
    code = out
    # bcc L1; br L2; L1:  ->  b!cc L2; L1:
    from .ir import NEG_CC
    out = []
    n = len(code)
    k = 0
    while k < n:
        i = code[k]
        if i.op == "bcc" and k + 2 < n and code[k + 1].op == "br" and code[k + 2].op == "label" and \
                code[k + 2].label == i.label:
            out.append(Ins("bcc", a=i.a, b=i.b, cc=NEG_CC[i.cc], label=code[k + 1].label))
            k += 2
            continue
        out.append(i)
        k += 1
    code = out
    # br to immediately following label
    out = []
    for k, i in enumerate(code):
        if i.op in ("br", "bcc"):
            j = k + 1
            nxt = False
            while j < len(code) and code[j].op == "label":
                if code[j].label == i.label:
                    nxt = True
                    break
                j += 1
            if nxt:
                continue
        out.append(i)
    # drop unused labels
    used = set()
    for i in out:
        if i.op in ("br", "bcc"):
            used.add(i.label)
        if i.op == "jt":
            used.update(i.extra)
    return [i for i in out if not (i.op == "label" and i.label not in used and not i.label.endswith("_ret"))]


LOWBIT_OPS = {"add", "sub", "mul", "and", "or", "xor"}


def demanded_bits(code):
    """Replace 'ext' instructions whose result is only consumed through its low bits
    (by narrower exts, narrow stores, or low-bit arithmetic feeding those) with moves."""
    dem = {}
    users = {}
    for i in code:
        for u in i.uses():
            if u is not None and u >= VREG0:
                users.setdefault(u, []).append(i)
    changed = True
    for _ in range(20):
        changed = False
        for i in reversed(code):
            op = i.op
            if op == "ext":
                need = {i.a: i.sz}
            elif op == "st":
                need = {i.a: i.sz * 8, i.b: 128}
            elif op == "bin" and i.cc in LOWBIT_OPS:
                dd = dem.get(i.d, 0)
                need = {i.a: dd}
                if i.b is not None:
                    need[i.b] = max(need.get(i.b, 0), dd)
            elif op == "bin" and i.cc == "sll" and i.b is None:
                need = {i.a: max(0, dem.get(i.d, 0) - (i.imm & 127))}
            elif op == "mov":
                need = {i.a: dem.get(i.d, 0) if (i.d is not None and i.d >= VREG0) else 128}
            else:
                need = {u: 128 for u in i.uses() if u is not None}
            for u, b in need.items():
                if u is None or u < VREG0:
                    continue
                if b > dem.get(u, 0):
                    dem[u] = b
                    changed = True
        if not changed:
            break
    did = False
    for k, i in enumerate(code):
        if i.op == "ext" and i.d >= VREG0 and dem.get(i.d, 0) <= i.sz:
            code[k] = Ins("mov", d=i.d, a=i.a)
            did = True
    return did


def _sbits(v):
    """Smallest n with v == sext(low n bits of v) (v signed)."""
    return (v.bit_length() if v >= 0 else (~v).bit_length()) + 1


def value_widths(code):
    """Per-vreg value ranges as bit widths: uw[r] = n means 0 <= r < 2**n (unsigned 128-bit view),
    sw[r] = n means r is the sign extension of its low n bits.  A forward fixpoint over all
    definitions (a vreg's width is the max over its defs); widths that keep growing jump to 128."""
    uw, sw, bumps = {}, {}, {}

    def U(r):
        if r is None:
            return 128
        if r == ZERO:
            return 0
        return uw.get(r, 0) if r >= VREG0 else 128

    def S(r):
        if r is None:
            return 128
        if r == ZERO:
            return 1
        return sw.get(r, 1) if r >= VREG0 else 128

    def widths(i):
        op = i.op
        if op == "li":
            v = sx(i.imm & M128)
            return (v.bit_length() if v >= 0 else 128), _sbits(v)
        if op == "mov":
            if isinstance(i.extra, tuple) and i.extra[0] == "parm":
                b = i.extra[1]
                return (128, b) if i.extra[2] else (b, b + 1)
            return U(i.a), S(i.a)
        if op == "ld":
            b = 8 * i.sz
            if b >= 128:
                return 128, 128
            return (b, b + 1) if not i.sign else (128, b)
        if op == "ext":
            if not i.sign:
                u = min(i.sz, U(i.a))
                return u, min(128, u + 1)
            s = min(i.sz, S(i.a))
            return (U(i.a) if U(i.a) < i.sz else 128), s
        if op != "bin" or i.extra == "w32" and i.cc not in ("and", "or", "xor", "srl", "sra"):
            return 128, 128
        cc = i.cc
        if i.b is None:
            if i.imm is None:
                return 128, 128
            iv = sx(i.imm & M128)
            ub, sb = (iv.bit_length() if iv >= 0 else 128), _sbits(iv)
        else:
            ub, sb = U(i.b), S(i.b)
        ua, sa = U(i.a), S(i.a)
        if cc == "and":
            u = min(ua, ub)
            return u, min(max(sa, sb), u + 1)
        if cc in ("or", "xor"):
            u = max(ua, ub)
            return u, min(max(sa, sb), u + 1)
        if cc == "add":
            u = min(128, max(ua, ub) + 1)
            return u, min(128, max(sa, sb) + 1, u + 1)
        if cc == "sub":
            return 128, min(128, max(sa, sb) + 1)
        if cc == "mul":
            u = min(128, ua + ub)
            return u, min(128, sa + sb, u + 1)
        if cc in ("slt", "sltu", "seq"):
            return 1, 2
        if i.b is None and cc in ("srl", "sra", "sll"):
            k = i.imm & 127
            if cc == "srl":
                u = max(0, ua - k)
                return u, min(128, u + 1)
            if cc == "sra":
                s = max(1, sa - k)
                return (max(0, ua - k) if ua < 128 else 128), s
            if k == 0:
                return ua, sa
            u = min(128, ua + k)
            return u, min(128, sa + k, u + 1)
        return 128, 128

    for _ in range(64):
        changed = False
        for i in code:
            if i.d is None or i.d < VREG0 or i.op in ("st", "bcc", "br", "jt", "label", "ret"):
                continue
            u, s = widths(i)
            u, s = min(u, 128), min(s, 128)
            ou, os_ = uw.get(i.d), sw.get(i.d)
            nu = u if ou is None else max(ou, u)
            ns = s if os_ is None else max(os_, s)
            if (nu, ns) != (ou, os_):
                if ou is not None:
                    bumps[i.d] = bumps.get(i.d, 0) + 1
                    if bumps[i.d] > 4:
                        nu, ns = 128, 128
                uw[i.d], sw[i.d] = nu, ns
                changed = True
        if not changed:
            return uw, sw
    return None


def redundant_exts(code):
    """v6 value-range extension elimination: an `ext` (or an `and` with a low-bit mask) whose
    operand is already known to fit becomes a mov.  Default (non-purecap) code only."""
    if PURECAP:
        return code
    r = value_widths(code)
    if r is None:
        return code
    uw, sw = r

    def U(x):
        return 0 if x == ZERO else (uw.get(x, 0) if x is not None and x >= VREG0 else 128)

    def S(x):
        return 1 if x == ZERO else (sw.get(x, 1) if x is not None and x >= VREG0 else 128)

    for k, i in enumerate(code):
        if i.d is None or i.a is None:
            continue
        if i.op == "ext" and ((not i.sign and U(i.a) <= i.sz) or (i.sign and S(i.a) <= i.sz)):
            code[k] = Ins("mov", d=i.d, a=i.a)
        elif i.op == "bin" and i.cc == "and" and i.b is None and i.imm is not None:
            m = i.imm & M128
            if m and (m & (m + 1)) == 0 and U(i.a) <= m.bit_length():
                code[k] = Ins("mov", d=i.d, a=i.a)
    return code


def hoist_constants(code):
    """Loop-invariant constant hoisting: single-definition `li`/`la` temporaries inside a loop
    move to just before the loop header, and identical constants in one loop share one vreg.
    A loop is a backward branch at t to a label at h whose labels [h, t] are entered only from
    inside [h, t] (plus fall-through into h), so the inserted code dominates the whole loop."""
    changed = True
    rounds = 0
    while changed and rounds < 500:
        changed = False
        rounds += 1
        label_pos = {i.label: k for k, i in enumerate(code) if i.op == "label"}
        refs = {}
        for k, i in enumerate(code):
            if i.op in ("br", "bcc"):
                refs.setdefault(i.label, []).append(k)
            elif i.op == "jt":
                for l in i.extra:
                    refs.setdefault(l, []).append(k)
        loops = []
        for t, i in enumerate(code):
            if i.op in ("br", "bcc") and i.label in label_pos and label_pos[i.label] < t:
                loops.append((t - label_pos[i.label], label_pos[i.label], t))
        loops.sort()
        dc = def_counts(code)
        for _, h, t in loops:
            ok = True
            for k in range(h, t + 1):
                if code[k].op == "label" and any(not (h <= r <= t) for r in refs.get(code[k].label, [])):
                    ok = False
                    break
            if not ok:
                continue
            first = {}
            rename = {}
            hoist = []
            for k in range(h, t + 1):
                i = code[k]
                if i.op in ("li", "la") and i.d is not None and i.d >= VREG0 and dc.get(i.d) == 1:
                    key = (i.op, i.imm, i.sym)
                    if key in first:
                        rename[i.d] = first[key]
                    else:
                        first[key] = i.d
                        hoist.append(i)
                    code[k] = None
            if not hoist:
                continue
            body = [i for i in code[h:t + 1] if i is not None]
            code[:] = code[:h] + hoist + body + code[t + 1:]
            if rename:
                for i in code:
                    if i.a in rename:
                        i.a = rename[i.a]
                    if i.b in rename:
                        i.b = rename[i.b]
            changed = True
            break     # positions moved: recompute loops
    return code


LICM_BIN = {"add", "sub", "and", "or", "xor", "sll", "srl", "sra", "slt", "sltu", "seq", "mul",
            "min", "max", "minu", "maxu", "addw", "subw", "mulw", "sllw", "addwu", "subwu", "mulwu", "sllwu"}


def hoist_invariants(code):
    """v6 loop-invariant code motion: a single-definition pure, non-trapping instruction inside a
    loop whose operands are not written anywhere in the loop moves to the preheader (repeated,
    so chains of invariant ops move together).  Loops as in hoist_constants (the preheader
    position dominates the loop); hoisting is speculative, which is safe for these ops."""
    rounds = 0
    changed = True
    while changed and rounds < 200:
        changed = False
        rounds += 1
        label_pos = {i.label: k for k, i in enumerate(code) if i.op == "label"}
        refs = {}
        for k, i in enumerate(code):
            if i.op in ("br", "bcc"):
                refs.setdefault(i.label, []).append(k)
            elif i.op == "jt":
                for l in i.extra:
                    refs.setdefault(l, []).append(k)
        loops = []
        for t, i in enumerate(code):
            if i.op in ("br", "bcc") and i.label in label_pos and label_pos[i.label] < t:
                loops.append((t - label_pos[i.label], label_pos[i.label], t))
        loops.sort()
        dc = def_counts(code)
        for _, h, t in loops:
            if any(code[k].op == "label" and any(not (h <= r <= t) for r in refs.get(code[k].label, []))
                   for k in range(h, t + 1)):
                continue
            written = set()
            for k in range(h, t + 1):
                written.update(d for d in code[k].defs() if d is not None)
            hoist = []
            for k in range(h, t + 1):
                i = code[k]
                if i.d is None or i.d < VREG0 or dc.get(i.d) != 1:
                    continue
                if i.op == "bin":
                    if i.cc not in LICM_BIN:
                        continue
                elif i.op == "ext":
                    pass
                elif i.op == "faddr" and not PURECAP and i.sym != "INCOMING":
                    pass
                else:
                    continue
                srcs = [u for u in i.uses() if u is not None]
                if any((u != ZERO and u < VREG0) or u in written for u in srcs):
                    continue
                hoist.append(k)
                written.discard(i.d)
            if not hoist:
                continue
            moved = [code[k] for k in hoist]
            hs = set(hoist)
            body = [code[k] for k in range(h, t + 1) if k not in hs]
            code[:] = code[:h] + moved + body + code[t + 1:]
            changed = True
            break
    return code


RLE_KEEP = {"bin", "ext", "li", "la", "mov", "faddr", "bcc", "ld"}


def redundant_loads(code):
    """v6 redundant-load elimination over extended basic blocks (a conditional branch's
    fall-through continues the block; labels, jumps and returns end it): a non-volatile load
    of the same base/offset/size/signedness as an earlier one becomes a mov of that value.
    Stores, calls and any other op that may touch memory forget every load; redefining a
    base or a value register forgets the loads that mention it."""
    avail = {}

    def kill(r):
        for k in [k for k, v in avail.items() if k[0] == r or v == r]:
            del avail[k]

    for idx, i in enumerate(code):
        if i.op == "label":
            avail = {}
            continue
        if i.op not in RLE_KEEP:
            avail = {}
        if i.op == "ld" and i.extra != "vol" and i.a is not None and i.d is not None:
            key = (i.a, i.imm, i.sz, i.sign)
            v = avail.get(key)
            if v is not None and v != i.d:
                code[idx] = Ins("mov", d=i.d, a=v)
                kill(i.d)
                continue
            kill(i.d)
            if i.d != i.a:
                avail[key] = i.d
            continue
        for d in i.defs():
            if d is not None:
                kill(d)
        if i.op in ("br", "ret", "jt"):
            avail = {}
    return code


CSE_OPS = {"bin", "ext", "li", "la", "faddr"}


def local_cse(code):
    """Block-local common-subexpression elimination over pure ops. Only single-definition
    vregs take part, so the surviving definition dominates every use of the removed one and
    its uses can simply be renamed."""
    dc = def_counts(code)
    rename = {}
    avail = {}
    out = []
    for i in code:
        if i.op == "label" or i.op in ("br", "bcc", "ret", "jt", "call"):
            avail = {}
        if i.a in rename:
            i.a = rename[i.a]
        if i.b in rename:
            i.b = rename[i.b]
        if i.op in CSE_OPS and i.d is not None and i.d >= VREG0 and dc.get(i.d) == 1:
            key = (i.op, i.cc, i.a, i.b, i.imm, i.sym, i.sz, i.sign)
            if key in avail:
                rename[i.d] = avail[key]
                continue
            avail[key] = i.d
        if i.op == "call":
            avail = {}
        for d in i.defs():
            # a multiply-defined (or physical) register changed: drop expressions reading it
            if d is not None and (d < VREG0 or dc.get(d, 0) != 1):
                avail = {k: v for k, v in avail.items() if d not in (k[2], k[3])}
        out.append(i)
    for i in out:     # uses reached around a loop back edge precede the def textually
        if i.a in rename:
            i.a = rename[i.a]
        if i.b in rename:
            i.b = rename[i.b]
    return out


SCHED_MOVABLE = {"bin", "ext", "li", "la", "mov", "faddr"}
# purecap capability arithmetic can trap (sealed/sentry operand, bounds): never hoisted above a store, so a
# trap stays behind every side effect (MMIO output included) that precedes it in program order
CAP_TRAPPING = {"cadd", "csetbnd", "csetaddr", "candperm"}


def _regs(i):
    return ([u for u in i.uses() if u is not None], [d for d in i.defs() if d is not None])


def schedule_loads(code):
    """Load-use bubble filling (the pipeline stalls one cycle when an instruction needs the
    result of the load just before it): when `ld d` is directly followed by a reader of d,
    pull the nearest later independent pure instruction of the same block up between them.
    Never crosses labels, branches, calls or returns."""
    out = list(code)
    n = len(out)
    k = 0
    while k < n - 2:
        ld = out[k]
        if ld.op != "ld" or ld.d is None or ld.d not in _regs(out[k + 1])[0]:
            k += 1
            continue
        lu, ldf = _regs(ld)
        busy_def = set(ldf)          # defined between k and j: j may not read these
        busy_use = set(lu)           # read between k and j: j may not redefine these
        busy_def_all = set(ldf)      # j may not redefine anything defined in between either
        crossed_store = False
        for m in range(k + 1, min(n, k + 12)):
            c = out[m]
            if c.op in ("label", "br", "bcc", "ret", "jt", "call"):
                break
            cu, cd = _regs(c)
            if m > k + 1 and c.op in SCHED_MOVABLE and not (set(cu) & busy_def) \
                    and not (set(cd) & busy_use) and not (set(cd) & busy_def_all) \
                    and not (crossed_store and c.op == "bin" and c.cc in CAP_TRAPPING):
                out.insert(k + 1, out.pop(m))
                break
            busy_def.update(cd)
            busy_def_all.update(cd)
            busy_use.update(cu)
            crossed_store = crossed_store or c.op not in SCHED_MOVABLE and c.op != "ld"
        k += 1
    return out


# v5 32-bit word ops: op + ext(32) -> one word instruction whose result is already canonical.
# add/sub/mul and sll by an immediate < 32 only need the low 32 operand bits, so any such pair fuses;
# sll by a register and div need the C operation itself to be 32-bit (count < 32, operands canonical
# ints), which ir.FuncGen.arith marks with extra = "w32".
WORD_SIGNED = {"add": "addw", "sub": "subw", "mul": "mulw", "sll": "sllw", "div": "divw"}
WORD_UNSIGNED = {"add": "addwu", "sub": "subwu", "mul": "mulwu", "sll": "sllwu"}
BARRIER = {"label", "br", "bcc", "jt", "call", "ret"}


def fuse_word_ops(code):
    dc = def_counts(code)
    uc = use_counts(code)
    pos = {}
    out = list(code)
    for k, i in enumerate(code):
        if i.op == "bin" and i.d is not None and i.d >= VREG0 and dc.get(i.d) == 1:
            pos[i.d] = k
    dead = set()
    for k, e in enumerate(code):
        if e.op != "ext" or e.sz != 32 or e.a is None or e.a < VREG0 or uc.get(e.a) != 1 or e.a not in pos:
            continue
        j = pos[e.a]
        b = code[j]
        if j > k:
            continue
        table = WORD_SIGNED if e.sign else WORD_UNSIGNED
        w = table.get(b.cc)
        if w is None:
            continue
        if b.cc == "sll" and not (b.b is None and (b.imm & 127) < 32 or b.extra == "w32"):
            continue
        if b.cc == "div" and b.extra != "w32":
            continue
        if b.b is None and b.cc not in ("add", "sll"):
            continue        # no immediate form (mul/div/sub by constant keep the register operand)
        srcs = {b.a, b.b} - {None}
        if any(x.op in BARRIER or any(d in srcs for d in x.defs()) for x in code[j + 1:k]):
            continue        # operands must still hold their values at the ext
        out[k] = Ins("bin", d=e.d, a=b.a, b=b.b, imm=b.imm, cc=w)
        dead.add(j)
    return [i for k, i in enumerate(out) if k not in dead]
