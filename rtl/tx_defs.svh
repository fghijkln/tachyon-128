// TACHYON-128 shared constants (mirrors tools/isa.py; tests/check_defs.py keeps them in sync)
localparam logic [5:0] OP_ALU = 6'h01, OP_MULDIV = 6'h02, OP_SIMD = 6'h03, OP_CAP = 6'h04;
localparam logic [5:0] OP_ADDI = 6'h08, OP_ANDI = 6'h09, OP_ORI = 6'h0A, OP_XORI = 6'h0B,
                       OP_SLTI = 6'h0C, OP_SLTIU = 6'h0D, OP_SLLI = 6'h0E, OP_SRLI = 6'h0F,
                       OP_SRAI = 6'h10, OP_CINCADDRI = 6'h11, OP_CSETBNDI = 6'h12, OP_WIDE = 6'h14;
localparam logic [5:0] OP_LB = 6'h18, OP_LH = 6'h19, OP_LW = 6'h1A, OP_LD = 6'h1B, OP_LQ = 6'h1C,
                       OP_LBU = 6'h1D, OP_LHU = 6'h1E, OP_LWU = 6'h1F, OP_LDU = 6'h20, OP_CLC = 6'h21;
localparam logic [5:0] OP_SB = 6'h28, OP_SH = 6'h29, OP_SW = 6'h2A, OP_SD = 6'h2B, OP_SQ = 6'h2C, OP_CSC = 6'h2D;
localparam logic [5:0] OP_BEQ = 6'h30, OP_BNE = 6'h31, OP_BLT = 6'h32, OP_BGE = 6'h33,
                       OP_BLTU = 6'h34, OP_BGEU = 6'h35;
localparam logic [5:0] OP_JAL = 6'h38, OP_JALR = 6'h39, OP_ECALL = 6'h3B, OP_HALT = 6'h3C, OP_CSRR = 6'h3D,
                       OP_CSRW = 6'h3E, OP_ERET = 6'h3F;

localparam logic [7:0] N_ALU = 8'd19, N_MULDIV = 8'd6, N_CAP = 8'd17;
localparam logic [4:0] CF_CGETPCC = 5'd9, CF_CSETEPCC = 5'd10, CF_CJALR = 5'd11,
                       CF_CSEAL = 5'd12, CF_CUNSEAL = 5'd13, CF_CGETTYPE = 5'd14,
                       CF_CSEALENTRY = 5'd15, CF_CINVOKE = 5'd16;
localparam logic [15:0] OTYPE_SENTRY = 16'hFFFF;    // reserved otype of sealed entry capabilities
localparam logic [5:0] N_SIMD = 6'd19;
localparam logic [13:0] N_CSR = 14'd8;
localparam logic [4:0] SIMD_VMUL = 5'd13;

// ALU function codes
localparam logic [4:0] A_ADD = 0, A_SUB = 1, A_AND = 2, A_OR = 3, A_XOR = 4, A_SLL = 5, A_SRL = 6,
                       A_SRA = 7, A_SLT = 8, A_SLTU = 9, A_MIN = 10, A_MAX = 11, A_MINU = 12,
                       A_MAXU = 13, A_ANDN = 14, A_SEQ = 15, A_CLZ = 16, A_CTZ = 17, A_POPCNT = 18;

// trap causes
localparam logic [3:0] C_ILLEGAL = 1, C_CAP_TAG = 2, C_CAP_BOUNDS = 3, C_CAP_PERM = 4,
                       C_ALIGN = 5, C_ACCESS = 6, C_CAP_SEALED = 7,
                       C_ECALL = 8, C_PRIV = 9;

// MMIO
localparam logic [127:0] MMIO_EXIT = {112'hFFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFF, 16'h0010};
localparam logic [127:0] MMIO_MTIME = {112'hFFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFF, 16'h0030};
localparam logic [127:0] MMIO_MTIMECMP = {112'hFFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFF, 16'h0040};
localparam logic [3:0] IRQ_TIMER = 4'd1;

// metadata packing: {tag, otype[15:0], perm[PW-1:0], base[127:0], top[128:0]}
//   perm bits: 0 LOAD, 1 STORE, 2 EXEC, 3 LOAD_CAP, 4 STORE_CAP, 5 SEAL, 6 UNSEAL; otype 0 = unsealed
localparam int PW = 7;
localparam int MW = 1 + 16 + PW + 128 + 129;
localparam int M_TAG = MW - 1;          // tag bit
localparam int M_PERM = 257;            // perm  = meta[M_PERM +: PW]
localparam int M_OT = M_PERM + PW;      // otype = meta[M_OT +: 16]
localparam logic [PW-1:0] PERM_ALL = 7'h7F;
localparam logic [MW-1:0] ROOT_META = {1'b1, 16'd0, PERM_ALL, 128'd0, 1'b1, 128'd0};
