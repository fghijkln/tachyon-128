#include <stdio.h>
void qs(long *a, int lo, int hi) {
    if (lo >= hi) return;
    long p = a[(lo + hi) / 2]; int i = lo, j = hi;
    while (i <= j) { while (a[i] < p) i++; while (a[j] > p) j--; if (i <= j) { long t = a[i]; a[i] = a[j]; a[j] = t; i++; j--; } }
    qs(a, lo, j); qs(a, i, hi);
}
int main(void) {
    long a[200]; unsigned long x = 88172645463325252UL;
    for (int i = 0; i < 200; i++) { x ^= x << 13; x ^= x >> 7; x ^= x << 17; a[i] = (long)(x % 100000) - 50000; }
    qs(a, 0, 199);
    int ok = 1; for (int i = 1; i < 200; i++) if (a[i - 1] > a[i]) ok = 0;
    printf("%d %ld %ld %ld\n", ok, a[0], a[100], a[199]);
    return 0;
}
