#!/usr/bin/env python3
"""Golden-model coverage of the random generator: successful vs trapping executions per feature.
Usage: coverage.py [N] [SEED0]"""
import collections
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import assemble_src  # noqa: E402
from random_tests import gen_program  # noqa: E402
from sim import Machine  # noqa: E402
from isa import CAP_FUNCS, OP_CAP, OP_CLC, OTYPE_SENTRY, PERM_STORE  # noqa: E402

WATCH = {"cjalr", "csealentry", "cinvoke", "cseal", "cunseal"}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    s0 = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    ok, trap = collections.Counter(), collections.Counter()
    extra = collections.Counter()
    for seed in range(s0, s0 + n):
        b = assemble_src(gen_program(seed))
        m = Machine(b).run(200_000)
        for line in m.trace:
            parts = line.split()
            if parts[0] == "I":
                extra["interrupts"] += 1
                continue
            is_trap = parts[0] == "T"
            pc = int(parts[2 if is_trap else 0], 16)
            w = struct.unpack_from("<I", m.ram, pc)[0] if pc + 4 <= len(m.ram) else 0
            op, fn = w & 63, w >> 24
            name = None
            if op == OP_CAP and fn < len(CAP_FUNCS):
                name = CAP_FUNCS[fn]
            elif op == OP_CLC:
                name = "clc"
            if name is None:
                continue
            if is_trap:
                trap[name] += 1
                continue
            ok[name] += 1
            if name == "cjalr" and len(parts) > 4 and int(parts[7], 16) == OTYPE_SENTRY:
                extra["sentry calls (sentry link)"] += 1
            if name == "clc" and parts[3] == "1" and not int(parts[4]) & PERM_STORE:
                extra["clc results without STORE"] += 1
    for k in sorted(set(ok) | set(trap)):
        if k in WATCH or k == "clc":
            print(f"{k:12s} ok={ok[k]:6d} trap={trap[k]:6d}")
    for k, v in extra.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
