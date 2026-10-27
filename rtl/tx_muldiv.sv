// TACHYON-128 iterative multiply/divide unit.
//  * MUL/MULHU: radix-2^MUL_BITS multiplier: each cycle one 128 x MUL_BITS partial-product array
//    is added into the 256-bit accumulator. Default MUL_BITS = 32: 4 passes, latency 6 cycles in EX
//    (v2: radix-16, 32 passes, 35 cycles). Full 256-bit product.
//    v4: with MUL_BITS = 32 the 128 x 32 array is NOT inside this module: each pass borrows the
//    core's shared tx_mul32x4 (four Booth-recoded 32 x 32 multipliers that SIMD vmul also uses) through
//    the sh_* ports and only adds the four 64-bit products into the accumulator here.
//  * DIV/DIVU/REM/REMU: radix-4 restoring on magnitudes (2 quotient bits per cycle: the three
//    candidates 4R+d-B, 4R+d-2B, 4R+d-3B are compared in parallel) with operand-normalised early
//    termination: only n = sig(|a|) - sig(|b|) + 1 quotient bits are produced (rounded up to even),
//    the remainder register is preloaded with the top bits of |a| that cannot yet produce a 1.
//    Latency = ceil(n/2) + 2 cycles (n = 0 when |a| has fewer significant bits than |b|).
//    Divide-by-zero is instant.
//  * Result cache: the last product (lo,hi) or quotient/remainder pair is kept with its
//    operands, so MULHU after MUL, or REMU after DIVU, on the same operands takes 0 extra cycles.
// op: 0 MUL, 1 MULHU, 2 DIV, 3 DIVU, 4 REM, 5 REMU; w1 (v5 mulw/mulwu): one 32-bit pass, low word in y[31:0]
`default_nettype none
module tx_muldiv #(
`ifdef TX_DIV_STEPS
  parameter int DIV_STEPS = `TX_DIV_STEPS
`else
  parameter int DIV_STEPS = 2      // radix-4 steps per cycle: 1 = radix-4 (2 b/cycle), 2 = 4 b/cycle
`endif
  ,
`ifdef TX_MUL_BITS
  parameter int MUL_BITS = `TX_MUL_BITS
`else
  parameter int MUL_BITS = 32      // multiplier bits retired per cycle (must divide 128): 4 = v2 radix-16
