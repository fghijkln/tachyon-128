// TACHYON-128 integer ALU (128-bit, single cycle)
`default_nettype none
module tx_alu (
  input  wire logic [4:0]   func,
  input  wire logic [127:0] a,
  input  wire logic [127:0] b,
  output logic      [127:0] y
);
  `include "tx_defs.svh"

  wire [6:0] sh = b[6:0];
  wire lt_s = $signed(a) < $signed(b);
  wire lt_u = a < b;

  // v5 word ops: 32-bit result extended to 128 bits (sign, or zero for the ...WU forms)
  wire        wu = (func == A_ADDWU) | (func == A_SUBWU) | (func == A_SLLWU);
  logic [31:0] w;
  always_comb begin
    case (func)
      A_ADDW, A_ADDWU: w = a[31:0] + b[31:0];
      A_SUBW, A_SUBWU: w = a[31:0] - b[31:0];
      A_SLLW, A_SLLWU: w = a[31:0] << b[4:0];
      A_SRLW:          w = a[31:0] >> b[4:0];
      default:         w = $unsigned($signed(a[31:0]) >>> b[4:0]);   // A_SRAW
    endcase
  end
  wire [127:0] wy = {{96{w[31] & ~wu}}, w};

  logic [7:0] clz, ctz, pop;
  always_comb begin
    clz = 8'd128;
    for (int i = 0; i < 128; i++) if (a[i]) clz = 8'd127 - i[7:0];
    ctz = 8'd128;
    for (int i = 127; i >= 0; i--) if (a[i]) ctz = i[7:0];
    pop = 8'd0;
    for (int i = 0; i < 128; i++) pop = pop + {7'd0, a[i]};
  end

  always_comb begin
    case (func)
      A_ADD:    y = a + b;
      A_SUB:    y = a - b;
      A_AND:    y = a & b;
      A_OR:     y = a | b;
      A_XOR:    y = a ^ b;
      A_SLL:    y = a << sh;
      A_SRL:    y = a >> sh;
      A_SRA:    y = $unsigned($signed(a) >>> sh);
      A_SLT:    y = {127'd0, lt_s};
      A_SLTU:   y = {127'd0, lt_u};
      A_MIN:    y = lt_s ? a : b;
      A_MAX:    y = lt_s ? b : a;
      A_MINU:   y = lt_u ? a : b;
      A_MAXU:   y = lt_u ? b : a;
      A_ANDN:   y = a & ~b;
      A_SEQ:    y = {127'd0, a == b};
      A_CLZ:    y = {120'd0, clz};
      A_CTZ:    y = {120'd0, ctz};
      A_POPCNT: y = {120'd0, pop};
      A_ADDW, A_SUBW, A_SLLW, A_SRLW, A_SRAW, A_ADDWU, A_SUBWU, A_SLLWU: y = wy;
      default:  y = '0;
    endcase
  end
endmodule
