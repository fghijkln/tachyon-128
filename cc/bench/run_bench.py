#!/usr/bin/env python3
"""tcc128 benchmarks: compile cc/bench/*.c, run on the golden simulator (retired instructions,
exit code must be 0) and optionally on the Verilator RTL model via tests/harness.run_diff
(full commit-trace/console/RAM comparison against golden, plus cycles and CPI).

  run_bench.py [--rtl] [-O0] [--both] [--json out.json] [name ...]
"""
import argparse
import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CC = os.path.dirname(HERE)
ROOT = os.path.dirname(CC)
sys.path.insert(0, CC)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from tcc128 import assemble, compile_files, run_sim  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*")
    ap.add_argument("--rtl", action="store_true")
    ap.add_argument("-O0", action="store_true")
    ap.add_argument("--both", action="store_true")
    ap.add_argument("--json")
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(HERE, "*.c")))
    if a.names:
        files = [f for f in files if any(n in os.path.basename(f) for n in a.names)]
    modes = [False, True] if a.both else [not a.O0]
    rows = []
    bad = 0
    for opt in modes:
        for f in files:
            name = os.path.splitext(os.path.basename(f))[0]
            t0 = time.time()
            binary = assemble(compile_files([f], optimize=opt))
            m = run_sim(binary, 200_000_000)
            ok = m.halted[0] == "exit" and m.exit_code == 0
            row = {"name": name, "opt": "-O" if opt else "-O0", "size": len(binary),
                   "retired": m.retired, "ok": ok, "out": m.console.decode("latin-1").strip()}
            if a.rtl:
                from harness import run_diff
                r = run_diff(f"bench_{name}{'' if opt else '_O0'}", binary,
                             os.path.join(ROOT, "build", "ccbench"), max_steps=200_000_000)
                row.update(rtl_ok=r.ok, rtl_msg=r.msg, cycles=r.cycles,
                           cpi=round(r.cpi, 3) if r.cycles else None)
                ok = ok and r.ok
            bad += not ok
            rows.append(row)
            extra = f" cycles={row['cycles']} CPI={row['cpi']} rtl={'ok' if row['rtl_ok'] else row['rtl_msg']}" \
                if a.rtl else ""
            print(f"{'OK ' if ok else 'BAD'} {row['opt']:3} {name:14} retired={m.retired:>10} "
                  f"size={len(binary):>6}{extra}  ({time.time() - t0:.1f}s)  | {row['out'][:60]}", flush=True)
    if a.json:
        json.dump(rows, open(a.json, "w"), indent=1)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
