#include <stdio.h>
int main(void) {
    long a = 9223372036854775807L;
    long b = a + 1;
    printf("%ld %ld\n", a, b);
    unsigned long u = 18446744073709551615UL;
    printf("%lu %lu\n", u, u + 2);
    long long x = 1LL << 40;
    printf("%lld %llx\n", x * 3, x * 3);
    printf("%ld\n", (long)(int)0x80000000u);
    printf("%lu\n", (unsigned long)(unsigned)-1);
    printf("%ld\n", (long)-5 / 2);
    printf("%ld %ld\n", 1000000007L * 1000000009L, (1000000007L * 1000000009L) % 998244353L);
    int i = -1; unsigned long ul = i; printf("%lu\n", ul);
    return 0;
}
