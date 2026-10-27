#include <stdio.h>
typedef unsigned __int128 u128; typedef __int128 s128;
static void hex(u128 v) { printf("%016lx%016lx\n", (unsigned long)(v >> 64), (unsigned long)v); }
int main(void) {
    u128 a = ((u128)0x0123456789ABCDEFULL << 64) | 0xFEDCBA9876543210ULL;
    u128 b = ((u128)0x1111111111111111ULL << 64) | 0x2222222222222222ULL;
    hex(a + b); hex(a - b); hex(a * b); hex(a / 12345); hex(a % 1000000007);
    hex(a & b); hex(a | b); hex(a ^ b); hex(~a); hex(a << 7); hex(a >> 77); hex(-a);
    s128 sa = -(s128)a; hex((u128)(sa >> 5)); hex((u128)(sa / 3)); hex((u128)(sa % 3));
    printf("%d %d %d\n", a > b, sa < 0, (s128)b > sa);
    u128 x = 1; int n = 0; while (x) { x <<= 1; n++; } printf("%d\n", n);
    long l = -7; u128 ex = (u128)l; hex(ex); s128 se = l; hex((u128)se);
    unsigned long ul = 0xFFFFFFFFFFFFFFFFUL; u128 wide = (u128)ul * ul; hex(wide);
    return 0;
}
