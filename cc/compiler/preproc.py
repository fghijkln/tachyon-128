"""C preprocessor subset: #include, #define (object/function-like, #, ##, __VA_ARGS__),
#undef, #if/#ifdef/#ifndef/#elif/#else/#endif, defined, #error, #pragma once, #line (ignored).
Macro expansion follows Prosser's hide-set algorithm."""
import os

from .lexer import CompileError, Tok, convert_number, error_at, tokenize, unescape


class Macro:
    def __init__(self, name, params, variadic, body):
        self.name, self.params, self.variadic, self.body = name, params, variadic, body


PREDEF = """
#define __TACHYON128__ 1
#define __tcc128__ 1
#define __STDC__ 1
#define __STDC_VERSION__ 199901L
#define __STDC_HOSTED__ 1
#define __CHAR_BIT__ 8
#define __SIZEOF_SHORT__ 2
#define __SIZEOF_INT__ 4
#define __SIZEOF_LONG__ 8
#define __SIZEOF_LONG_LONG__ 8
#define __SIZEOF_POINTER__ 16
#define __SIZEOF_INT128__ 16
#define __ORDER_LITTLE_ENDIAN__ 1234
#define __BYTE_ORDER__ 1234
#define __attribute__(x)
#define __extension__
#define __inline inline
#define __inline__ inline
#define __restrict restrict
#define __restrict__ restrict
#define __const const
#define __signed__ signed
#define __volatile__ volatile
"""


