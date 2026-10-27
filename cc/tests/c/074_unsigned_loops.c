#include <stdio.h>
int main(void) {
    unsigned char c = 0; int n = 0; do { n++; c++; } while (c != 0); printf("%d\n", n);
    unsigned short s; n = 0; for (s = 65530; s != 4; s++) n++; printf("%d\n", n);
    unsigned u = 10; n = 0; while (u--) n++; printf("%d %u\n", n, u);
    unsigned long long x = 1; int bits = 0; while (x) { x <<= 1; bits++; } printf("%d\n", bits);
    int sum = 0; for (unsigned i = 0; i < 100; i += 7) sum += i; printf("%d\n", sum);
    signed char sc = 0; n = 0; do { sc++; n++; } while (sc > 0); printf("%d %d\n", n, sc);
    return 0;
}
