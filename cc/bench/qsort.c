/* in-place quicksort of 2000 pseudo-random ints + verification */
#include <stdio.h>
#define N 2000
static int a[N];
static void sort(int *v, int lo, int hi) {
    while (lo < hi) {
        int p = v[(lo + hi) >> 1], i = lo, j = hi;
        while (i <= j) {
            while (v[i] < p) i++;
            while (v[j] > p) j--;
            if (i <= j) { int t = v[i]; v[i] = v[j]; v[j] = t; i++; j--; }
        }
        if (j - lo < hi - i) { sort(v, lo, j); lo = i; } else { sort(v, i, hi); hi = j; }
    }
}
int main(void) {
    unsigned x = 2463534242u;
    for (int i = 0; i < N; i++) { x ^= x << 13; x ^= x >> 17; x ^= x << 5; a[i] = (int)(x % 100000u); }
    sort(a, 0, N - 1);
    unsigned long sum = 0; int ok = 1;
    for (int i = 0; i < N; i++) { sum = sum * 31 + (unsigned)a[i]; if (i && a[i - 1] > a[i]) ok = 0; }
    printf("sorted=%d checksum=%lu min=%d max=%d\n", ok, sum, a[0], a[N - 1]);
    return ok ? 0 : 1;
}
