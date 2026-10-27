/* -mpurecap (v6): patching code through a function pointer (a store through a sentry) traps (cause 7). */
#include <stdio.h>
#include <tx128.h>
typedef void (*fn_t)(void);
static void hello(void) { printf("hello\n"); }
int main(void) {
    fn_t f = hello;
    f();
    printf("overwriting the code at ");
    tx_hexout((unsigned __int128)(unsigned long)f);
    *(volatile unsigned *)f = 0x00000013u;
    printf("NOT REACHED\n");
    return 0;
}
