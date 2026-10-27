#include <stdio.h>
int depth(int n) { volatile int pad[4]; pad[0] = n; if (n == 0) return 0; return 1 + depth(n - 1) + pad[0] * 0; }
long sumto(long n) { return n == 0 ? 0 : n + sumto(n - 1); }
int main(void) { printf("%d %ld\n", depth(1500), sumto(2000)); return 0; }
