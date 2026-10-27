#include <stdio.h>
typedef unsigned __int128 u128;
typedef __int128 i128;
static void pu(u128 v) { char b[50]; int n = 0; do { b[n++] = '0' + (int)(v % 10); v /= 10; } while (v); while (n) putchar(b[--n]); }
static void pi(i128 v) { if (v < 0) { putchar('-'); pu(-(u128)v); } else pu(v); }
int main(void) {
    u128 f = 1;
    for (int i = 1; i <= 34; i++) f *= i;
    pu(f); putchar('\n');
    i128 m = -(i128)f; pi(m); putchar('\n');
    u128 max = ~(u128)0; pu(max); putchar('\n');
    pu(max / 3); putchar('\n');
    pi((i128)(max >> 1)); putchar('\n');
    pi(m / 1000000007); putchar('\n');
    pi(m % 1000000007); putchar('\n');
    printf("%d\n", (int)(f >> 100));
    long l = (long)f; printf("%ld\n", l);
    u128 a = 0xFFFFFFFFFFFFFFFFull; a = a * a; pu(a); putchar('\n');
    return 0;
}
