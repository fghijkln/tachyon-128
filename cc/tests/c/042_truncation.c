#include <stdio.h>
int main(void) {
    long big = 0x123456789ABCDEF0L;
    int i = big; short s = big; char c = big; unsigned char uc = big; unsigned short us = big;
    printf("%d %d %d %d %d\n", i, s, c, uc, us);
    unsigned __int128 w = ((unsigned __int128)0xFEDCBA9876543210ULL << 64) | 0x0123456789ABCDEFULL;
    long l = w; unsigned u = w; int hi = (int)(w >> 96);
    printf("%ld %u %d\n", l, u, hi);
    long long sx = (int)-5; unsigned long zx = (unsigned)-5;
    printf("%lld %lu\n", sx, zx);
    char neg = -3; unsigned int ui = neg; unsigned long ul = neg; unsigned short ush = neg;
    printf("%u %lu %u\n", ui, ul, ush);
    int x = 300; char y = x; unsigned char z = x; printf("%d %d\n", y, z);
    _Bool b1 = 256, b2 = 0, b3 = -1; printf("%d %d %d\n", b1, b2, b3);
    _Bool b4 = 3 > 2; printf("%d\n", b4);
    return 0;
}
