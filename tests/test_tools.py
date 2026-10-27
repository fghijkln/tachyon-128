#!/usr/bin/env python3
"""Tool-chain self-tests (no RTL needed):
  1. tools/isa.py and rtl/tx_defs.svh agree on every opcode / count / cause code
  2. `li` constant fusion: 1000 random 128-bit constants materialise exactly (golden sim)
  3. disassembler -> assembler round trip over every instruction of every unit test and program
"""
import os
import random
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tests")]
import isa  # noqa: E402
from asm import Assembler, preprocess  # noqa: E402
from disasm import disasm, decode  # noqa: E402
from sim import Machine  # noqa: E402
from run_tests import PROGRAMS  # noqa: E402


def check_defs():
    sv = open(os.path.join(ROOT, "rtl", "tx_defs.svh")).read()
    n = 0
    for name, val in re.findall(r"(OP_\w+)\s*=\s*6'h([0-9A-Fa-f]+)", sv):
        assert getattr(isa, name) == int(val, 16), name
        n += 1
    counts = dict(re.findall(r"(N_\w+)\s*=\s*\d+'d(\d+)", sv))
    assert int(counts["N_ALU"]) == len(isa.ALU_FUNCS)
    assert int(counts["N_MULDIV"]) == len(isa.MULDIV_FUNCS)
    assert int(counts["N_SIMD"]) == len(isa.SIMD_FUNCS)
    assert int(counts["N_CAP"]) == len(isa.CAP_FUNCS)
    assert int(counts["N_CSR"]) == isa.NUM_CSRS
    for name, val in re.findall(r"C_(\w+)\s*=\s*(\d+)", sv):
        assert getattr(isa, "CAUSE_" + name) == int(val), name
    cf = re.findall(r"CF_(\w+)\s*=\s*5'd(\d+)", sv)
    for name, val in cf:
        assert isa.CAP_FUNCS[int(val)] == name.lower(), name
    for name in ("MTIME", "MTIMECMP", "EXIT"):
        m = re.search(r"MMIO_%s = \{112'hFFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFF, 16'h([0-9A-F]+)\}" % name, sv)
        assert getattr(isa, "MMIO_" + name) == isa.MMIO_BASE + int(m.group(1), 16), name
    n += len(cf) + 3
    alu = re.findall(r"A_(\w+)\s*=\s*(\d+)", sv)
    for name, val in alu:
        assert isa.ALU_FUNCS[int(val)] == name.lower(), name
    return n + len(alu)


def check_li(count=1000):
    r = random.Random(7)
    vals = [r.getrandbits(r.choice([8, 14, 16, 32, 64, 100, 128])) for _ in range(count)]
    vals += [(1 << 128) - r.getrandbits(20) for _ in range(50)] + [0, 1, (1 << 128) - 1, 1 << 127]
    total = 0
    for chunk in range(0, len(vals), 50):
        part = vals[chunk:chunk + 50]
        src = "".join(f"        li r{4 + i}, {v}\n" for i, v in enumerate(part)) + "        halt zero\n"
        binary = Assembler().assemble(src)[0]
        total += len(binary) // 4 - 1
        m = Machine(binary).run()
        for i, v in enumerate(part):
            assert m.val[4 + i] == v % (1 << 128), (hex(v), hex(m.val[4 + i]))
    return len(vals), total / len(vals)


def check_roundtrip():
    from unit_tests import tests
    srcs = list(tests().values())
    srcs += [preprocess(os.path.join(ROOT, "programs", p + ".s")) for p in PROGRAMS]
    n = 0
    for src in srcs:
        binary, listing = Assembler().assemble(src)
        for pc, w, _ in listing:
            if w is None or decode(w) is None:
                continue
            text = disasm(w, pc)
            again = Assembler().assemble(f"        .org {pc}\n        {text}\n")[0]
            w2 = struct.unpack_from("<I", again, pc)[0]
            assert w2 == w or decode(w2) == decode(w) and disasm(w2, pc) == text, (hex(pc), text, hex(w), hex(w2))
            n += 1
    return n


if __name__ == "__main__":
    print(f"defs in sync: {check_defs()} constants checked")
    n, avg = check_li()
    print(f"li fusion: {n} constants exact, avg {avg:.2f} instructions each")
    print(f"disasm/asm round trip: {check_roundtrip()} instructions")
    print("tool tests PASSED")
