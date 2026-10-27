"""Compilation driver: translation units -> assembly items, and a tiny 'linker' that
concatenates the start-up code, all reachable functions and data into one .s file for
tools/asm.py (which has no object format)."""
import os
import pickle
import re

from . import backend, inline, ir, opt
from .lexer import CompileError
from .parser import Parser
from .preproc import Preprocessor

HERE = os.path.dirname(os.path.abspath(__file__))
CC_DIR = os.path.dirname(HERE)
INCLUDE_DIR = os.path.join(CC_DIR, "include")
LIB_DIR = os.path.join(CC_DIR, "lib")
CACHE_DIR = os.path.join(CC_DIR, ".cache")

def inline_enabled():
    """-O inlines small static functions; TCC128_NO_INLINE=1 (or tcc128.py -fno-inline) turns it off."""
    return os.environ.get("TCC128_NO_INLINE", "") in ("", "0")


PC_FEATURES = ("subobject",)   # purecap hardening, each on by default; -fno-<feature> / TCC128_NO_<FEATURE>=1 turns it off


def pc_feature(name):
    return os.environ.get("TCC128_NO_" + name.upper(), "") in ("", "0")


def feature_key():
    return "".join(".no" + f for f in PC_FEATURES if not pc_feature(f))


def perf_key():
    """libc cache key part for TCC128_DISABLE (v6 perf passes switched off)."""
    d = os.environ.get("TCC128_DISABLE", "")
    return ".dis-" + d.replace(",", "-") if d else ""


SYM_RE = re.compile(r"\b(_[A-Za-z0-9_]+)\b")


class Item:
    """A function or data object: assembly lines and referenced symbols."""

    def __init__(self, name, kind, lines, refs, tentative=False, size=0, align=1):
        self.name, self.kind, self.lines, self.refs = name, kind, lines, refs
        self.caprelocs = []     # purecap: (offset, label, addend) of pointer slots initialised by crt0
        self.tentative, self.size, self.align = tentative, size, align


class Unit:
    def __init__(self, uid, purecap=False):
        self.uid = uid
        self.purecap = purecap
        self.fnid = 0
        self.items = []
        self.inline_stats = {}  # callee name -> call sites inlined


def compile_unit(path, uid, include_paths=(), defines=None, optimize=True, src=None, purecap=False):
    if purecap:
        defines = dict(defines or {}, __PURECAP__="1", __CHERI_PURE_CAPABILITY__="1")
    pp = Preprocessor([*include_paths, INCLUDE_DIR], defines)
    if src is None:
        toks = pp.preprocess_file(path)
    else:
        from .lexer import tokenize
        toks = pp.process(tokenize(src, path))
    p = Parser(toks, uid)
    objs = p.parse()
    unit = Unit(uid, purecap)
    seen = set()
    # IR for every function first, so small static functions can be inlined into their callers (-O)
    fgs = {}
    for o in objs:
        if id(o) in seen:
            continue
        seen.add(id(o))
        if o.is_func and o.body is not None:
            unit.fnid += 1
            fg = ir.FuncGen(o, unit)
            fg.own_fnid = unit.fnid
            fgs[id(o)] = fg.gen()
    if optimize and inline_enabled():
        by_name = {fg.fn.asm_name: fg for fg in fgs.values()}
        for fg in fgs.values():
            inline.inline_into(fg, by_name, unit.inline_stats)
    seen = set()
    for o in objs:
        if id(o) in seen:
            continue
        seen.add(id(o))
        if o.is_func:
            if o.body is None:
                continue
            fg = fgs[id(o)]
            code = fg.code
            if optimize:
                opt.PURECAP = purecap
                code = opt.fuse_word_ops(opt.schedule_loads(opt.hoist_constants(opt.optimize(opt.local_cse(opt.optimize(code))))))
            else:
                code = opt.jump_cleanup(code)
            alloc = backend.allocate(code)
            em = backend.Emitter(fg, code, alloc, o.asm_name)
            lines = em.emit()
            for tl, labels in fg.data:
                lines.append("        .align 16")
                lines.append(f"{tl}:")
                for l in labels:
                    lines.append(f"        .quad {l}")
            refs = set()
            for ln in lines:
                if ln.startswith(" "):
                    refs.update(SYM_RE.findall(ln))
            refs.discard(o.asm_name)
            unit.items.append(Item(o.asm_name, "func", lines, refs))
        else:
            if o.is_extern and not o.is_definition:
                continue
            if not o.is_definition:
                continue
            unit.items.append(data_item(o, purecap))
    return unit


