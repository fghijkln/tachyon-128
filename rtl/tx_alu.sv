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
      default:  y = '0;
    endcase
  end
endmodule
