#!/usr/bin/env python3
"""Produce reference outputs for cc/tests/c/*.c with the host C compiler.

The host must provide a C compiler with __int128 (gcc/clang on a 64-bit target). Flags make
host semantics match the tcc128 data model where it matters: signed plain char, wrapping
signed arithmetic. Tests never depend on sizeof(void*) (16 on TACHYON-128, 8 on the host).
A test may instead ship a hand-written expected file named <name>.out.manual (copied as-is).

  gen_expected.py [--force] [pattern ...]
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED = os.path.join(HERE, "expected")
HOSTCC = os.environ.get("HOSTCC", os.path.expanduser("~/bin/gcc") if os.path.exists(
    os.path.expanduser("~/bin/gcc")) else "gcc")
FLAGS = ["-std=gnu99", "-fsigned-char", "-fwrapv", "-fno-strict-aliasing", "-w", "-O1"]


def host_run(path, exe, timeout=60):
    r = subprocess.run([HOSTCC, *FLAGS, path, "-o", exe], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"host compile failed: {r.stderr[:2000]}")
    p = subprocess.run([exe], capture_output=True, timeout=timeout)
    return p.stdout.decode("latin-1"), p.returncode


def main():
    force = "--force" in sys.argv
    pats = [a for a in sys.argv[1:] if not a.startswith("--")]
    os.makedirs(EXPECTED, exist_ok=True)
    tmp = "/tmp/tcc128_host_exe"
    for f in sorted(glob.glob(os.path.join(HERE, "c", "*.c"))):
        name = os.path.splitext(os.path.basename(f))[0]
        if pats and not any(p in name for p in pats):
            continue
        out = os.path.join(EXPECTED, name + ".out")
        manual = os.path.join(HERE, "c", name + ".out.manual")
        if os.path.exists(manual):
            shutil.copy(manual, out)
            continue
        if os.path.exists(out) and not force:
            continue
        stdout, code = host_run(f, tmp)
        with open(out, "w", encoding="latin-1") as fh:
            fh.write(stdout + f"\n---exit {code}\n")
        print(f"{name}: exit {code}, {len(stdout)} bytes")


if __name__ == "__main__":
    main()