class Preprocessor:
    def __init__(self, include_paths=(), defines=None):
        self.include_paths = list(include_paths)
        self.macros = {}
        self.once = set()
        self.depth = 0
        self.process(tokenize(PREDEF, "<predef>"))
        for k, v in (defines or {}).items():
            self.process(tokenize(f"#define {k} {v}\n", "<cmdline>"))

    # ------------------------------------------------------------------ driver
    def preprocess_file(self, path):
        src = open(path, encoding="utf-8", errors="replace").read()
        return self.process(tokenize(src, path))

    def process(self, toks):
        out = []
        stack = list(reversed(toks))
        cond = []      # stack of [taking, any_taken, in_else]
        while stack:
            t = stack.pop()
            if t.kind == "punct" and t.text == "#" and t.bol and not t.hide:
                line = self.read_line(stack)
                self.directive(t, line, stack, cond, out)
                continue
            if cond and not cond[-1][0]:
                continue
            if t.kind == "id":
                r = self.try_expand(t, stack)
                if r:
                    continue
            out.append(t)
        if cond:
            raise CompileError("unterminated #if")
        return out

    @staticmethod
    def read_line(stack):
        line = []
        while stack and not stack[-1].bol:
            line.append(stack.pop())
        return line

    # ------------------------------------------------------------------ directives
    def directive(self, hash_tok, line, stack, cond, out):
        if not line:
            return
        d = line[0].text
        skipping = cond and not cond[-1][0]
        if d in ("if", "ifdef", "ifndef"):
            if skipping:
                cond.append([False, True, False])
                return
            if d == "if":
                v = self.eval_if(line[1:], line[0])
            else:
                if len(line) < 2:
                    error_at(line[0], "macro name expected")
                v = (line[1].text in self.macros) == (d == "ifdef")
            cond.append([bool(v), bool(v), False])
            return
        if d == "elif":
            if not cond:
                error_at(line[0], "#elif without #if")
            c = cond[-1]
            parent_skip = len(cond) > 1 and not cond[-2][0]
            if c[1] or parent_skip:
                c[0] = False
            else:
                v = bool(self.eval_if(line[1:], line[0]))
                c[0] = v
                c[1] = v
            return
        if d == "else":
            if not cond:
                error_at(line[0], "#else without #if")
            c = cond[-1]
            parent_skip = len(cond) > 1 and not cond[-2][0]
            c[0] = (not c[1]) and not parent_skip
            c[1] = True
            return
        if d == "endif":
            if not cond:
                error_at(line[0], "#endif without #if")
            cond.pop()
            return
        if skipping:
            return
        if d == "define":
            self.define(line[1:], line[0])
        elif d == "undef":
            if len(line) > 1:
                self.macros.pop(line[1].text, None)
        elif d == "include":
            self.include(line, stack)
        elif d == "error":
            error_at(line[0], "#error " + " ".join(t.text for t in line[1:]))
        elif d in ("pragma", "line", "warning", "ident"):
            if d == "pragma" and len(line) > 1 and line[1].text == "once":
                self.once.add(os.path.abspath(hash_tok.file))
            if d == "warning":
                pass
        elif line[0].kind == "num":
            pass   # GNU line marker
        else:
            error_at(line[0], f"unknown directive #{d}")

    def define(self, line, where):
        if not line or line[0].kind != "id":
            error_at(where, "macro name expected")
        name = line[0].text
        if len(line) > 1 and line[1].text == "(" and not line[1].space:
            params = []
            variadic = False
            i = 2
            while True:
                if i >= len(line):
                    error_at(where, "unterminated macro parameter list")
                t = line[i]
                if t.text == ")":
                    i += 1
                    break
                if t.text == "...":
                    variadic = True
                    params.append("__VA_ARGS__")
                elif t.kind == "id":
                    params.append(t.text)
                    if i + 1 < len(line) and line[i + 1].text == "...":
                        variadic = True
                        i += 1
                elif t.text != ",":
                    error_at(t, "bad macro parameter")
                i += 1
            self.macros[name] = Macro(name, params, variadic, line[i:])
        else:
            self.macros[name] = Macro(name, None, False, line[1:])

    def include(self, line, stack):
        if len(line) < 2:
            error_at(line[0], "#include expects a file name")
        toks = line[1:]
        if toks[0].kind != "str" and toks[0].text != "<":
            toks = self.expand_list(toks)
        if toks[0].kind == "str":
            name = toks[0].text[1:-1]
            dirs = [os.path.dirname(toks[0].file)] + self.include_paths
        elif toks[0].text == "<":
            name = ""
            for t in toks[1:]:
                if t.text == ">":
                    break
                name += t.text
            dirs = self.include_paths + [os.path.dirname(toks[0].file)]
        else:
            error_at(toks[0], "bad #include")
        for d in dirs:
            p = os.path.join(d, name)
            if os.path.isfile(p):
                ap = os.path.abspath(p)
                if ap in self.once:
                    return
                self.depth += 1
                if self.depth > 64:
                    error_at(toks[0], "#include nested too deeply")
                src = open(p, encoding="utf-8", errors="replace").read()
                inc = tokenize(src, p)
                # mark the first token after the include as bol (it already is), push included tokens
                if stack:
                    stack[-1].bol = True
                stack.extend(reversed(inc))
                self.depth -= 1
                return
        error_at(toks[0], f"cannot find include file '{name}'")

    # ------------------------------------------------------------------ #if expressions
    def eval_if(self, toks, where):
        res = []
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.kind == "id" and t.text == "defined":
                i += 1
                paren = i < len(toks) and toks[i].text == "("
                if paren:
                    i += 1
                if i >= len(toks):
                    error_at(where, "bad defined()")
                nm = toks[i].text
                i += 1
                if paren:
                    i += 1
                nt = Tok("num", "1" if nm in self.macros else "0", t.file, t.line)
                res.append(nt)
                continue
            res.append(t)
            i += 1
        res = self.expand_list(res)
        res = [Tok("num", "0", t.file, t.line) if t.kind == "id" else t for t in res]
        p = _IfParser(res, where)
        v = p.cond()
        if p.i != len(res):
            error_at(res[p.i], "garbage in #if expression")
        return v

    # ------------------------------------------------------------------ macro expansion
    def expand_list(self, toks):
        out = []
        stack = list(reversed(toks))
        while stack:
            t = stack.pop()
            if t.kind == "id" and self.try_expand(t, stack):
                continue
            out.append(t)
        return out

    def try_expand(self, t, stack):
        name = t.text
        if name == "__LINE__" and "__LINE__" not in t.hide:
            nt = Tok("num", str(t.line), t.file, t.line, t.bol, t.space)
            nt.hide = frozenset(["__LINE__"])
            stack.append(nt)
            return True
        if name == "__FILE__" and "__FILE__" not in t.hide:
            s = t.file.replace("\\", "\\\\").replace('"', '\\"')
            nt = Tok("str", f'"{s}"', t.file, t.line, t.bol, t.space)
            nt.hide = frozenset(["__FILE__"])
            stack.append(nt)
            return True
        m = self.macros.get(name)
        if m is None or name in t.hide:
            return False
        if m.params is None:
            body = []
            hs = t.hide | {name}
            for i, b in enumerate(m.body):
                body.append(b)
            body = self.subst(m, body, {}, hs, t)
            stack.extend(reversed(body))
            return True
        # function-like: need '('
        if not stack or stack[-1].text != "(":
            return False
        stack.pop()
        args = []
        cur = []
        depth = 0
        while True:
            if not stack:
                error_at(t, f"unterminated call to macro {name}")
            a = stack.pop()
            if a.text == "(" and a.kind == "punct":
                depth += 1
            elif a.text == ")" and a.kind == "punct":
                if depth == 0:
                    rparen = a
                    break
                depth -= 1
            elif a.text == "," and a.kind == "punct" and depth == 0 and not (
                    m.variadic and len(args) == len(m.params) - 1):
                args.append(cur)
                cur = []
                continue
            cur.append(a)
        args.append(cur)
        if len(m.params) == 0 and args == [[]]:
            args = []
        if m.variadic and len(args) == len(m.params) - 1:
            args.append([])
        if len(args) != len(m.params):
            error_at(t, f"macro {name} expects {len(m.params)} arguments, got {len(args)}")
        amap = dict(zip(m.params, args))
        hs = (t.hide & rparen.hide) | {name}
        body = self.subst(m, list(m.body), amap, hs, t)
        stack.extend(reversed(body))
        return True

    def subst(self, m, body, amap, hs, origin):
        out = []
        i = 0
        n = len(body)
        while i < n:
            b = body[i]
            # stringize
            if b.text == "#" and m.params is not None and i + 1 < n and body[i + 1].text in amap:
                out.append(self.stringize(amap[body[i + 1].text], b))
                i += 2
                continue
            # paste:  x ## y
            if b.text == "##" and b.kind == "punct" and out is not None:
                if i + 1 >= n:
                    error_at(b, "'##' at end of macro")
                rhs_t = body[i + 1]
                if rhs_t.text in amap:
                    rhs = [x.copy() for x in amap[rhs_t.text]]
                else:
                    rhs = [rhs_t.copy()]
                i += 2
                # GNU: , ## __VA_ARGS__ with empty args drops the comma
                if rhs_t.text == "__VA_ARGS__" and out and out[-1].text == ",":
                    if not rhs:
                        out.pop()
                    out.extend(rhs)
                    continue
                if not out:
                    out.extend(rhs)
                    continue
                if not rhs:
                    continue
                lhs = out.pop()
                pasted = tokenize(lhs.text + rhs[0].text, lhs.file)
                if len(pasted) != 1:
                    error_at(b, f"pasting '{lhs.text}' and '{rhs[0].text}' does not give a valid token")
                p = pasted[0]
                p.line, p.space, p.bol = lhs.line, lhs.space, False
                out.append(p)
                out.extend(rhs[1:])
                continue
            if b.text in amap:
                arg = amap[b.text]
                if i + 1 < n and body[i + 1].text == "##":
                    out.extend(x.copy() for x in arg)
                else:
                    exp = self.expand_list([x.copy() for x in arg])
                    out.extend(exp)
                i += 1
                continue
            out.append(b.copy())
            i += 1
        res = []
        for k, x in enumerate(out):
            x = x.copy()
            x.hide = x.hide | hs
            x.bol = False
            x.file, x.line = origin.file, origin.line
            if k == 0:
                x.space = origin.space
            res.append(x)
        return res

    @staticmethod
    def stringize(toks, where):
        s = ""
        for k, t in enumerate(toks):
            if k and t.space:
                s += " "
            if t.kind in ("str", "char"):
                s += t.text.replace("\\", "\\\\").replace('"', '\\"')
            else:
                s += t.text
        return Tok("str", '"' + s + '"', where.file, where.line)


