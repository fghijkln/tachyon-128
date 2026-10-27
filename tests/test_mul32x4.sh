#!/bin/bash
# Unit check of the shared fracturable multiplier array, both implementations (Booth default, AND array).
set -e
source ~/env.sh 2>/dev/null || true
ROOT=$(cd "$(dirname "$0")/.." && pwd)
for V in BOOTH ANDARRAY; do
  D=${TX_WORK:-$ROOT/build/work}/mul32x4_$V; mkdir -p $D
  DEF=""; [ $V = ANDARRAY ] && DEF="+define+TX_MUL_ANDARRAY"
  verilator --cc --exe --build -j 2 -O2 -Wno-fatal --top-module tx_mul32x4 $DEF --Mdir $D/obj \
    $ROOT/rtl/tx_mul32x4.sv $ROOT/tests/mul32x4_tb.cpp -o $D/Vmul > $D/build.log 2>&1
  echo -n "[$V] "; $D/Vmul
done
