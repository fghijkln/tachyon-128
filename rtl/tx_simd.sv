// TACHYON-128 packed-SIMD unit: lanes of 8/16/32/64 bits inside one 128-bit GPR.
`default_nettype none

// All lanes of one width W.  sop numbering = SIMD_FUNCS in tools/isa.py
module tx_simd_lanes #(parameter int W = 8) (
  input  wire logic [4:0]   sop,
  input  wire logic [127:0] a,
  input  wire logic [127:0] b,
  output logic      [127:0] y
);
  localparam int N = 128 / W;
  localparam int SB = $clog2(W);
  wire [SB-1:0] sh = b[SB-1:0];

  // horizontal sum of unsigned lanes
  logic [127:0] hsum;
  always_comb begin
    hsum = '0;
    for (int i = 0; i < N; i++) hsum = hsum + {{(128-W){1'b0}}, a[i*W +: W]};
  end

  genvar i;
  generate for (i = 0; i < N; i = i + 1) begin : g_lane
    wire [W-1:0] x = a[i*W +: W];
    wire [W-1:0] z = b[i*W +: W];
    wire [W:0] uadd = {1'b0, x} + {1'b0, z};
    wire [W:0] usub = {1'b0, x} - {1'b0, z};
    wire [W:0] sadd = {x[W-1], x} + {z[W-1], z};
    wire [W:0] ssub = {x[W-1], x} - {z[W-1], z};
    wire slt = $signed(x) < $signed(z);
    wire ult = x < z;
    localparam logic [W-1:0] SMAX = {1'b0, {(W-1){1'b1}}};
    localparam logic [W-1:0] SMIN = {1'b1, {(W-1){1'b0}}};
    logic [W-1:0] r;
    logic [2*W-1:0] prod;
    always_comb begin
      prod = (W == 64) ? '0 : x * z;   // vmul.d is illegal; no 64x64 multipliers built
      case (sop)
        5'd0:  r = uadd[W-1:0];                                           // vadd
        5'd1:  r = usub[W-1:0];                                           // vsub
        5'd2:  r = (sadd[W] != sadd[W-1]) ? (sadd[W] ? SMIN : SMAX) : sadd[W-1:0]; // vaddss
        5'd3:  r = uadd[W] ? {W{1'b1}} : uadd[W-1:0];                     // vaddus
        5'd4:  r = (ssub[W] != ssub[W-1]) ? (ssub[W] ? SMIN : SMAX) : ssub[W-1:0]; // vsubss
        5'd5:  r = usub[W] ? '0 : usub[W-1:0];                            // vsubus
        5'd6:  r = slt ? x : z;                                           // vmins
        5'd7:  r = ult ? x : z;                                           // vminu
        5'd8:  r = slt ? z : x;                                           // vmaxs
        5'd9:  r = ult ? z : x;                                           // vmaxu
        5'd10: r = (x == z) ? {W{1'b1}} : '0;                             // vcmpeq
        5'd11: r = (!slt && x != z) ? {W{1'b1}} : '0;                     // vcmpgts
        5'd12: r = (!ult && x != z) ? {W{1'b1}} : '0;                     // vcmpgtu
        5'd13: r = prod[W-1:0];                                           // vmul
        5'd14: r = a[W-1:0];                                              // vsplat
        5'd16: r = x << sh;                                               // vsll
        5'd17: r = x >> sh;                                               // vsrl
        5'd18: r = $unsigned($signed(x) >>> sh);                          // vsra
        default: r = '0;
      endcase
    end
    assign y[i*W +: W] = (sop == 5'd15) ? hsum[i*W +: W] : r;          // vsum (whole reg)
  end endgenerate
endmodule

module tx_simd (
  input  wire logic [4:0]   sop,
  input  wire logic [1:0]   lw,
  input  wire logic [127:0] a,
  input  wire logic [127:0] b,
  output logic      [127:0] y
);
  logic [127:0] y8, y16, y32, y64;
  tx_simd_lanes #(8) u8 (.sop(sop), .a(a), .b(b), .y(y8));
  tx_simd_lanes #(16) u16 (.sop(sop), .a(a), .b(b), .y(y16));
  tx_simd_lanes #(32) u32 (.sop(sop), .a(a), .b(b), .y(y32));
  tx_simd_lanes #(64) u64 (.sop(sop), .a(a), .b(b), .y(y64));
  always_comb
    case (lw)
      2'd0: y = y8;
      2'd1: y = y16;
      2'd2: y = y32;
      default: y = y64;
    endcase
endmodule
