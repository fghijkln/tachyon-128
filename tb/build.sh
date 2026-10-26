#!/bin/bash
# Build the Verilator model of the TACHYON-128 testbench into build/vtb/Vtb
set -e
source ~/env.sh 2>/dev/null || true
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$ROOT/build/vtb
mkdir -p $OUT
cd $OUT
verilator --cc --exe --build -j 2 -O2 -Wall -Wno-fatal -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM \
  --top-module tb -I$ROOT/rtl --Mdir $OUT/obj \
  $ROOT/rtl/tx_alu.sv $ROOT/rtl/tx_simd.sv $ROOT/rtl/tx_muldiv.sv $ROOT/rtl/tx_core.sv $ROOT/tb/tb.sv $ROOT/tb/tb_main.cpp \
  -o $OUT/Vtb "$@"
