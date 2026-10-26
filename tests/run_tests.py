#!/usr/bin/env python3
"""TACHYON-128 test runner: golden-vs-RTL differential testing.

  run_tests.py unit            per-instruction directed tests
  run_tests.py programs        demo programs (+ exact-value checks of their output)
  run_tests.py random N [SEED] N random instruction-stream programs
  run_tests.py all [N]         everything (default N=200 random)
Results are appended to build/results.json.
"""
import json
import math
import os
import sys
import time
from multiprocessing import Pool

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import ROOT, assemble_path, assemble_src, run_diff  # noqa: E402

PROGRAMS = ["fib", "fact", "sort", "simd", "capfault", "caplist", "timer"]
WORK = os.environ.get("TX_WORK", os.path.join(ROOT, "build", "work"))


def fib(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def lcg_sorted():
    x = 0x0123456789abcdef0fedcba987654321
    A, C = 0x2360ed051fc65da44385df649fccf645, 0x5851f42d4c957f2d14057b7ef767814f
    v = []
    for _ in range(24):
        x = (x * A + C) % (1 << 128)
        v.append(x)
    return sorted(v)


def expect_program(name):
    def chk(m):
        out = m.console.decode()
        if m.halted != ("exit", 0) and not (name == "sort" and m.halted[0] == "exit"):
            return f"halted {m.halted}"
        if name == "fib":
            for n in (10, 50, 93, 94, 100, 150, 180):
                if f"fib({n}) = {fib(n)}\n" not in out:
                    return f"fib({n}) wrong"
        if name == "fact":
            for n in range(30, 35):
                if f"{n}! = {math.factorial(n)}\n" not in out:
                    return f"{n}! wrong"
            if f"(mulhu) = {(math.factorial(34) * 35) >> 128}" not in out:
                return "mulhu wrong"
        if name == "sort":
            s = lcg_sorted()
            if f"min      = {s[0]:032x}" not in out or f"max      = {s[-1]:032x}" not in out \
                    or "inversions = 0" not in out:
                return "sort result wrong"
        if name == "simd":
            if "dot(1..8,8..1)  = " + f"{120:032x}" not in out or f"SAD(16 bytes)   = {0x3ff:032x}" not in out:
                return "simd result wrong"
        if name == "capfault":
            if out.count("!! trap cause=") != 3 or "faults caught = 3" not in out \
                    or "tag after mv (forge attempt) = 0" not in out:
                return "capfault behaviour wrong"
        if name == "caplist":
            v = 0x1000000000000000000000001
            if "nodes walked        = 6\n" not in out or f"payload sum         = {21 * v:032x}" not in out \
                    or "nodes after forge   = 3\n" not in out or f"{15 * v:032x}" not in out \
                    or "nodes via read-only = 3\n" not in out or "faults caught = 3\n" not in out \
                    or [l for l in out.splitlines() if "trap cause" in l] != \
                    ["  !! trap cause=2", "  !! trap cause=3", "  !! trap cause=4"]:
                return "caplist behaviour wrong"
        if name == "timer":
            ticks = sum(1 for l in m.trace if l.startswith("I 1 "))
            if f"sum(i^2, 1..1000) = {sum(i * i for i in range(1, 1001))}\n" not in out \
                    or f"timer ticks       = {ticks}\n" not in out or ticks < 10 or out.splitlines()[0] != "." * ticks:
                return "timer behaviour wrong"
        return None
    return chk


def _job(args):
    kind, name, payload, seed = args
    if kind == "src":
        binary = assemble_src(payload)
        return run_diff(name, binary, WORK)
    if kind == "prog":
        return run_diff(name, assemble_path(payload), WORK, expect=expect_program(name))
    if kind == "rand":
        from random_tests import gen_program
        return run_diff(name, assemble_src(gen_program(seed)), WORK, max_steps=200_000)
    raise ValueError(kind)


def run(jobs, label):
    t0 = time.time()
    with Pool(2) as p:
        results = p.map(_job, jobs, chunksize=1)
    fails = [r for r in results if not r.ok]
    for r in fails:
        print(f"FAIL {r.name}: {r.msg}")
    cyc = sum(r.cycles for r in results if r.ok)
    ret = sum(r.retired for r in results if r.ok)
    print(f"[{label}] {len(results) - len(fails)}/{len(results)} passed "
          f"({time.time() - t0:.1f}s, cycles={cyc}, retired={ret}, CPI={cyc / max(ret, 1):.3f})")
    return results


def save(label, results):
    if os.environ.get("TX_NOSAVE"):
        return
    path = os.path.join(ROOT, "build", "results.json")
    db = json.load(open(path)) if os.path.exists(path) else {}
    db[label] = {"passed": sum(r.ok for r in results), "total": len(results),
                 "cycles": sum(r.cycles for r in results if r.ok),
                 "retired": sum(r.retired for r in results if r.ok),
                 "per_test": {r.name: {"ok": r.ok, "cycles": r.cycles, "retired": r.retired,
                                       "cpi": round(r.cpi, 3)} for r in results}}
    json.dump(db, open(path, "w"), indent=1)


def main():
    os.makedirs(WORK, exist_ok=True)
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    rc = 0
    if what in ("unit", "all"):
        from unit_tests import tests
        res = run([("src", n, s, 0) for n, s in tests().items()], "unit")
        save("unit", res)
        rc |= any(not r.ok for r in res)
    if what in ("programs", "all"):
        progs = PROGRAMS
        res = run([("prog", p, os.path.join(ROOT, "programs", p + ".s"), 0) for p in progs], "programs")
        for r in res:
            print(f"   {r.name:9s} cycles={r.cycles:7d} retired={r.retired:6d} CPI={r.cpi:.3f}")
        save("programs", res)
        rc |= any(not r.ok for r in res)
    if what in ("random", "all"):
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 200
        seed0 = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        res = run([("rand", f"rand_{s}", None, s) for s in range(seed0, seed0 + n)], "random")
        save("random", res)
        rc |= any(not r.ok for r in res)
    sys.exit(1 if rc else 0)


if __name__ == "__main__":
    main()
