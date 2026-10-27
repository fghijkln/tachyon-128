#!/usr/bin/env python3
"""tcc128 - a C compiler for TACHYON-128.

  tcc128.py prog.c [more.c ...] -o prog.s       compile + link to one assembly file
  tcc128.py prog.c --run                        ... then assemble and run on the golden simulator
  tcc128.py prog.c --run --rtl                  ... and on the Verilator RTL model (build/vtb/Vtb)
Options: -I dir, -D name[=val], -O0 (no IR optimisation), --nolibc, --max N (instruction limit),
         --bin out.bin, --hex out.hex, --stats.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools"))

from compiler.driver import compile_unit, libc_units, link  # noqa: E402
from compiler.lexer import CompileError  # noqa: E402


def compile_files(files, include=(), defines=None, optimize=True, nolibc=False):
    units = []
    for k, f in enumerate(files):
        units.append(compile_unit(f, k + 1, include, defines, optimize))
    if not nolibc:
        units.extend(libc_units(include, optimize))
    return link(units)


def assemble(asm_text):
    from asm import Assembler
    binary, _ = Assembler().assemble(asm_text)
    return binary


class _NoTrace:
    def append(self, x):
        pass


def run_sim(binary, max_steps=50_000_000):
    from sim import Machine
    m = Machine(binary)
    m.trace = _NoTrace()
    m.run(max_steps)
    return m


def main():
    ap = argparse.ArgumentParser(description="tcc128: C compiler for TACHYON-128")
    ap.add_argument("files", nargs="+")
    ap.add_argument("-o", "--out")
    ap.add_argument("-I", dest="inc", action="append", default=[])
    ap.add_argument("-D", dest="defs", action="append", default=[])
    ap.add_argument("-O0", dest="O0", action="store_true")
    ap.add_argument("-O", dest="Olevel", default=None)
    ap.add_argument("--nolibc", action="store_true")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--rtl", action="store_true")
    ap.add_argument("--max", type=int, default=50_000_000)
    ap.add_argument("--bin")
    ap.add_argument("--hex")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    defines = {}
    for d in a.defs:
        k, _, v = d.partition("=")
        defines[k] = v if v else "1"
    try:
        asm_text = compile_files(a.files, a.inc, defines, not a.O0, a.nolibc)
    except CompileError as e:
        sys.exit(str(e))
    out = a.out or os.path.splitext(a.files[0])[0] + ".s"
    with open(out, "w") as f:
        f.write(asm_text)
    if not (a.run or a.bin or a.hex):
        return
    binary = assemble(asm_text)
    if a.bin:
        open(a.bin, "wb").write(binary)
    if a.hex or a.rtl:
        from asm import write_hex128
        hexf = a.hex or os.path.splitext(out)[0] + ".hex"
        write_hex128(binary, hexf)
    if a.run:
        m = run_sim(binary, a.max)
        sys.stdout.write(m.console.decode("latin-1"))
        sys.stdout.flush()
        if a.stats or m.halted[0] != "exit":
            print(f"--- sim: {m.halted[0]} code={m.exit_code if m.halted[0] == 'exit' else m.halted[1]} "
                  f"retired={m.retired} image={len(binary)} bytes", file=sys.stderr)
        if a.rtl:
            sys.path.insert(0, os.path.join(HERE, "tests"))
            from rtl_run import run_rtl
            r = run_rtl(hexf)
            print(f"--- rtl: {r}", file=sys.stderr)
        sys.exit(m.exit_code if m.halted[0] == "exit" else 125)


if __name__ == "__main__":
    main()
