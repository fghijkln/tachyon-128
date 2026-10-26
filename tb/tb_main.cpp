// Verilator driver for the TACHYON-128 testbench.  +max=N bounds the run (cycles).
#include "Vtb.h"
#include "verilated.h"
#include "svdpi.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "Vtb__Dpi.h"
int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    unsigned long long maxc = 20000000ULL;
    for (int i = 1; i < argc; i++) if (!strncmp(argv[i], "+max=", 5)) maxc = strtoull(argv[i] + 5, 0, 10);
    Vtb* top = new Vtb;
    top->clk = 0; top->rst = 1;
    for (int i = 0; i < 4; i++) { top->clk = !top->clk; top->eval(); }
    top->rst = 0;
    unsigned long long c = 0;
    while (!top->done && c < maxc) {
        top->clk = 1; top->eval();
        top->clk = 0; top->eval();
        c++;
    }
    int rc = 0;
    if (!top->done) {
        svSetScope(svGetScopeFromName("TOP.tb"));
        tb_timeout();
        top->eval();
        fprintf(stderr, "TIMEOUT after %llu cycles\n", c);
        rc = 2;
    }
    top->final();
    delete top;
    return rc;
}
