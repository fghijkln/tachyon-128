/* -mpurecap (v6): a function pointer is a sentry, so moving it -- e.g. to skip a function's prologue or
   to land in the middle of another function -- is a modification of a sealed capability: cause 7. */
#include <stdio.h>
#include <tx128.h>
typedef int (*op_t)(int, int);
static int add(int a, int b) { return a + b; }
int main(void) {
    op_t f = add;
    printf("add(2, 3) = %d through the sentry at ", f(2, 3));
    tx_hexout((unsigned __int128)(unsigned long)f);
    char *c = (char *)f;
    c += 4;                                          /* cincaddr on a sealed capability */
    op_t g = (op_t)c;
    printf("%d\n", g(2, 3));
    printf("NOT REACHED\n");
    return 0;
}
