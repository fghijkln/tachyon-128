"""TACHYON-128 ISA definitions shared by the assembler, disassembler and golden simulator.

Single source of truth for opcodes, function codes, formats, register names, CSRs,
trap causes and the memory map.  The RTL (rtl/tx_pkg.sv) mirrors these numbers;
tests/check_pkg.py verifies the two stay in sync.
"""

XLEN = 128
MASK = (1 << XLEN) - 1
TOP_MAX = 1 << XLEN          # capability top is 129 bits wide (can equal 2^128)

# ---------------------------------------------------------------- memory map
RAM_BYTES = 256 * 1024                       # physical RAM at address 0
MMIO_BASE = (1 << 128) - 0x10000             # top 64 KiB of the 128-bit space
MMIO_CONSOLE = MMIO_BASE + 0x00              # write: low byte -> console
MMIO_EXIT = MMIO_BASE + 0x10                 # write: halt, exit code = value
MMIO_HEXOUT = MMIO_BASE + 0x20               # write: print value as 32 hex digits + '\n'

# ---------------------------------------------------------------- opcodes (bits [5:0])
OP_ALU = 0x01      # R-type, func = ALU op
OP_MULDIV = 0x02   # R-type, func = MULDIV op
OP_SIMD = 0x03     # R-type, func = (simd_op << 2) | lane_width
OP_CAP = 0x04      # R-type, func = CAP op

OP_ADDI, OP_ANDI, OP_ORI, OP_XORI, OP_SLTI, OP_SLTIU, OP_SLLI, OP_SRLI, OP_SRAI = range(0x08, 0x11)
OP_CINCADDRI = 0x11
OP_CSETBNDI = 0x12
OP_WIDE = 0x14     # K-type wide immediate: wli / wins

OP_LB, OP_LH, OP_LW, OP_LD, OP_LQ, OP_LBU, OP_LHU, OP_LWU, OP_LDU = range(0x18, 0x21)
OP_CLC = 0x21      # clc rd, imm(rs1): 128-bit capability load (tag + metadata from shadow memory)
OP_SB, OP_SH, OP_SW, OP_SD, OP_SQ = range(0x28, 0x2D)
OP_CSC = 0x2D      # csc rA, imm(rs1): 128-bit capability store (tag + metadata to shadow memory)
OP_BEQ, OP_BNE, OP_BLT, OP_BGE, OP_BLTU, OP_BGEU = range(0x30, 0x36)
OP_JAL = 0x38
OP_JALR = 0x39
OP_HALT = 0x3C
OP_CSRR = 0x3D
OP_CSRW = 0x3E
OP_ERET = 0x3F

# ---------------------------------------------------------------- function codes
ALU_FUNCS = ["add", "sub", "and", "or", "xor", "sll", "srl", "sra", "slt", "sltu",
             "min", "max", "minu", "maxu", "andn", "seq", "clz", "ctz", "popcnt"]
ALU_UNARY = {"clz", "ctz", "popcnt"}
MULDIV_FUNCS = ["mul", "mulhu", "div", "divu", "rem", "remu"]
SIMD_FUNCS = ["vadd", "vsub", "vaddss", "vaddus", "vsubss", "vsubus", "vmins", "vminu",
              "vmaxs", "vmaxu", "vcmpeq", "vcmpgts", "vcmpgtu", "vmul", "vsplat", "vsum",
              "vsll", "vsrl", "vsra"]
SIMD_UNARY = {"vsplat", "vsum"}
LANE_SUFFIX = {"b": 0, "h": 1, "w": 2, "d": 3}     # 8, 16, 32, 64-bit lanes
LANE_BITS = [8, 16, 32, 64]
CAP_FUNCS = ["csetaddr", "cincaddr", "csetbnd", "candperm", "cgetbase", "cgetlen",
             "cgetperm", "cgettag", "cclrtag", "cgetpcc", "csetepcc", "cjalr",
             "cseal", "cunseal", "cgettype"]
CAP_UNARY = {"cgetbase", "cgetlen", "cgetperm", "cgettag", "cclrtag", "cjalr", "cgettype"}   # rd, rs1
CAP_RD_ONLY = {"cgetpcc"}                                                     # rd
CAP_RS1_ONLY = {"csetepcc"}                                                   # rs1

I_OPS = {"addi": OP_ADDI, "andi": OP_ANDI, "ori": OP_ORI, "xori": OP_XORI, "slti": OP_SLTI,
         "sltiu": OP_SLTIU, "slli": OP_SLLI, "srli": OP_SRLI, "srai": OP_SRAI,
         "cincaddri": OP_CINCADDRI, "csetbndi": OP_CSETBNDI}
