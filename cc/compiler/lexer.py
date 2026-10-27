"""Tokenizer for tcc128 (C89/C99 subset)."""
import re


class CompileError(Exception):
    pass


class Tok:
    __slots__ = ("kind", "text", "val", "file", "line", "bol", "space", "hide", "ty")

    def __init__(self, kind, text, file="?", line=0, bol=False, space=False, val=None):
        self.kind = kind      # 'id' 'num' 'str' 'char' 'punct' 'eof'
        self.text = text
        self.val = val        # numeric value / bytes for strings
        self.file = file
        self.line = line
        self.bol = bol        # first token on its line
        self.space = space    # preceded by whitespace
        self.hide = frozenset()
        self.ty = None        # numeric literal type tag

    def copy(self):
        t = Tok(self.kind, self.text, self.file, self.line, self.bol, self.space, self.val)
        t.hide = self.hide
        t.ty = self.ty
        return t

    def __repr__(self):
        return f"Tok({self.kind},{self.text!r})"

    def where(self):
        return f"{self.file}:{self.line}"


def error_at(tok, msg):
    if tok is None:
        raise CompileError(msg)
    raise CompileError(f"{tok.where()}: error: {msg} (near '{tok.text}')")


PUNCTS = ["<<=", ">>=", "...", "->", "++", "--", "<<", ">>", "<=", ">=", "==", "!=", "&&", "||",
          "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "##"]
PUNCT_RE = "|".join(re.escape(p) for p in PUNCTS) + r"|[-+*/%&|^~!<>=?:;,.(){}\[\]#]"

TOKEN_RE = re.compile(
    r"(?P<cont>\\\r?\n)|"
    r"(?P<ws>[ \t\r\f\v]+)|"
    r"(?P<nl>\n)|"
    r"(?P<lc>//[^\n]*)|"
    r"(?P<bc>/\*.*?\*/)|"
    r"(?P<num>\.?[0-9](?:[eEpP][+-]|[0-9A-Za-z_.])*)|"
    r"(?P<id>[A-Za-z_][A-Za-z_0-9]*)|"
    r"(?P<chr>L?'(?:\\.|[^'\\\n])*')|"
    r"(?P<str>L?\"(?:\\.|[^\"\\\n])*\")|"
    r"(?P<p>" + PUNCT_RE + r")|"
    r"(?P<bad>.)", re.S)

ESC = {"n": 10, "t": 9, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11, "e": 27,
       "\\": 92, "'": 39, '"': 34, "?": 63}


def unescape(s, tok=None):
    """Decode C escapes in s (without quotes) into a list of byte values."""
    out = []
    i = 0
    while i < len(s):
        c = s[i]
        if c != "\\":
            out.extend(c.encode("utf-8"))
            i += 1
            continue
        i += 1
        c = s[i]
        if c in ESC:
            out.append(ESC[c])
            i += 1
        elif c == "x":
            j = i + 1
            while j < len(s) and s[j] in "0123456789abcdefABCDEF":
                j += 1
            out.append(int(s[i + 1:j], 16) & 0xFF)
            i = j
        elif c in "01234567":
            j = i
            while j < len(s) and j < i + 3 and s[j] in "01234567":
                j += 1
            out.append(int(s[i:j], 8) & 0xFF)
            i = j
        else:
            out.append(ord(c))
            i += 1
    return out


def tokenize(src, file):
    """Return a flat list of tokens (no EOF); line continuations removed."""
    toks = []
    line = 1
    bol = True
    space = False
    pos = 0
    n = len(src)
    m_ = TOKEN_RE.match
    while pos < n:
        m = m_(src, pos)
        k = m.lastgroup
        txt = m.group(k)
        pos = m.end()
        if k == "cont":
            line += 1
            space = True
            continue
        if k == "ws":
            space = True
            continue
        if k == "nl":
            line += 1
            bol = True
            space = False
            continue
        if k == "lc":
            space = True
            continue
        if k == "bc":
            nl = txt.count("\n")
            if nl:
                line += nl
                bol = True
            space = True
            continue
        if k == "bad":
            raise CompileError(f"{file}:{line}: error: stray character {txt!r}")
        kind = {"num": "num", "id": "id", "chr": "char", "str": "str", "p": "punct"}[k]
        t = Tok(kind, txt, file, line, bol, space)
        toks.append(t)
        bol = False
        space = False
    return toks


def convert_number(tok):
    """Parse a preprocessing number token into (value, type-name)."""
    s = tok.text.lower()
    m = re.fullmatch(r"(0x[0-9a-f]+|0b[01]+|0[0-7]*|[1-9][0-9]*)(u?l{0,2}u?|u?ll|i128|ui128)?", s)
    if not m or (m.group(2) and m.group(2).count("u") > 1):
        error_at(tok, f"invalid or unsupported numeric constant '{tok.text}' (no floating point)")
    body, suf = m.group(1), m.group(2) or ""
    if body.startswith("0x"):
        v, base = int(body, 16), 16
    elif body.startswith("0b"):
        v, base = int(body[2:], 2), 2
    elif body.startswith("0") and len(body) > 1:
        v, base = int(body, 8), 8
    else:
        v, base = int(body), 10
    u = "u" in suf
    nl = suf.count("l")
    # C99 rules: choose the first type that fits
    if suf.endswith("i128"):
        return v, ("uint128" if u else "int128")
    if base == 10:
        cands = {0: ["int", "long", "int128"], 1: ["long", "int128"], 2: ["llong", "int128"]}[nl]
        if u:
            cands = {0: ["uint", "ulong", "uint128"], 1: ["ulong", "uint128"], 2: ["ullong", "uint128"]}[nl]
    else:
        cands = {0: ["int", "uint", "long", "ulong", "int128", "uint128"],
                 1: ["long", "ulong", "int128", "uint128"],
                 2: ["llong", "ullong", "int128", "uint128"]}[nl]
        if u:
            cands = [c for c in cands if c.startswith("u")]
    lim = {"int": 31, "uint": 32, "long": 63, "ulong": 64, "llong": 63, "ullong": 64,
           "int128": 127, "uint128": 128}
    for c in cands:
        if v < (1 << lim[c]):
            return v, c
    return v & ((1 << 128) - 1), "uint128"
