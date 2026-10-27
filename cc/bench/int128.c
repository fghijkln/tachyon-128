/* native 128-bit arithmetic: factorials, a 128-bit LCG, and modular exponentiation (Miller-Rabin
   bases on 64-bit primes, products computed exactly in 128 bits) */
#include <stdio.h>
typedef unsigned __int128 u128;
static void put(u128 v) { char b[48]; int n = 0; do { b[n++] = (char)('0' + (int)(v % 10)); v /= 10; } while (v); while (n) putchar(b[--n]); }
static unsigned long mulmod(unsigned long a, unsigned long b, unsigned long m) { return (unsigned long)((u128)a * b % m); }
static unsigned long powmod(unsigned long a, unsigned long e, unsigned long m) { unsigned long r = 1; while (e) { if (e & 1) r = mulmod(r, a, m); a = mulmod(a, a, m); e >>= 1; } return r; }
static int is_prime(unsigned long n) {
    if (n < 4) return n >= 2;
    if (!(n & 1)) return 0;
    unsigned long d = n - 1; int s = 0; while (!(d & 1)) { d >>= 1; s++; }
    static const unsigned long bases[] = {2, 3, 5, 7, 11, 13, 17};
    for (int i = 0; i < 7; i++) {
        unsigned long a = bases[i] % n; if (!a) continue;
        unsigned long x = powmod(a, d, n);
        if (x == 1 || x == n - 1) continue;
        int comp = 1;
        for (int r = 1; r < s; r++) { x = mulmod(x, x, n); if (x == n - 1) { comp = 0; break; } }
        if (comp) return 0;
    }
    return 1;
}
int main(void) {
    u128 f = 1; for (int i = 1; i <= 34; i++) f *= (unsigned)i;
    printf("34! = "); put(f); putchar('\n');
    u128 x = 1; for (int i = 0; i < 1000; i++) x = x * (((u128)0x2360ed051fc65da4ULL << 64) | 0x4385df649fccf645ULL) + 1442695040888963407ULL;
    printf("lcg = "); put(x); putchar('\n');
    int cnt = 0; unsigned long last = 0;
    for (unsigned long n = 18446744073709551557UL; cnt < 3; n -= 2) if (is_prime(n)) { cnt++; last = n; }
    printf("3rd largest 64-bit prime candidate found: %lu\n", last);
    return 0;
}
