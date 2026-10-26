// TACHYON-128 iterative multiply/divide unit.
//  * MUL/MULHU: radix-16 shift-add, 32 iterations, full 256-bit product.
//  * DIV/DIVU/REM/REMU: radix-2 restoring on magnitudes, skipping the dividend's leading
//    zeros (latency = 1 + significant bits of |dividend|).  Divide-by-zero is instant.
//  * Result cache: the last product (lo,hi) or quotient/remainder pair is kept with its
//    operands, so MULHU after MUL, or REMU after DIVU, on the same operands takes 0 extra cycles.
// op: 0 MUL, 1 MULHU, 2 DIV, 3 DIVU, 4 REM, 5 REMU
`default_nettype none
module tx_muldiv (
  input  wire logic         clk,
  input  wire logic         rst,
  input  wire logic         req,     // EX holds a valid mul/div instruction
  input  wire logic         abort,   // EX is being flushed
  input  wire logic [2:0]   op,
  input  wire logic [127:0] a,
  input  wire logic [127:0] b,
  output logic              ready,   // y valid this cycle; EX may advance
  output logic      [127:0] y
);
  localparam logic [1:0] IDLE = 2'd0, RUN = 2'd1, DONE = 2'd2;
  logic [1:0] st;

  wire is_mul   = (op == 3'd0) || (op == 3'd1);
  wire is_sdiv  = (op == 3'd2) || (op == 3'd4);
  wire want_hi  = (op == 3'd1) || (op == 3'd4) || (op == 3'd5);
  wire [1:0] kind = is_mul ? 2'd1 : (is_sdiv ? 2'd3 : 2'd2);

  // ---------------------------------------------------------------- result cache
  logic [1:0]   c_kind;            // 0 = invalid
  logic [127:0] c_a, c_b, c_lo, c_hi;
  wire hit = (c_kind == kind) && (c_a == a) && (c_b == b);

  // ---------------------------------------------------------------- divide by zero (instant)
  wire dz = !is_mul && (b == '0);
  wire [127:0] dz_y = want_hi ? a : {128{1'b1}};

  // ---------------------------------------------------------------- datapath registers
  logic [255:0] acc;               // mul: {H,L}
  logic [127:0] mA;                // mul multiplicand
  logic [128:0] R;                 // div remainder
  logic [127:0] Q, Bd;             // div quotient/dividend shift reg, divisor
  logic         qneg, rneg, lmul;
  logic [7:0]   cnt;
  logic [1:0]   l_kind;
  logic [127:0] l_a, l_b;

  // magnitudes & leading-zero count for the divider
  wire sa = is_sdiv & a[127];
  wire sb = is_sdiv & b[127];
  wire [127:0] magA = sa ? -a : a;
  wire [127:0] magB = sb ? -b : b;
  logic [7:0] lz;
  always_comb begin
    lz = 8'd128;
    for (int i = 0; i < 128; i++) if (magA[i]) lz = 8'd127 - i[7:0];
  end

  // one multiply step
  wire [131:0] mstep = {4'd0, acc[255:128]} + mA * acc[3:0];
  // one divide step
  wire [128:0] r_sh = {R[127:0], Q[127]};
  wire [129:0] r_df = {1'b0, r_sh} - {2'b0, Bd};
  wire         r_ge = !r_df[129];

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
      c_kind <= 2'd0;
      cnt <= '0;
    end else if (abort && st != DONE) begin
      st <= IDLE;
    end else begin
      case (st)
        IDLE: if (start) begin
          l_kind <= kind; l_a <= a; l_b <= b;
          lmul <= is_mul;
          if (is_mul) begin
            acc <= {128'd0, b};
            mA  <= a;
            cnt <= 8'd32;
            st  <= RUN;
          end else begin
            qneg <= sa ^ sb;
            rneg <= sa;
            Bd   <= magB;
            R    <= '0;
            Q    <= magA << lz;
            cnt  <= 8'd128 - lz;
            st   <= RUN;
          end
        end
        RUN: begin
          if (cnt == 0) begin
            c_kind <= l_kind; c_a <= l_a; c_b <= l_b;
            if (lmul) begin
              c_lo <= acc[127:0];
              c_hi <= acc[255:128];
            end else begin
              c_lo <= qneg ? -Q : Q;
              c_hi <= rneg ? -R[127:0] : R[127:0];
            end
            st <= DONE;
          end else begin
            cnt <= cnt - 8'd1;
            if (lmul) acc <= {mstep, acc[127:4]};
            else begin
              R <= r_ge ? r_df[128:0] : r_sh;
              Q <= {Q[126:0], r_ge};
            end
          end
        end
        DONE: st <= IDLE;
        default: st <= IDLE;
      endcase
    end
  end
endmodule
