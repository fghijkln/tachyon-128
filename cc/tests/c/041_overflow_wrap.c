#include <stdio.h>
#include <limits.h>
int main(void) {
    int a = INT_MAX; a += 1; printf("%d\n", a);
    int b = INT_MIN; b -= 1; printf("%d\n", b);
    int c = 65536; c *= 65536; printf("%d\n", c);
    int d = 46341; printf("%d\n", d * d);
    short s = SHRT_MAX; s += s; printf("%d\n", s);
    long l = LONG_MAX; l++; printf("%ld\n", l);
    unsigned u = 0; u -= 1; u *= 3; printf("%u\n", u);
    unsigned long long ull = 0xFFFFFFFFFFFFFFFFULL; ull *= ull; printf("%llu\n", ull);
    int neg = -INT_MAX - 1; printf("%d\n", -neg);
    printf("%d\n", (int)(unsigned)3000000000u);
    printf("%d\n", (int)2147483648LL);
    printf("%d\n", (short)40000 + (short)-40000);
    signed char sc = 100; sc = sc * 3; printf("%d\n", sc);
    return 0;
}