class _IfParser:
    def __init__(self, toks, where):
        self.t, self.i, self.where = toks, 0, where

    def peek(self):
        return self.t[self.i].text if self.i < len(self.t) else None

    def take(self, s):
        if self.peek() == s:
            self.i += 1
            return True
        return False

    def cond(self):
        c = self.lor()
        if self.take("?"):
            a = self.cond()
            if not self.take(":"):
                error_at(self.where, "expected ':' in #if")
            b = self.cond()
            return a if c else b
        return c

    def lor(self):
        v = self.land()
        while self.take("||"):
            r = self.land()
            v = 1 if (v or r) else 0
        return v

    def land(self):
        v = self.bor()
        while self.take("&&"):
            r = self.bor()
            v = 1 if (v and r) else 0
        return v

    def bor(self):
        v = self.bxor()
        while self.peek() == "|":
            self.i += 1
            v |= self.bxor()
        return v

    def bxor(self):
        v = self.band()
        while self.take("^"):
            v ^= self.band()
        return v

    def band(self):
        v = self.eq()
        while self.peek() == "&":
            self.i += 1
            v &= self.eq()
        return v

    def eq(self):
        v = self.rel()
        while self.peek() in ("==", "!="):
            op = self.t[self.i].text
            self.i += 1
            r = self.rel()
            v = int(v == r) if op == "==" else int(v != r)
        return v

    def rel(self):
        v = self.shift()
        while self.peek() in ("<", ">", "<=", ">="):
            op = self.t[self.i].text
            self.i += 1
            r = self.shift()
            v = int({"<": v < r, ">": v > r, "<=": v <= r, ">=": v >= r}[op])
        return v

    def shift(self):
        v = self.add()
        while self.peek() in ("<<", ">>"):
            op = self.t[self.i].text
            self.i += 1
            r = self.add()
            v = v << r if op == "<<" else v >> r
        return v

    def add(self):
        v = self.mul()
        while self.peek() in ("+", "-"):
            op = self.t[self.i].text
            self.i += 1
            r = self.mul()
            v = v + r if op == "+" else v - r
        return v

    def mul(self):
        v = self.unary()
        while self.peek() in ("*", "/", "%"):
            op = self.t[self.i].text
            self.i += 1
            r = self.unary()
            if op == "*":
                v *= r
            else:
                if r == 0:
                    error_at(self.where, "division by zero in #if")
                q = abs(v) // abs(r) * (1 if (v >= 0) == (r >= 0) else -1)
                v = q if op == "/" else v - q * r
        return v

    def unary(self):
        p = self.peek()
        if p == "-":
            self.i += 1
            return -self.unary()
        if p == "+":
            self.i += 1
            return self.unary()
        if p == "!":
            self.i += 1
            return int(not self.unary())
        if p == "~":
            self.i += 1
            return ~self.unary()
        if p == "(":
            self.i += 1
            v = self.cond()
            if not self.take(")"):
                error_at(self.where, "expected ')' in #if")
            return v
        if self.i >= len(self.t):
            error_at(self.where, "unexpected end of #if expression")
        t = self.t[self.i]
        self.i += 1
        if t.kind == "num":
            return convert_number(t)[0]
        if t.kind == "char":
            b = unescape(t.text[t.text.index("'") + 1:-1])
            v = b[0] if b else 0
            return v - 256 if v >= 128 else v
        error_at(t, "bad token in #if")
