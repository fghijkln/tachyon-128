"""Recursive-descent C parser producing a typed AST (types are computed while parsing,
implicit conversions are inserted as explicit 'cast' nodes)."""
from . import ctype as T
from .ctype import (BOOL, CHAR, INT, INT128, LONG, UINT128, ULONG, VOID, Member, Type, align_to,
                    array_of, common_type, func_type, int_promote, pointer_to, wrap)
from .lexer import CompileError, Tok, convert_number, error_at, unescape


class Node:
    def __init__(self, kind, tok=None, ty=None, **kw):
        self.kind = kind
        self.tok = tok
        self.ty = ty
        self.__dict__.update(kw)

    def __repr__(self):
        return f"Node({self.kind},{self.ty})"


class Obj:
    def __init__(self, name, ty, is_local, tok=None):
        self.name = name
        self.ty = ty
        self.is_local = is_local
        self.tok = tok
        self.is_func = ty.is_func()
        self.is_static = False
        self.is_definition = False
        self.is_extern = False
        self.is_inline = False
        self.asm_name = None
        self.addr_taken = False
        self.volatile = False
        # globals
        self.init_data = None      # (bytes, relocs[(offset, label, addend)])
        # functions
        self.params = []
        self.locals = []
        self.body = None
        self.va_save = False
        self.referenced = False

    def __repr__(self):
        return f"Obj({self.name})"


class Init:
    def __init__(self, ty):
        self.ty = ty
        self.expr = None
        self.elems = None          # list for arrays, dict index->Init
        self.mem = None            # for union: chosen member index

    def child(self, i, ty):
        if self.elems is None:
            self.elems = {}
        if i not in self.elems:
            self.elems[i] = Init(ty)
        return self.elems[i]


class Scope:
    def __init__(self):
        self.vars = {}     # name -> ('var', Obj) | ('typedef', Type) | ('enum', value)
        self.tags = {}


ARITH_OPS = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod", "&": "band", "|": "bor",
             "^": "bxor", "<<": "shl", ">>": "shr"}

TYPE_KEYWORDS = {"void", "_Bool", "char", "short", "int", "long", "signed", "unsigned", "struct",
                 "union", "enum", "typedef", "static", "extern", "const", "volatile", "inline",
                 "register", "auto", "restrict", "_Noreturn", "__int128", "__int128_t", "__uint128_t",
                 "_Alignas", "float", "double", "_Thread_local", "__thread", "__builtin_va_list"}


# __builtin_cheri_<op>(ptr[, x]): argument count, result type (None = the pointer's type)
CHERI_BUILTINS = {"bounds_set": (2, None), "address_set": (2, None), "perms_and": (2, None),
                  "tag_get": (1, T.ULONG), "length_get": (1, T.UINT128), "base_get": (1, T.UINT128),
                  "perms_get": (1, T.ULONG)}


