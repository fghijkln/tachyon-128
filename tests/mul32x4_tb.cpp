// Exhaustive-corner + random check of rtl/tx_mul32x4.sv (all three modes) against C arithmetic.
#include "Vtx_mul32x4.h"
#include <cstdio>
#include <cstdint>
#include <random>
int main() {
  Vtx_mul32x4 m; std::mt19937_64 rng(12345); long bad = 0, n = 0;
  const uint32_t corner[] = {0, 1, 2, 3, 0x7F, 0x80, 0xFF, 0x100, 0x7FFF, 0x8000, 0xFFFF, 0x10000, 0x7FFFFFFF,
                             0x80000000u, 0xFFFFFFFFu, 0xAAAAAAAAu, 0x55555555u, 0x80808080u, 0x7F7F7F7Fu, 0xFF00FF00u,
                             0x00FF00FFu, 0x80008000u, 0x7FFF7FFFu, 0xFFFF0000u, 0x0000FFFFu, 0x01010101u};
  const int NC = sizeof(corner) / sizeof(corner[0]);
  for (long it = 0; it < 400000; it++) {
    uint32_t xa[4], za[4];
    for (int i = 0; i < 4; i++) {
      if (it < NC * NC) { xa[i] = corner[(it / NC + i) % NC]; za[i] = corner[(it + 3 * i) % NC]; }
      else { uint64_t r = rng(); int sh = rng() % 32; xa[i] = (uint32_t)r >> (rng() & 1 ? sh : 0); za[i] = (uint32_t)(r >> 32) >> (rng() & 1 ? sh : 0); }
      m.x[i] = xa[i]; m.z[i] = za[i];
    }
    for (int mode = 0; mode < 3; mode++) {
      m.mode = mode; m.eval(); n++;
      for (int i = 0; i < 4; i++) {
        uint64_t got = ((uint64_t)m.p[2 * i + 1] << 32) | m.p[2 * i], exp = 0;
        if (mode == 0) exp = (uint64_t)xa[i] * za[i];
        if (mode == 1) for (int l = 0; l < 2; l++) exp |= (uint64_t)(((xa[i] >> 16 * l) & 0xFFFF) * ((za[i] >> 16 * l) & 0xFFFF)) << 32 * l;
        if (mode == 2) for (int l = 0; l < 4; l++) exp |= (uint64_t)(((xa[i] >> 8 * l) & 0xFF) * ((za[i] >> 8 * l) & 0xFF)) << 16 * l;
        if (got != exp && bad++ < 10) printf("mode %d x=%08x z=%08x got %016llx exp %016llx\n", mode, xa[i], za[i],
                                            (unsigned long long)got, (unsigned long long)exp);
      }
    }
  }
  printf("tx_mul32x4: %ld vectors x 4 multipliers, %ld mismatches\n", n, bad);
  return bad != 0;
}
