#include <stdio.h>
long f10(long a, long b, long c, long d, long e, long f, long g, long h, long i, long j) {
    return a + 2 * b + 3 * c + 4 * d + 5 * e + 6 * f + 7 * g + 8 * h + 9 * i + 10 * j;
}
int mixed(char a, short b, int c, long d, unsigned char e, unsigned short f, unsigned g, long long h, char i, int j, short k) {
    return a + b + c + (int)d + e + f + (int)g + (int)h + i + j + k;
}
int rec(int n, int a, int b, int c, int d, int e, int f, int g, int h, int i) {
    if (n == 0) return a + b + c + d + e + f + g + h + i;
    return rec(n - 1, b, c, d, e, f, g, h, i, a + 1);
}
int main(void) {
    printf("%ld\n", f10(1, 2, 3, 4, 5, 6, 7, 8, 9, 10));
    printf("%d\n", mixed(-1, -2, -3, -4, 250, 65000, 7, 8, -9, 10, -11));
    printf("%d\n", rec(20, 1, 2, 3, 4, 5, 6, 7, 8, 9));
    return 0;
}