class Parser:
    def __init__(self, toks, unit_id=0):
        eof = Tok("eof", "<eof>", toks[-1].file if toks else "?", toks[-1].line if toks else 0)
        self.toks = toks + [eof]
        self.pos = 0
        self.scopes = [Scope()]
        self.globals = []
        self.cur_fn = None
        self.label_id = 0
        self.unit_id = unit_id
        self.str_id = 0
        self.brk = []          # stack of break labels
        self.cont = []         # stack of continue labels
        self.switches = []
        self.gotos = []
        self.labels = {}
        self.va_list_type = pointer_to(CHAR)
        self.builtin_typedefs()

    def builtin_typedefs(self):
        self.scopes[0].vars["__builtin_va_list"] = ("typedef", self.va_list_type)

    # ------------------------------------------------------------------ token helpers
    @property
    def tok(self):
        return self.toks[self.pos]

    def peek(self, k=1):
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.pos]
        if t.kind != "eof":
            self.pos += 1
        return t

    def is_(self, s):
        t = self.toks[self.pos]
        return t.text == s and t.kind in ("punct", "id")

    def consume(self, s):
        if self.is_(s):
            self.pos += 1
            return True
        return False

    def expect(self, s):
        if not self.is_(s):
            error_at(self.tok, f"expected '{s}'")
        return self.next()

    def expect_ident(self):
        t = self.tok
        if t.kind != "id":
            error_at(t, "expected identifier")
        self.pos += 1
        return t

    def new_label(self):
        self.label_id += 1
        return self.label_id

    # ------------------------------------------------------------------ scopes
    def enter(self):
        self.scopes.append(Scope())

    def leave(self):
        self.scopes.pop()

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s.vars:
                return s.vars[name]
        return None

    def lookup_tag(self, name):
        for s in reversed(self.scopes):
            if name in s.tags:
                return s.tags[name]
        return None

    def is_typename(self, t=None):
        t = t or self.tok
        if t.kind != "id":
            return False
        if t.text in TYPE_KEYWORDS:
            return True
        v = self.lookup(t.text)
        return v is not None and v[0] == "typedef"

    # ------------------------------------------------------------------ objects
    def new_lvar(self, name, ty, tok=None):
        o = Obj(name, ty, True, tok)
        self.scopes[-1].vars[name] = ("var", o)
        if self.cur_fn is not None:
            self.cur_fn.locals.append(o)
        return o

    def new_gvar(self, name, ty, tok=None, static=False):
        o = Obj(name, ty, False, tok)
        o.is_static = static
        o.asm_name = (f"_S{self.unit_id}_{name}" if static else "_" + name)
        self.scopes[0].vars[name] = ("var", o) if len(self.scopes) == 1 else self.scopes[0].vars.get(name, ("var", o))
        self.globals.append(o)
        return o

    def new_anon_gvar(self, ty):
        self.str_id += 1
        o = Obj(f".L{self.str_id}", ty, False)
        o.is_static = True
        o.is_definition = True
        o.asm_name = f"_A{self.unit_id}_{self.str_id}"
        self.globals.append(o)
        return o

    def new_string(self, data, ty):
        o = self.new_anon_gvar(ty)
        o.init_data = (bytes(data), [])
        o.is_string = True
        return o

    # ------------------------------------------------------------------ top level
    def parse(self):
        while self.tok.kind != "eof":
            if self.consume(";"):
                continue
            attr = {}
            base = self.declspec(attr)
            if attr.get("typedef"):
                self.parse_typedef(base)
                continue
            if self.is_(";"):
                self.next()
                continue
            ty, name = self.declarator(base)
            if ty.is_func():
                self.function(ty, name, attr)
                continue
            self.global_var(ty, name, base, attr)
        return self.globals

    def parse_typedef(self, base):
        first = True
        while not self.consume(";"):
            if not first:
                self.expect(",")
            first = False
            ty, name = self.declarator(base)
            if name is None:
                error_at(self.tok, "typedef name omitted")
            self.scopes[-1].vars[name.text] = ("typedef", ty)

    def global_var(self, ty, name, base, attr):
        first = True
        while True:
            if not first:
                ty, name = self.declarator(base)
            first = False
            if name is None:
                error_at(self.tok, "variable name omitted")
            if ty.is_func():
                self.declare_func(ty, name, attr)
            else:
                prev = self.scopes[0].vars.get(name.text)
                if prev and prev[0] == "var" and not prev[1].is_func:
                    o = prev[1]
                    if ty.is_array() and ty.length >= 0:
                        o.ty = ty
                else:
                    o = self.new_gvar(name.text, ty, name, attr.get("static", False))
                o.is_extern = attr.get("extern", False) and not o.is_definition
                if not attr.get("extern"):
                    o.is_definition = True
                if self.consume("="):
                    o.is_definition = True
                    o.is_extern = False
                    init = self.initializer(o.ty)
                    o.ty = init.ty
                    o.init_data = self.global_init(init, o.ty)
                elif o.is_definition and o.ty.is_array() and o.ty.length < 0:
                    o.ty = array_of(o.ty.base, 1)
            if self.consume(";"):
                return
            self.expect(",")

    def declare_func(self, ty, name, attr):
        prev = self.scopes[0].vars.get(name.text)
        if prev and prev[0] == "var" and prev[1].is_func:
            o = prev[1]
            if ty.params is not None:
                o.ty = ty
            if attr.get("static"):
                o.is_static = True
            return o
        o = Obj(name.text, ty, False, name)
        o.is_static = attr.get("static", False)
        o.asm_name = "_" + name.text if not o.is_static else f"_S{self.unit_id}_{name.text}"
        o.is_inline = attr.get("inline", False)
        self.scopes[0].vars[name.text] = ("var", o)
        if len(self.scopes) > 1:
            self.scopes[-1].vars[name.text] = ("var", o)
        self.globals.append(o)
        return o

    def function(self, ty, name, attr):
        o = self.declare_func(ty, name, attr)
        if self.consume(";"):
            return
        if self.is_(","):
            self.next()
            self.global_var(*self.declarator_after_func(attr))
            return
        if o.is_definition:
            error_at(name, f"redefinition of {name.text}")
        if getattr(ty, "kr", False) and self.is_typename():
            decl = {}
            while self.is_typename():
                base = self.declspec({})
                while True:
                    pty, pn = self.declarator(base)
                    if pty.is_array():
                        pty = pointer_to(pty.base)
                    decl[pn.text] = pty
                    if not self.consume(","):
                        break
                self.expect(";")
            ty.param_names = [(decl.get(n.text, t), n) for t, n in ty.param_names]
            ty.params = [t for t, n in ty.param_names]
        o.ty = ty
        o.is_definition = True
        self.cur_fn = o
        o.locals = []
        self.labels = {}
        self.gotos = []
        self.enter()
        o.params = []
        for i, (pty, pname) in enumerate(ty.param_names):
            nm = pname.text if pname else f".p{i}"
            p = self.new_lvar(nm, pty, pname)
            o.params.append(p)
        if ty.variadic:
            o.va_save = True
        self.expect("{")
        self.scopes[-1].vars["__func__"] = ("var", self.new_string(name.text.encode() + b"\0",
                                                                     array_of(CHAR, len(name.text) + 1)))
        o.body = self.compound_stmt()
        self.leave()
        for g, tk in self.gotos:
            if g not in self.labels:
                error_at(tk, f"label '{g}' used but not defined")
        o.label_map = self.labels
        self.cur_fn = None

    def declarator_after_func(self, attr):
        raise CompileError("unsupported: function definition followed by ','")

    # ------------------------------------------------------------------ declaration specifiers
    def declspec(self, attr=None):
        counts = {}
        ty = None
        const = volatile = False
        seen_any = False
        while self.is_typename():
            t = self.next()
            s = t.text
            seen_any = True
            if s in ("typedef", "static", "extern", "inline", "_Noreturn", "_Thread_local", "__thread"):
                if attr is None:
                    error_at(t, "storage class specifier not allowed here")
                attr[s] = True
                continue
            if s in ("register", "auto", "restrict"):
                continue
            if s == "const":
                const = True
                continue
            if s == "volatile":
                volatile = True
                continue
            if s == "_Alignas":
                self.expect("(")
                if self.is_typename():
                    a = self.typename().align
                else:
                    a = self.const_expr()
                self.expect(")")
                if attr is not None:
                    attr["align"] = a
                continue
            if s in ("struct", "union"):
                if ty is not None or counts:
                    error_at(t, "invalid type")
                ty = self.struct_decl(s)
                continue
            if s == "enum":
                if ty is not None or counts:
                    error_at(t, "invalid type")
                ty = self.enum_decl()
                continue
            if s in ("float", "double"):
                error_at(t, "floating point is not supported by tcc128")
            v = self.lookup(s)
            if v is not None and v[0] == "typedef" and s not in TYPE_KEYWORDS - {"__builtin_va_list"}:
                if ty is not None or counts:
                    # typedef name used as declarator name (e.g. redeclaration) -> stop
                    self.pos -= 1
                    break
                ty = v[1]
                continue
            if s == "__builtin_va_list":
                ty = self.va_list_type
                continue
            if s in ("__int128_t",):
                counts["__int128"] = 1
                continue
            if s == "__uint128_t":
                counts["__int128"] = 1
                counts["unsigned"] = 1
                continue
            counts[s] = counts.get(s, 0) + 1
        if not seen_any:
            error_at(self.tok, "expected type")
        if ty is None:
            ty = self.basic_type(counts)
        elif counts:
            error_at(self.tok, "invalid type combination")
        return T.qualified(ty, const, volatile)

    def basic_type(self, c):
        u = c.pop("unsigned", 0)
        s = c.pop("signed", 0)
        if u and s:
            raise CompileError(f"{self.tok.where()}: signed and unsigned")
        key = tuple(sorted(c.items()))
        if key == ():
            return T.UINT if u else T.INT
        if key == (("void", 1),):
            return VOID
        if key == (("_Bool", 1),):
            return BOOL
        if key == (("char", 1),):
            return T.UCHAR if u else T.CHAR
        if key in ((("short", 1),), (("int", 1), ("short", 1))):
            return T.USHORT if u else T.SHORT
        if key == (("int", 1),):
            return T.UINT if u else T.INT
        if key in ((("long", 1),), (("int", 1), ("long", 1))):
            return T.ULONG if u else T.LONG
        if key in ((("long", 2),), (("int", 1), ("long", 2))):
            return T.ULLONG if u else T.LLONG
        if key == (("__int128", 1),):
            return T.UINT128 if u else T.INT128
        error_at(self.tok, "invalid type specifier combination")

    def struct_decl(self, kind):
        tag = None
        if self.tok.kind == "id" and not self.is_("{"):
            tag = self.next().text
        if tag and not self.is_("{"):
            t = self.lookup_tag(tag)
            if t is not None and t.kind == kind:
                return t
            t = T.struct_type(kind)
            t.tag = tag
            self.scopes[-1].tags[tag] = t
            return t
        self.expect("{")
        if tag:
            t = self.scopes[-1].tags.get(tag)
            if t is None or t.kind != kind or t.members is not None:
                t = T.struct_type(kind)
                t.tag = tag
                self.scopes[-1].tags[tag] = t
        else:
            t = T.struct_type(kind)
        members = []
        while not self.consume("}"):
            attr = {}
            base = self.declspec(attr)
            if self.consume(";"):
                if base.is_struct():   # anonymous struct/union member
                    members.append(Member(None, base))
                continue
            first = True
            while not self.consume(";"):
                if not first:
                    self.expect(",")
                first = False
                if self.is_(":"):
                    mty, name = base, None
                else:
                    mty, name = self.declarator(base)
                bw = None
                if self.consume(":"):
                    bw = self.const_expr()
                    if not mty.is_integer():
                        error_at(self.tok, "bit-field must have integer type")
                m = Member(name.text if name else None, mty, 0, bw, 0, name)
                if attr.get("align"):
                    m.align = attr["align"]
                members.append(m)
        self.layout(t, members)
        return t

    def layout(self, t, members):
        if t.kind == "union":
            size, align = 0, 1
            for m in members:
                m.offset = 0
                if m.bit_width is not None:
                    m.bit_offset = 0
                size = max(size, m.ty.size)
                align = max(align, m.ty.align)
            t.size = align_to(size, align)
            t.align = align
        else:
            bitpos = 0        # absolute bit position
            align = 1
            for m in members:
                if m.bit_width is not None:
                    sz = m.ty.size
                    if m.bit_width == 0:
                        bitpos = align_to(bitpos, sz * 8)
                        continue
                    unit = (bitpos // (sz * 8)) * sz * 8
                    start = bitpos
                    if start + m.bit_width > unit + sz * 8:
                        unit = align_to(start, sz * 8)
                        start = unit
                    m.offset = unit // 8
                    m.bit_offset = start - unit
                    bitpos = start + m.bit_width
                    if m.name is not None:
                        align = max(align, m.ty.align)
                    continue
                a = getattr(m, "align", None) or m.ty.align
                off = align_to((bitpos + 7) // 8, a)
                m.offset = off
                if m.ty.is_array() and m.ty.length < 0:
                    m.ty = array_of(m.ty.base, 0)   # flexible array member
                bitpos = (off + m.ty.size) * 8
                align = max(align, a)
            off = (bitpos + 7) // 8
            t.size = align_to(off, align)
            t.align = align
        t.members = members

    def enum_decl(self):
        tag = None
        if self.tok.kind == "id":
            tag = self.next().text
        if tag and not self.is_("{"):
            t = self.lookup_tag(tag)
            if t is None:
                t = T.enum_type()
                t.tag = tag
                self.scopes[-1].tags[tag] = t
            return t
        self.expect("{")
        t = T.enum_type()
        t.tag = tag
        val = 0
        while not self.consume("}"):
            name = self.expect_ident()
            if self.consume("="):
                val = self.const_expr()
            self.scopes[-1].vars[name.text] = ("enum", val)
            val += 1
            if not self.is_("}"):
                self.expect(",")
        if tag:
            self.scopes[-1].tags[tag] = t
        return t

    # ------------------------------------------------------------------ declarators
    def pointers(self, ty):
        while self.consume("*"):
            ty = pointer_to(ty)
            while self.tok.text in ("const", "volatile", "restrict", "__restrict") and self.tok.kind == "id":
                q = self.next().text
                ty = T.qualified(ty, const=q == "const", volatile=q == "volatile")
        return ty

    def declarator(self, ty):
        ty = self.pointers(ty)
        if self.is_("(") and not self.is_typename(self.peek()) and not self.peek().text == ")":
            # nested declarator: parse it with a placeholder, then apply suffix
            self.next()
            start = self.pos
            depth = 1
            while depth:
                t = self.next()
                if t.kind == "eof":
                    error_at(t, "unbalanced parentheses")
                if t.text == "(":
                    depth += 1
                elif t.text == ")":
                    depth -= 1
            ty = self.type_suffix(ty)
            end = self.pos
            self.pos = start
            inner_ty, name = self.declarator(ty)
            self.expect(")")
            self.pos = end
            return inner_ty, name
        name = None
        if self.tok.kind == "id" and not (self.tok.text in TYPE_KEYWORDS):
            name = self.next()
        return self.type_suffix(ty), name

    def abstract_declarator(self, ty):
        ty = self.pointers(ty)
        if self.is_("(") and not self.is_typename(self.peek()) and self.peek().text != ")":
            self.next()
            start = self.pos
            depth = 1
            while depth:
                t = self.next()
                if t.text == "(":
                    depth += 1
                elif t.text == ")":
                    depth -= 1
            ty = self.type_suffix(ty)
            end = self.pos
            self.pos = start
            ty = self.abstract_declarator(ty)
            self.expect(")")
            self.pos = end
            return ty
        return self.type_suffix(ty)

    def typename(self):
        ty = self.declspec()
        return self.abstract_declarator(ty)

    def type_suffix(self, ty):
        if self.is_("("):
            self.next()
            return self.func_params(ty)
        if self.is_("["):
            self.next()
            while self.tok.text in ("static", "const", "restrict", "volatile"):
                self.next()
            if self.consume("]"):
                n = -1
            else:
                n = self.const_expr()
                self.expect("]")
            ty = self.type_suffix(ty)
            return array_of(ty, n)
        return ty

    def func_params(self, ret):
        params = []
        names = []
        variadic = False
        kr = False
        if self.is_("void") and self.peek().text == ")":
            self.next()
            self.next()
            f = func_type(ret, [], False)
            f.param_names = []
            return f
        if self.consume(")"):
            f = func_type(ret, None, False)   # unspecified (old style)
            f.param_names = []
            return f
        while not self.consume(")"):
            if params or variadic:
                self.expect(",")
            if self.consume("..."):
                variadic = True
                continue
            if not self.is_typename():
                # K&R identifier list: int unless a declaration list follows
                nm = self.expect_ident()
                params.append(INT)
                names.append((INT, nm))
                kr = True
                continue
            base = self.declspec({})
            pty, pname = self.declarator(base)
            if pty.is_array():
                pty = pointer_to(pty.base)
            elif pty.is_func():
                pty = pointer_to(pty)
            params.append(pty)
            names.append((pty, pname))
        f = func_type(ret, params, variadic)
        f.param_names = names
        f.kr = kr
        return f

    # ------------------------------------------------------------------ statements
    def compound_stmt(self):
        tok = self.tok
        stmts = []
        self.enter()
        while not self.consume("}"):
            if self.tok.kind == "eof":
                error_at(tok, "unterminated block")
            if self.is_typename() and self.peek().text != ":":
                stmts.extend(self.declaration())
            else:
                stmts.append(self.stmt())
        self.leave()
        return Node("block", tok, body=stmts)

    def declaration(self):
        attr = {}
        base = self.declspec(attr)
        out = []
        if attr.get("typedef"):
            self.parse_typedef(base)
            return out
        first = True
        while not self.consume(";"):
            if not first:
                self.expect(",")
            first = False
            ty, name = self.declarator(base)
            if name is None:
                if base.is_struct() or base.kind == "enum":
                    continue
                error_at(self.tok, "variable name omitted")
            if ty.is_func():
                self.declare_func(ty, name, attr)
                continue
            if ty.is_void():
                error_at(name, "variable declared void")
            if attr.get("extern"):
                g = self.scopes[0].vars.get(name.text)
                if g and g[0] == "var":
                    self.scopes[-1].vars[name.text] = g
                else:
                    o = Obj(name.text, ty, False, name)
                    o.asm_name = "_" + name.text
                    o.is_extern = True
                    self.globals.append(o)
                    self.scopes[-1].vars[name.text] = ("var", o)
                continue
            if attr.get("static"):
                o = Obj(name.text, ty, False, name)
                o.is_static = True
                o.is_definition = True
                self.str_id += 1
                o.asm_name = f"_L{self.unit_id}_{self.str_id}_{name.text}"
                self.globals.append(o)
                self.scopes[-1].vars[name.text] = ("var", o)
                if self.consume("="):
                    init = self.initializer(ty)
                    o.ty = init.ty
                    o.init_data = self.global_init(init, o.ty)
                continue
            v = self.new_lvar(name.text, ty, name)
            if ty.volatile:
                v.volatile = True
            if attr.get("align"):
                v.align = attr["align"]
            if self.consume("="):
                init = self.initializer(ty)
                v.ty = init.ty
                out.append(Node("init", name, var=v, init=init))
            elif ty.is_array() and ty.length < 0:
                error_at(name, "array size missing")
        return out

    def stmt(self):
        t = self.tok
        if t.kind == "id":
            s = t.text
            if s == "return":
                self.next()
                if self.consume(";"):
                    return Node("return", t, expr=None)
                e = self.expr()
                self.expect(";")
                rt = self.cur_fn.ty.ret
                if rt.is_void():
                    return Node("block", t, body=[Node("expr", t, expr=e), Node("return", t, expr=None)])
                if not rt.is_struct():
                    e = self.cast(e, rt)
                return Node("return", t, expr=e)
            if s == "if":
                self.next()
                self.expect("(")
                c = self.cond_expr_of(self.expr())
                self.expect(")")
                th = self.stmt()
                el = self.stmt() if self.consume("else") else None
                return Node("if", t, cond=c, then=th, els=el)
            if s == "while":
                self.next()
                self.expect("(")
                c = self.cond_expr_of(self.expr())
                self.expect(")")
                n = Node("for", t, init=None, cond=c, inc=None, brk=self.new_label(), cnt=self.new_label())
                self.brk.append(n.brk)
                self.cont.append(n.cnt)
                n.body = self.stmt()
                self.brk.pop()
                self.cont.pop()
                return n
            if s == "do":
                self.next()
                n = Node("do", t, brk=self.new_label(), cnt=self.new_label())
                self.brk.append(n.brk)
                self.cont.append(n.cnt)
                n.body = self.stmt()
                self.brk.pop()
                self.cont.pop()
                self.expect("while")
                self.expect("(")
                n.cond = self.cond_expr_of(self.expr())
                self.expect(")")
                self.expect(";")
                return n
            if s == "for":
                self.next()
                self.expect("(")
                self.enter()
                n = Node("for", t, brk=self.new_label(), cnt=self.new_label())
                if self.is_typename():
                    n.init = Node("block", t, body=self.declaration())
                elif self.consume(";"):
                    n.init = None
                else:
                    n.init = Node("expr", t, expr=self.expr())
                    self.expect(";")
                n.cond = None if self.is_(";") else self.cond_expr_of(self.expr())
                self.expect(";")
                n.inc = None if self.is_(")") else self.expr()
                self.expect(")")
                self.brk.append(n.brk)
                self.cont.append(n.cnt)
                n.body = self.stmt()
                self.brk.pop()
                self.cont.pop()
                self.leave()
                return n
            if s == "switch":
                self.next()
                self.expect("(")
                e = self.expr()
                self.expect(")")
                if not e.ty.is_integer():
                    error_at(t, "switch quantity not an integer")
                e = self.cast(e, int_promote(e.ty))
                n = Node("switch", t, cond=e, cases=[], default=None, brk=self.new_label())
                self.switches.append(n)
                self.brk.append(n.brk)
                n.body = self.stmt()
                self.brk.pop()
                self.switches.pop()
                return n
            if s == "case":
                self.next()
                if not self.switches:
                    error_at(t, "case outside switch")
                v = self.const_expr()
                hi = None
                if self.consume("..."):
                    hi = self.const_expr()
                self.expect(":")
                lbl = self.new_label()
                sw = self.switches[-1]
                v = wrap(v, sw.cond.ty)
                if hi is None:
                    sw.cases.append((v, v, lbl))
                else:
                    sw.cases.append((v, wrap(hi, sw.cond.ty), lbl))
                body = self.stmt() if not self.is_("}") else Node("block", t, body=[])
                return Node("label", t, label=lbl, body=body)
            if s == "default":
                self.next()
                self.expect(":")
                if not self.switches:
                    error_at(t, "default outside switch")
                lbl = self.new_label()
                self.switches[-1].default = lbl
                body = self.stmt() if not self.is_("}") else Node("block", t, body=[])
                return Node("label", t, label=lbl, body=body)
            if s == "break":
                self.next()
                self.expect(";")
                if not self.brk:
                    error_at(t, "break outside loop/switch")
                return Node("goto", t, label=self.brk[-1])
            if s == "continue":
                self.next()
                self.expect(";")
                if not self.cont:
                    error_at(t, "continue outside loop")
                return Node("goto", t, label=self.cont[-1])
            if s == "goto":
                self.next()
                nm = self.expect_ident()
                self.expect(";")
                self.gotos.append((nm.text, nm))
                if nm.text not in self.labels:
                    self.labels[nm.text] = self.new_label()
                return Node("goto", t, label=self.labels[nm.text])
            if self.peek().text == ":" and not self.is_typename():
                self.next()
                self.next()
                if t.text not in self.labels:
                    self.labels[t.text] = self.new_label()
                body = self.stmt() if not self.is_("}") else Node("block", t, body=[])
                return Node("label", t, label=self.labels[t.text], body=body)
        if self.is_("{"):
            self.next()
            return self.compound_stmt()
        if self.consume(";"):
            return Node("block", t, body=[])
        e = self.expr()
        self.expect(";")
        return Node("expr", t, expr=e)

    def cond_expr_of(self, e):
        e = self.decay(e)
        if not e.ty.is_scalar():
            error_at(e.tok, "used non-scalar value where a scalar is required")
        return e

    # ------------------------------------------------------------------ initializers
    def initializer(self, ty):
        init = Init(ty)
        self.init_rec(init, ty, True)
        return init

    def is_string_tok(self):
        return self.tok.kind == "str"

    def init_rec(self, init, ty, top=False):
        if ty.is_array() and ty.base.is_integer() and ty.base.size == 1 and \
                (self.is_string_tok() or (self.is_("{") and self.peek().kind == "str" and self.peek(2).text in ("}", ","))):
            brace = self.consume("{")
            data = self.string_data()
            if brace:
                self.consume(",")
                self.expect("}")
            if ty.length < 0:
                ty = array_of(ty.base, len(data))
                init.ty = ty
            init.elems = {}
            for i in range(min(ty.length, len(data))):
                c = Init(ty.base)
                c.expr = Node("num", None, ty=ty.base, val=wrap(data[i], ty.base))
                init.elems[i] = c
            return
        if ty.is_array():
            if self.consume("{"):
                self.array_init(init, ty, True)
            else:
                self.array_init(init, ty, False)
            return
        if ty.is_struct():
            if self.is_("{"):
                self.next()
                self.struct_init(init, ty, True)
                return
            # struct from expression
            e = self.assign()
            if e.ty.is_struct():
                init.expr = e
                return
            # brace elision
            self.pos -= 0
            init.expr = None
            self.struct_init_elided_first(init, ty, e)
            return
        # scalar
        if self.consume("{"):
            self.init_rec(init, ty)
            self.consume(",")
            self.expect("}")
            return
        e = self.assign()
        init.expr = self.cast(e, ty)

    def array_init(self, init, ty, braced):
        init.elems = init.elems or {}
        i = 0
        maxi = 0
        n = ty.length
        while True:
            if braced and self.consume("}"):
                break
            if not braced and (n >= 0 and i >= n or self.is_("}")):
                break
            if i > 0 or (not braced and False):
                pass
            if braced and self.is_("["):
                self.next()
                i = self.const_expr()
                self.expect("]")
                self.consume("=")
            if n >= 0 and i >= n:
                # excess elements: parse and discard
                self.init_rec(Init(ty.base), ty.base)
            else:
                c = init.child(i, ty.base)
                self.init_rec(c, ty.base)
            i += 1
            maxi = max(maxi, i)
            if braced:
                if not self.consume(","):
                    self.expect("}")
                    break
            else:
                if n >= 0 and i >= n:
                    break
                if not self.is_(","):
                    break
                if self.peek().text == "}":
                    break
                self.next()
        if ty.length < 0:
            ty = array_of(ty.base, maxi)
            init.ty = ty

    def struct_members(self, ty):
        return [m for m in ty.members]

    def struct_init(self, init, ty, braced):
        mems = ty.members
        init.elems = init.elems or {}
        i = 0
        while True:
            if braced and self.consume("}"):
                break
            if self.is_(".") and self.peek().kind == "id":
                self.next()
                nm = self.expect_ident().text
                for k, m in enumerate(mems):
                    if m.name == nm:
                        i = k
                        break
                else:
                    # member of anonymous struct
                    error_at(self.tok, f"no member named '{nm}'")
                self.consume("=")
            if i >= len(mems):
                self.init_rec(Init(INT), INT)   # excess: discard
            else:
                m = mems[i]
                while m.name is None and m.bit_width is not None and i + 1 < len(mems):
                    i += 1
                    m = mems[i]
                c = init.child(i, m.ty)
                if ty.kind == "union":
                    init.mem = i
                    init.elems = {i: c}
                self.init_rec(c, m.ty)
            i += 1
            if ty.kind == "union" and not braced:
                break
            if braced:
                if not self.consume(","):
                    self.expect("}")
                    break
            else:
                if i >= len(mems) or not self.is_(",") or self.peek().text == "}":
                    break
                self.next()

    def struct_init_elided_first(self, init, ty, first_expr):
        # brace elision inside an aggregate: first scalar already parsed
        mems = ty.members
        init.elems = {}
        m = mems[0]
        c = init.child(0, m.ty)
        if m.ty.is_scalar():
            c.expr = self.cast(first_expr, m.ty)
        else:
            error_at(self.tok, "complex brace elision not supported")
        if ty.kind == "union":
            init.mem = 0
            return
        i = 1
        while i < len(mems) and self.is_(",") and self.peek().text != "}" and self.peek().text != ".":
            self.next()
            c = init.child(i, mems[i].ty)
            self.init_rec(c, mems[i].ty)
            i += 1

    # -------------------------------------------------- global initializer evaluation
    def global_init(self, init, ty):
        buf = bytearray(ty.size)
        relocs = []
        self.write_ginit(init, ty, buf, 0, relocs)
        return (bytes(buf), relocs)

    def write_ginit(self, init, ty, buf, off, relocs):
        if init.expr is not None and not (ty.is_array()):
            e = init.expr
            if ty.is_struct():
                # struct copied from a constant compound/other global: not supported
                error_at(e.tok, "initializer element is not constant")
            val, label = self.eval_reloc(e)
            if label is not None:
                relocs.append((off, label, val, ty.size))
                return
            v = val & ((1 << (8 * ty.size)) - 1)
            buf[off:off + ty.size] = v.to_bytes(ty.size, "little")
            return
        if init.elems is None:
            return
        if ty.is_array():
            for i, c in init.elems.items():
                self.write_ginit(c, ty.base, buf, off + i * ty.base.size, relocs)
            return
        if ty.is_struct():
            for i, c in init.elems.items():
                m = ty.members[i]
                if m.bit_width is not None:
                    val, label = self.eval_reloc(c.expr)
                    sz = m.ty.size
                    cur = int.from_bytes(buf[off + m.offset:off + m.offset + sz], "little")
                    mask = ((1 << m.bit_width) - 1) << m.bit_offset
                    cur = (cur & ~mask) | ((val << m.bit_offset) & mask)
                    buf[off + m.offset:off + m.offset + sz] = cur.to_bytes(sz, "little")
                    continue
                self.write_ginit(c, m.ty, buf, off + m.offset, relocs)

    def eval_reloc(self, e):
        """Evaluate a constant initializer: returns (value, None) or (addend, label)."""
        k = e.kind
        if k == "num":
            return e.val, None
        if k == "cast":
            v, l = self.eval_reloc(e.lhs)
            if l is None:
                return wrap(v, e.ty), None
            return v, l
        if k == "addr":
            return self.eval_addr(e.lhs)
        if k in ("add", "sub") and e.ty.is_ptr():
            v, l = self.eval_reloc(e.lhs)
            r, l2 = self.eval_reloc(e.rhs)
            if l2 is not None:
                error_at(e.tok, "initializer element is not constant")
            return (v + r if k == "add" else v - r), l
        if k == "var" and (e.ty.is_array() or e.ty.is_func()):
            return 0, e.var.asm_name
        if k == "comma":
            return self.eval_reloc(e.rhs)
        try:
            return self.eval(e), None
        except CompileError:
            error_at(e.tok, "initializer element is not constant")

    def eval_addr(self, e):
        k = e.kind
        if k == "var":
            if e.var.is_local:
                error_at(e.tok, "initializer element is not constant")
            e.var.referenced = True
            return 0, e.var.asm_name
        if k == "deref":
            return self.eval_reloc(e.lhs)
        if k == "member":
            v, l = self.eval_addr(e.lhs)
            return v + e.mem.offset, l
        if k == "cliteral":
            return 0, e.var.asm_name
        error_at(e.tok, "initializer element is not constant")

    # ------------------------------------------------------------------ constant expressions
    def const_expr(self):
        e = self.conditional()
        return self.eval(e)

    def eval(self, e):
        k = e.kind
        if k == "num":
            return e.val
        if k == "cast":
            return wrap(self.eval(e.lhs), e.ty)
        if k in ("add", "sub", "mul", "div", "mod", "band", "bor", "bxor", "shl", "shr"):
            a, b = self.eval(e.lhs), self.eval(e.rhs)
            return fold_binary(k, a, b, e.ty, e.tok)
        if k in ("eq", "ne", "lt", "le"):
            a, b = self.eval(e.lhs), self.eval(e.rhs)
            return int({"eq": a == b, "ne": a != b, "lt": a < b, "le": a <= b}[k])
        if k == "logand":
            return int(bool(self.eval(e.lhs)) and bool(self.eval(e.rhs)))
        if k == "logor":
            return int(bool(self.eval(e.lhs)) or bool(self.eval(e.rhs)))
        if k == "cond":
            return self.eval(e.then) if self.eval(e.cond) else self.eval(e.els)
        if k == "neg":
            return wrap(-self.eval(e.lhs), e.ty)
        if k == "bnot":
            return wrap(~self.eval(e.lhs), e.ty)
        if k == "lnot":
            return int(not self.eval(e.lhs))
        if k == "comma":
            return self.eval(e.rhs)
        if k == "addr":
            return wrap(self.const_addr(e.lhs), e.ty)
        error_at(e.tok, "not a compile-time constant")

    def const_addr(self, e):
        if e.kind == "member":
            return self.const_addr(e.lhs) + e.mem.offset
        if e.kind == "deref":
            return self.eval(e.lhs)
        error_at(e.tok, "not a compile-time constant")

    # ------------------------------------------------------------------ expressions
    def expr(self):
        e = self.assign()
        while self.is_(","):
            t = self.next()
            r = self.assign()
            r2 = self.decay(r)
            e = Node("comma", t, ty=r2.ty, lhs=e, rhs=r2)
        return e

    def is_lvalue(self, e):
        return e.kind in ("var", "deref", "member", "cliteral") and not (e.kind == "var" and e.ty.is_func())

    def assign(self):
        lhs = self.conditional()
        t = self.tok
        if t.kind == "punct" and t.text == "=":
            self.next()
            rhs = self.assign()
            return self.new_assign(lhs, rhs, t)
        if t.kind == "punct" and t.text.endswith("=") and t.text[:-1] in ARITH_OPS:
            self.next()
            rhs = self.decay(self.assign())
            return self.new_opassign(ARITH_OPS[t.text[:-1]], lhs, rhs, t)
        return lhs

    def new_assign(self, lhs, rhs, t):
        if not self.is_lvalue(lhs):
            error_at(t, "lvalue required as left operand of assignment")
        if lhs.ty.is_array():
            error_at(t, "assignment to array")
        self.mark_written(lhs)
        rhs = self.decay(rhs)
        if lhs.ty.is_struct():
            if not rhs.ty.is_struct():
                error_at(t, "incompatible types in struct assignment")
            return Node("assign", t, ty=lhs.ty, lhs=lhs, rhs=rhs)
        return Node("assign", t, ty=lhs.ty, lhs=lhs, rhs=self.cast(rhs, lhs.ty))

    def mark_written(self, lhs):
        pass

    def new_opassign(self, op, lhs, rhs, t):
        if not self.is_lvalue(lhs):
            error_at(t, "lvalue required for compound assignment")
        lt = lhs.ty
        if lt.is_ptr() and op in ("add", "sub"):
            if not rhs.ty.is_integer():
                error_at(t, "invalid pointer compound assignment")
            sz = max(lt.base.size, 1) if not lt.base.is_void() else 1
            r = self.cast(rhs, T.INT128 if rhs.ty.is_signed() else T.UINT128)
            r = Node("mul", t, ty=lt, lhs=self.cast(r, lt), rhs=Node("num", t, ty=lt, val=sz))
            return Node("opassign", t, ty=lt, op=op, lhs=lhs, rhs=r, opty=lt)
        if not lt.is_integer() or not rhs.ty.is_integer():
            error_at(t, "invalid operands to compound assignment")
        if op in ("shl", "shr"):
            opty = int_promote(lt)
            r = self.cast(rhs, int_promote(rhs.ty))
        else:
            opty = common_type(lt, rhs.ty)
            r = self.cast(rhs, opty)
        return Node("opassign", t, ty=lt, op=op, lhs=lhs, rhs=r, opty=opty)

    def conditional(self):
        c = self.logor()
        if not self.is_("?"):
            return c
        t = self.next()
        c = self.cond_expr_of(c)
        if self.is_(":"):   # GNU a ?: b
            self.next()
            els = self.decay(self.conditional())
            then = c
        else:
            then = self.decay(self.expr())
            self.expect(":")
            els = self.decay(self.conditional())
        if then.ty.is_void() or els.ty.is_void():
            ty = VOID
        elif then.ty.is_struct():
            ty = then.ty
        elif then.ty.is_ptr() or els.ty.is_ptr():
            ty = then.ty if then.ty.is_ptr() else els.ty
            if then.ty.is_ptr() and els.ty.is_ptr() and then.ty.base.is_void():
                ty = els.ty if not els.ty.base.is_void() else then.ty
            then = self.cast(then, ty)
            els = self.cast(els, ty)
        else:
            ty = common_type(then.ty, els.ty)
            then = self.cast(then, ty)
            els = self.cast(els, ty)
        if c.kind == "num" and then.kind == "num" and els.kind == "num":
            return then if c.val else els
        return Node("cond", t, ty=ty, cond=c, then=then, els=els)

    def logor(self):
        e = self.logand()
        while self.is_("||"):
            t = self.next()
            r = self.cond_expr_of(self.logand())
            e = self.cond_expr_of(e)
            e = self.fold(Node("logor", t, ty=INT, lhs=e, rhs=r))
        return e

    def logand(self):
        e = self.bitor()
        while self.is_("&&"):
            t = self.next()
            r = self.cond_expr_of(self.bitor())
            e = self.cond_expr_of(e)
            e = self.fold(Node("logand", t, ty=INT, lhs=e, rhs=r))
        return e

    def bitor(self):
        e = self.bitxor()
        while self.is_("|"):
            t = self.next()
            e = self.new_arith("bor", e, self.bitxor(), t)
        return e

    def bitxor(self):
        e = self.bitand()
        while self.is_("^"):
            t = self.next()
            e = self.new_arith("bxor", e, self.bitand(), t)
        return e

    def bitand(self):
        e = self.equality()
        while self.is_("&"):
            t = self.next()
            e = self.new_arith("band", e, self.equality(), t)
        return e

    def equality(self):
        e = self.relational()
        while self.is_("==") or self.is_("!="):
            t = self.next()
            e = self.new_cmp("eq" if t.text == "==" else "ne", e, self.relational(), t)
        return e

    def relational(self):
        e = self.shift()
        while True:
            t = self.tok
            if t.kind == "punct" and t.text in ("<", "<=", ">", ">="):
                self.next()
                r = self.shift()
                if t.text == "<":
                    e = self.new_cmp("lt", e, r, t)
                elif t.text == "<=":
                    e = self.new_cmp("le", e, r, t)
                elif t.text == ">":
                    e = self.new_cmp("lt", r, e, t)
                else:
                    e = self.new_cmp("le", r, e, t)
            else:
                return e

    def shift(self):
        e = self.add()
        while self.is_("<<") or self.is_(">>"):
            t = self.next()
            r = self.add()
            e = self.new_arith("shl" if t.text == "<<" else "shr", e, r, t)
        return e

    def add(self):
        e = self.mul()
        while self.is_("+") or self.is_("-"):
            t = self.next()
            r = self.mul()
            e = self.new_add(e, r, t) if t.text == "+" else self.new_sub(e, r, t)
        return e

    def mul(self):
        e = self.cast_expr()
        while self.is_("*") or self.is_("/") or self.is_("%"):
            t = self.next()
            e = self.new_arith({"*": "mul", "/": "div", "%": "mod"}[t.text], e, self.cast_expr(), t)
        return e

    # --------------------------------------------------- node constructors with typing
    def decay(self, e):
        if e.ty is None:
            return e
        if e.ty.is_array():
            return Node("addr", e.tok, ty=pointer_to(e.ty.base), lhs=e)
        if e.ty.is_func():
            return Node("addr", e.tok, ty=pointer_to(e.ty), lhs=e)
        return e

    def cast(self, e, ty):
        e = self.decay(e)
        if e.ty is ty:
            return e
        if ty.is_void():
            return Node("cast", e.tok, ty=VOID, lhs=e)
        if e.ty.is_struct() or ty.is_struct():
            if e.ty.is_struct() and ty.is_struct():
                return e
            error_at(e.tok, f"cannot convert {T.type_name(e.ty)} to {T.type_name(ty)}")
        if e.ty.is_void():
            error_at(e.tok, "void value not ignored as it ought to be")
        ty = T.unqual(ty)
        if e.kind == "num" and ty.is_scalar():
            return Node("num", e.tok, ty=ty, val=wrap(e.val, ty))
        if e.ty.kind == ty.kind and e.ty.unsigned == ty.unsigned and e.ty.size == ty.size and ty.kind != "ptr":
            n = Node("cast", e.tok, ty=ty, lhs=e)
            return n
        return Node("cast", e.tok, ty=ty, lhs=e)

    def fold(self, n):
        try:
            if n.kind in ("logand", "logor"):
                if n.lhs.kind == "num" and n.rhs.kind == "num":
                    return Node("num", n.tok, ty=n.ty, val=self.eval(n))
                return n
            if n.lhs.kind == "num" and (getattr(n, "rhs", None) is None or n.rhs.kind == "num"):
                if n.ty.is_scalar() and not n.ty.is_ptr():
                    return Node("num", n.tok, ty=n.ty, val=self.eval(n))
        except CompileError:
            pass
        return n

    def new_arith(self, op, a, b, t):
        a, b = self.decay(a), self.decay(b)
        if not a.ty.is_integer() or not b.ty.is_integer():
            error_at(t, f"invalid operands to binary operator ({T.type_name(a.ty)}, {T.type_name(b.ty)})")
        if op in ("shl", "shr"):
            ty = int_promote(a.ty)
            return self.fold(Node(op, t, ty=ty, lhs=self.cast(a, ty), rhs=self.cast(b, int_promote(b.ty))))
        ty = common_type(a.ty, b.ty)
        return self.fold(Node(op, t, ty=ty, lhs=self.cast(a, ty), rhs=self.cast(b, ty)))

    def new_cmp(self, op, a, b, t):
        a, b = self.decay(a), self.decay(b)
        if a.ty.is_ptr() or b.ty.is_ptr():
            pt = a.ty if a.ty.is_ptr() else b.ty
            a2 = self.cast(a, pt)
            b2 = self.cast(b, pt)
            n = Node(op, t, ty=INT, lhs=a2, rhs=b2)
            n.cmpty = pt
            return self.fold(n)
        if not a.ty.is_integer() or not b.ty.is_integer():
            error_at(t, "invalid operands to comparison")
        ty = common_type(a.ty, b.ty)
        n = Node(op, t, ty=INT, lhs=self.cast(a, ty), rhs=self.cast(b, ty))
        n.cmpty = ty
        return self.fold(n)

    def new_add(self, a, b, t):
        a, b = self.decay(a), self.decay(b)
        if a.ty.is_integer() and b.ty.is_integer():
            return self.new_arith("add", a, b, t)
        if a.ty.is_integer() and b.ty.is_ptr():
            a, b = b, a
        if not (a.ty.is_ptr() and b.ty.is_integer()):
            error_at(t, "invalid operands to binary +")
        return self.ptr_offset("add", a, b, t)

    def ptr_offset(self, op, p, i, t):
        sz = p.ty.base.size if not p.ty.base.is_void() and not p.ty.base.is_func() else 1
        it = T.INT128 if i.ty.is_signed() else T.UINT128
        if i.kind == "num":
            off = Node("num", t, ty=p.ty, val=wrap(i.val * sz, p.ty))
        else:
            ic = self.cast(self.cast(i, it), p.ty)
            off = ic if sz == 1 else Node("mul", t, ty=p.ty, lhs=ic, rhs=Node("num", t, ty=p.ty, val=sz))
        return Node(op, t, ty=p.ty, lhs=p, rhs=off)

    def new_sub(self, a, b, t):
        a, b = self.decay(a), self.decay(b)
        if a.ty.is_integer() and b.ty.is_integer():
            return self.new_arith("sub", a, b, t)
        if a.ty.is_ptr() and b.ty.is_integer():
            return self.ptr_offset("sub", a, b, t)
        if a.ty.is_ptr() and b.ty.is_ptr():
            sz = a.ty.base.size if not a.ty.base.is_void() else 1
            d = Node("sub", t, ty=T.INT128, lhs=self.cast(a, T.INT128), rhs=self.cast(b, T.INT128))
            if sz != 1:
                d = Node("div", t, ty=T.INT128, lhs=d, rhs=Node("num", t, ty=T.INT128, val=sz))
            return self.cast(d, T.PTRDIFF_T)
        error_at(t, "invalid operands to binary -")

    # ------------------------------------------------------------------ unary / casts
    def cast_expr(self):
        if self.is_("(") and self.is_typename(self.peek()):
            start = self.pos
            t = self.next()
            ty = self.typename()
            self.expect(")")
            if self.is_("{"):
                # compound literal
                self.pos = start
                return self.unary()
            e = self.cast_expr()
            if ty.is_struct():
                error_at(t, "cast to struct type")
            return self.fold_cast(self.cast(e, ty))
        return self.unary()

    def fold_cast(self, e):
        return e

    def unary(self):
        t = self.tok
        if t.kind == "punct":
            s = t.text
            if s == "+":
                self.next()
                e = self.decay(self.cast_expr())
                return self.cast(e, int_promote(e.ty)) if e.ty.is_integer() else e
            if s == "-":
                self.next()
                e = self.decay(self.cast_expr())
                if not e.ty.is_integer():
                    error_at(t, "wrong type argument to unary minus")
                ty = int_promote(e.ty)
                return self.fold(Node("neg", t, ty=ty, lhs=self.cast(e, ty)))
            if s == "~":
                self.next()
                e = self.decay(self.cast_expr())
                if not e.ty.is_integer():
                    error_at(t, "wrong type argument to bit-complement")
                ty = int_promote(e.ty)
                return self.fold(Node("bnot", t, ty=ty, lhs=self.cast(e, ty)))
            if s == "!":
                self.next()
                e = self.cond_expr_of(self.cast_expr())
                return self.fold(Node("lnot", t, ty=INT, lhs=e))
            if s == "&":
                self.next()
                e = self.cast_expr()
                if e.kind == "member" and e.mem.bit_width is not None:
                    error_at(t, "cannot take address of bit-field")
                if not (self.is_lvalue(e) or e.ty.is_func()):
                    error_at(t, "lvalue required as unary '&' operand")
                self.mark_addr(e)
                return Node("addr", t, ty=pointer_to(e.ty), lhs=e)
            if s == "*":
                self.next()
                e = self.decay(self.cast_expr())
                if not e.ty.is_ptr():
                    error_at(t, "invalid type argument of unary '*'")
                if e.ty.base.is_func():
                    return e
                if e.ty.base.is_void():
                    return Node("deref", t, ty=VOID, lhs=e)
                return Node("deref", t, ty=e.ty.base, lhs=e)
            if s in ("++", "--"):
                self.next()
                e = self.unary()
                return self.new_incdec(e, 1 if s == "++" else -1, False, t)
        if t.kind == "id":
            if t.text == "sizeof":
                self.next()
                if self.is_("(") and self.is_typename(self.peek()):
                    self.next()
                    ty = self.typename()
                    self.expect(")")
                    if self.is_("{"):
                        # sizeof (T){...}
                        self.pos -= 1
                        while self.toks[self.pos].text != "(":
                            self.pos -= 1
                        e = self.unary()
                        return Node("num", t, ty=T.SIZE_T, val=e.ty.size)
                else:
                    e = self.unary()
                    ty = e.ty
                if ty.is_void() or ty.is_func():
                    return Node("num", t, ty=T.SIZE_T, val=1)
                if ty.is_array() and ty.length < 0:
                    error_at(t, "sizeof incomplete array")
                if ty.is_struct() and ty.members is None:
                    error_at(t, "sizeof incomplete struct")
                return Node("num", t, ty=T.SIZE_T, val=ty.size)
            if t.text in ("_Alignof", "__alignof__", "__alignof"):
                self.next()
                self.expect("(")
                if self.is_typename():
                    ty = self.typename()
                else:
                    ty = self.expr().ty
                self.expect(")")
                return Node("num", t, ty=T.SIZE_T, val=ty.align)
        return self.postfix()

    def mark_addr(self, e):
        if e.kind == "var" and e.var.is_local:
            e.var.addr_taken = True
        elif e.kind == "member":
            self.mark_addr(e.lhs)
        elif e.kind == "cliteral":
            e.var.addr_taken = True

    def new_incdec(self, e, d, post, t):
        if not self.is_lvalue(e):
            error_at(t, "lvalue required for increment/decrement")
        if e.ty.is_ptr():
            sz = e.ty.base.size if not e.ty.base.is_void() else 1
            delta = d * sz
        elif e.ty.is_integer():
            delta = d
        else:
            error_at(t, "wrong type argument to increment")
        return Node("incdec", t, ty=e.ty, lhs=e, delta=delta, post=post)

    def postfix(self):
        t = self.tok
        if self.is_("(") and self.is_typename(self.peek()):
            # compound literal
            self.next()
            ty = self.typename()
            self.expect(")")
            if self.cur_fn is None:
                o = self.new_anon_gvar(ty)
                init = self.initializer(ty)
                o.ty = init.ty
                o.init_data = self.global_init(init, o.ty)
                e = Node("var", t, ty=o.ty, var=o)
            else:
                o = self.new_lvar(f".cl{self.new_label()}", ty, t)
                o.addr_taken = True
                init = self.initializer(ty)
                o.ty = init.ty
                e = Node("cliteral", t, ty=o.ty, var=o, init=init)
        else:
            e = self.primary()
        while True:
            t = self.tok
            if self.is_("("):
                self.next()
                e = self.funcall(e, t)
                continue
            if self.is_("["):
                self.next()
                idx = self.expr()
                self.expect("]")
                p = self.new_add(e, idx, t)
                if not p.ty.is_ptr():
                    error_at(t, "subscripted value is neither array nor pointer")
                e = Node("deref", t, ty=p.ty.base, lhs=p)
                continue
            if self.is_("."):
                self.next()
                e = self.member_ref(e, self.expect_ident(), t)
                continue
            if self.is_("->"):
                self.next()
                p = self.decay(e)
                if not p.ty.is_ptr() or not p.ty.base.is_struct():
                    error_at(t, "invalid type argument of '->'")
                e = self.member_ref(Node("deref", t, ty=p.ty.base, lhs=p), self.expect_ident(), t)
                continue
            if self.is_("++") or self.is_("--"):
                self.next()
                e = self.new_incdec(e, 1 if t.text == "++" else -1, True, t)
                continue
            return e

    def find_member(self, ty, name):
        for m in ty.members or []:
            if m.name == name:
                return [m]
            if m.name is None and m.ty.is_struct():
                sub = self.find_member(m.ty, name)
                if sub:
                    return [m] + sub
        return None

    def member_ref(self, e, name, t):
        if not e.ty.is_struct():
            error_at(t, "request for member in something not a structure or union")
        if e.ty.members is None:
            error_at(t, "dereferencing incomplete struct")
        path = self.find_member(e.ty, name.text)
        if not path:
            error_at(name, f"no member named '{name.text}'")
        for m in path:
            ty = m.ty
            if m.bit_width is not None and ty.is_integer() and ty.unsigned and m.bit_width < 32 and ty.size <= 4:
                ty = INT     # an unsigned bit-field narrower than int promotes to int
            if e.ty.const:
                ty = T.qualified(ty, const=True)
            e = Node("member", t, ty=ty, lhs=e, mem=m)
        return e

    def funcall(self, fn, t):
        fn = self.decay(fn)
        if fn.ty.is_ptr() and fn.ty.base.is_func():
            fty = fn.ty.base
        else:
            error_at(t, "called object is not a function")
        args = []
        while not self.consume(")"):
            if args:
                self.expect(",")
            args.append(self.decay(self.assign()))
        params = fty.params
        out = []
        for i, a in enumerate(args):
            if params is not None and i < len(params):
                pt = params[i]
                if pt.is_struct():
                    if not a.ty.is_struct():
                        error_at(a.tok, "incompatible argument type")
                    out.append(a)
                else:
                    out.append(self.cast(a, pt))
            else:
                if params is not None and not fty.variadic:
                    error_at(t, "too many arguments to function")
                if a.ty.is_integer():
                    out.append(self.cast(a, int_promote(a.ty)))
                else:
                    out.append(a)
        if params is not None and len(args) < len(params):
            error_at(t, "too few arguments to function")
        name = fn.lhs.var.name if fn.kind == "addr" and fn.lhs.kind == "var" else None
        return Node("call", t, ty=fty.ret, fn=fn, args=out, fty=fty, fname=name)

    def string_data(self):
        data = []
        while self.tok.kind == "str":
            s = self.next().text
            if s.startswith("L"):
                error_at(self.tok, "wide strings not supported")
            data.extend(unescape(s[1:-1]))
        data.append(0)
        return data

    def primary(self):
        t = self.tok
        if self.is_("("):
            self.next()
            if self.is_("{"):
                # GNU statement expression
                self.next()
                blk = self.compound_stmt()
                self.expect(")")
                last = blk.body[-1] if blk.body else None
                ty = last.expr.ty if last is not None and last.kind == "expr" else VOID
                return Node("stmtexpr", t, ty=ty, body=blk)
            e = self.expr()
            self.expect(")")
            return e
        if t.kind == "num":
            self.next()
            v, tn = convert_number(t)
            ty = T.NUM_TYPES[tn]
            return Node("num", t, ty=ty, val=wrap(v, ty))
        if t.kind == "char":
            self.next()
            b = unescape(t.text[t.text.index("'") + 1:-1])
            v = 0
            for x in b:
                v = (v << 8) | x
            if len(b) == 1:
                v = wrap(b[0], CHAR)
            return Node("num", t, ty=INT, val=wrap(v, INT))
        if t.kind == "str":
            data = self.string_data()
            o = self.new_string(data, array_of(CHAR, len(data)))
            return Node("var", t, ty=o.ty, var=o)
        if t.kind == "id":
            if t.text in ("__builtin_va_start", "__builtin_va_arg", "__builtin_va_end", "__builtin_va_copy"):
                return self.builtin_va(t)
            if t.text.startswith("__builtin_cheri_") and t.text[16:] in CHERI_BUILTINS:
                op = t.text[16:]
                nargs, rty = CHERI_BUILTINS[op]
                self.next()
                self.expect("(")
                args = [self.decay(self.assign())]
                for _ in range(nargs - 1):
                    self.expect(",")
                    args.append(self.cast(self.decay(self.assign()), T.UINT128))
                self.expect(")")
                if not args[0].ty.is_ptr():
                    error_at(t, f"{t.text}: first argument must be a pointer")
                return Node("cheri", t, ty=args[0].ty if rty is None else rty, op=op, args=args)
            if t.text == "__builtin_expect":
                self.next()
                self.expect("(")
                e = self.assign()
                self.expect(",")
                self.assign()
                self.expect(")")
                return e
            if t.text == "__builtin_offsetof" or t.text == "offsetof":
                if t.text == "__builtin_offsetof" or self.peek().text == "(":
                    pass
            self.next()
            v = self.lookup(t.text)
            if v is None:
                if self.is_("("):
                    # implicit declaration: int f()
                    ft = func_type(INT, None, False)
                    ft.param_names = []
                    o = Obj(t.text, ft, False, t)
                    o.asm_name = "_" + t.text
                    self.scopes[0].vars[t.text] = ("var", o)
                    self.globals.append(o)
                    return Node("var", t, ty=ft, var=o)
                error_at(t, f"'{t.text}' undeclared")
            if v[0] == "enum":
                return Node("num", t, ty=INT, val=v[1])
            if v[0] == "typedef":
                error_at(t, "unexpected type name")
            o = v[1]
            o.referenced = True
            return Node("var", t, ty=o.ty, var=o)
        error_at(t, "expected expression")

    def builtin_va(self, t):
        self.next()
        self.expect("(")
        if t.text == "__builtin_va_start":
            ap = self.assign()
            self.expect(",")
            self.assign()
            self.expect(")")
            if not self.cur_fn or not self.cur_fn.ty.variadic:
                error_at(t, "va_start used in non-variadic function")
            return Node("va_start", t, ty=VOID, ap=ap, nparams=len(self.cur_fn.params))
        if t.text == "__builtin_va_end":
            self.assign()
            self.expect(")")
            return Node("num", t, ty=INT, val=0)
        if t.text == "__builtin_va_copy":
            d = self.assign()
            self.expect(",")
            s = self.assign()
            self.expect(")")
            return self.new_assign(d, s, t)
        ap = self.assign()
        self.expect(",")
        ty = self.typename()
        self.expect(")")
        if ty.is_struct():
            error_at(t, "va_arg of struct type not supported")
        return Node("va_arg", t, ty=ty, ap=ap)


def fold_binary(k, a, b, ty, tok):
    bits = 128 if ty.kind == "ptr" else ty.size * 8
    if k == "add":
        r = a + b
    elif k == "sub":
        r = a - b
    elif k == "mul":
        r = a * b
    elif k in ("div", "mod"):
        if b == 0:
            raise CompileError(f"{tok.where() if tok else '?'}: division by zero in constant expression")
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0):
            q = -q
        r = q if k == "div" else a - q * b
    elif k == "band":
        r = a & b
    elif k == "bor":
        r = a | b
    elif k == "bxor":
        r = a ^ b
    elif k == "shl":
        r = a << (b & 127) if 0 <= b < bits else 0
    elif k == "shr":
        r = a >> b if 0 <= b < bits else (0 if a >= 0 else -1)
    else:
        raise CompileError("bad fold")
    return wrap(r, ty)
