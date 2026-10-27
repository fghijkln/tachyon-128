#!/usr/bin/env python3
"""Differential fuzzing: random programs (randprog.py) compiled by host gcc and by tcc128
(run on the golden simulator); outputs must match exactly.

  fuzz.py N [START_SEED] [-O0] [--keep]
Failing programs are saved to cc/tests/fuzz_failures/seed_<n>.c.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.path.dirname(HERE)
sys.path.insert(0, CC)
sys.path.insert(0, HERE)
from gen_expected import FLAGS, HOSTCC  # noqa: E402
from randprog import Gen  # noqa: E402
from tcc128 import assemble, compile_files, run_sim  # noqa: E402

FAILDIR = os.path.join(HERE, "fuzz_failures")


def host(src_path, exe):
    r = subprocess.run([HOSTCC, *FLAGS, src_path, "-o", exe], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("host compile failed:\n" + r.stderr[:3000])
    try:
        p = subprocess.run([exe], capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        return None
    return p.stdout.decode("latin-1"), p.returncode


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    n = int(args[0]) if args else 100
    start = int(args[1]) if len(args) > 1 else 1
    optimize = "-O0" not in sys.argv
    os.makedirs(FAILDIR, exist_ok=True)
    src = f"/tmp/tcc128_fuzz_{os.getpid()}.c"
    exe = f"/tmp/tcc128_fuzz_{os.getpid()}"
    npass = nfail = nskip = 0
    instr = 0
    t0 = time.time()
    for seed in range(start, start + n):
        prog = Gen(seed).program()
        with open(src, "w") as f:
            f.write(prog)
        exp = host(src, exe)
        if exp is None:
            nskip += 1
            print(f"seed {seed}: host timeout, skipped")
            continue
        try:
            asm = compile_files([src], optimize=optimize)
            m = run_sim(assemble(asm), 20_000_000)
            if m.halted[0] == "timeout":
                nskip += 1
                print(f"seed {seed}: sim instruction limit, skipped")
                continue
            got = (m.console.decode("latin-1"), m.exit_code if m.halted[0] == "exit" else -1)
            instr += m.retired
            err = None
        except Exception as e:  # noqa: BLE001
            got, err = None, f"{type(e).__name__}: {e}"
        if got == exp:
            npass += 1
        else:
            nfail += 1
            path = os.path.join(FAILDIR, f"seed_{seed}{'_O0' if not optimize else ''}.c")
            with open(path, "w") as f:
                f.write(prog)
            detail = err
            if got is not None:
                el, gl = exp[0].splitlines(), got[0].splitlines()
                for k in range(max(len(el), len(gl))):
                    a = el[k] if k < len(el) else "<missing>"
                    b = gl[k] if k < len(gl) else "<missing>"
                    if a != b:
                        detail = f"first diff line {k + 1}: gcc {a!r} tcc128 {b!r}"
                        break
                else:
                    detail = f"exit code gcc {exp[1]} tcc128 {got[1]}"
            print(f"seed {seed}: FAIL {detail} -> {path}")
    dt = time.time() - t0
    print(f"\nfuzz: {npass} pass, {nfail} fail, {nskip} skipped of {n} "
          f"({'-O' if optimize else '-O0'}, {instr} instructions simulated, {dt:.0f}s)")
    sys.exit(1 if nfail else 0)


if __name__ == "__main__":
    main()
