#include <stdio.h>
int even(unsigned n); int odd(unsigned n) { return n ? even(n - 1) : 0; } int even(unsigned n) { return n ? odd(n - 1) : 1; }
long acc(long n, long a) { return n == 0 ? a : acc(n - 1, a + n * n); }
int digits(unsigned long v) { return v < 10 ? 1 : 1 + digits(v / 10); }
int main(void) {
    printf("%d %d\n", even(500), odd(301));
    printf("%ld\n", acc(500, 0));
    printf("%d %d\n", digits(0), digits(18446744073709551615UL));
    return 0;
}