def data_item(o, purecap=False):
    ty = o.ty
    size = max(ty.size, 1)
    align = max(ty.align, 1)
    lines = [f"        .align {align}", f"{o.asm_name}:"]
    refs = set()
    if o.init_data is None:
        lines.append(f"        .space {size}")
        return Item(o.asm_name, "data", lines, refs, tentative=not o.is_static, size=size, align=align)
    data, relocs = o.init_data
    relocs = sorted(relocs)
    pos = 0
    directive = {16: ".quad", 8: ".dword", 4: ".word", 2: ".half", 1: ".byte"}

    def emit_bytes(b):
        for k in range(0, len(b), 16):
            chunk = b[k:k + 16]
            if any(chunk):
                lines.append("        .byte " + ",".join(str(x) for x in chunk))
            else:
                lines.append(f"        .space {len(chunk)}")
    for off, label, addend, sz in relocs:
        emit_bytes(data[pos:off])
        expr = label + (f"+{addend}" if addend > 0 else (f"-{-addend}" if addend < 0 else ""))
        lines.append(f"        {directive[sz]} {expr}")
        refs.add(label)
        pos = off + sz
    emit_bytes(data[pos:])
    it = Item(o.asm_name, "data", lines, refs, size=size, align=align)
    if purecap:
        it.caprelocs = [(off, label, addend) for off, label, addend, sz in relocs if sz == 16]
    return it


def libc_units(include_paths=(), optimize=True, purecap=False):
    """Compile (and cache) the C runtime library."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    srcs = sorted(f for f in os.listdir(LIB_DIR) if f.endswith(".c"))
    units = []
    compiler_files = [os.path.join(HERE, f) for f in os.listdir(HERE) if f.endswith(".py")]
    newest_compiler = max(os.path.getmtime(f) for f in compiler_files)
    hdr = max([os.path.getmtime(os.path.join(INCLUDE_DIR, f)) for f in os.listdir(INCLUDE_DIR)] + [0])
    for k, f in enumerate(srcs):
        path = os.path.join(LIB_DIR, f)
        cache = os.path.join(CACHE_DIR, f + (".O" if optimize else ".O0") + (".pc" if purecap else "") + ("" if inline_enabled() else ".noinl") + (feature_key() if purecap else "") + perf_key() + ".pkl")
        if os.path.exists(cache) and os.path.getmtime(cache) > max(os.path.getmtime(path), newest_compiler, hdr):
            with open(cache, "rb") as fh:
                units.append(pickle.load(fh))
            continue
        u = compile_unit(path, 900 + k, include_paths, None, optimize, purecap=purecap)
        tmp = cache + f".{os.getpid()}.tmp"
        with open(tmp, "wb") as fh:
            pickle.dump(u, fh)
        os.replace(tmp, cache)
        units.append(u)
    return units


def link(units, entry="_main", purecap=False):
    crt0 = open(os.path.join(LIB_DIR, "crt0_purecap.s" if purecap else "crt0.s")).read()
    defs = {}
    for u in units:
        for it in u.items:
            prev = defs.get(it.name)
            if prev is not None:
                if it.tentative and prev.kind == "data":
                    if it.size > prev.size and prev.tentative:
                        defs[it.name] = it
                    continue
                if prev.tentative and it.kind == "data":
                    defs[it.name] = it
                    continue
                raise CompileError(f"multiple definition of '{it.name[1:]}'")
            defs[it.name] = it
    # reachability from the entry point and crt0 references
    roots = set(SYM_RE.findall(crt0)) | {entry}
    keep = set()
    work = [r for r in roots if r in defs]
    while work:
        s = work.pop()
        if s in keep:
            continue
        keep.add(s)
        for r in defs[s].refs:
            if r in defs and r not in keep:
                work.append(r)
    missing = set()
    for s in keep:
        for r in defs[s].refs:
            if r not in defs and not r.startswith("__L") and r != "__end" and r not in crt0_labels(crt0):
                missing.add(r)
    for r in roots:
        if r not in defs and r != "_start" and r.startswith("_") and not r.startswith("__"):
            if r not in crt0_labels(crt0):
                missing.add(r)
    if missing:
        raise CompileError("undefined reference(s): " + ", ".join(sorted(m[1:] for m in missing)))
    ordered = []
    for u in units:
        for it in u.items:
            if it.name in keep and defs[it.name] is it:
                ordered.append(it)
    out = [crt0, "# ---- text"]
    for it in ordered:
        if it.kind == "func":
            out.extend(it.lines)
    out.append("# ---- data")
    for it in ordered:
        if it.kind == "data":
            out.extend(it.lines)
    if purecap:
        # capability relocation table, walked by crt0_purecap.s: {slot, target, size, addend} per
        # initialised pointer slot; size = -1 marks a function (derived from the PCC, not gp)
        out.append("        .align 16")
        out.append("__cap_relocs:")
        for it in ordered:
            for off, label, addend in it.caprelocs:
                tgt = defs.get(label)
                size = -1 if tgt is not None and tgt.kind == "func" else (tgt.size if tgt is not None else 0)
                out.append(f"        .quad {it.name}+{off}, {label}, {size}, {addend}")
        out.append("__cap_relocs_end:")
    out.append("        .align 16")
    out.append("__end:")
    return "\n".join(out) + "\n"


def crt0_labels(src):
    return set(re.findall(r"^\s*([A-Za-z_][\w]*):", src, re.M))
