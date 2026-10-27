#!/usr/bin/env python3
"""tcc128 test suite: compile every cc/tests/c/*.c, run it on the golden simulator and compare
stdout + exit code with the reference output in cc/tests/expected/ (produced by host gcc,
see gen_expected.py).

  run_tests.py [-O0] [--both] [pattern ...]
"""
import argparse
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.path.dirname(HERE)
sys.path.insert(0, CC)
from tcc128 import assemble, compile_files, run_sim  # noqa: E402
from compiler.lexer import CompileError  # noqa: E402

EXPECTED = os.path.join(HERE, "expected")


def run_one(path, optimize=True, max_steps=30_000_000):
    asm = compile_files([path], optimize=optimize)
    binary = assemble(asm)
    m = run_sim(binary, max_steps)
    code = m.exit_code if m.halted[0] == "exit" else f"{m.halted[0]}:{m.halted[1]}"
    return m.console.decode("latin-1"), code, m.retired, len(binary)


def fmt_result(out, code):
    return out + f"\n---exit {code}\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", nargs="*")
    ap.add_argument("-O0", action="store_true")
    ap.add_argument("--both", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(HERE, "c", "*.c")))
    if a.patterns:
        files = [f for f in files if any(p in os.path.basename(f) for p in a.patterns)]
    modes = [False, True] if a.both else [not a.O0]
    results = []
    npass = nfail = 0
    t0 = time.time()
    for opt in modes:
        for f in files:
            name = os.path.splitext(os.path.basename(f))[0]
            exp_path = os.path.join(EXPECTED, name + ".out")
            if not os.path.exists(exp_path):
                print(f"SKIP {name} (no expected output)")
                continue
            exp = open(exp_path, encoding="latin-1").read()
            try:
                out, code, retired, size = run_one(f, opt)
                got = fmt_result(out, code)
                ok = got == exp
                err = None
            except CompileError as e:
                ok, got, retired, size, err = False, "", 0, 0, str(e)
            except Exception as e:   # assembler errors etc.
                ok, got, retired, size, err = False, "", 0, 0, f"{type(e).__name__}: {e}"
            tag = "-O " if opt else "-O0"
            if ok:
                npass += 1
                print(f"PASS {tag} {name}  ({retired} instr, {size} B)")
            else:
                nfail += 1
                print(f"FAIL {tag} {name}  {err or ''}")
                if not err:
                    el, gl = exp.splitlines(), got.splitlines()
                    for k in range(max(len(el), len(gl))):
                        e1 = el[k] if k < len(el) else "<missing>"
                        g1 = gl[k] if k < len(gl) else "<missing>"
                        if e1 != g1:
                            print(f"     line {k + 1}: expected {e1!r}\n     {'':9}     got {g1!r}")
                            break
            results.append({"name": name, "opt": opt, "pass": ok, "retired": retired, "size": size})
    print(f"\n{npass}/{npass + nfail} passed in {time.time() - t0:.1f}s")
    if a.json:
        json.dump(results, open(a.json, "w"), indent=1)
    sys.exit(0 if nfail == 0 else 1)


if __name__ == "__main__":
    main()
