/* -mpurecap (v6): a function pointer cannot be used as a data pointer: reading the code it points to
   through it is a load through a sealed capability (cause 7). */
#include <stdio.h>
#include <tx128.h>
typedef int (*op_t)(int, int);
static int add(int a, int b) { return a + b; }
int main(void) {
    op_t f = add;
    printf("add(4, 5) = %d, reading the code at ", f(4, 5));
    tx_hexout((unsigned __int128)(unsigned long)f);
    const volatile unsigned *code = (const volatile unsigned *)f;
    printf("first instruction %x\n", code[0]);
    printf("NOT REACHED\n");
    return 0;
}