LOAD_OPS = {"lb": (OP_LB, 1, True), "lh": (OP_LH, 2, True), "lw": (OP_LW, 4, True),
            "ld": (OP_LD, 8, True), "lq": (OP_LQ, 16, False), "lbu": (OP_LBU, 1, False),
            "lhu": (OP_LHU, 2, False), "lwu": (OP_LWU, 4, False), "ldu": (OP_LDU, 8, False)}
STORE_OPS = {"sb": (OP_SB, 1), "sh": (OP_SH, 2), "sw": (OP_SW, 4), "sd": (OP_SD, 8), "sq": (OP_SQ, 16)}
CAP_LOAD_OPS = {"clc": OP_CLC}
CAP_STORE_OPS = {"csc": OP_CSC}
BRANCH_OPS = {"beq": OP_BEQ, "bne": OP_BNE, "blt": OP_BLT, "bge": OP_BGE, "bltu": OP_BLTU, "bgeu": OP_BGEU}

# ---------------------------------------------------------------- CSRs
CSR_NAMES = {"tvec": 0, "epc": 1, "cause": 2, "tval": 3, "scratch": 4}
NUM_CSRS = 5

# ---------------------------------------------------------------- traps
CAUSE_ILLEGAL = 1
CAUSE_CAP_TAG = 2
CAUSE_CAP_BOUNDS = 3
CAUSE_CAP_PERM = 4
CAUSE_ALIGN = 5
CAUSE_ACCESS = 6
CAUSE_CAP_SEALED = 7
CAUSE_NAMES = {1: "illegal-instruction", 2: "capability-tag", 3: "capability-bounds",
               4: "capability-permission", 5: "misaligned", 6: "access-fault", 7: "capability-sealed"}

# capability permissions
PERM_LOAD, PERM_STORE, PERM_EXEC, PERM_LOAD_CAP, PERM_STORE_CAP, PERM_SEAL, PERM_UNSEAL = 1, 2, 4, 8, 16, 32, 64
PERM_ALL = 0x7F
OTYPE_MAX = 0xFFFF           # otype 0 = unsealed; sealed capabilities carry otype 1..0xFFFF
NULL_META = (0, 0, 0, 0)     # (perm, base, top, otype)
ROOT_META = (PERM_ALL, 0, TOP_MAX, 0)
GRANULE = 16                 # tagged-memory granule (bytes): one shadow tag + metadata per granule

# ---------------------------------------------------------------- registers
NREGS = 64
REG_ALIAS = {"zero": 0, "ra": 1, "sp": 2, "gp": 3, "rc": 63}
for _i in range(8):
    REG_ALIAS[f"a{_i}"] = 4 + _i
for _i in range(16):
    REG_ALIAS[f"t{_i}"] = 12 + _i
for _i in range(16):
    REG_ALIAS[f"s{_i}"] = 28 + _i
REG_NAME = {v: k for k, v in REG_ALIAS.items()}


def reg_name(i):
    return REG_NAME.get(i, f"r{i}")


def sext(v, bits):
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >> (bits - 1) else v


def to_signed(v):
    return sext(v, XLEN)


# ---------------------------------------------------------------- encoding helpers
def enc_r(op, rd, rs1, rs2, func):
    return (op & 63) | (rd & 63) << 6 | (rs1 & 63) << 12 | (rs2 & 63) << 18 | (func & 255) << 24


def enc_i(op, a, rs1, imm):
    """I/S/B layout: field A [11:6] (rd, or the data/compare register for S/B), rs1 [17:12], imm14 [31:18]."""
    return (op & 63) | (a & 63) << 6 | (rs1 & 63) << 12 | (imm & 0x3FFF) << 18


def enc_j(op, rd, imm20):
    return (op & 63) | (rd & 63) << 6 | (imm20 & 0xFFFFF) << 12


def enc_k(rd, imm16, slot, keep):
    return OP_WIDE | (rd & 63) << 6 | (slot & 7) << 12 | (keep & 1) << 15 | (imm16 & 0xFFFF) << 16


def fields(w):
    return dict(op=w & 63, rd=(w >> 6) & 63, rs1=(w >> 12) & 63, rs2=(w >> 18) & 63,
                func=(w >> 24) & 255, imm14=sext(w >> 18, 14), imm20=sext(w >> 12, 20),
                uimm14=(w >> 18) & 0x3FFF, slot=(w >> 12) & 7, keep=(w >> 15) & 1,
                imm16=(w >> 16) & 0xFFFF)
