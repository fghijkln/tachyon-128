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
    ("mispredict_taken_missed", "tx_core.sv", "ex_k[K_BR] ? (br_taken ? br_target : ex_pc4)",
     "ex_k[K_BR] ? (br_taken ? idex_pnpc : ex_pc4)"),
    ("csetbnd_no_monotonic", "tx_core.sv", "else if (a < a_base || cap_ntop > a_top)", "else if (a < a_base)"),
    ("wb_bypass_missing", "tx_core.sv",
     "if (wb_we && memwb_rd == id_rs1) begin id_v1 = memwb_val; id_m1 = memwb_meta; end", ""),
    # ---- v2 features
    ("tag_not_cleared_by_data_store", "../tb/tb.sv",
     "tmeta[dmem_addr[RB-1:4]] <= dmem_wmeta;", "if (dmem_wmeta[M_TAG]) tmeta[dmem_addr[RB-1:4]] <= dmem_wmeta;"),
    ("clc_ignores_load_cap", "tx_core.sv", "exmem_ldcap <= ~a_tag | a_perm[3];", "exmem_ldcap <= 1'b1;"),
    ("csc_no_store_cap_check", "tx_core.sv",
     "else if (a_tag && capst && b_tag && !a_perm[4]) mem_cause = C_CAP_PERM;", ""),
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
    ("sentry_link_not_sealed", "tx_core.sv", "a_sentry ? OTYPE_SENTRY : 16'd0", "16'd0"),
    ("cinvoke_no_otype_match", "tx_core.sv", " || mb[M_OT +: 16] != a_ot)", ")"),
    ("clc_no_ro_attenuation", "tx_core.sv", "clc_ro   = exmem_ldro &", "clc_ro   = 1'b0 &"),
    ("pcc_keeps_sentry_seal", "tx_core.sv", "ma_unsealed = {ma[M_TAG], 16'd0, ma[M_OT-1:0]};", "ma_unsealed = ma;"),
    ("priv_csr_in_user_allowed", "tx_core.sv", "exmem_priv   <= ex_k[K_CSRR] | ", "exmem_priv   <= "),
    ("user_window_no_lower_check", "tx_core.sv", "hyb_out   = (exmem_ea < csr_ubase) |", "hyb_out   = 1'b0 |"),
    ("eret_no_mode_restore", "tx_core.sv", "{1'b0, csr_status[4], csr_status[2], 1'b1, csr_status[1]}",
     "{1'b0, 1'b0, csr_status[2], 1'b1, csr_status[1]}"),
    ("csrw_can_set_user_bit", "tx_core.sv", "{exmem_val[4], csr_status[3], exmem_val[2:0]}", "exmem_val[4:0]"),
    ("priv_store_not_squashed", "tx_core.sv", "assign dmem_we    = mem_v & exmem_store & ~exmem_trap &",
     "assign dmem_we    = mem_v & exmem_store & ~exmem_trap0 &"),
    ("btb_not_taken_uncorrected", "tx_core.sv", "ex_k[K_BR] ? (br_taken ? br_target : ex_pc4)",
     "ex_k[K_BR] ? (br_taken ? br_target : idex_pnpc)"),
    ("btb_jalr_target_low_bits_only", "tx_core.sv", "ex_k[K_JALR] ? jalr_tgt : ex_pc4;",
     "ex_k[K_JALR] ? {jalr_tgt[127:18], idex_pnpc[17:0]} : ex_pc4;"),
    # ---- v4 features
    ("booth_no_lane_closing_digit", "tx_mul32x4.sv", "s = s + ({32'd0, a & pm & {32{b[2*j-1] & bnd}}} << (2*j));", "s = s;"),
    ("booth_lane_boundary_bit_kept", "tx_mul32x4.sv", "(b[2*j-1] & ~bnd);", "b[2*j-1];"),
    ("booth_top_digit_ignores_lane", "tx_mul32x4.sv", "((s16 | s8) ? pm : 32'hFFFF_FFFF)", "32'hFFFF_FFFF"),
    ("shared_mul_16b_mode_wrong", "tx_core.sv", "ex_fn[1:0] == 2'd1 ? 2'd1 : 2'd0", "ex_fn[1:0] == 2'd1 ? 2'd2 : 2'd0"),
    ("shared_mul_not_claimed", "tx_core.sv", ".x(sh_busy ? sh_x : a)", ".x(a)"),
    ("mul_pass_product_misaligned", "tx_muldiv.sv", "{sh_p[255:192], sh_p[127:64], 32'd0}", "{sh_p[223:192], sh_p[127:64], 64'd0}"),
    ("ras_return_not_verified", "tx_core.sv", "ex_k[K_JALR] ? jalr_tgt : ex_pc4;",
     "(ex_k[K_JALR] & idex_ret) ? idex_pnpc : ex_k[K_JALR] ? jalr_tgt : ex_pc4;"),
    ("ras_no_restore_on_trap", "tx_core.sv", "for (int i = 0; i < RAS_N; i++) ras_s[i] <= ras_c[i];\n        ras_sp <= ras_cp;", ""),
    ("ras_no_if_bypass", "tx_core.sv", "wire  [15:0] if_ras_top = (ifid_valid & id_call) ? id_link_w :",
     "wire  [15:0] if_ras_top = 1'b0 ? id_link_w :"),
    ("ras_pop_missing", "tx_core.sv", "else ras_sp <= ras_t1;", "else ;"),
    ("ras_btb_ret_bit_ignored", "tx_core.sv", "(btb_ret[if_bi] & ras_on) ?", "1'b0 ?"),
    ("local_cap_store_unchecked", "tx_core.sv",
     "else if (a_tag && capst && b_tag && !b_perm[P_GLOBAL] && !a_perm[P_STORE_LOCAL]) mem_cause = C_CAP_PERM;", ""),
    ("local_rule_tests_authority", "tx_core.sv", "!b_perm[P_GLOBAL] && !a_perm[P_STORE_LOCAL]",
     "!a_perm[P_GLOBAL] && !a_perm[P_STORE_LOCAL]"),
    ("lm_rule_uses_store_bit", "tx_core.sv", "exmem_ldro  <= a_tag & ~a_perm[P_LM];", "exmem_ldro  <= a_tag & ~a_perm[1];"),
    ("lm_strip_keeps_lm_bit", "tx_core.sv", "MW'(PERM_LM_STRIP)", "MW'(11'h412)"),
    ("cinvoke_data_ci_unchecked", "tx_core.sv",
     "else if (!b_perm[P_CINVOKE]) begin cap_cause = C_CAP_PERM; cap_tv = b; end", ""),
    ("sc_ignores_reservation", "tx_core.sv", "& ~(mem_sc & ~resv_hit);", ";"),
    ("resv_kept_across_store", "tx_core.sv", "end else if (mem_v && !exmem_trap && exmem_store) resv_v <= 1'b0;", "end"),
    ("resv_kept_across_trap", "tx_core.sv", "if (mem_trap) resv_v <= 1'b0;", "if (1'b0) resv_v <= 1'b0;"),
    ("resv_granule_unchecked", "tx_core.sv", "resv_v & (resv_g == exmem_ea[RB-1:4]);", "resv_v;"),
    ("amo_arith_keeps_tag", "tx_core.sv", "exmem_csc   <= capst; ", "exmem_csc   <= capst | is_amo; "),
    ("amo_no_load_use_interlock", "tx_core.sv", " || idex_inst[5:0] == OP_AMO ||", " ||"),
    ("amo_mmio_allowed", "tx_core.sv", "(!in_mmio || is_amo)", "!in_mmio"),
    ("amoswap_no_store_cap_check", "tx_core.sv", "((amo_fn == AMO_SC) | (amo_fn == AMO_SWAP)));  // stores rs2's tag",
     "(amo_fn == AMO_SC));  // stores rs2's tag"),
    ("cgetepcc_reads_in_ex", "tx_core.sv", "exmem_getepcc ? csr_epc : exmem_val);", "exmem_val);"),
    ("cgetepcc_user_allowed", "tx_core.sv", "ex_setepcc | ex_getepcc;", "ex_setepcc;"),
    ("cgetepcc_no_interlock", "tx_core.sv", " ||   // AMO results come from MEM\n                    (idex_inst[5:0] == OP_CAP && idex_inst[28:24] == CF_CGETEPCC));",
     ");"),
    # ---- v5 32-bit word ops
    ("word_result_not_sign_extended", "tx_alu.sv", "wire [127:0] wy = {{96{w[31] & ~wu}}, w};", "wire [127:0] wy = {96'd0, w};"),
    ("word_wu_sign_extends", "tx_alu.sv", "{{96{w[31] & ~wu}}, w}", "{{96{w[31]}}, w}"),
    ("sraw_is_logical", "tx_alu.sv", "default:         w = $unsigned($signed(a[31:0]) >>> b[4:0]);",
     "default:         w = a[31:0] >> b[4:0];"),
    ("sllw_6bit_shamt", "tx_alu.sv", "w = a[31:0] << b[4:0];", "w = a[31:0] << b[5:0];"),
    ("addiw_decoded_as_addi", "tx_core.sv", "OP_ADDIW: alu_fn = A_ADDW;", "OP_ADDIW: alu_fn = A_ADD;"),
    ("mulw_low_word_misplaced", "tx_muldiv.sv", "cnt <= w1 ? 8'(32 / MUL_BITS) : 8'(MPASS);", "cnt <= 8'(MPASS);"),
    ("mulw_shares_mul_cache_kind", "tx_muldiv.sv", "(is_mul & w1) ? 3'd4 : ", ""),
    ("divw_operands_not_extended", "tx_core.sv", "wire [127:0] md_a = md_dw ? {{96{a[31]}}, a[31:0]} : a;", "wire [127:0] md_a = a;"),
    ("mulwu_sign_extends", "tx_core.sv", "md_y[31] & (ex_fn != MD_MULWU)", "md_y[31]"),
    ("irq_store_not_squashed", "tx_core.sv", "assign dmem_we    = mem_v & exmem_store", "assign dmem_we    = exmem_valid & exmem_store"),
    # ---- v6: cmove (exact register copy, sealed capabilities included)
    ("cmove_drops_seal", "tx_core.sv", "CF_CMOVE: begin cap_y = a; cap_m = ma; end",
     "CF_CMOVE: begin cap_y = a; cap_m = {ma[M_TAG], 16'd0, ma[M_OT-1:0]}; end"),
    ("cmove_clears_tag", "tx_core.sv", "CF_CMOVE: begin cap_y = a; cap_m = ma; end", "CF_CMOVE: begin cap_y = a; end"),
    ("cmove_traps_on_sealed", "tx_core.sv", "if (cap_fn <= 5'd3 && a_sealed)", "if ((cap_fn <= 5'd3 || cap_fn == CF_CMOVE) && a_sealed)"),
    ("cmove_decoded_illegal", "tx_defs.svh", "N_CAP = 8'd19", "N_CAP = 8'd18"),
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
