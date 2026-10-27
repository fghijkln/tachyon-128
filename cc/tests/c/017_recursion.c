#include <stdio.h>
int ack(int m, int n) { return m == 0 ? n + 1 : n == 0 ? ack(m - 1, 1) : ack(m - 1, ack(m, n - 1)); }
long fact(int n) { return n <= 1 ? 1 : n * fact(n - 1); }
int hanoi(int n, int a, int b, int c) { if (!n) return 0; return hanoi(n - 1, a, c, b) + 1 + hanoi(n - 1, c, b, a); }
int gcd(int a, int b) { return b ? gcd(b, a % b) : a; }
int is_even(int n);
int is_odd(int n) { return n == 0 ? 0 : is_even(n - 1); }
int is_even(int n) { return n == 0 ? 1 : is_odd(n - 1); }
int main(void) {
    printf("%d\n", ack(2, 3));
    printf("%ld\n", fact(20));
    printf("%d\n", hanoi(10, 1, 2, 3));
    printf("%d\n", gcd(1071, 462));
    printf("%d %d\n", is_even(10), is_odd(7));
    return 0;
}
