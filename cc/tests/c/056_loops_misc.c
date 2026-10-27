#include <stdio.h>
int main(void) {
    int collatz_max = 0, arg = 0;
    for (int n = 1; n < 300; n++) { long x = n; int steps = 0; while (x != 1) { x = x & 1 ? 3 * x + 1 : x / 2; steps++; } if (steps > collatz_max) { collatz_max = steps; arg = n; } }
    printf("%d %d\n", arg, collatz_max);
    int tri = 0; for (int i = 1; i <= 100; i++) tri += i; printf("%d\n", tri);
    long fib[60]; fib[0] = 0; fib[1] = 1; for (int i = 2; i < 60; i++) fib[i] = fib[i - 1] + fib[i - 2]; printf("%ld\n", fib[59]);
    int perfect = 0; for (int n = 2; n < 1000; n++) { int s = 1; for (int d = 2; d * d <= n; d++) if (n % d == 0) { s += d; if (d * d != n) s += n / d; } if (s == n) { printf("%d ", n); perfect++; } }
    printf("\n%d\n", perfect);
    unsigned bits = 0; for (unsigned v = 0xF0F0F0F0u; v; v &= v - 1) bits++; printf("%u\n", bits);
    return 0;
}
