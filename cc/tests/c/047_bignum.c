#include <stdio.h>
#include <string.h>
/* 2^500 and 100! with decimal digit arrays */
int main(void) {
    int d[200]; int n = 1; memset(d, 0, sizeof d); d[0] = 1;
    for (int k = 0; k < 500; k++) { int c = 0; for (int i = 0; i < n; i++) { int v = d[i] * 2 + c; d[i] = v % 10; c = v / 10; } if (c) d[n++] = c; }
    for (int i = n - 1; i >= 0; i--) putchar('0' + d[i]); putchar('\n');
    n = 1; memset(d, 0, sizeof d); d[0] = 1;
    for (int k = 2; k <= 100; k++) { int c = 0; for (int i = 0; i < n; i++) { int v = d[i] * k + c; d[i] = v % 10; c = v / 10; } while (c) { d[n++] = c % 10; c /= 10; } }
    for (int i = n - 1; i >= 0; i--) putchar('0' + d[i]); putchar('\n');
    return 0;
}
