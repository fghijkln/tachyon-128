#!/usr/bin/env python3
"""Mutation sanity check of the verification flow: inject known bugs into copies of the RTL,
rebuild, and confirm the differential test suite catches every one of them."""
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MUTANTS = [
    ("no_memwb_forward", "tx_core.sv",
     "else if (memwb_valid && memwb_we && memwb_rd == idex_rs1)", "else if (1'b0)"),
    ("no_load_use_stall", "tx_core.sv", "wire stall_lu = ifid_valid & ex_is_late &", "wire stall_lu = 1'b0 & ex_is_late &"),
    ("cap_bounds_off_by_one", "tx_core.sv", "ea_end > a_top))", "ea_end > a_top + 129'd1))"),
    ("simd_unsigned_sat", "tx_simd.sv", "r = uadd[W] ? {W{1'b1}} : uadd[W-1:0];", "r = uadd[W] ? '0 : uadd[W-1:0];"),
    ("div_cache_ignores_b", "tx_muldiv.sv", "(c_a == a) && (c_b == b)", "(c_a == a)"),
    ("mispredict_taken_missed", "tx_core.sv", "(br_taken != idex_pred)", "(br_taken & ~idex_pred)"),
    ("csetbnd_no_monotonic", "tx_core.sv", "else if (a < a_base || cap_ntop > a_top)", "else if (a < a_base)"),
    ("wb_bypass_missing", "tx_core.sv",
     "if (wb_we && memwb_rd == id_rs1) begin id_v1 = memwb_val; id_m1 = memwb_meta; end", ""),
]


def main():
    sel = sys.argv[1:] or [m[0] for m in MUTANTS]
    for name, f, old, new in MUTANTS:
        if name not in sel:
            continue
        d = os.path.join(ROOT, "build", "mut", name)
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(os.path.join(ROOT, "rtl"), os.path.join(d, "rtl"))
        shutil.copytree(os.path.join(ROOT, "tb"), os.path.join(d, "tb"))
        p = os.path.join(d, "rtl", f)
        s = open(p).read()
        assert old in s, (name, old)
        open(p, "w").write(s.replace(old, new, 1))
        b = subprocess.run(["bash", os.path.join(d, "tb", "build.sh")], capture_output=True, text=True)
        if b.returncode:
            print(f"{name}: BUILD FAILED"); continue
        env = dict(os.environ, TX_VTB=os.path.join(d, "build", "vtb", "Vtb"), TX_NOSAVE="1",
                   TX_WORK=os.path.join(d, "work"))
        t = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "run_tests.py"), "all", "60"],
                           capture_output=True, text=True, env=env)
        summary = [l for l in t.stdout.splitlines() if l.startswith("[")]
        print(f"{name}: {'CAUGHT' if t.returncode else 'MISSED'}  " + "  ".join(summary), flush=True)


if __name__ == "__main__":
    main()
