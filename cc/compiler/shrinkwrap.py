"""v6 shrink-wrapping: an early-exit path of a function that makes calls runs without the
prologue/epilogue.

The entry block E ends in a conditional branch.  For one successor S, the blocks R reachable
from the other successor without passing through S (the "fast region", together with E) must
contain no call, no frame access, no jump table and at least one ret, and must not be
reachable from S.  Then

  * every vreg live into S that E/R touch is renamed inside E/R, and a block P
    (`label P; mov v, v'...`) placed in front of S copies them back, so the fast region's
    values are not live across a call and get caller-saved registers;
  * branches from E/R to S go to P instead; the emitter puts the prologue at P and emits a
    bare `ret` for the returns of the fast region.

The emitter re-checks the regions on the final code and the register assignment (no vreg of
the fast region in a callee-saved register or a spill slot); if anything does not hold it
falls back to the ordinary entry prologue, which is always correct because the IR change
above is only a renaming plus copies.
"""
from .ir import FRAME, INCOMING, RA, SP, VREG0, Ins


def _fast_ok(i):
    if i.op in ("call", "jt", "faddr"):
        return False
    if i.op == "ld" and i.a in (FRAME, INCOMING, SP):
        return False
    if i.op == "st" and i.b in (FRAME, INCOMING, SP):
        return False
    regs = [r for r in i.uses() if r is not None] + [d for d in i.defs() if d is not None]
    return not any(r in (SP, RA, FRAME, INCOMING) for r in regs)


def _reach(start, stop):
    seen = set()
    todo = [start]
    while todo:
        b = todo.pop()
        if id(b) in seen or (stop is not None and b is stop):
            continue
        seen.add(id(b))
        todo.extend(b.succ)
    return seen


def prepare(code, fname):
    """Returns (code, prologue_label or None)."""
    from .backend import bits_of, build_blocks, liveness
    if not any(i.op == "call" for i in code):
        return code, None
    blocks = build_blocks(code)
    if len(blocks) < 3:
        return code, None
    liveness(code, blocks)
    E = blocks[0]
    if code[E.end].op != "bcc" or len(E.succ) != 2:
        return code, None
    byid = {id(b): b for b in blocks}
    for S, other in ((E.succ[0], E.succ[1]), (E.succ[1], E.succ[0])):
        if S is E or other is E or S is other:
            continue
        R = _reach(other, S)
        if id(E) in R:
            continue
        fast = R | {id(E)}
        SR = _reach(S, None)
        if SR & fast:
            continue
        ok = True
        has_ret = False
        for bid in fast:
            b = byid[bid]
            for k in range(b.start, b.end + 1):
                if not _fast_ok(code[k]):
                    ok = False
                    break
            if code[b.end].op == "ret":
                has_ret = True
        if not ok or not has_ret:
            continue
        new = _rewrite(code, blocks, E, S, fast, byid, fname)
        if new is not None:
            return new, f"__Lsw{fname}"
    return code, None


def _rewrite(code, blocks, E, S, fast, byid, fname):
    from .backend import bits_of
    nv = VREG0
    for i in code:
        for r in i.uses() + i.defs():
            if r is not None and r >= nv:
                nv = r + 1
    touched = set()
    for bid in fast:
        b = byid[bid]
        for k in range(b.start, b.end + 1):
            for r in code[k].uses() + code[k].defs():
                if r is not None and r >= VREG0:
                    touched.add(r)
    # every vreg the fast region touches gets a fast-only name (the region's values only leave it
    # through P), so no unrelated slow-path live range can force it into a callee-saved register
    ren = {}
    for v in sorted(touched):
        ren[v] = nv
        nv += 1
    live_s = {v + VREG0 for v in bits_of(S.live_in)}
    plabel = f"__Lsw{fname}"
    slabel = code[S.start].label if code[S.start].op == "label" else None
    fast_idx = set()
    for bid in fast:
        b = byid[bid]
        fast_idx.update(range(b.start, b.end + 1))
    prev = S.start - 1
    falls_in = prev >= 0 and code[prev].op not in ("br", "ret", "jt") and prev not in fast_idx
    if falls_in and slabel is None:
        return None
    for k in fast_idx:
        i = code[k]
        if i.a in ren:
            i.a = ren[i.a]
        if i.b in ren:
            i.b = ren[i.b]
        if i.d in ren and i.op in ("li", "la", "mov", "bin", "ext", "ld", "faddr"):
            i.d = ren[i.d]
        if slabel is not None and i.op in ("br", "bcc") and i.label == slabel:
            i.label = plabel
    pblock = [Ins("label", label=plabel)] + [Ins("mov", d=v, a=nvr) for v, nvr in sorted(ren.items()) if v in live_s]
    # place P right in front of S when nothing outside the fast region falls through into S;
    # otherwise at the end, jumping to S
    if not falls_in:
        return code[:S.start] + pblock + code[S.start:]
    return code + pblock + [Ins("br", label=slabel)]


def check(code, alloc, plabel):
    """Emitter-side validation on the final code: returns the set of instruction indices of the
    fast region (prologue-free), or None to fall back to the entry prologue."""
    from .backend import CALLEE_SAVED, build_blocks
    blocks = build_blocks(code)
    P = None
    for b in blocks:
        if code[b.start].op == "label" and code[b.start].label == plabel:
            P = b
    if P is None or P is blocks[0]:
        return None
    fast = _reach(blocks[0], P)
    slow = _reach(P, None)
    if fast & slow:
        return None
    idx = set()
    for b in blocks:
        if id(b) not in fast:
            continue
        for k in range(b.start, b.end + 1):
            i = code[k]
            if not _fast_ok(i):
                return None
            for r in i.uses() + i.defs():
                if r is not None and r >= VREG0:
                    if r in alloc.spill or r not in alloc.reg or alloc.reg[r] in CALLEE_SAVED:
                        return None
            idx.add(k)
    return idx
