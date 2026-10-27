/* recursive Fibonacci: call/return heavy */
#include <stdio.h>
static int fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }
int main(void) { int r = fib(20); printf("fib(20) = %d\n", r); return r == 6765 ? 0 : 1; }
