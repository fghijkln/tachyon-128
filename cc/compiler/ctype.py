"""C types and the TACHYON-128 data model (see cc/ABI.md):
char 8, short 16, int 32, long 64, long long 64, __int128 128, pointers 128 bits."""

PTR_SIZE = 16


class Member:
    __slots__ = ("name", "ty", "offset", "bit_width", "bit_offset", "tok")

    def __init__(self, name, ty, offset=0, bit_width=None, bit_offset=0, tok=None):
        self.name, self.ty, self.offset = name, ty, offset
        self.bit_width, self.bit_offset, self.tok = bit_width, bit_offset, tok


class Type:
    def __init__(self, kind, size=0, align=1, unsigned=False):
        self.kind = kind
        self.size = size
        self.align = align
        self.unsigned = unsigned
        self.base = None          # pointer / array element
        self.length = -1          # array length (-1: incomplete)
        self.ret = None           # function return type
        self.params = None        # list of Types (None: unspecified, old style)
        self.variadic = False
        self.members = None       # struct/union members (None: incomplete)
        self.tag = None
        self.const = False
        self.volatile = False
        self.origin = None        # for qualified copies

    def __repr__(self):
        return type_name(self)

    # predicates
    def is_integer(self):
        return self.kind in ("bool", "char", "short", "int", "long", "llong", "int128", "enum")

    def is_scalar(self):
        return self.is_integer() or self.kind == "ptr"

    def is_ptr(self):
        return self.kind == "ptr"

    def is_aggregate(self):
        return self.kind in ("struct", "union", "array")

    def is_struct(self):
        return self.kind in ("struct", "union")

    def is_void(self):
        return self.kind == "void"

    def is_func(self):
        return self.kind == "func"

    def is_array(self):
        return self.kind == "array"

    def is_signed(self):
        return self.is_integer() and not self.unsigned

    @property
    def bits(self):
        return self.size * 8


def copy_type(t):
    n = Type(t.kind, t.size, t.align, t.unsigned)
    n.__dict__.update(t.__dict__)
    n.origin = t.origin or t
    return n


def qualified(t, const=False, volatile=False):
    if (not const and not volatile) or t.kind in ("struct", "union", "array", "func"):
        return t
    n = copy_type(t)
    n.const = n.const or const
    n.volatile = n.volatile or volatile
    return n


VOID = Type("void", 1, 1)
BOOL = Type("bool", 1, 1, True)
CHAR = Type("char", 1, 1)
UCHAR = Type("char", 1, 1, True)
SHORT = Type("short", 2, 2)
USHORT = Type("short", 2, 2, True)
INT = Type("int", 4, 4)
UINT = Type("int", 4, 4, True)
LONG = Type("long", 8, 8)
ULONG = Type("long", 8, 8, True)
LLONG = Type("llong", 8, 8)
ULLONG = Type("llong", 8, 8, True)
INT128 = Type("int128", 16, 16)
UINT128 = Type("int128", 16, 16, True)

SIZE_T = ULONG
PTRDIFF_T = LONG

NUM_TYPES = {"int": INT, "uint": UINT, "long": LONG, "ulong": ULONG, "llong": LLONG,
             "ullong": ULLONG, "int128": INT128, "uint128": UINT128}

RANK = {"bool": 0, "char": 1, "short": 2, "int": 3, "enum": 3, "long": 4, "llong": 5, "int128": 6}


def pointer_to(base):
    t = Type("ptr", PTR_SIZE, PTR_SIZE, True)
    t.base = base
    return t


def array_of(base, n):
    t = Type("array", base.size * n if n >= 0 else 0, base.align)
    t.base = base
    t.length = n
    return t


def func_type(ret, params=None, variadic=False):
    t = Type("func", 1, 1)
    t.ret = ret
    t.params = params
    t.variadic = variadic
    return t


def enum_type():
    t = Type("enum", 4, 4)
    return t


def struct_type(kind="struct"):
    t = Type(kind, 0, 1)
    return t


def unqual(t):
    return t.origin if (t.origin is not None and (t.const or t.volatile)) else t


def int_promote(t):
    if t.kind == "enum":
        return INT
    if t.is_integer() and t.size < 4:
        return INT
    if t.kind == "bool":
        return INT
    return unqual(t)


def make_int(rank_kind, unsigned):
    table = {("int", False): INT, ("int", True): UINT, ("long", False): LONG, ("long", True): ULONG,
             ("llong", False): LLONG, ("llong", True): ULLONG, ("int128", False): INT128,
             ("int128", True): UINT128}
    return table[(rank_kind, unsigned)]


def common_type(a, b):
    """Usual arithmetic conversions for integer types."""
    a, b = int_promote(a), int_promote(b)
    if a.kind == "ptr":
        return a
    if b.kind == "ptr":
        return b
    if a.kind == b.kind and a.unsigned == b.unsigned:
        return a
    ra, rb = RANK[a.kind], RANK[b.kind]
    if a.unsigned == b.unsigned:
        return a if ra > rb else b
    u, s = (a, b) if a.unsigned else (b, a)
    if RANK[u.kind] >= RANK[s.kind]:
        return u
    if s.size > u.size:
        return s
    return make_int(s.kind, True)


def is_compatible(a, b):
    a, b = unqual(a), unqual(b)
    if a is b:
        return True
    if a.kind != b.kind:
        return False
    if a.kind == "ptr":
        return is_compatible(a.base, b.base)
    if a.kind == "array":
        return is_compatible(a.base, b.base)
    if a.kind in ("struct", "union", "enum"):
        return a is b
    if a.is_integer():
        return a.unsigned == b.unsigned
    if a.kind == "func":
        return is_compatible(a.ret, b.ret)
    return True


def type_name(t):
    if t is None:
        return "?"
    if t.kind == "ptr":
        return type_name(t.base) + "*"
    if t.kind == "array":
        return f"{type_name(t.base)}[{t.length}]"
    if t.kind == "func":
        return f"{type_name(t.ret)}(...)"
    if t.kind in ("struct", "union", "enum"):
        return f"{t.kind} {t.tag or '<anon>'}"
    names = {"llong": "long long", "int128": "__int128", "bool": "_Bool"}
    n = names.get(t.kind, t.kind)
    return ("unsigned " + n) if t.unsigned and t.kind not in ("bool",) else n


def align_to(n, a):
    return (n + a - 1) // a * a


def wrap(v, t):
    """Wrap integer v to the value range of type t (canonical value as Python int)."""
    if t.kind == "bool":
        return 1 if v else 0
    if t.kind == "void":
        return v
    bits = t.size * 8 if t.kind != "ptr" else 128
    v &= (1 << bits) - 1
    if not t.unsigned and t.kind != "ptr" and v >> (bits - 1):
        v -= 1 << bits
    return v
