#!/usr/bin/env python3
"""tcc128 test suite: compile every cc/tests/c/*.c, run it on the golden simulator and compare
stdout + exit code with the reference output in cc/tests/expected/ (produced by host gcc,
see gen_expected.py).

  run_tests.py [-O0] [--both] [--purecap] [pattern ...]
"""
import argparse
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.path.dirname(HERE)
sys.path.insert(0, CC)
from tcc128 import assemble, compile_files, run_sim  # noqa: E402
from compiler.lexer import CompileError  # noqa: E402

EXPECTED = os.path.join(HERE, "expected")


def run_one(path, optimize=True, max_steps=30_000_000, purecap=False, rtl=False):
    asm = compile_files([path], optimize=optimize, purecap=purecap)
    binary = assemble(asm)
    if rtl:     # also run on the Verilator model; the commit trace must match the golden model
        sys.path.insert(0, os.path.join(os.path.dirname(CC), "tests"))
        from harness import run_diff
        name = os.path.splitext(os.path.basename(path))[0] + ("" if optimize else "_O0") + ("_pc" if purecap else "")
        r = run_diff(name, binary, os.path.join(os.path.dirname(CC), "build", "cctests"), max_steps=max_steps)
        if not r.ok:
            raise RuntimeError("RTL: " + r.msg)
    m = run_sim(binary, max_steps, audit_untagged=purecap)
    if m.untagged_ram:      # purecap must never fall back to unchecked (untagged-base) RAM accesses
        raise RuntimeError("untagged RAM access at pc " + ", ".join(f"{pc:#x}x{n}" for pc, n in m.untagged_ram.items()))
    code = m.exit_code if m.halted[0] == "exit" else f"{m.halted[0]}:{m.halted[1]}"
    return m.console.decode("latin-1"), code, m.retired, len(binary)


def fmt_result(out, code):
    return out + f"\n---exit {code}\n"


HEX32 = re.compile(r"\b[0-9a-f]{32}\b")


def placeholders(text):
    """purecap fault tests: each distinct 32-hex-digit value (an address printed by the program, the trap's
    tval) becomes <A>, <B>, ... in order of appearance, so the expected file pins equalities, not layout."""
    names = {}
    return HEX32.sub(lambda m: names.setdefault(m.group(0), f"<{chr(65 + len(names))}>"), text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("patterns", nargs="*")
    ap.add_argument("-O0", action="store_true")
    ap.add_argument("--both", action="store_true")
    ap.add_argument("--json")
    ap.add_argument("--rtl", action="store_true", help="also run every test on the RTL model (trace-checked)")
    ap.add_argument("--regen-purecap", action="store_true", help="rewrite cc/tests/purecap/*.out from this run")
    ap.add_argument("--purecap", action="store_true",
                    help="compile with -mpurecap; also runs cc/tests/purecap/*.c (capability-fault tests)")
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(HERE, "c", "*.c")))
    if a.purecap:
        files += sorted(glob.glob(os.path.join(HERE, "purecap", "*.c")))
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
            pc_test = os.path.basename(os.path.dirname(f)) == "purecap"
            if pc_test:
                exp_path = f[:-2] + ".out"
                if a.regen_purecap:
                    out, code, _, _ = run_one(f, opt, purecap=True)
                    open(exp_path, "w").write(placeholders(fmt_result(out, code)))
            elif a.purecap and os.path.exists(exp_path + ".purecap"):
                exp_path += ".purecap"      # output that legitimately differs under -mpurecap
            if not os.path.exists(exp_path):
                print(f"SKIP {name} (no expected output)")
                continue
            exp = open(exp_path, encoding="latin-1").read()
            try:
                out, code, retired, size = run_one(f, opt, purecap=a.purecap, rtl=a.rtl)
                got = fmt_result(out, code)
                if pc_test:
                    got = placeholders(got)
                ok = got == exp
                err = None
            except CompileError as e:
                ok, got, retired, size, err = False, "", 0, 0, str(e)
            except Exception as e:   # assembler errors etc.
                ok, got, retired, size, err = False, "", 0, 0, f"{type(e).__name__}: {e}"
            tag = ("-O " if opt else "-O0") + (" purecap" if a.purecap else "")
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
            results.append({"name": name, "opt": opt, "purecap": a.purecap, "pass": ok, "retired": retired, "size": size})
    print(f"\n{npass}/{npass + nfail} passed in {time.time() - t0:.1f}s")
    if a.json:
        json.dump(results, open(a.json, "w"), indent=1)
    sys.exit(0 if nfail == 0 else 1)


if __name__ == "__main__":
    main()
