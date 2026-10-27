"""Machine-independent IR clean-up: constant propagation into immediates, constant folding,
redundant-extension removal, copy propagation, retargeting and dead-code elimination."""
from .ir import VREG0, ZERO, Ins, fits14

M128 = (1 << 128) - 1
IMM_OPS = {"add", "and", "or", "xor", "slt", "sltu", "sll", "srl", "sra"}
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
    for _ in range(4):
        changed = False
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
                    if (i.cc in ("add", "or", "xor", "sll", "srl", "sra") and i.imm == 0):
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
