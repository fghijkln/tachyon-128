// TACHYON-128 simulation top: RAM + MMIO console + commit-trace writer.
`default_nettype none
module tb (
  input  wire logic clk,
  input  wire logic rst,
  output logic      done
);
  `include "tx_defs.svh"
  localparam int RAM_BYTES = 262144;
  localparam int RAMW = RAM_BYTES / 16;
  localparam int RB = $clog2(RAM_BYTES);

  logic [127:0] ram [0:RAMW-1];
  logic [MW-1:0] tmeta [0:RAMW-1];      // shadow tag memory: tag + capability metadata per granule
  string prog, tracef, conf, memf, statf, tagf;
  integer ftr, fcon;
  longint unsigned cycles, retired;

  initial begin
    if (!$value$plusargs("prog=%s", prog)) prog = "prog.hex";
    if (!$value$plusargs("trace=%s", tracef)) tracef = "rtl.trace";
    if (!$value$plusargs("console=%s", conf)) conf = "rtl.console";
    if (!$value$plusargs("mem=%s", memf)) memf = "rtl.mem";
    if (!$value$plusargs("stat=%s", statf)) statf = "rtl.stat";
    if (!$value$plusargs("tags=%s", tagf)) tagf = "rtl.tags";
    for (int i = 0; i < RAMW; i++) begin ram[i] = '0; tmeta[i] = '0; end
    $readmemh(prog, ram);
    ftr = $fopen(tracef, "w");
    fcon = $fopen(conf, "wb");
    cycles = 0; retired = 0; done = 0;
  end

  logic [127:0] imem_addr, dmem_addr, dmem_wdata, dmem_rdata;
  logic [MW-1:0] dmem_wmeta, dmem_rmeta;
  logic [31:0] imem_rdata, exit_code;
  logic dmem_re, dmem_we, halted;
  logic [15:0] dmem_be;
  logic tr_valid, tr_we, tr_trap;
  logic [127:0] tr_pc, tr_val, tr_tval;
  logic [5:0] tr_rd;
  logic [MW-1:0] tr_meta;
  logic [3:0] tr_cause;

  tx_core #(.RAM_BYTES(RAM_BYTES)) u_core (.*);

  wire i_in = ~|imem_addr[127:RB];
  wire [127:0] iword = ram[imem_addr[RB-1:4]];
  assign imem_rdata = i_in ? iword[imem_addr[3:2]*32 +: 32] : 32'd0;
  wire d_in = ~|dmem_addr[127:RB];
  assign dmem_rdata = d_in ? ram[dmem_addr[RB-1:4]] : '0;
  assign dmem_rmeta = d_in ? tmeta[dmem_addr[RB-1:4]] : '0;

  logic [127:0] bemask;
  always_comb for (int i = 0; i < 16; i++) bemask[i*8 +: 8] = {8{dmem_be[i]}};

  always @(posedge clk) begin
    if (!rst && !done) begin
      cycles <= cycles + 1;
      if (dmem_we) begin
        if (d_in) begin
          ram[dmem_addr[RB-1:4]] <= (ram[dmem_addr[RB-1:4]] & ~bemask) | (dmem_wdata & bemask);
          tmeta[dmem_addr[RB-1:4]] <= dmem_wmeta;
        end
        else if (dmem_addr == {112'hFFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFF, 16'h0000})
          $fwrite(fcon, "%c", dmem_wdata[7:0]);
        else if (dmem_addr == {112'hFFFF_FFFF_FFFF_FFFF_FFFF_FFFF_FFFF, 16'h0020})
          $fwrite(fcon, "%032h\n", dmem_wdata & bemask);
      end
      if (tr_valid) begin
        if (tr_trap) $fwrite(ftr, "T %0d %0h %0h\n", tr_cause, tr_pc, tr_tval);
        else begin
          retired <= retired + 1;
          if (tr_we) begin
            if (tr_meta[M_TAG]) $fwrite(ftr, "%0h %0d %0h 1 %0d %0h %0h\n", tr_pc, tr_rd, tr_val,
                                      tr_meta[M_PERM +: PW], tr_meta[256:129], tr_meta[128:0]);
            else $fwrite(ftr, "%0h %0d %0h 0\n", tr_pc, tr_rd, tr_val);
          end else $fwrite(ftr, "%0h 0 0 0\n", tr_pc);
        end
      end
      if (halted) finish_up();
    end
  end

  task automatic finish_up();
    integer fm, fs;
    fm = $fopen(memf, "w");
    for (int i = 0; i < RAMW; i++) $fwrite(fm, "%032h\n", ram[i]);
    $fclose(fm);
    fm = $fopen(tagf, "w");
    for (int i = 0; i < RAMW; i++)
      if (tmeta[i][M_TAG]) $fwrite(fm, "%0h %0d %0h %0h\n", i, tmeta[i][M_PERM +: PW], tmeta[i][256:129], tmeta[i][128:0]);
    $fclose(fm);
    fs = $fopen(statf, "w");
    $fwrite(fs, "cycles %0d\nretired %0d\nexit %0d\n", cycles, retired, exit_code);
    $fclose(fs);
    $fclose(ftr);
    $fclose(fcon);
    done = 1;
  endtask

  // timeout path (called from C++ when max cycles reached)
  export "DPI-C" task tb_timeout;
  task tb_timeout();
    finish_up();
  endtask
endmodule
