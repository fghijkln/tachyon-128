/* loops with invariant constants/addresses, repeated subexpressions, stores between them,
   calls inside loops (invariants must survive in callee-saved registers) */
#include <stdio.h>
static int tab[64];
static unsigned char bytes[300];
static int g;
static int bump(int x) { g += x; return g & 0xff; }
int main(void) {
    for (int r = 0; r < 3; r++)
        for (int i = 0; i < 64; i++) tab[i] = (i * 7 + r) % 13 - 6;
    long acc = 0;
    for (int i = 0; i < 64; i++) {
        int a = tab[i] * 3 + 100000;
        int b = tab[i] * 3 + 100000;      /* load not CSE'd, arithmetic is */
        tab[i] = a - 99999;               /* store between */
        acc += a + b + tab[i] + 1234567;
        acc ^= bump(i) + 1234567;
    }
    printf("acc=%ld g=%d\n", acc, g);
    for (int k = 0; k < 300; k++) bytes[k] = (unsigned char)(k * 37);
    unsigned h = 0;
    for (int k = 0; k < 300; k++) {
        unsigned x = bytes[k];
        h = (h << 5) + h + (x ^ 0xa5u) + (x ^ 0xa5u) * 3u + 0x9e3779b9u;
        if (k % 50 == 49) h ^= (unsigned)bump(k);
    }
    printf("h=%u\n", h);
    int s = 0;
    for (int i = 0; i < 10; i++) {
        int j = 0;
        while (j < 10) { if ((i + j) % 3 == 0) { j++; continue; } s += i * j + 70000; j++; }
        if (i == 7) goto out;
    }
out:
    printf("s=%d\n", s);
    return 0;
}
