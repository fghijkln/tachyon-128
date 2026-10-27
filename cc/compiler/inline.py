"""IR-level inlining of small static functions (-O only).

A callee is inlinable when it is a static, non-variadic function defined in the same unit with at most
NARGREG scalar parameters and a scalar/void return (no struct params/return, no stack arguments, no jump
tables), does not call itself, and its IR (after its own inlining) has at most MAX_INSNS instructions.

The call site produced by FuncGen.e_call is `mov a0..aN <- args; call sym; [mov r <- a0]`. The callee's
IR starts by moving its parameters out of a0..aN and ends with `label ret; ret` with the result in a0,
so inlining is a splice: the `call` instruction is replaced by the callee body with
  * callee vregs renamed to fresh caller vregs,
  * callee labels renamed per inlined instance,
  * callee frame objects (FRAME-relative ld/st/faddr) moved into a fresh slot of the caller's frame,
  * the final `ret` dropped (control falls through to the code after the call).
Copy propagation in opt.py then removes the a-register shuffles."""
from .ir import A0, FRAME, INCOMING, NARGREG, VREG0

MAX_INSNS = 40


def inlinable(fg):
    fn = fg.fn
    if not fn.is_static or fn.va_save or fn.name == "main" or fg.data or fg.sret is not None:
        return False
    if fn.ty.ret.is_struct() or len(fn.params) > NARGREG or any(p.ty.is_struct() for p in fn.params):
        return False
    code = fg.code
    if sum(1 for i in code if i.op != "label") > MAX_INSNS:
        return False
    if [k for k, i in enumerate(code) if i.op == "ret"] != [len(code) - 1]:
        return False
    for i in code:
        if i.op == "call" and i.sym == fn.asm_name:
            return False                # directly recursive
        for f in ("d", "a", "b"):
            v = getattr(i, f)
            if v == INCOMING:
                return False
            if v == FRAME and not ((i.op == "ld" and f == "a") or (i.op == "st" and f == "b")):
                return False
        if i.op == "faddr" and i.sym == "INCOMING":
            return False
    return True


def _copy(i):
    from .ir import Ins
    j = Ins(i.op)
    for s in Ins.__slots__:
        setattr(j, s, getattr(i, s))
    return j


def inline_into(caller, callees, stats=None):
    """Splice every call in caller.code to a function in callees (asm_name -> FuncGen) whose
    inlinable() holds. Returns the number of call sites inlined."""
    out = []
    n = 0
    pending_ret = [None]
    for i in caller.code:
        if pending_ret[0] is not None:
            if i.op == "mov" and i.a == A0:
                i = _copy(i)
                i.a = pending_ret[0]
            pending_ret[0] = None
        cg = callees.get(i.sym) if i.op == "call" and i.sym else None
        if cg is None or cg is caller or not inlinable(cg):
            out.append(i)
            continue
        n += 1
        tag = f"_i{caller.own_fnid}_{len(out)}"
        base = 0
        if cg.frame_size:
            base = caller.alloc_slot(cg.frame_size, 16)
            caller.slots.extend((so + base, sz) for so, sz in cg.slots)
        caller.out_area = max(caller.out_area, cg.out_area)
        # pass the arguments straight to the callee's parameter moves instead of through a0..aN
        amap = {}
        k = i.nargs
        tail = out[len(out) - k:] if k else []
        if k and len(tail) == k and all(t.op == "mov" and A0 <= t.d < A0 + k for t in tail) \
                and len({t.d for t in tail}) == k and all(t.a == 0 or t.a >= VREG0 for t in tail):
            amap = {t.d: t.a for t in tail}
            del out[len(out) - k:]
        body = cg.code[:-1]                  # drop the trailing ret
        pro = 0
        while pro < len(body) and body[pro].op in ("mov", "st") and body[pro].a in amap and \
                (body[pro].op == "mov" or body[pro].b == FRAME):
            pro += 1
        if amap and any(A0 <= r < A0 + NARGREG for j in body[pro:] for r in j.uses()
                        if not any(c.op == "call" for c in body[:body.index(j)])):
            out.extend(tail)                 # a0..aN read after the prologue: keep the plain splice
            amap, pro = {}, 0
        # return value: `mov a0, v; br ret` becomes `mov rr, v; br ret` when every return has that form
        rr = None
        rl = cg.retlabel
        brs = [x for x, j in enumerate(body) if j.op == "br" and j.label == rl]
        lab = [x for x, j in enumerate(body) if j.op == "label" and j.label == rl]
        if not cg.fn.ty.ret.is_void() and lab and lab[0] > 0 and body[lab[0] - 1].op == "br" and \
                all(x > 0 and body[x - 1].op == "mov" and body[x - 1].d == A0 for x in brs):
            rr = caller.vreg()
        ret_movs = {x - 1 for x in brs} if rr is not None else set()
        vmap = {}

        def rv(v):
            if v is None or not isinstance(v, int) or v < VREG0:
                return v
            if v not in vmap:
                vmap[v] = caller.vreg()
            return vmap[v]
        for x, ci in enumerate(body):
            j = _copy(ci)
            j.d, j.a, j.b = rv(j.d), rv(j.a), rv(j.b)
            if x < pro:
                j.a = amap[ci.a]
            if x in ret_movs:
                j.d = rr
            if j.label is not None:
                j.label = j.label + tag
            if j.op == "faddr" or (j.op == "ld" and ci.a == FRAME) or (j.op == "st" and ci.b == FRAME):
                j.imm += base
                if j.op == "faddr" and j.extra is not None:
                    j.extra += base
            out.append(j)
        if rr is not None:
            pending_ret[0] = rr
        if stats is not None:
            stats[cg.fn.name] = stats.get(cg.fn.name, 0) + 1
    caller.code = out
    if n:
        caller.has_call = any(i.op == "call" for i in out)
    return n
