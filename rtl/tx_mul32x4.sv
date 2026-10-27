// TACHYON-128 shared multiplier array (v4): four fracturable 32 x 32 multipliers.
//  Multiplier i takes x[32i+31:32i] and z[32i+31:32i] and produces a 64-bit result p[64i+63:64i]:
//   mode 0: one unsigned 32 x 32 product (full 64 bits)
//   mode 1: two 16 x 16 products, lane l (l = 0,1) at p[64i + 32l +: 32]
//   mode 2: four 8 x 8 products,  lane l (l = 0..3) at p[64i + 16l +: 16]
//  Every lane product is exact and non-negative, so lanes never interfere.
//  Users: the scalar multiplier (one 128 x 32 pass per cycle = 4 x mode-0 products of the same 32-bit
//  multiplier chunk) and SIMD vmul.b/.h/.w (lane product low halves). They never need it in the same
//  cycle: while a mul iterates, EX holds the mul and no SIMD instruction can be there.
//  Default implementation: radix-4 Booth recoding with per-lane digit boundaries (17 digit rows + one
//  closing row per inner lane boundary, instead of 32 AND rows).  +define+TX_MUL_ANDARRAY selects a plain
//  masked AND-array (32 rows) with the same function.
`default_nettype none
module tx_mul32x4 (
  input  wire logic [127:0] x,
  input  wire logic [127:0] z,
  input  wire logic [1:0]   mode,
  output logic      [255:0] p
);
  wire s16 = (mode == 2'd1), s8 = (mode == 2'd2);
  genvar i;
  generate for (i = 0; i < 4; i = i + 1) begin : g_m
    wire [31:0] a = x[32*i +: 32];
    wire [31:0] b = z[32*i +: 32];
    logic [63:0] s;
`ifdef TX_MUL_ANDARRAY
    always_comb begin
      logic [31:0] row;
      s = '0;
      for (int j = 0; j < 32; j++) begin
        for (int k = 0; k < 32; k++)
          row[k] = a[k] & b[j] & (~(s16 | s8) | (s16 & (j / 16 == k / 16)) | (s8 & (j / 8 == k / 8)));
        s = s + ({32'd0, row} << j);
      end
    end
`else
    always_comb begin
      logic [2:0]  d;
      logic [33:0] pp;
      logic        neg, bnd, bm1;
      logic [31:0] lm, pm, m;
      s = '0;
      for (int j = 0; j < 17; j++) begin
        // digit j covers multiplier bits 2j+1, 2j, 2j-1; bit 2j-1 is dropped when a lane starts at 2j
        bnd = (j == 0) | (j == 16) | ((s16 | s8) & (j == 8)) | (s8 & ((j == 4) | (j == 12)));
        bm1 = (j == 0) ? 1'b0 : (j == 16) ? b[31] : (b[2*j-1] & ~bnd);
        d   = {(j == 16) ? 1'b0 : b[2*j+1], (j == 16) ? 1'b0 : b[2*j], bm1};
        // multiplicand = the x lane that z bit 2j belongs to (lm); pm = lane of z bit 2j-1
        lm = s8 ? (32'hFF << (8 * ((2*j) / 8))) : s16 ? (32'hFFFF << (16 * ((2*j) / 16))) : 32'hFFFF_FFFF;
        pm = (j == 0) ? 32'd0 : s8 ? (32'hFF << (8 * ((2*j-1) / 8))) : (32'hFFFF << (16 * ((2*j-1) / 16)));
        m  = a & ((j == 16) ? ((s16 | s8) ? pm : 32'hFFFF_FFFF) : lm);   // top digit closes the last lane
        case (d)
          3'b001, 3'b010: begin pp = {2'b00, m};       neg = 1'b0; end   // +1
          3'b011:         begin pp = {1'b0, m, 1'b0};  neg = 1'b0; end   // +2
          3'b100:         begin pp = {1'b0, m, 1'b0};  neg = 1'b1; end   // -2
          3'b101, 3'b110: begin pp = {2'b00, m};       neg = 1'b1; end   // -1
          default:        begin pp = '0;               neg = 1'b0; end
        endcase
        if (neg) pp = ~pp;
        if (j < 16) s = s + (({{30{pp[33]}}, pp} + {63'd0, neg}) << (2*j));
        else        s = s + ({30'd0, pp} << 32);                          // top digit: 0 or +1
        // an inner lane ending at bit 2j-1 needs its own closing digit (0 or +1) at weight 4^j (split modes)
        if (j == 4 || j == 8 || j == 12)
          s = s + ({32'd0, a & pm & {32{b[2*j-1] & bnd}}} << (2*j));
      end
    end
`endif
    assign p[64*i +: 64] = s;
  end endgenerate
endmodule
