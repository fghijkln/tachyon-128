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
  output logic      [3:0]   tr_cause,
  output logic      [127:0] tr_tval
);
  `include "tx_defs.svh"
  localparam int RB = $clog2(RAM_BYTES);

  // decoded instruction class bits
  localparam int K_ALUR = 0, K_MD = 1, K_SIMD = 2, K_CAPR = 3, K_ALUI = 4, K_CAPI = 5, K_WIDE = 6,
                 K_LOAD = 7, K_STORE = 8, K_BR = 9, K_JAL = 10, K_JALR = 11, K_HALT = 12,
                 K_CSRR = 13, K_CSRW = 14, K_ERET = 15, K_ILL = 16, NK = 17;

  function automatic logic [NK-1:0] decode(input logic [31:0] i);
    logic [5:0] op; logic [7:0] fn; logic [NK-1:0] k;
    op = i[5:0]; fn = i[31:24]; k = '0;
    case (op)
      OP_ALU:    if (fn < N_ALU) k[K_ALUR] = 1; else k[K_ILL] = 1;
      OP_MULDIV: if (fn < N_MULDIV) k[K_MD] = 1; else k[K_ILL] = 1;
      OP_SIMD:   if (fn[7:2] < N_SIMD && !(fn[7:2] == {1'b0, SIMD_VMUL} && fn[1:0] == 2'd3)) k[K_SIMD] = 1;
                 else k[K_ILL] = 1;
      OP_CAP:    if (fn < N_CAP) k[K_CAPR] = 1; else k[K_ILL] = 1;
      OP_ADDI, OP_ANDI, OP_ORI, OP_XORI, OP_SLTI, OP_SLTIU, OP_SLLI, OP_SRLI, OP_SRAI: k[K_ALUI] = 1;
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
      default:   k[K_ILL] = 1;
    endcase
    decode = k;
  endfunction

  function automatic logic writes_rd(input logic [NK-1:0] k);
    writes_rd = k[K_ALUR] | k[K_MD] | k[K_SIMD] | k[K_CAPR] | k[K_ALUI] | k[K_CAPI] | k[K_WIDE] |
           k[K_LOAD] | k[K_JAL] | k[K_JALR] | k[K_CSRR];
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
  logic         idex_valid, idex_fault, idex_pred, idex_we;
  logic [127:0] idex_pc, idex_v1, idex_v2;
  logic [MW-1:0] idex_m1, idex_m2;
  logic [31:0]  idex_inst;
  logic [5:0]   idex_rs1, idex_rs2, idex_rd;
  // EX/MEM
  logic         exmem_valid, exmem_we, exmem_load, exmem_store, exmem_trap, exmem_csrr,
                exmem_csrw, exmem_eret, exmem_halt, exmem_mmio, exmem_clc, exmem_csc, exmem_ldcap;
  logic [MW-1:0] exmem_smeta, exmem_tmeta;
  logic         exmem_cjalr, exmem_setepcc;
  logic [127:0] exmem_pc, exmem_val, exmem_ea, exmem_sdata, exmem_tval;
  logic [MW-1:0] exmem_meta;
  logic [5:0]   exmem_rd, exmem_op;
  logic [3:0]   exmem_cause;
  logic [2:0]   exmem_csr;
  logic [31:0]  exmem_code;
  // MEM/WB
  logic         memwb_valid, memwb_we, memwb_trap, memwb_halt;
  logic [127:0] memwb_pc, memwb_val, memwb_tval;
  logic [MW-1:0] memwb_meta;
  logic [5:0]   memwb_rd;
  logic [3:0]   memwb_cause;
  logic [31:0]  memwb_code;
  // CSRs
  logic [127:0] csr_tvec, csr_epc, csr_cause, csr_tval, csr_scratch;

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

  // ======================================================================== ID
  wire [NK-1:0] id_k   = decode(ifid_inst);
  wire [5:0]   id_fa   = ifid_inst[11:6];
  wire [5:0]   id_rs1  = ifid_inst[17:12];
  wire [5:0]   id_rs2  = (id_k[K_STORE] | id_k[K_BR] | id_k[K_WIDE]) ? id_fa : ifid_inst[23:18];
  wire         id_use1 = id_k[K_ALUR] | id_k[K_MD] | id_k[K_SIMD] | id_k[K_CAPR] | id_k[K_ALUI] |
                         id_k[K_CAPI] | id_k[K_LOAD] | id_k[K_STORE] | id_k[K_BR] | id_k[K_JALR] |
                         id_k[K_HALT] | id_k[K_CSRW];
  wire         id_use2 = id_k[K_ALUR] | id_k[K_MD] | id_k[K_SIMD] | id_k[K_CAPR] | id_k[K_STORE] |
                         id_k[K_BR] | (id_k[K_WIDE] & ifid_inst[15]);
  wire         id_csetepcc = id_k[K_CAPR] & (ifid_inst[27:24] == CF_CSETEPCC);
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
  wire         id_pred  = id_k[K_BR] & ifid_inst[31];          // backward branch -> taken
  wire [127:0] id_target = id_k[K_JAL] ? ifid_pc + (id_imm20 << 2) : ifid_pc + (id_imm14 << 2);

  // load-use / csrr-use interlock
  wire ex_is_late = idex_valid & idex_we & ((idex_inst[5:0] >= OP_LB && idex_inst[5:0] <= OP_CLC) ||
                    idex_inst[5:0] == OP_CSRR);
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
  wire mem_fwd_ok = exmem_valid & exmem_we & ~exmem_load & ~exmem_csrr;
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
      default:  alu_fn = A_ADD;
    endcase
  end
  wire is_shi = (ex_op == OP_SLLI) | (ex_op == OP_SRLI) | (ex_op == OP_SRAI);
  wire [127:0] alu_b = ex_k[K_ALUR] ? b : (is_shi ? ex_uimm : ex_imm);
  logic [127:0] alu_y;
  tx_alu u_alu (.func(alu_fn), .a(a), .b(alu_b), .y(alu_y));

  // ---- SIMD
  logic [127:0] simd_y;
  tx_simd u_simd (.sop(ex_fn[6:2]), .lw(ex_fn[1:0]), .a(a), .b(b), .y(simd_y));

  // ---- MUL/DIV
  logic md_ready;
  logic [127:0] md_y;
  logic mem_redirect;
  tx_muldiv u_md (.clk(clk), .rst(rst), .req(idex_valid & ex_k[K_MD] & ~halted_q), .abort(mem_redirect),
                  .op(ex_fn[2:0]), .a(a), .b(b), .ready(md_ready), .y(md_y));
  wire stall_md = idex_valid & ex_k[K_MD] & ~md_ready;

  // ---- capabilities
  logic [3:0]   cap_fn;
  logic [127:0] cap_y, cap_x, cap_tv;
  logic [MW-1:0] cap_m;
  logic         cap_fault;
  logic [3:0]   cap_cause;
  wire  [128:0] cap_ntop = {1'b0, a} + {1'b0, cap_x};
  wire  [128:0] cap_len  = a_top - {1'b0, a_base};
  always_comb begin
    cap_fn = ex_k[K_CAPR] ? ex_fn[3:0] : (ex_op == OP_CINCADDRI ? 4'd1 : 4'd2);
    cap_x  = ex_k[K_CAPR] ? b : (ex_op == OP_CINCADDRI ? ex_imm : ex_uimm);
    cap_y = '0; cap_m = '0; cap_fault = 1'b0; cap_cause = C_CAP_TAG; cap_tv = a;
    case (cap_fn)
      4'd0: begin cap_y = cap_x; cap_m = ma; end                     // csetaddr
      4'd1: begin cap_y = a + cap_x; cap_m = ma; end                 // cincaddr
      4'd2: begin                                                    // csetbnd
        cap_y = a;
        cap_m = {1'b1, 16'd0, a_perm, a, cap_ntop};
        if (!a_tag) begin cap_fault = 1'b1; cap_cause = C_CAP_TAG; end
        else if (a < a_base || cap_ntop > a_top) begin cap_fault = 1'b1; cap_cause = C_CAP_BOUNDS; end
      end
      4'd3: begin                                                    // candperm
        cap_y = a;
        cap_m = a_tag ? {1'b1, 16'd0, a_perm & cap_x[PW-1:0], a_base, a_top} : '0;
      end
      4'd4: cap_y = a_base;                                          // cgetbase
      4'd5: cap_y = cap_len[128] ? {128{1'b1}} : cap_len[127:0];     // cgetlen
      4'd6: cap_y = {{(128-PW){1'b0}}, a_perm};                                // cgetperm
      4'd7: cap_y = {127'd0, a_tag};                                 // cgettag
      CF_CGETPCC: begin cap_y = idex_pc; cap_m = pcc_q; end
      CF_CSETEPCC: begin
        cap_m = ma;
        if (!a_tag) begin cap_fault = 1'b1; cap_cause = C_CAP_TAG; end
        else if (a_sealed) begin cap_fault = 1'b1; cap_cause = C_CAP_SEALED; end
      end
      CF_CJALR: begin                                                // link = PCC, cursor pc+4
        cap_y = idex_pc + 128'd4; cap_m = pcc_q;
        if (!a_tag) begin cap_fault = 1'b1; cap_cause = C_CAP_TAG; end
        else if (a_sealed) begin cap_fault = 1'b1; cap_cause = C_CAP_SEALED; end
        else if (!a_perm[2]) begin cap_fault = 1'b1; cap_cause = C_CAP_PERM; end
      end
      CF_CSEAL, CF_CUNSEAL: begin                                    // rs2 = sealing authority, cursor = otype
        cap_y = a;
        cap_m = {1'b1, (cap_fn == CF_CSEAL) ? b[15:0] : 16'd0, a_perm, a_base, a_top};
        cap_fault = 1'b1; cap_tv = b;
        if (!a_tag) begin cap_cause = C_CAP_TAG; cap_tv = a; end
        else if (!b_tag) cap_cause = C_CAP_TAG;
        else if ((cap_fn == CF_CSEAL) ? a_sealed : !a_sealed) begin cap_cause = C_CAP_SEALED; cap_tv = a; end
        else if (b_sealed) cap_cause = C_CAP_SEALED;
        else if (!b_perm[(cap_fn == CF_CSEAL) ? 5 : 6]) cap_cause = C_CAP_PERM;
        else if (b < b_base || {1'b0, b} >= b_top) cap_cause = C_CAP_BOUNDS;
        else if (cap_fn == CF_CSEAL && (b[15:0] == 16'd0 || |b[127:16])) cap_cause = C_CAP_BOUNDS;
        else if (cap_fn == CF_CUNSEAL && b != {112'd0, a_ot}) cap_cause = C_CAP_SEALED;
        else cap_fault = 1'b0;
      end
      CF_CGETTYPE: cap_y = {112'd0, a_ot};
      default: cap_y = a;                                            // cclrtag
    endcase
    // sealed capabilities are immutable: csetaddr / cincaddr / csetbnd / candperm trap
    if (cap_fn <= 4'd3 && a_sealed) begin cap_fault = 1'b1; cap_cause = C_CAP_SEALED; cap_tv = a; end
  end

  // ---- wide immediate
  wire [6:0]   wide_sh  = {idex_inst[14:12], 4'd0};
  wire [127:0] wide_ins = {112'd0, idex_inst[31:16]} << wide_sh;
  wire [127:0] wide_y   = idex_inst[15] ? ((b & ~({112'd0, 16'hFFFF} << wide_sh)) | wide_ins) : wide_ins;

  // ---- memory address + checks
  wire [127:0] ea = a + ex_imm;
  logic [4:0] msize;
  always_comb
    case (ex_op)
      OP_LB, OP_LBU, OP_SB: msize = 5'd1;
      OP_LH, OP_LHU, OP_SH: msize = 5'd2;
      OP_LW, OP_LWU, OP_SW: msize = 5'd4;
      OP_LD, OP_LDU, OP_SD: msize = 5'd8;
      default:              msize = 5'd16;
    endcase
  wire         is_mem   = ex_k[K_LOAD] | ex_k[K_STORE];
  wire [128:0] ea_end   = {1'b0, ea} + {124'd0, msize};
  wire         need_p   = ex_k[K_STORE] ? a_perm[1] : a_perm[0];
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
    else if (a_tag && is_csc && b_tag && !a_perm[4]) mem_cause = C_CAP_PERM;   // STORE_CAP
    else if (a_tag && (ea < a_base || ea_end > a_top)) mem_cause = C_CAP_BOUNDS;
    else if (misalign) mem_cause = C_ALIGN;
    else if (!in_ram && !in_mmio) mem_cause = C_ACCESS;
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
  wire ex_mispred = ex_k[K_BR] & (br_taken != idex_pred);
  wire ex_cjalr  = ex_k[K_CAPR] & (ex_fn[3:0] == CF_CJALR);
  wire ex_setepcc = ex_k[K_CAPR] & (ex_fn[3:0] == CF_CSETEPCC);
  wire ex_redirect = idex_valid & (ex_mispred | ex_k[K_JALR] | (ex_cjalr & ~cap_fault));
  wire [127:0] ex_target = ex_cjalr ? (a & ~128'd3) : ex_k[K_JALR] ? jalr_tgt : (br_taken ? br_target : ex_pc4);

  // ---- result + trap select
  logic [127:0]  ex_val, ex_tval;
  logic [MW-1:0] ex_meta;
  logic          ex_trap;
  logic [3:0]    ex_cause;
  always_comb begin
    ex_val = alu_y; ex_meta = '0;
    if (ex_k[K_SIMD]) ex_val = simd_y;
    else if (ex_k[K_MD]) ex_val = md_y;
    else if (ex_k[K_CAPR] | ex_k[K_CAPI]) begin ex_val = cap_y; ex_meta = cap_m; end
    else if (ex_k[K_WIDE]) ex_val = wide_y;
    else if (ex_k[K_JAL] | ex_k[K_JALR]) ex_val = ex_pc4;
    else if (ex_k[K_CSRW]) ex_val = a;                   // CSR write data rides in exmem_val
    ex_trap = 1'b0; ex_cause = C_ACCESS; ex_tval = '0;
    if (idex_fault) begin ex_trap = 1'b1; ex_cause = idex_fcause; ex_tval = idex_pc; end
    else if (ex_k[K_ILL]) begin ex_trap = 1'b1; ex_cause = C_ILLEGAL; ex_tval = {96'd0, idex_inst}; end
    else if (is_mem && mem_fault) begin ex_trap = 1'b1; ex_cause = mem_cause; ex_tval = ea; end
    else if ((ex_k[K_CAPR] | ex_k[K_CAPI]) && cap_fault) begin ex_trap = 1'b1; ex_cause = cap_cause; ex_tval = cap_tv; end
  end

  // ======================================================================== MEM
  wire        mem_v     = exmem_valid;
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
  assign dmem_addr  = exmem_ea;
  assign dmem_re    = mem_v & exmem_load & ~exmem_trap;
  assign dmem_we    = mem_v & exmem_store & ~exmem_trap & ~halted_q;
  assign dmem_be    = be_raw << exmem_ea[3:0];
  assign dmem_wdata = exmem_sdata << mshift;
  assign dmem_wmeta = exmem_csc ? exmem_smeta : '0;

  wire [127:0] ld_raw = exmem_mmio ? '0 : (dmem_rdata >> mshift);
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
      default: csr_rd = csr_scratch;
    endcase

  wire mem_trap      = mem_v & exmem_trap;
  wire mem_trap_halt = mem_trap & (csr_tvec == '0);
  wire mem_halt      = mem_v & ~exmem_trap & exmem_halt;
  wire mem_eret      = mem_v & ~exmem_trap & exmem_eret;
  assign mem_redirect = mem_trap | mem_halt | mem_eret;
  wire [127:0] mem_target = mem_eret ? (csr_epc & ~128'd3) : (csr_tvec & ~128'd3);
  wire [MW-1:0] mem_tpcc  = mem_eret ? epcc_q : ROOT_META;   // PCC after the MEM redirect

  // ======================================================================== control
  wire stall = stall_lu | stall_md;
  wire id_redirect = ifid_valid & ~ifid_fault & (id_k[K_JAL] | id_pred);

  always_ff @(posedge clk) begin
    if (rst) begin
      pc_q <= '0; stop_fetch_q <= 1'b0; halted_q <= 1'b0; exit_q <= '0;
      fpcc_q <= ROOT_META; pcc_q <= ROOT_META; epcc_q <= ROOT_META;
      ifid_valid <= 1'b0; idex_valid <= 1'b0; exmem_valid <= 1'b0; memwb_valid <= 1'b0;
      csr_tvec <= '0; csr_epc <= '0; csr_cause <= '0; csr_tval <= '0; csr_scratch <= '0;
    end else if (!halted_q) begin
      // ---------------- PC
      if (mem_redirect)      pc_q <= mem_target;
      else if (ex_redirect)  pc_q <= ex_target;
      else if (stall)        pc_q <= pc_q;
      else if (id_redirect)  pc_q <= id_target;
      else if (!stop_fetch_q) pc_q <= pc_q + 128'd4;
      if (mem_halt | mem_trap_halt) stop_fetch_q <= 1'b1;
      if (mem_redirect)     fpcc_q <= mem_tpcc;
      else if (ex_redirect & ex_cjalr) fpcc_q <= ma;
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
        idex_pred <= id_pred;
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
        exmem_load  <= ex_k[K_LOAD];
        exmem_store <= ex_k[K_STORE];
        exmem_ea    <= ea;
        exmem_mmio  <= in_mmio;
        exmem_sdata <= b;
        exmem_smeta <= mb;
        exmem_tmeta <= ma;
        exmem_cjalr <= ex_cjalr & ~ex_trap;
        exmem_setepcc <= ex_setepcc & ~ex_trap;
        exmem_clc   <= is_clc;
        exmem_csc   <= is_csc;
        exmem_ldcap <= ~a_tag | a_perm[3];               // LOAD_CAP (or unchecked base)
        exmem_trap  <= ex_trap;
        exmem_cause <= ex_cause;
        exmem_tval  <= ex_tval;
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
      if (mem_trap) begin
        csr_epc <= exmem_pc; csr_cause <= {124'd0, exmem_cause}; csr_tval <= exmem_tval;
      end else if (mem_v && exmem_csrw) begin
        case (exmem_csr)
          3'd0: csr_tvec <= exmem_val;
          3'd1: csr_epc <= exmem_val;
          3'd2: csr_cause <= exmem_val;
          3'd3: csr_tval <= exmem_val;
          default: csr_scratch <= exmem_val;
        endcase
      end

      // ---------------- MEM/WB
      memwb_valid <= mem_v;
      memwb_pc    <= exmem_pc;
      memwb_rd    <= exmem_rd;
      memwb_we    <= exmem_we & ~exmem_trap;
      memwb_val   <= exmem_load ? ld_val : (exmem_csrr ? csr_rd : exmem_val);
      memwb_meta  <= exmem_load ? ((exmem_clc & ~exmem_mmio & exmem_ldcap & dmem_rmeta[M_TAG]) ? dmem_rmeta : '0)
                                : (exmem_csrr ? '0 : exmem_meta);
      memwb_trap  <= exmem_trap;
      memwb_cause <= exmem_cause;
      memwb_tval  <= exmem_tval;
      memwb_halt  <= mem_halt | mem_trap_halt;
      memwb_code  <= exmem_code;

      // ---------------- WB
      if (memwb_valid && memwb_halt) begin
        halted_q <= 1'b1;
        exit_q   <= memwb_trap ? 32'd0 : memwb_code;
      end
    end
  end

  assign halted    = halted_q;
  assign exit_code = exit_q;

  assign tr_valid = memwb_valid & ~halted_q;
  assign tr_pc    = memwb_pc;
  assign tr_we    = memwb_we;
  assign tr_rd    = memwb_rd;
  assign tr_val   = memwb_val;
  assign tr_meta  = memwb_meta;
  assign tr_trap  = memwb_trap;
  assign tr_cause = memwb_cause;
  assign tr_tval  = memwb_tval;
endmodule
