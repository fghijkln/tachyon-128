// TACHYON-128 core: classic 5-stage in-order pipeline (IF ID EX MEM WB)
//  * full forwarding EX/MEM->EX and MEM/WB->EX, regfile write-through to ID
//  * 1-cycle load-use (and CSR-read-use) interlock
//  * JAL redirected in ID; conditional branches statically predicted in ID
//    (backward = taken, forward = not taken) and verified in EX; JALR resolved in EX
//  * iterative MUL/DIV in EX stalls the front end
//  * traps, ERET and HALT are taken precisely in MEM
//  * every GPR is a "fat" register: 128-bit value + capability tag/perms/base/top
`default_nettype none
module tx_core #(
  parameter int RAM_BYTES = 262144
) (
  input  wire logic         clk,
  input  wire logic         rst,
  // instruction port (combinational read)
  output logic      [127:0] imem_addr,
  input  wire logic [31:0]  imem_rdata,
  // data port (combinational read, synchronous write)
  output logic      [127:0] dmem_addr,
  output logic              dmem_re,
  output logic              dmem_we,
  output logic      [15:0]  dmem_be,
  output logic      [127:0] dmem_wdata,
  input  wire logic [127:0] dmem_rdata,
  // shadow tag memory (one tag + capability metadata per 16-byte granule), same address/strobe
  output logic      [MW-1:0] dmem_wmeta,   // written on every RAM store: 0 for data stores, cap for csc
  input  wire logic [MW-1:0] dmem_rmeta,
  // status
  output logic              halted,
  output logic      [31:0]  exit_code,
  // commit trace (WB)
  output logic              tr_valid,
  output logic      [127:0] tr_pc,
  output logic              tr_we,
  output logic      [5:0]   tr_rd,
  output logic      [127:0] tr_val,
  output logic      [MW-1:0] tr_meta,
  output logic              tr_trap,
  output logic              tr_irq,
  output logic      [3:0]   tr_cause,
  output logic      [127:0] tr_tval
);
  `include "tx_defs.svh"
  localparam int RB = $clog2(RAM_BYTES);

  // decoded instruction class bits
  localparam int K_ALUR = 0, K_MD = 1, K_SIMD = 2, K_CAPR = 3, K_ALUI = 4, K_CAPI = 5, K_WIDE = 6,
                 K_LOAD = 7, K_STORE = 8, K_BR = 9, K_JAL = 10, K_JALR = 11, K_HALT = 12,
                 K_CSRR = 13, K_CSRW = 14, K_ERET = 15, K_ILL = 16, K_ECALL = 17, K_AMO = 18, NK = 19;

  function automatic logic [NK-1:0] decode(input logic [31:0] i);
    logic [5:0] op; logic [7:0] fn; logic [NK-1:0] k;
    op = i[5:0]; fn = i[31:24]; k = '0;
    case (op)
      OP_ALU:    if (fn < N_ALU) k[K_ALUR] = 1; else k[K_ILL] = 1;
      OP_MULDIV: if (fn < N_MULDIV) k[K_MD] = 1; else k[K_ILL] = 1;
      OP_SIMD:   if (fn[7:2] < N_SIMD && !(fn[7:2] == {1'b0, SIMD_VMUL} && fn[1:0] == 2'd3)) k[K_SIMD] = 1;
                 else k[K_ILL] = 1;
      OP_CAP:    if (fn < N_CAP) k[K_CAPR] = 1; else k[K_ILL] = 1;
      OP_AMO:    if (fn < N_AMO) k[K_AMO] = 1; else k[K_ILL] = 1;
      OP_ADDI, OP_ANDI, OP_ORI, OP_XORI, OP_SLTI, OP_SLTIU, OP_SLLI, OP_SRLI, OP_SRAI,
      OP_ADDIW, OP_SLLIW, OP_SRLIW, OP_SRAIW, OP_ADDIWU, OP_SLLIWU: k[K_ALUI] = 1;
      OP_CINCADDRI, OP_CSETBNDI: k[K_CAPI] = 1;
      OP_WIDE:   k[K_WIDE] = 1;
      OP_LB, OP_LH, OP_LW, OP_LD, OP_LQ, OP_LBU, OP_LHU, OP_LWU, OP_LDU, OP_CLC: k[K_LOAD] = 1;
      OP_SB, OP_SH, OP_SW, OP_SD, OP_SQ, OP_CSC: k[K_STORE] = 1;
      OP_BEQ, OP_BNE, OP_BLT, OP_BGE, OP_BLTU, OP_BGEU: k[K_BR] = 1;
      OP_JAL:    k[K_JAL] = 1;
      OP_JALR:   k[K_JALR] = 1;
      OP_HALT:   k[K_HALT] = 1;
      OP_CSRR:   if (i[31:18] < N_CSR) k[K_CSRR] = 1; else k[K_ILL] = 1;
      OP_CSRW:   if (i[31:18] < N_CSR) k[K_CSRW] = 1; else k[K_ILL] = 1;
      OP_ERET:   k[K_ERET] = 1;
      OP_ECALL:  k[K_ECALL] = 1;
      default:   k[K_ILL] = 1;
    endcase
    decode = k;
  endfunction

  function automatic logic writes_rd(input logic [NK-1:0] k);
    writes_rd = k[K_ALUR] | k[K_MD] | k[K_SIMD] | k[K_CAPR] | k[K_ALUI] | k[K_CAPI] | k[K_WIDE] |
           k[K_LOAD] | k[K_JAL] | k[K_JALR] | k[K_CSRR] | k[K_AMO];
  endfunction

  // ======================================================================== state
  logic         halted_q, stop_fetch_q;
  logic [31:0]  exit_q;
  logic [127:0] pc_q;
  // program-counter capabilities: fpcc = PCC used by fetch (updated at the cjalr redirect in EX),
  // pcc = architectural PCC (updated when cjalr passes MEM), epcc = PCC saved by a trap
  logic [MW-1:0] fpcc_q, pcc_q, epcc_q;
  // IF/ID
  logic         ifid_valid, ifid_fault;
  logic [3:0]   ifid_fcause, idex_fcause;
  logic [127:0] ifid_pc;
  logic [31:0]  ifid_inst;
  // ID/EX
  logic         idex_valid, idex_fault, idex_we;
  logic         ifid_bpred, ifid_bhit;        // BTB predicted taken / BTB hit for this fetch
  logic [127:0] ifid_pnpc, idex_pnpc;         // predicted next pc carried with the instruction
  logic [127:0] idex_pc, idex_v1, idex_v2;
  logic [MW-1:0] idex_m1, idex_m2;
  logic [31:0]  idex_inst;
  logic [5:0]   idex_rs1, idex_rs2, idex_rd;
  // EX/MEM
  logic         exmem_valid, exmem_we, exmem_load, exmem_store, exmem_trap0, exmem_csrr,
                exmem_csrw, exmem_eret, exmem_halt, exmem_mmio, exmem_clc, exmem_csc, exmem_ldcap, exmem_ldro;
  logic [MW-1:0] exmem_smeta, exmem_tmeta;
  logic         exmem_cjalr, exmem_setepcc;
  logic         idex_call, idex_ret, exmem_call, exmem_ret;   // RAS classification (v4)
  logic         exmem_amo;                                    // v4 atomic in MEM (fn in exmem_amofn)
  logic         exmem_getepcc;                                // v4 cgetepcc: value read in MEM
  logic [2:0]   exmem_amofn;
  logic         resv_v;                                       // lr/sc reservation (valid, granule)
  logic [RB-5:0] resv_g;
  logic [127:0] exmem_pc, exmem_val, exmem_ea, exmem_sdata, exmem_tval0;
  logic [128:0] exmem_eaend;
  logic         exmem_priv, exmem_hyb;     // privileged instruction / untagged-base memory access
  logic [31:0]  exmem_inst;
  logic [MW-1:0] exmem_meta;
  logic [5:0]   exmem_rd, exmem_op;
  logic [3:0]   exmem_cause0;
  logic [2:0]   exmem_csr;
  logic [31:0]  exmem_code;
  // MEM/WB
  logic         memwb_valid, memwb_we, memwb_trap, memwb_halt, memwb_irq;
  logic [127:0] memwb_pc, memwb_val, memwb_tval;
  logic [MW-1:0] memwb_meta;
  logic [5:0]   memwb_rd;
  logic [3:0]   memwb_cause;
  logic [31:0]  memwb_code;
  // CSRs
  logic [127:0] csr_tvec, csr_epc, csr_cause, csr_tval, csr_scratch;
  logic [4:0]   csr_status;            // {PU, U, TIE, PIE, IE}
  logic [127:0] csr_ubase, csr_ubound;  // user-mode window for untagged (hybrid) data accesses
  // ---- privilege check (MEM): user mode may not execute privileged instructions, and its untagged-base
  //      accesses must lie in [ubase, ubound). The violation replaces any trap EX found for the instruction.
  wire          mode_user = csr_status[3];
  wire          hyb_out   = (exmem_ea < csr_ubase) | (exmem_eaend > {1'b0, csr_ubound});
  wire          mem_priv  = mode_user & (exmem_priv | (exmem_hyb & hyb_out));
  wire          exmem_trap  = exmem_trap0 | mem_priv;
  wire [3:0]    exmem_cause = mem_priv ? C_PRIV : exmem_cause0;
  wire [127:0]  exmem_tval  = mem_priv ? (exmem_priv ? {96'd0, exmem_inst} : exmem_ea) : exmem_tval0;
  // deterministic timer: mtime = instructions retired (counted as they pass MEM)
  logic [127:0] mtime_q, mtimecmp_q;

  // ======================================================================== register file
  // value + metadata arrays (no reset: map to RAM macros) + per-register "written" bits.
  // A register that has not been written since reset reads as 0 (r63: the root capability).
  logic [127:0]  rf_val  [0:63];
  logic [MW-1:0] rf_meta [0:63];
  logic [63:0]   rf_wr;

  wire          wb_we  = memwb_valid & memwb_we & ~halted_q;


  always_ff @(posedge clk) begin
    if (rst) rf_wr <= '0;
    else if (wb_we) begin
      rf_val[memwb_rd]  <= memwb_val;
      rf_meta[memwb_rd] <= memwb_meta;
      rf_wr[memwb_rd]   <= 1'b1;
    end
  end

  // ======================================================================== IF
  wire [128:0] if_end   = {1'b0, pc_q} + 129'd4;
  wire         if_noexec = ~fpcc_q[M_PERM + 2];
  wire         if_oob    = (pc_q < fpcc_q[256:129]) | (if_end > fpcc_q[128:0]);
  wire         if_fault  = if_noexec | if_oob | (|pc_q[127:RB]);
  wire [3:0]   if_fcause = if_noexec ? C_CAP_PERM : (if_oob ? C_CAP_BOUNDS : C_ACCESS);
  assign imem_addr = pc_q;

  // ---- branch target buffer: 16 entries, direct-mapped on pc[5:2], tag pc[17:6] (with the index this covers
  //      every word of the 256 KiB RAM), 16-bit word target (pc[17:2]) and a 2-bit saturating counter.
  //      Predicts taken branches, JAL and JALR in IF; every prediction is verified in EX.
  //      +define+TX_NO_BTB gives the v2 front end (static BTFN in ID only).
  (* mem2reg *) logic          btb_v   [0:15];      // small: flip-flops, not a memory macro
  (* mem2reg *) logic [11:0]   btb_tag [0:15];
  (* mem2reg *) logic [15:0]   btb_tgt [0:15];
  (* mem2reg *) logic [1:0]    btb_ctr [0:15];
  wire  [3:0]    if_bi   = pc_q[5:2];
`ifdef TX_NO_BTB
  wire           if_bhit = 1'b0;
`else
  wire           if_bhit = btb_v[if_bi] & (btb_tag[if_bi] == pc_q[17:6]);
`endif
  (* mem2reg *) logic          btb_ret [0:15];      // v4: entry is a return (target comes from the RAS)
  wire           if_bpred = if_bhit & btb_ctr[if_bi][1];

  // ---- return address stack (v4): 8 entries of 16-bit word targets (pc[17:2]), circular (overflow
  //      overwrites the oldest entry, underflow just mispredicts). Speculative copy updated in ID as calls
  //      (jal/jalr with rd = ra: push) and returns (jalr with rs1 = ra, rd != ra: pop) advance to EX; committed copy
  //      updated in MEM and copied back on every MEM redirect (trap, interrupt, eret, halt), which flushes
  //      exactly the younger instructions whose speculative updates must be undone.
  //      +define+TX_NO_RAS removes it.
  localparam int RAS_N = 8;
  (* mem2reg *) logic [15:0] ras_s [0:RAS_N-1];      // speculative
  (* mem2reg *) logic [15:0] ras_c [0:RAS_N-1];      // committed
  logic [2:0]  ras_sp, ras_cp;                       // index of the next free slot
  wire  [2:0]  ras_t1 = ras_sp - 3'd1, ras_t2 = ras_sp - 3'd2;
  logic        id_call, id_ret, id_ras_go;
  logic [15:0] id_link_w;
`ifdef TX_NO_RAS
  wire         ras_on = 1'b0;
`else
  wire         ras_on = 1'b1;
`endif
  // top of stack as seen by the instruction in IF (bypassing the update of the call/return in ID)
  wire  [15:0] if_ras_top = (ifid_valid & id_call) ? id_link_w : (ifid_valid & id_ret) ? ras_s[ras_t2] : ras_s[ras_t1];
  wire [127:0]   if_pnpc  = if_bpred ? {pc_q[127:18], (btb_ret[if_bi] & ras_on) ? if_ras_top : btb_tgt[if_bi], 2'b00}
                                     : pc_q + 128'd4;

  // ======================================================================== ID
  wire [NK-1:0] id_k   = decode(ifid_inst);
  wire [5:0]   id_fa   = ifid_inst[11:6];
  wire [5:0]   id_rs1  = ifid_inst[17:12];
  wire [5:0]   id_rs2  = (id_k[K_STORE] | id_k[K_BR] | id_k[K_WIDE]) ? id_fa : ifid_inst[23:18];
  wire         id_use1 = id_k[K_ALUR] | id_k[K_MD] | id_k[K_SIMD] | id_k[K_CAPR] | id_k[K_ALUI] |
                         id_k[K_CAPI] | id_k[K_LOAD] | id_k[K_STORE] | id_k[K_BR] | id_k[K_JALR] |
                         id_k[K_HALT] | id_k[K_CSRW] | id_k[K_AMO];
  wire         id_use2 = id_k[K_ALUR] | id_k[K_MD] | id_k[K_SIMD] | id_k[K_CAPR] | id_k[K_STORE] |
                         id_k[K_BR] | (id_k[K_WIDE] & ifid_inst[15]) | id_k[K_AMO];
  wire         id_csetepcc = id_k[K_CAPR] & (ifid_inst[28:24] == CF_CSETEPCC);
  wire         id_we   = writes_rd(id_k) & (id_fa != 6'd0) & ~ifid_fault & ~id_csetepcc;

  // register read with WB write-through
  logic [127:0]  id_v1, id_v2;
  logic [MW-1:0] id_m1, id_m2;
  always_comb begin
    // r0 = 0; a register not written since reset reads 0 (r63: root capability)
    id_v1 = rf_val[id_rs1];  id_m1 = rf_meta[id_rs1];
    id_v2 = rf_val[id_rs2];  id_m2 = rf_meta[id_rs2];
    if (id_rs1 == 6'd0 || !rf_wr[id_rs1]) begin id_v1 = '0; id_m1 = (id_rs1 == 6'd63) ? ROOT_META : '0; end
    if (id_rs2 == 6'd0 || !rf_wr[id_rs2]) begin id_v2 = '0; id_m2 = (id_rs2 == 6'd63) ? ROOT_META : '0; end
    if (wb_we && memwb_rd == id_rs1) begin id_v1 = memwb_val; id_m1 = memwb_meta; end
    if (wb_we && memwb_rd == id_rs2) begin id_v2 = memwb_val; id_m2 = memwb_meta; end
  end

  wire [127:0] id_imm14 = {{114{ifid_inst[31]}}, ifid_inst[31:18]};
  wire [127:0] id_imm20 = {{108{ifid_inst[31]}}, ifid_inst[31:12]};
  // static fallback when the BTB had no entry: backward branch -> taken; JAL always (unless the BTB already did)
  wire         id_static = id_k[K_BR] & ifid_inst[31] & ~ifid_bhit;
  // RAS: call = jal/jalr writing ra; return = jalr through ra not writing ra
  assign id_call   = ~ifid_fault & (id_k[K_JAL] | id_k[K_JALR]) & (id_fa == 6'd1);
  assign id_ret    = ~ifid_fault & id_k[K_JALR] & (id_rs1 == 6'd1) & (id_fa != 6'd1);
  assign id_link_w = ifid_pc[17:2] + 16'd1;
  // a return the BTB did not know yet is predicted from the RAS in ID (1 bubble, like the static rule)
  wire         id_rasp   = id_ret & ~ifid_bhit & ras_on;
  wire [127:0] id_target = id_k[K_JAL] ? ifid_pc + (id_imm20 << 2) :
                           id_rasp ? {ifid_pc[127:18], ras_s[ras_t1], 2'b00} : ifid_pc + (id_imm14 << 2);

  // load-use / csrr-use interlock
  wire ex_is_late = idex_valid & idex_we & ((idex_inst[5:0] >= OP_LB && idex_inst[5:0] <= OP_CLC) ||
                    idex_inst[5:0] == OP_CSRR || idex_inst[5:0] == OP_AMO ||   // AMO results come from MEM
                    (idex_inst[5:0] == OP_CAP && idex_inst[28:24] == CF_CGETEPCC));   // so does cgetepcc (v4)
  wire stall_lu = ifid_valid & ex_is_late &
                  ((id_use1 & id_rs1 == idex_rd) | (id_use2 & id_rs2 == idex_rd));

  // ======================================================================== EX
  wire [NK-1:0] ex_k0 = decode(idex_inst);
  wire [NK-1:0] ex_k  = idex_fault ? '0 : ex_k0;
  wire [5:0]   ex_op  = idex_inst[5:0];
  wire [7:0]   ex_fn  = idex_inst[31:24];
  wire [127:0] ex_imm = {{114{idex_inst[31]}}, idex_inst[31:18]};
  wire [127:0] ex_uimm = {114'd0, idex_inst[31:18]};

  // forwarding
  logic [127:0]  a, b;
  logic [MW-1:0] ma, mb;
  wire mem_fwd_ok = exmem_valid & exmem_we & ~exmem_load & ~exmem_csrr & ~exmem_getepcc;
  always_comb begin
    a = idex_v1; ma = idex_m1;
    if (mem_fwd_ok && exmem_rd == idex_rs1) begin a = exmem_val; ma = exmem_meta; end
    else if (memwb_valid && memwb_we && memwb_rd == idex_rs1) begin a = memwb_val; ma = memwb_meta; end
    b = idex_v2; mb = idex_m2;
    if (mem_fwd_ok && exmem_rd == idex_rs2) begin b = exmem_val; mb = exmem_meta; end
    else if (memwb_valid && memwb_we && memwb_rd == idex_rs2) begin b = memwb_val; mb = memwb_meta; end
  end
  wire         a_tag  = ma[M_TAG];
  wire [PW-1:0] a_perm = ma[M_PERM +: PW];
  wire [15:0]  a_ot   = ma[M_OT +: 16];
  wire         a_sealed = a_tag & (|a_ot);
  wire         b_tag  = mb[M_TAG];
  wire [PW-1:0] b_perm = mb[M_PERM +: PW];
  wire [127:0] b_base = mb[256:129];
  wire [128:0] b_top  = mb[128:0];
  wire         b_sealed = b_tag & (|mb[M_OT +: 16]);
  wire [127:0] a_base = ma[256:129];
  wire [128:0] a_top  = ma[128:0];
  wire         a_sentry = a_tag & (a_ot == OTYPE_SENTRY);
  wire         b_sentry = b_tag & (mb[M_OT +: 16] == OTYPE_SENTRY);
  wire [MW-1:0] ma_unsealed = {ma[M_TAG], 16'd0, ma[M_OT-1:0]};   // PCC installed by cjalr / cinvoke
  wire [MW-1:0] mb_unsealed = {mb[M_TAG], 16'd0, mb[M_OT-1:0]};

  // ---- ALU
  logic [4:0] alu_fn;
  always_comb begin
    if (ex_k[K_ALUR]) alu_fn = ex_fn[4:0];
    else case (ex_op)
      OP_ANDI:  alu_fn = A_AND;
      OP_ORI:   alu_fn = A_OR;
      OP_XORI:  alu_fn = A_XOR;
      OP_SLTI:  alu_fn = A_SLT;
      OP_SLTIU: alu_fn = A_SLTU;
      OP_SLLI:  alu_fn = A_SLL;
      OP_SRLI:  alu_fn = A_SRL;
      OP_SRAI:  alu_fn = A_SRA;
      OP_ADDIW: alu_fn = A_ADDW;
      OP_SLLIW: alu_fn = A_SLLW;
      OP_SRLIW: alu_fn = A_SRLW;
      OP_SRAIW: alu_fn = A_SRAW;
      OP_ADDIWU: alu_fn = A_ADDWU;
      OP_SLLIWU: alu_fn = A_SLLWU;
      default:  alu_fn = A_ADD;
    endcase
  end
  wire is_shi = (ex_op == OP_SLLI) | (ex_op == OP_SRLI) | (ex_op == OP_SRAI) |
                (ex_op == OP_SLLIW) | (ex_op == OP_SRLIW) | (ex_op == OP_SRAIW) | (ex_op == OP_SLLIWU);
  wire [127:0] alu_b = ex_k[K_ALUR] ? b : (is_shi ? ex_uimm : ex_imm);
  logic [127:0] alu_y;
  tx_alu u_alu (.func(alu_fn), .a(a), .b(alu_b), .y(alu_y));

  // ---- shared multiplier array (v4): 4 fracturable Booth 32x32 multipliers, used by SIMD vmul and by the
  //      scalar multiplier's 128 x 32 passes (EX holds the mul while it iterates, so they never collide)
  logic         sh_busy;
  logic [127:0] sh_x;
  logic [31:0]  sh_z;
  logic [255:0] sh_p;
  tx_mul32x4 u_mul (.x(sh_busy ? sh_x : a), .z(sh_busy ? {4{sh_z}} : b),
                    .mode(sh_busy ? 2'd0 : (ex_fn[1:0] == 2'd0 ? 2'd2 : ex_fn[1:0] == 2'd1 ? 2'd1 : 2'd0)),
                    .p(sh_p));

  // ---- SIMD
  logic [127:0] simd_y;
  tx_simd u_simd (.sop(ex_fn[6:2]), .lw(ex_fn[1:0]), .a(a), .b(b), .mp(sh_p), .y(simd_y));

  // ---- MUL/DIV
  logic md_ready;
  logic [127:0] md_y;
  logic mem_redirect;
  // v5 word ops: mulw/mulwu = one 32-bit multiplier pass; divw/remw = div/rem on sign-extended low words
  wire md_mw  = (ex_fn == MD_MULW) | (ex_fn == MD_MULWU);
  wire md_dw  = (ex_fn == MD_DIVW) | (ex_fn == MD_REMW);
  wire [2:0] md_op = md_mw ? 3'd0 : (ex_fn == MD_DIVW) ? 3'd2 : (ex_fn == MD_REMW) ? 3'd4 : ex_fn[2:0];
  wire [127:0] md_a = md_dw ? {{96{a[31]}}, a[31:0]} : a;
  wire [127:0] md_b = md_dw ? {{96{b[31]}}, b[31:0]} : b;
  wire [127:0] md_res = (md_mw | md_dw) ? {{96{md_y[31] & (ex_fn != MD_MULWU)}}, md_y[31:0]} : md_y;
  tx_muldiv u_md (.clk(clk), .rst(rst), .req(idex_valid & ex_k[K_MD] & ~halted_q), .abort(mem_redirect),
                  .op(md_op), .w1(md_mw), .a(md_a), .b(md_b), .ready(md_ready), .y(md_y),
                  .sh_busy(sh_busy), .sh_x(sh_x), .sh_z(sh_z), .sh_p(sh_p));
  wire stall_md = idex_valid & ex_k[K_MD] & ~md_ready;

  // ---- capabilities
  logic [4:0]   cap_fn;
  logic [127:0] cap_y, cap_x, cap_tv;
  logic [MW-1:0] cap_m;
  logic         cap_fault;
  logic [3:0]   cap_cause;
  wire  [128:0] cap_ntop = {1'b0, a} + {1'b0, cap_x};
  wire  [128:0] cap_len  = a_top - {1'b0, a_base};
  always_comb begin
    cap_fn = ex_k[K_CAPR] ? ex_fn[4:0] : (ex_op == OP_CINCADDRI ? 5'd1 : 5'd2);
    cap_x  = ex_k[K_CAPR] ? b : (ex_op == OP_CINCADDRI ? ex_imm : ex_uimm);
    cap_y = '0; cap_m = '0; cap_fault = 1'b0; cap_cause = C_CAP_TAG; cap_tv = a;
    case (cap_fn)
      5'd0: begin cap_y = cap_x; cap_m = ma; end                     // csetaddr
      5'd1: begin cap_y = a + cap_x; cap_m = ma; end                 // cincaddr
      5'd2: begin                                                    // csetbnd
        cap_y = a;
        cap_m = {1'b1, 16'd0, a_perm, a, cap_ntop};
        if (!a_tag) begin cap_fault = 1'b1; cap_cause = C_CAP_TAG; end
        else if (a < a_base || cap_ntop > a_top) begin cap_fault = 1'b1; cap_cause = C_CAP_BOUNDS; end
      end
      5'd3: begin                                                    // candperm
        cap_y = a;
        cap_m = a_tag ? {1'b1, 16'd0, a_perm & cap_x[PW-1:0], a_base, a_top} : '0;
      end
      5'd4: cap_y = a_base;                                          // cgetbase
      5'd5: cap_y = cap_len[128] ? {128{1'b1}} : cap_len[127:0];     // cgetlen
      5'd6: cap_y = {{(128-PW){1'b0}}, a_perm};                                // cgetperm
      5'd7: cap_y = {127'd0, a_tag};                                 // cgettag
      CF_CGETPCC: begin cap_y = idex_pc; cap_m = pcc_q; end
      CF_CSETEPCC: begin
        cap_m = ma;
        if (!a_tag) begin cap_fault = 1'b1; cap_cause = C_CAP_TAG; end
        else if (a_sealed) begin cap_fault = 1'b1; cap_cause = C_CAP_SEALED; end
      end
      CF_CJALR: begin                                                // link = PCC, cursor pc+4
        cap_y = idex_pc + 128'd4;                                    // (a sentry link through a sentry)
        cap_m = {pcc_q[M_TAG], a_sentry ? OTYPE_SENTRY : 16'd0, pcc_q[M_OT-1:0]};
        if (!a_tag) begin cap_fault = 1'b1; cap_cause = C_CAP_TAG; end
        else if (a_sealed && !a_sentry) begin cap_fault = 1'b1; cap_cause = C_CAP_SEALED; end
        else if (!a_perm[2]) begin cap_fault = 1'b1; cap_cause = C_CAP_PERM; end
      end
      CF_CSEALENTRY: begin
        cap_y = a;
        cap_m = {1'b1, OTYPE_SENTRY, a_perm, a_base, a_top};
        if (!a_tag) begin cap_fault = 1'b1; cap_cause = C_CAP_TAG; end
        else if (a_sealed) begin cap_fault = 1'b1; cap_cause = C_CAP_SEALED; end
        else if (!a_perm[2]) begin cap_fault = 1'b1; cap_cause = C_CAP_PERM; end
      end
      CF_CINVOKE: begin                                              // rs1 = sealed code, rs2 = sealed data
        cap_y = b; cap_m = mb_unsealed;
        cap_fault = 1'b1;
        if (!a_tag) cap_cause = C_CAP_TAG;
        else if (!b_tag) begin cap_cause = C_CAP_TAG; cap_tv = b; end
        else if (!a_sealed || a_sentry) cap_cause = C_CAP_SEALED;
        else if (!b_sealed || b_sentry || mb[M_OT +: 16] != a_ot) begin cap_cause = C_CAP_SEALED; cap_tv = b; end
        else if (!a_perm[P_CINVOKE]) cap_cause = C_CAP_PERM;
        else if (!b_perm[P_CINVOKE]) begin cap_cause = C_CAP_PERM; cap_tv = b; end
        else if (!a_perm[2]) cap_cause = C_CAP_PERM;
        else if (b_perm[2]) begin cap_cause = C_CAP_PERM; cap_tv = b; end
        else cap_fault = 1'b0;
      end
      CF_CSEAL, CF_CUNSEAL: begin                                    // rs2 = sealing authority, cursor = otype
        cap_y = a;
        cap_m = {1'b1, (cap_fn == CF_CSEAL) ? b[15:0] : 16'd0, a_perm, a_base, a_top};
        cap_fault = 1'b1; cap_tv = b;
        if (!a_tag) begin cap_cause = C_CAP_TAG; cap_tv = a; end
        else if (!b_tag) cap_cause = C_CAP_TAG;
        else if ((cap_fn == CF_CSEAL) ? a_sealed : (!a_sealed || a_sentry)) begin cap_cause = C_CAP_SEALED; cap_tv = a; end
        else if (b_sealed) cap_cause = C_CAP_SEALED;
        else if (!b_perm[(cap_fn == CF_CSEAL) ? 5 : 6]) cap_cause = C_CAP_PERM;
        else if (b < b_base || {1'b0, b} >= b_top) cap_cause = C_CAP_BOUNDS;
        else if (cap_fn == CF_CSEAL && (b[15:0] == 16'd0 || b[15:0] == OTYPE_SENTRY || |b[127:16])) cap_cause = C_CAP_BOUNDS;
        else if (cap_fn == CF_CUNSEAL && b != {112'd0, a_ot}) cap_cause = C_CAP_SEALED;
        else cap_fault = 1'b0;
      end
      CF_CGETTYPE: cap_y = {112'd0, a_ot};
      CF_CMOVE: begin cap_y = a; cap_m = ma; end                     // v6: copy, seal and all
      default: cap_y = a;                                            // cclrtag
    endcase
    // sealed capabilities are immutable: csetaddr / cincaddr / csetbnd / candperm trap
    if (cap_fn <= 5'd3 && a_sealed) begin cap_fault = 1'b1; cap_cause = C_CAP_SEALED; cap_tv = a; end
  end

  // ---- wide immediate
  wire [6:0]   wide_sh  = {idex_inst[14:12], 4'd0};
  wire [127:0] wide_ins = {112'd0, idex_inst[31:16]} << wide_sh;
  wire [127:0] wide_y   = idex_inst[15] ? ((b & ~({112'd0, 16'hFFFF} << wide_sh)) | wide_ins) : wide_ins;

  // ---- memory address + checks
  // ---- v4 atomics: address = rs1 (no offset); lr loads, sc stores, amo* read-modify-write in MEM
  wire         is_amo   = ex_k[K_AMO];
  wire [2:0]   amo_fn   = ex_fn[2:0];
  wire         amo_ld   = is_amo & (amo_fn != AMO_SC);          // reads memory (lr, amoswap, arithmetic)
  wire         amo_st   = is_amo & (amo_fn != AMO_LR);          // writes memory (sc, amoswap, arithmetic)
  wire         capst    = (ex_op == OP_CSC) | (is_amo & ((amo_fn == AMO_SC) | (amo_fn == AMO_SWAP)));  // stores rs2's tag
  wire [127:0] ea = a + (is_amo ? 128'd0 : ex_imm);
  logic [4:0] msize;
  always_comb
    case (ex_op)
      OP_LB, OP_LBU, OP_SB: msize = 5'd1;
      OP_LH, OP_LHU, OP_SH: msize = 5'd2;
      OP_LW, OP_LWU, OP_SW: msize = 5'd4;
      OP_LD, OP_LDU, OP_SD: msize = 5'd8;
      default:              msize = 5'd16;
    endcase
  wire         is_mem   = ex_k[K_LOAD] | ex_k[K_STORE] | is_amo;
  wire [128:0] ea_end   = {1'b0, ea} + {124'd0, msize};
  wire         need_p   = is_amo ? ((~amo_ld | a_perm[0]) & (~amo_st | a_perm[1])) :
                          ex_k[K_STORE] ? a_perm[1] : a_perm[0];
  wire         is_csc   = ex_op == OP_CSC;
  wire         is_clc   = ex_op == OP_CLC;
  wire [3:0]   amask    = msize[3:0] - 4'd1;           // 16 -> 4'hF
  wire         misalign = |(ea[3:0] & amask);
  wire         in_ram   = ~|ea[127:RB];
  wire         in_mmio  = &ea[127:16];
  logic        mem_fault;
  logic [3:0]  mem_cause;
  always_comb begin
    mem_fault = 1'b1;
    if (a_sealed) mem_cause = C_CAP_SEALED;
    else if (a_tag && !need_p) mem_cause = C_CAP_PERM;
    else if (a_tag && capst && b_tag && !a_perm[4]) mem_cause = C_CAP_PERM;   // STORE_CAP
    else if (a_tag && capst && b_tag && !b_perm[P_GLOBAL] && !a_perm[P_STORE_LOCAL]) mem_cause = C_CAP_PERM; // local cap
    else if (a_tag && (ea < a_base || ea_end > a_top)) mem_cause = C_CAP_BOUNDS;
    else if (misalign) mem_cause = C_ALIGN;
    else if (!in_ram && (!in_mmio || is_amo)) mem_cause = C_ACCESS;           // atomics: RAM only
    else begin mem_fault = 1'b0; mem_cause = C_ACCESS; end
  end

  // ---- branches / jumps
  logic br_taken;
  always_comb
    case (ex_op)
      OP_BEQ:  br_taken = a == b;
      OP_BNE:  br_taken = a != b;
      OP_BLT:  br_taken = $signed(a) < $signed(b);
      OP_BGE:  br_taken = $signed(a) >= $signed(b);
      OP_BLTU: br_taken = a < b;
      default: br_taken = a >= b;
    endcase
  wire [127:0] ex_pc4    = idex_pc + 128'd4;
  wire [127:0] br_target = idex_pc + (ex_imm << 2);
  wire [127:0] jalr_tgt  = (a + ex_imm) & ~128'd3;
  wire [127:0] jal_tgt   = idex_pc + ({{108{idex_inst[31]}}, idex_inst[31:12]} << 2);
  // actual next pc of the instruction in EX; any difference from the predicted one is a misprediction
  wire [127:0] ex_anpc   = ex_k[K_BR] ? (br_taken ? br_target : ex_pc4) : ex_k[K_JAL] ? jal_tgt :
                           ex_k[K_JALR] ? jalr_tgt : ex_pc4;
  // cjalr and cinvoke both jump to rs1's cursor and install rs1 (unsealed) as the PCC
  wire ex_cjalr  = ex_k[K_CAPR] & ((ex_fn[4:0] == CF_CJALR) | (ex_fn[4:0] == CF_CINVOKE));
  wire ex_setepcc = ex_k[K_CAPR] & (ex_fn[4:0] == CF_CSETEPCC);
  wire ex_getepcc = ex_k[K_CAPR] & (ex_fn[4:0] == CF_CGETEPCC);   // reads EPCC/epc in MEM, like csrr
  // cjalr / cinvoke always redirect (they also switch the fetch PCC); trapping instructions never do
  wire ex_redirect = idex_valid & ~ex_trap & (ex_cjalr | (ex_anpc != idex_pnpc));
  wire [127:0] ex_target = ex_cjalr ? (a & ~128'd3) : ex_anpc;
`ifdef TX_NO_BTB
  wire btb_upd = 1'b0;
`else
  wire btb_upd = idex_valid & ~ex_trap & ~stall_md & ~mem_redirect & (ex_k[K_BR] | ex_k[K_JAL] | ex_k[K_JALR]);
`endif
  wire [3:0] ex_bi = idex_pc[5:2];
  wire ex_bhit = btb_v[ex_bi] & (btb_tag[ex_bi] == idex_pc[17:6]);

  // ---- result + trap select
  logic [127:0]  ex_val, ex_tval;
  logic [MW-1:0] ex_meta;
  logic          ex_trap;
  logic [3:0]    ex_cause;
  always_comb begin
    ex_val = alu_y; ex_meta = '0;
    if (ex_k[K_SIMD]) ex_val = simd_y;
    else if (ex_k[K_MD]) ex_val = md_res;
    else if (ex_k[K_CAPR] | ex_k[K_CAPI]) begin ex_val = cap_y; ex_meta = cap_m; end
    else if (ex_k[K_WIDE]) ex_val = wide_y;
    else if (ex_k[K_JAL] | ex_k[K_JALR]) ex_val = ex_pc4;
    else if (ex_k[K_CSRW]) ex_val = a;                   // CSR write data rides in exmem_val
    ex_trap = 1'b0; ex_cause = C_ACCESS; ex_tval = '0;
    if (idex_fault) begin ex_trap = 1'b1; ex_cause = idex_fcause; ex_tval = idex_pc; end
    else if (ex_k[K_ILL]) begin ex_trap = 1'b1; ex_cause = C_ILLEGAL; ex_tval = {96'd0, idex_inst}; end
    else if (is_mem && mem_fault) begin ex_trap = 1'b1; ex_cause = mem_cause; ex_tval = ea; end
    else if ((ex_k[K_CAPR] | ex_k[K_CAPI]) && cap_fault) begin ex_trap = 1'b1; ex_cause = cap_cause; ex_tval = cap_tv; end
    else if (ex_k[K_ECALL]) begin ex_trap = 1'b1; ex_cause = C_ECALL; ex_tval = '0; end
  end

  // ======================================================================== MEM
  // timer interrupt: taken on the oldest instruction (the one in MEM) before it has any effect,
  // so it lands between two retirements exactly where the ISA model puts it
  wire        irq_pend  = csr_status[0] & csr_status[2] & (mtime_q >= mtimecmp_q);
  wire        mem_irq   = exmem_valid & irq_pend;
  wire        mem_v     = exmem_valid & ~irq_pend;      // instruction in MEM really executes
  wire [6:0]  mshift    = {exmem_ea[3:0], 3'd0};
  logic [15:0] be_raw;
  always_comb
    case (exmem_op)
      OP_SB:   be_raw = 16'h0001;
      OP_SH:   be_raw = 16'h0003;
      OP_SW:   be_raw = 16'h000F;
      OP_SD:   be_raw = 16'h00FF;
      default: be_raw = 16'hFFFF;
    endcase
  // v4 atomics: sc stores only with a matching reservation; arithmetic AMOs write op(old, rs2) in the same
  // cycle as they read the old value (combinational read, synchronous write)
  wire         mem_sc    = exmem_amo & (exmem_amofn == AMO_SC);
  wire         resv_hit  = resv_v & (resv_g == exmem_ea[RB-1:4]);
  wire         amo_arith = exmem_amo & (exmem_amofn >= AMO_ADD);
  logic [127:0] amo_new;
  always_comb
    case (exmem_amofn)
      AMO_ADD: amo_new = dmem_rdata + exmem_sdata;
      AMO_AND: amo_new = dmem_rdata & exmem_sdata;
      AMO_OR:  amo_new = dmem_rdata | exmem_sdata;
      default: amo_new = dmem_rdata ^ exmem_sdata;
    endcase
  assign dmem_addr  = exmem_ea;
  assign dmem_re    = mem_v & exmem_load & ~exmem_trap;
  assign dmem_we    = mem_v & exmem_store & ~exmem_trap & ~halted_q & ~(mem_sc & ~resv_hit);
  assign dmem_be    = be_raw << exmem_ea[3:0];
  assign dmem_wdata = amo_arith ? amo_new : (exmem_sdata << mshift);
  assign dmem_wmeta = exmem_csc ? exmem_smeta : '0;

  wire [127:0] mmio_word = (exmem_ea[127:4] == MMIO_MTIME[127:4]) ? mtime_q :
                           (exmem_ea[127:4] == MMIO_MTIMECMP[127:4]) ? mtimecmp_q : '0;
  wire [127:0] ld_raw = (exmem_mmio ? mmio_word : dmem_rdata) >> mshift;
  // clc through an authority without LOAD_MUTABLE (v4; v3 used STORE): an unsealed loaded capability
  // loses STORE, STORE_CAP, STORE_LOCAL and LOAD_MUTABLE (deeply immutable)
  wire          clc_ro   = exmem_ldro & (dmem_rmeta[M_OT +: 16] == 16'd0);
  wire [MW-1:0] clc_meta = clc_ro ? (dmem_rmeta & ~(MW'(PERM_LM_STRIP) << M_PERM)) : dmem_rmeta;
  logic [127:0] st_mask;
  always_comb
    case (exmem_op)
      OP_SB:   st_mask = {120'd0, 8'hFF};
      OP_SH:   st_mask = {112'd0, 16'hFFFF};
      OP_SW:   st_mask = {96'd0, 32'hFFFF_FFFF};
      OP_SD:   st_mask = {64'd0, {64{1'b1}}};
      default: st_mask = {128{1'b1}};
    endcase
  wire mem_wr_cmp = mem_v & ~exmem_trap & exmem_store & (exmem_ea == MMIO_MTIMECMP);
  logic [127:0] ld_val;
  always_comb
    case (exmem_op)
      OP_LB:   ld_val = {{120{ld_raw[7]}},  ld_raw[7:0]};
      OP_LH:   ld_val = {{112{ld_raw[15]}}, ld_raw[15:0]};
      OP_LW:   ld_val = {{96{ld_raw[31]}},  ld_raw[31:0]};
      OP_LD:   ld_val = {{64{ld_raw[63]}},  ld_raw[63:0]};
      OP_LBU:  ld_val = {120'd0, ld_raw[7:0]};
      OP_LHU:  ld_val = {112'd0, ld_raw[15:0]};
      OP_LWU:  ld_val = {96'd0,  ld_raw[31:0]};
      OP_LDU:  ld_val = {64'd0,  ld_raw[63:0]};
      default: ld_val = ld_raw;
    endcase

  logic [127:0] csr_rd;
  always_comb
    case (exmem_csr)
      3'd0: csr_rd = csr_tvec;
      3'd1: csr_rd = csr_epc;
      3'd2: csr_rd = csr_cause;
      3'd3: csr_rd = csr_tval;
      3'd4: csr_rd = csr_scratch;
      3'd5: csr_rd = {123'd0, csr_status};
      3'd6: csr_rd = csr_ubase;
      default: csr_rd = csr_ubound;
    endcase

  wire mem_trap      = (mem_v & exmem_trap) | mem_irq;
  wire mem_trap_halt = mem_trap & (csr_tvec == '0);
  wire mem_halt      = mem_v & ~exmem_trap & exmem_halt;
  wire mem_eret      = mem_v & ~exmem_trap & exmem_eret;
  assign mem_redirect = mem_trap | mem_halt | mem_eret;
  wire [127:0] mem_target = mem_eret ? (csr_epc & ~128'd3) : (csr_tvec & ~128'd3);
  wire [MW-1:0] mem_tpcc  = mem_eret ? epcc_q : ROOT_META;   // PCC after the MEM redirect

  // ======================================================================== control
  wire stall = stall_lu | stall_md;
  wire id_redirect = ifid_valid & ~ifid_fault & ((id_k[K_JAL] & ~ifid_bpred) | id_static | id_rasp);
  // the call/return in ID updates the speculative RAS when it advances to EX
  assign id_ras_go = ifid_valid & ~stall & ~ex_redirect & ~mem_redirect & (id_call | id_ret) & ras_on;
  wire [127:0] id_pnpc = id_redirect ? id_target : ifid_pnpc;

  always_ff @(posedge clk) begin
    if (rst) begin
      pc_q <= '0; stop_fetch_q <= 1'b0; halted_q <= 1'b0; exit_q <= '0;
      fpcc_q <= ROOT_META; pcc_q <= ROOT_META; epcc_q <= ROOT_META;
      ifid_valid <= 1'b0; idex_valid <= 1'b0; exmem_valid <= 1'b0; memwb_valid <= 1'b0;
      csr_tvec <= '0; csr_epc <= '0; csr_cause <= '0; csr_tval <= '0; csr_scratch <= '0;
      csr_status <= '0; csr_ubase <= '0; csr_ubound <= '0; mtime_q <= '0; mtimecmp_q <= {128{1'b1}};
      resv_v <= 1'b0;
    end else if (!halted_q) begin
      // ---------------- PC
      if (mem_redirect)      pc_q <= mem_target;
      else if (ex_redirect)  pc_q <= ex_target;
      else if (stall)        pc_q <= pc_q;
      else if (id_redirect)  pc_q <= id_target;
      else if (!stop_fetch_q) pc_q <= if_pnpc;
      if (mem_halt | mem_trap_halt) stop_fetch_q <= 1'b1;
      if (mem_redirect)     fpcc_q <= mem_tpcc;
      else if (ex_redirect & ex_cjalr) fpcc_q <= ma_unsealed;
      // architectural PCC / EPCC (MEM stage)
      if (mem_trap) begin epcc_q <= pcc_q; pcc_q <= ROOT_META; end
      else if (mem_eret) pcc_q <= epcc_q;
      else if (mem_v && exmem_cjalr) pcc_q <= exmem_tmeta;
      else if (mem_v && exmem_setepcc) epcc_q <= exmem_tmeta;

      // ---------------- IF/ID
      if (mem_redirect | ex_redirect | (id_redirect & ~stall)) ifid_valid <= 1'b0;
      else if (!stall) begin
        ifid_valid <= ~stop_fetch_q;
        ifid_pc    <= pc_q;
        ifid_inst  <= imem_rdata;
        ifid_fault <= if_fault;
        ifid_fcause <= if_fcause;
        ifid_pnpc  <= if_pnpc;
        ifid_bpred <= if_bpred;
        ifid_bhit  <= if_bhit;
      end

      // ---------------- ID/EX
      if (mem_redirect | ex_redirect) idex_valid <= 1'b0;
      else if (stall_md) ;
      else if (stall_lu) idex_valid <= 1'b0;
      else begin
        idex_valid <= ifid_valid;
        idex_pc <= ifid_pc; idex_inst <= ifid_inst; idex_fault <= ifid_fault; idex_fcause <= ifid_fcause;
        idex_rs1 <= id_rs1; idex_rs2 <= id_rs2; idex_rd <= id_fa; idex_we <= id_we;
        idex_v1 <= id_v1; idex_v2 <= id_v2; idex_m1 <= id_m1; idex_m2 <= id_m2;
        idex_pnpc <= id_pnpc;
        idex_call <= id_call; idex_ret <= id_ret;
      end

      // ---------------- EX/MEM
      if (mem_redirect | stall_md) exmem_valid <= 1'b0;
      else begin
        exmem_valid <= idex_valid;
        exmem_pc    <= idex_pc;
        exmem_rd    <= idex_rd;
        exmem_we    <= idex_we & ~ex_trap;
        exmem_val   <= ex_val;
        exmem_meta  <= ex_meta;
        exmem_op    <= ex_op;
        exmem_load  <= ex_k[K_LOAD] | is_amo;          // every AMO's rd comes from MEM (sc: success flag)
        exmem_store <= ex_k[K_STORE] | amo_st;
        exmem_amo   <= is_amo;
        exmem_amofn <= amo_fn;
        exmem_ea    <= ea;
        exmem_mmio  <= in_mmio;
        exmem_sdata <= b;
        exmem_smeta <= mb;
        exmem_tmeta <= ma_unsealed;              // csetepcc: rs1 is unsealed anyway
        exmem_cjalr <= ex_cjalr & ~ex_trap;
        exmem_setepcc <= ex_setepcc & ~ex_trap;
        exmem_call  <= idex_call & ~idex_fault;
        exmem_ret   <= idex_ret & ~idex_fault;
        exmem_clc   <= is_clc | (is_amo & ((amo_fn == AMO_LR) | (amo_fn == AMO_SWAP)));   // clc tag rules
        exmem_csc   <= capst;                                                          // csc tag rules
        exmem_ldcap <= ~a_tag | a_perm[3];               // LOAD_CAP (or unchecked base)
        exmem_ldro  <= a_tag & ~a_perm[P_LM];            // no LOAD_MUTABLE: clc result loses the store perms + LM
        exmem_trap0  <= ex_trap;
        exmem_cause0 <= ex_cause;
        exmem_tval0  <= ex_tval;
        exmem_inst   <= idex_inst;
        exmem_eaend  <= ea_end;
        exmem_priv   <= ex_k[K_CSRR] | ex_k[K_CSRW] | ex_k[K_ERET] | ex_k[K_HALT] | ex_setepcc | ex_getepcc;
        exmem_getepcc <= ex_getepcc;
        exmem_hyb    <= is_mem & ~a_tag;
        exmem_csrr  <= ex_k[K_CSRR];
        exmem_csrw  <= ex_k[K_CSRW];
        exmem_csr   <= idex_inst[20:18];
        exmem_eret  <= ex_k[K_ERET];
        exmem_halt  <= ex_k[K_HALT] | (ex_k[K_STORE] & ea == MMIO_EXIT);
        case (ex_op)
          OP_SB:   exmem_code <= {24'd0, b[7:0]};
          OP_SH:   exmem_code <= {16'd0, b[15:0]};
          OP_HALT: exmem_code <= a[31:0];
          default: exmem_code <= b[31:0];
        endcase
      end

      // ---------------- MEM: CSRs, traps
      if (mem_v && !exmem_trap) mtime_q <= mtime_q + 128'd1;     // retirement
      // lr/sc reservation: set by lr, cleared by every completed store/sc/AMO and by every trap or interrupt
      if (mem_trap) resv_v <= 1'b0;
      else if (mem_v && !exmem_trap && exmem_amo && exmem_amofn == AMO_LR) begin
        resv_v <= 1'b1; resv_g <= exmem_ea[RB-1:4];
      end else if (mem_v && !exmem_trap && exmem_store) resv_v <= 1'b0;
      if (mem_wr_cmp) mtimecmp_q <= exmem_sdata & st_mask;
      if (mem_trap) begin
        csr_epc <= exmem_pc;
        csr_cause <= mem_irq ? {1'b1, 123'd0, IRQ_TIMER} : {124'd0, exmem_cause};
        csr_tval <= mem_irq ? '0 : exmem_tval;
        csr_status <= {csr_status[3], 1'b0, csr_status[2], csr_status[0], 1'b0};  // PU <- U, U <- 0, PIE <- IE, IE <- 0
      end else if (mem_eret) begin
        csr_status <= {1'b0, csr_status[4], csr_status[2], 1'b1, csr_status[1]};  // U <- PU, PU <- 0, IE <- PIE, PIE <- 1
      end else if (mem_v && exmem_csrw) begin
        case (exmem_csr)
          3'd0: csr_tvec <= exmem_val;
          3'd1: csr_epc <= exmem_val;
          3'd2: csr_cause <= exmem_val;
          3'd5: csr_status <= {exmem_val[4], csr_status[3], exmem_val[2:0]};   // U is read-only
          3'd6: csr_ubase <= exmem_val;
          3'd7: csr_ubound <= exmem_val;
          3'd3: csr_tval <= exmem_val;
          3'd4: csr_scratch <= exmem_val;
          default: ;
        endcase
      end

      // ---------------- MEM/WB
      memwb_valid <= exmem_valid;
      memwb_irq   <= mem_irq;
      memwb_pc    <= exmem_pc;
      memwb_rd    <= exmem_rd;
      memwb_we    <= exmem_we & ~exmem_trap & ~mem_irq;
      memwb_val   <= mem_sc ? {127'd0, ~resv_hit} : exmem_load ? ld_val : (exmem_csrr ? csr_rd :
                     exmem_getepcc ? csr_epc : exmem_val);
      memwb_meta  <= exmem_load ? ((exmem_clc & ~exmem_mmio & exmem_ldcap & dmem_rmeta[M_TAG]) ? clc_meta : '0)
                                : (exmem_csrr ? '0 : exmem_getepcc ? epcc_q : exmem_meta);
      memwb_trap  <= exmem_trap | mem_irq;
      memwb_cause <= mem_irq ? IRQ_TIMER : exmem_cause;
      memwb_tval  <= mem_irq ? '0 : exmem_tval;
      memwb_halt  <= mem_halt | mem_trap_halt;
      memwb_code  <= exmem_code;

      // ---------------- WB
      if (memwb_valid && memwb_halt) begin
        halted_q <= 1'b1;
        exit_q   <= memwb_trap ? 32'd0 : memwb_code;
      end
    end
  end

  // ---- BTB update (EX): allocate on taken branches / jumps, train the counter on every branch
  always_ff @(posedge clk) begin
    if (rst) begin
      for (int i = 0; i < 16; i++) btb_v[i] <= 1'b0;
    end else if (btb_upd && !halted_q) begin
      if (ex_k[K_BR]) begin
        if (ex_bhit) begin
          btb_ctr[ex_bi] <= br_taken ? ((btb_ctr[ex_bi] == 2'd3) ? 2'd3 : btb_ctr[ex_bi] + 2'd1)
                                     : ((btb_ctr[ex_bi] == 2'd0) ? 2'd0 : btb_ctr[ex_bi] - 2'd1);
          btb_tgt[ex_bi] <= br_target[17:2];
        end else if (br_taken) begin
          btb_v[ex_bi] <= 1'b1; btb_tag[ex_bi] <= idex_pc[17:6];
          btb_tgt[ex_bi] <= br_target[17:2]; btb_ctr[ex_bi] <= 2'd2;
        end
      end else begin                     // JAL / JALR: last target, always taken; returns use the RAS
        btb_v[ex_bi] <= 1'b1; btb_tag[ex_bi] <= idex_pc[17:6];
        btb_tgt[ex_bi] <= ex_anpc[17:2]; btb_ctr[ex_bi] <= 2'd3;
      end
      btb_ret[ex_bi] <= ~ex_k[K_BR] & idex_ret;
    end
  end

  // ---- RAS update: speculative in ID, committed in MEM, restore on MEM redirect
  wire mem_ras = mem_v & ~exmem_trap & (exmem_call | exmem_ret) & ras_on;
  wire [15:0] mem_link_w = exmem_pc[17:2] + 16'd1;
  always_ff @(posedge clk) begin
    if (rst) begin
      ras_sp <= '0; ras_cp <= '0;
      for (int i = 0; i < RAS_N; i++) begin ras_s[i] <= '0; ras_c[i] <= '0; end
    end else if (!halted_q) begin
      // committed copy (instruction in MEM retires)
      if (mem_ras) begin
        if (exmem_call) begin ras_c[ras_cp] <= mem_link_w; ras_cp <= ras_cp + 3'd1; end
        else ras_cp <= ras_cp - 3'd1;
      end
      // speculative copy; a MEM redirect never coincides with a retiring call/return (traps do not
      // retire, eret/halt are neither), so restoring the committed state is exact
      if (mem_redirect) begin
        for (int i = 0; i < RAS_N; i++) ras_s[i] <= ras_c[i];
        ras_sp <= ras_cp;
      end else if (id_ras_go) begin
        if (id_call) begin ras_s[ras_sp] <= id_link_w; ras_sp <= ras_sp + 3'd1; end
        else ras_sp <= ras_t1;
      end
    end
  end

`ifdef TX_PERF
  // optional cycle-loss counters (simulation only): +define+TX_PERF, printed to stderr at the end
  longint unsigned pf_br, pf_jal, pf_jalr, pf_ret, pf_cj, pf_idr, pf_lu, pf_md;
  initial begin pf_br = 0; pf_jal = 0; pf_jalr = 0; pf_ret = 0; pf_cj = 0; pf_idr = 0; pf_lu = 0; pf_md = 0; end
  always_ff @(posedge clk) if (!rst && !halted_q) begin
    if (ex_redirect && !mem_redirect) begin
      if (ex_cjalr) pf_cj <= pf_cj + 1;
      else if (ex_k[K_BR]) pf_br <= pf_br + 1;
      else if (ex_k[K_JAL]) pf_jal <= pf_jal + 1;
      else if (ex_k[K_JALR] && idex_ret) pf_ret <= pf_ret + 1;
      else pf_jalr <= pf_jalr + 1;
    end
    if (id_redirect && !stall && !ex_redirect && !mem_redirect) pf_idr <= pf_idr + 1;
    if (stall_lu && !stall_md) pf_lu <= pf_lu + 1;
    if (stall_md) pf_md <= pf_md + 1;
  end
  final $fwrite(32'h8000_0002, "perf: EX-redirects br=%0d jal=%0d ret=%0d jalr=%0d cjalr/cinvoke=%0d  ID-redirects=%0d  load-use=%0d muldiv-stall=%0d\n",
                pf_br, pf_jal, pf_ret, pf_jalr, pf_cj, pf_idr, pf_lu, pf_md);
`endif

  assign halted    = halted_q;
  assign exit_code = exit_q;

  assign tr_valid = memwb_valid & ~halted_q;
  assign tr_pc    = memwb_pc;
  assign tr_we    = memwb_we;
  assign tr_rd    = memwb_rd;
  assign tr_val   = memwb_val;
  assign tr_meta  = memwb_meta;
  assign tr_trap  = memwb_trap;
  assign tr_irq   = memwb_irq;
  assign tr_cause = memwb_cause;
  assign tr_tval  = memwb_tval;
endmodule