`endif
) (
  input  wire logic         clk,
  input  wire logic         rst,
  input  wire logic         req,     // EX holds a valid mul/div instruction
  input  wire logic         abort,   // EX is being flushed
  input  wire logic [2:0]   op,
  input  wire logic         w1,      // v5 mulw: only the low 32 product bits are needed (32 multiplier bits)
  input  wire logic [127:0] a,
  input  wire logic [127:0] b,
  output logic              ready,   // y valid this cycle; EX may advance
  output logic      [127:0] y,
  // shared multiplier array (used when MUL_BITS == 32): one 128 x 32 pass per cycle
  output logic              sh_busy, // a multiply pass needs the array this cycle
  output logic      [127:0] sh_x,    // multiplicand
  output logic      [31:0]  sh_z,    // multiplier chunk (same for all four 32 x 32 multipliers)
  input  wire logic [255:0] sh_p     // four 64-bit products: sh_p[64i +: 64] = sh_x[32i +: 32] * sh_z
);
  localparam logic [1:0] IDLE = 2'd0, RUN = 2'd1, DONE = 2'd2;
  logic [1:0] st;

  wire is_mul   = (op == 3'd0) || (op == 3'd1);
  wire is_sdiv  = (op == 3'd2) || (op == 3'd4);
  wire want_hi  = (op == 3'd1) || (op == 3'd4) || (op == 3'd5);
  wire [2:0] kind = (is_mul & w1) ? 3'd4 : is_mul ? 3'd1 : (is_sdiv ? 3'd3 : 3'd2);   // 4: mulw low word

  // ---------------------------------------------------------------- result cache
  logic [2:0]   c_kind;            // 0 = invalid
  logic [127:0] c_a, c_b, c_lo, c_hi;
  wire hit = (c_kind == kind) && (c_a == a) && (c_b == b);

  // ---------------------------------------------------------------- divide by zero (instant)
  wire dz = !is_mul && (b == '0);
  wire [127:0] dz_y = want_hi ? a : {128{1'b1}};

  // ---------------------------------------------------------------- datapath registers
  logic [255:0] acc;               // mul: {H,L}
  logic [127:0] mA;                // mul multiplicand
  logic [127:0] R;                 // div partial remainder (always < divisor)
  logic [127:0] Q, Bd;             // div quotient/dividend shift reg, divisor
  logic [129:0] Bd3;               // 3 x divisor
  logic         qneg, rneg, lmul;
  logic [7:0]   cnt;
  logic [2:0]   l_kind;
  logic         l_w1;
  logic [127:0] l_a, l_b;

  // magnitudes & leading-zero count for the divider
  wire sa = is_sdiv & a[127];
  wire sb = is_sdiv & b[127];
  wire [127:0] magA = sa ? -a : a;
  wire [127:0] magB = sb ? -b : b;
  logic [7:0] lz, lzb;
  always_comb begin
    lz = 8'd128; lzb = 8'd128;
    for (int i = 0; i < 128; i++) begin
      if (magA[i]) lz  = 8'd127 - i[7:0];
      if (magB[i]) lzb = 8'd127 - i[7:0];
    end
  end
  // quotient bits needed: n = sigA - sigB + 1 = lzb - lz + 1 (0 if negative), rounded up to a
  // multiple of the bits retired per cycle (2*DIV_STEPS); never exceeds 128
  localparam int BPC = 2 * DIV_STEPS;
  wire [8:0] qn_raw = (lz > lzb) ? 9'd0 : ({1'b0, lzb} - {1'b0, lz} + 9'd1);
  wire [8:0] qn_up  = qn_raw + 9'(BPC - 1);
  wire [7:0] qn     = qn_up[7:0] & ~8'(BPC - 1);

  // one multiply pass: high half + multiplicand x next MUL_BITS multiplier bits
  localparam int MPASS = 128 / MUL_BITS;
  logic [127+MUL_BITS:0] mstep;
  assign sh_x = mA;
  assign sh_z = acc[31:0];
  generate if (MUL_BITS == 32) begin : g_shared
    assign sh_busy = (st == RUN) & lmul;
    // four products at bit offsets 0/32/64/96: two non-overlapping concatenations + the accumulator
    assign mstep = {32'd0, acc[255:128]} + {32'd0, sh_p[191:128], sh_p[63:0]} + {sh_p[255:192], sh_p[127:64], 32'd0};
  end else begin : g_own
    assign sh_busy = 1'b0;
    assign mstep = {{MUL_BITS{1'b0}}, acc[255:128]} + mA * acc[MUL_BITS-1:0];
  end endgenerate
  wire [255:0]          acc_nx = {mstep, acc[127:MUL_BITS]};
  // radix-4 divide step: r4 = 4R + next two dividend bits (< 4B); candidates compared in parallel
  function automatic logic [129:0] r4step(input logic [127:0] r, input logic [1:0] nb,
                                          input logic [127:0] bd, input logic [129:0] bd3);
    logic [130:0] r4, d1, d2, d3;
    r4 = {1'b0, r, nb};
    d1 = r4 - {3'd0, bd};
    d2 = r4 - {2'd0, bd, 1'b0};
    d3 = r4 - {1'd0, bd3};
    if (!d3[130])      r4step = {2'd3, d3[127:0]};
    else if (!d2[130]) r4step = {2'd2, d2[127:0]};
    else if (!d1[130]) r4step = {2'd1, d1[127:0]};
    else               r4step = {2'd0, r4[127:0]};
  endfunction
  logic [127:0] r_nx, q_nx;
  always_comb begin
    logic [129:0] st1;
    r_nx = R; q_nx = Q;
    for (int k = 0; k < DIV_STEPS; k++) begin
      st1  = r4step(r_nx, q_nx[127:126], Bd, Bd3);
      r_nx = st1[127:0];
      q_nx = {q_nx[125:0], st1[129:128]};
    end
  end

  wire start = req && !abort && (st == IDLE) && !hit && !dz;

  always_comb begin
    if (st == DONE) begin
      ready = 1'b1;
      y = want_hi ? c_hi : c_lo;
    end else if (st == IDLE && req && hit) begin
      ready = 1'b1;
      y = want_hi ? c_hi : c_lo;
    end else if (st == IDLE && req && dz) begin
      ready = 1'b1;
      y = dz_y;
    end else begin
      ready = 1'b0;
      y = '0;
    end
  end

  always_ff @(posedge clk) begin
    if (rst) begin
      st <= IDLE;
      c_kind <= 3'd0;
      cnt <= '0;
    end else if (abort && st != DONE) begin
      st <= IDLE;
    end else begin
      case (st)
        IDLE: if (start) begin
          l_kind <= kind; l_a <= a; l_b <= b;
          lmul <= is_mul;
          l_w1 <= w1;
          if (is_mul) begin
            acc <= {128'd0, b};
            mA  <= a;
            cnt <= w1 ? 8'(32 / MUL_BITS) : 8'(MPASS);
            st  <= RUN;
          end else begin
            qneg <= sa ^ sb;
            rneg <= sa;
            Bd   <= magB;
            Bd3  <= {2'd0, magB} + {1'd0, magB, 1'b0};
            R    <= magA >> qn;
            Q    <= magA << (8'd128 - qn);
            cnt  <= qn / 8'(BPC);
            st   <= RUN;
          end
        end
        RUN: begin
          if (lmul && cnt == 8'd1) begin       // last pass writes the cache directly
            c_kind <= l_kind; c_a <= l_a; c_b <= l_b;
            c_lo <= l_w1 ? {96'd0, acc_nx[127:96]} : acc_nx[127:0];   // after 32 multiplier bits the low word is here
            c_hi <= acc_nx[255:128];
            st <= DONE;
          end else if (cnt == 0) begin
            c_kind <= l_kind; c_a <= l_a; c_b <= l_b;
            if (lmul) begin
              c_lo <= acc[127:0];
              c_hi <= acc[255:128];
            end else begin
              c_lo <= qneg ? -Q : Q;
              c_hi <= rneg ? -R : R;
            end
            st <= DONE;
          end else begin
            cnt <= cnt - 8'd1;
            if (lmul) acc <= acc_nx;
            else begin
              R <= r_nx;
              Q <= q_nx;
            end
          end
        end
        DONE: st <= IDLE;
        default: st <= IDLE;
      endcase
    end
  end
endmodule
