/* nested calls, results flowing straight into arguments, arguments reused after calls */
#include <stdio.h>
static int add(int a, int b) { return a + b; }
static int mul(int a, int b) { return a * b; }
static int neg(int a) { return -a; }
static long pick(int c, long a, long b) { return c ? a : b; }
static int many(int a, int b, int c, int d, int e, int f, int g, int h, int i, int j) {
    return a - b + c - d + e - f + g - h + i - j;
}
static unsigned char uc(unsigned x) { return (unsigned char)(x + 1); }
static short ss(int x) { return (short)x; }
int main(void) {
    int x = 5, y = 7;
    printf("%d\n", add(mul(x, y), neg(add(x, neg(y)))));
    printf("%d\n", many(add(1, 2), 3, mul(2, 2), neg(4), 5, add(x, y), 7, 8, mul(3, 3), neg(10)));
    printf("%ld\n", pick(add(x, -5), 10L, pick(1, (long)mul(x, 1000000), 3L)));
    printf("%d %d\n", uc(255u), uc(uc(254u)));
    printf("%d %d\n", ss(40000), ss(add(32767, 1)));
    int t = 0;
    for (int i = 0; i < 20; i++) t = add(t, mul(i, add(i, neg(1))));
    printf("%d %d %d\n", t, x, y);
    return mul(add(x, y), 0);
}
