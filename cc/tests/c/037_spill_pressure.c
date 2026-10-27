#include <stdio.h>
int f(int x) { return x * 3 + 1; }
int main(void) {
    int a0 = 1, a1 = 2, a2 = 3, a3 = 4, a4 = 5, a5 = 6, a6 = 7, a7 = 8, a8 = 9, a9 = 10;
    int b0 = 11, b1 = 12, b2 = 13, b3 = 14, b4 = 15, b5 = 16, b6 = 17, b7 = 18, b8 = 19, b9 = 20;
    int c0 = 21, c1 = 22, c2 = 23, c3 = 24, c4 = 25, c5 = 26, c6 = 27, c7 = 28, c8 = 29, c9 = 30;
    int d0 = 31, d1 = 32, d2 = 33, d3 = 34, d4 = 35, d5 = 36, d6 = 37, d7 = 38, d8 = 39, d9 = 40;
    for (int i = 0; i < 3; i++) {
        a0 = f(a0 + d9); a1 = f(a1 + a0); a2 = f(a2 + a1); a3 = f(a3 + a2); a4 = f(a4 + a3);
        a5 = f(a5 + a4); a6 = f(a6 + a5); a7 = f(a7 + a6); a8 = f(a8 + a7); a9 = f(a9 + a8);
        b0 += a9; b1 += b0; b2 += b1; b3 += b2; b4 += b3; b5 += b4; b6 += b5; b7 += b6; b8 += b7; b9 += b8;
        c0 ^= b9; c1 ^= c0; c2 ^= c1; c3 ^= c2; c4 ^= c3; c5 ^= c4; c6 ^= c5; c7 ^= c6; c8 ^= c7; c9 ^= c8;
        d0 -= c9; d1 -= d0; d2 -= d1; d3 -= d2; d4 -= d3; d5 -= d4; d6 -= d5; d7 -= d6; d8 -= d7; d9 -= d8;
    }
    printf("%d %d %d %d\n", a0 + a1 + a2 + a3 + a4 + a5 + a6 + a7 + a8 + a9, b0 + b1 + b2 + b3 + b4 + b5 + b6 + b7 + b8 + b9,
           c0 + c1 + c2 + c3 + c4 + c5 + c6 + c7 + c8 + c9, d0 + d1 + d2 + d3 + d4 + d5 + d6 + d7 + d8 + d9);
    long e = ((a0 * b1 + c2) * (d3 - a4) + (b5 ^ c6) * (d7 | a8)) - ((b9 & c0) + (d1 << 3)) * ((a2 >> 1) + (b3 % 7) + (c4 / 3));
    printf("%ld\n", e);
    return 0;
}
