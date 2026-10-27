/* -mpurecap va_list bounds: a variadic callee's va_list covers exactly the arguments the caller passed
   (register save area + the caller's stack arguments), so reading past them (a printf-style format/argument
   mismatch) traps (cause 3) instead of leaking the caller's frame. */
#include <stdio.h>
#include <stdarg.h>
#include <tx128.h>
static long sum(int n, ...) {
    va_list ap;
    va_start(ap, n);
    long s = 0;
    for (int i = 0; i < n; i++) s += va_arg(ap, long);
    va_end(ap);
    return s;
}
int main(void) {
    long secret = 0x5ec2e7;
    printf("sum of 3: %ld, sum of 7: %ld, sum of 10 (2 on the stack): %ld\n", sum(3, 1L, 2L, 3L),
           sum(7, 1L, 2L, 3L, 4L, 5L, 6L, 7L), sum(10, 1L, 2L, 3L, 4L, 5L, 6L, 7L, 8L, 9L, 10L));
    printf("%s %d%c\n", "printf still works:", 100, '%');
    volatile int n = 9;                       /* claims 9 arguments, passes 2 (7 slots + 0 stack bytes) */
    printf("over-read: ");
    printf("%ld\n", sum(n, 1L, 2L));
    printf("NOT REACHED %ld\n", secret);
    return 0;
}
