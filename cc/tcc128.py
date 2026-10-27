#!/usr/bin/env python3
"""tcc128 - a C compiler for TACHYON-128.

  tcc128.py prog.c [more.c ...] -o prog.s       compile + link to one assembly file
  tcc128.py prog.c --run                        ... then assemble and run on the golden simulator
  tcc128.py prog.c --run --rtl                  ... and on the Verilator RTL model (build/vtb/Vtb)
Options: -I dir, -D name[=val], -O0 (no IR optimisation), -mpurecap (capability pointers), -fno-inline, --nolibc, --max N (instruction limit),
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


def compile_files(files, include=(), defines=None, optimize=True, nolibc=False, purecap=False):
    units = []
    for k, f in enumerate(files):
        units.append(compile_unit(f, k + 1, include, defines, optimize, purecap=purecap))
    if not nolibc:
        units.extend(libc_units(include, optimize, purecap))
    return link(units, purecap=purecap)


def assemble(asm_text):
    from asm import Assembler
    binary, _ = Assembler().assemble(asm_text)
    return binary


class _NoTrace:
    def append(self, x):
        pass


def run_sim(binary, max_steps=50_000_000, audit_untagged=False):
    """Run on the golden simulator. audit_untagged (for -mpurecap code): count RAM accesses made through an
    untagged base register, i.e. unchecked "hybrid" accesses that slipped past capability checking;
    m.untagged_ram maps pc -> count (MMIO accesses through integer addresses are not counted)."""
    from sim import Machine
    m = Machine(binary)
    m.trace = _NoTrace()
    m.untagged_ram = {}
    if audit_untagged:
        check = m.check_access

        def audited(rs1, ea, *args, **kw):
            where = check(rs1, ea, *args, **kw)
            if where == "ram" and not m.tag[rs1]:
                m.untagged_ram[m.pc] = m.untagged_ram.get(m.pc, 0) + 1
            return where
        m.check_access = audited
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
    ap.add_argument("-fno-inline", dest="noinline", action="store_true", help="do not inline small static functions")
    ap.add_argument("-mpurecap", dest="purecap", action="store_true",
                    help="pure-capability code: every pointer is a bounded capability (cc/ABI.md section 8)")
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
    if a.noinline:
        os.environ["TCC128_NO_INLINE"] = "1"
    try:
        asm_text = compile_files(a.files, a.inc, defines, not a.O0, a.nolibc, a.purecap)
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
            sys.path.insert(0, os.path.join(ROOT, "tests"))
            from harness import run_diff
            r = run_diff(os.path.splitext(os.path.basename(out))[0], binary, os.path.join(ROOT, "build", "ccrun"),
                         max_steps=a.max)
            print(f"--- rtl: {'commit trace matches the golden model' if r.ok else r.msg}, cycles={r.cycles}",
                  file=sys.stderr)
        sys.exit(m.exit_code if m.halted[0] == "exit" else 125)


if __name__ == "__main__":
    main()
