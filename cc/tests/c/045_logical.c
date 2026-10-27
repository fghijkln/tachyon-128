#include <stdio.h>
int calls;
int t(int v) { calls++; return v; }
int main(void) {
    int r1 = t(0) && t(1);
    int r2 = t(1) || t(0);
    int r3 = t(1) && t(2) && t(0) && t(5);
    int r4 = t(0) || t(0) || t(3);
    printf("%d %d %d %d %d\n", r1, r2, r3, r4, calls);
    int a = 5;
    printf("%d %d %d %d\n", !a, !!a, a && 0, a || 0);
    printf("%d\n", (a > 3) + (a < 10) + (a == 5) + (a != 5));
    long big = 1L << 40; printf("%d %d\n", !big, big && 1);
    int x = 0; if (!x && (x = 7)) printf("%d\n", x);
    return 0;
}
