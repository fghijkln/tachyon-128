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
    # ---- v2 features
    ("tag_not_cleared_by_data_store", "../tb/tb.sv",
     "tmeta[dmem_addr[RB-1:4]] <= dmem_wmeta;", "if (dmem_wmeta[M_TAG]) tmeta[dmem_addr[RB-1:4]] <= dmem_wmeta;"),
    ("clc_ignores_load_cap", "tx_core.sv", "exmem_ldcap <= ~a_tag | a_perm[3];", "exmem_ldcap <= 1'b1;"),
    ("csc_no_store_cap_check", "tx_core.sv",
     "else if (a_tag && is_csc && b_tag && !a_perm[4]) mem_cause = C_CAP_PERM;", ""),
    ("pcc_no_fetch_top_check", "tx_core.sv", "| (if_end > fpcc_q[128:0]);", "| 1'b0;"),
    ("eret_no_fetch_pcc_restore", "tx_core.sv", "mem_tpcc  = mem_eret ? epcc_q : ROOT_META;", "mem_tpcc  = ROOT_META;"),
    ("sealed_deref_allowed", "tx_core.sv", "if (a_sealed) mem_cause = C_CAP_SEALED;", "if (1'b0) mem_cause = C_CAP_SEALED;"),
    ("unseal_no_otype_check", "tx_core.sv",
     "else if (cap_fn == CF_CUNSEAL && b != {112'd0, a_ot}) cap_cause = C_CAP_SEALED;", ""),
    ("div_r4_never_digit3", "tx_muldiv.sv", "if (!d3[130])      r4step", "if (1'b0)          r4step"),
    ("div_early_term_off_by_one", "tx_muldiv.sv", "{1'b0, lz} + 9'd1);", "{1'b0, lz} + 9'd0);"),
    ("irq_ignores_tie", "tx_core.sv", "irq_pend  = csr_status[0] & csr_status[2] &", "irq_pend  = csr_status[0] &"),
    ("mtime_counts_traps", "tx_core.sv", "if (mem_v && !exmem_trap) mtime_q <=", "if (mem_v) mtime_q <="),
    # ---- v3 features
    ("mul_pass_drops_carry", "tx_muldiv.sv", "acc_nx = {mstep, acc[127:MUL_BITS]};",
     "acc_nx = {1'b0, mstep[126+MUL_BITS:0], acc[127:MUL_BITS]};"),
    ("mul_last_pass_stale", "tx_muldiv.sv", "c_hi <= acc_nx[255:128];", "c_hi <= acc[255:128];"),
    ("irq_store_not_squashed", "tx_core.sv", "assign dmem_we    = mem_v & exmem_store", "assign dmem_we    = exmem_valid & exmem_store"),
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
        p = os.path.normpath(os.path.join(d, "rtl", f))
        s = open(p).read()
        assert old in s, (name, old)
        open(p, "w").write(s.replace(old, new, 1))
        b = subprocess.run(["bash", os.path.join(d, "tb", "build.sh")], capture_output=True, text=True,
                           env=dict(os.environ, TX_VTB_DIR=os.path.join(d, "build", "vtb")))
        if b.returncode:
            print(f"{name}: BUILD FAILED {b.stdout[-300:]}{b.stderr[-300:]}")
            continue
        env = dict(os.environ, TX_VTB_DIR=os.path.join(d, "build", "vtb"), TX_VTB=os.path.join(d, "build", "vtb", "Vtb"), TX_NOSAVE="1",
                   TX_WORK=os.path.join(d, "work"))
        t = subprocess.run([sys.executable, os.path.join(ROOT, "tests", "run_tests.py"), "all", "200"],
                           capture_output=True, text=True, env=env)
        summary = [l for l in t.stdout.splitlines() if l.startswith("[")]
        print(f"{name}: {'CAUGHT' if t.returncode else 'MISSED'}  " + "  ".join(summary), flush=True)
        shutil.rmtree(d, ignore_errors=True)        # Verilator objects are ~300 MB per mutant


if __name__ == "__main__":
    main()
