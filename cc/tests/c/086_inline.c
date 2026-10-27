/* -O inlining of small static functions: multiple returns, address-taken locals and arrays in the
   callee (frame slots moved into the caller), nested inlining, callees that call, void callees,
   static functions also used through a function pointer, recursion (never inlined), many call sites */
#include <stdio.h>
#include <string.h>

static int clamp(int v, int lo, int hi) { if (v < lo) return lo; if (v > hi) return hi; return v; }
static int sum_arr(int a, int b, int c) { int t[3] = {a, b, c}; int *p = t; return p[0] + p[1] * 2 + p[2] * 3; }
static int via_addr(int x) { int y = x + 1; int *q = &y; *q *= 3; return y; }
static int twice(int x) { return clamp(x, -50, 50) * 2; }          /* nested */
static unsigned char lowbyte(unsigned x) { return (unsigned char)x; } /* narrowing return */
static long long widen(int x) { return (long long)x << 33; }
static int counter;
static void bump(int k) { counter += k; }                          /* void */
static int show(int x) { printf("[%d]", x); return x + 1; }        /* calls */
static int fact(int n) { return n <= 1 ? 1 : n * fact(n - 1); }    /* recursive */
static int sq(int x) { return x * x; }
static unsigned __int128 big(unsigned __int128 a) { return a * a + 1; }
static const char *pick(int k) { static const char *w[] = {"zero", "one", "two"}; return w[k % 3]; }
static void fill(char *d, int n, char c) { for (int i = 0; i < n; i++) d[i] = c; d[n] = 0; }
static int many(int a, int b, int c, int d, int e, int f, int g, int h) { return a - b + c - d + e - f + g - h; }

int main(void) {
    int s = 0;
    for (int i = -70; i <= 70; i += 7) s += clamp(i, -20, 30) + twice(i);
    printf("clamp/twice %d\n", s);
    printf("sum_arr %d %d\n", sum_arr(1, 2, 3), sum_arr(-4, 5, sum_arr(1, 1, 1)));
    printf("via_addr %d %d\n", via_addr(4), via_addr(via_addr(0)));
    printf("lowbyte %u widen %lld\n", lowbyte(0x1234u) + lowbyte(0xffu), widen(-3));
    for (int i = 0; i < 10; i++) bump(i);
    printf("counter %d\n", counter);
    int r = show(show(1));
    printf(" -> %d\n", r);
    printf("fact %d\n", fact(10));
    int (*fp)(int) = sq;
    printf("sq %d fp %d\n", sq(12), fp(13));
    unsigned __int128 b = big((unsigned __int128)1 << 40);
    printf("big %llx %llx\n", (unsigned long long)(b >> 64), (unsigned long long)b);
    printf("pick %s %s\n", pick(4), pick(8));
    char buf[8];
    fill(buf, 5, 'q');
    printf("fill %s %d\n", buf, (int)strlen(buf));
    printf("many %d\n", many(1, 2, 3, 4, 5, 6, 7, 8));
    int acc = 0;
    for (int i = 0; i < 100; i++) acc += sq(i) - sq(i - 1) + clamp(sq(i) % 17, 3, 9);
    printf("acc %d\n", acc);
    return 0;
}
