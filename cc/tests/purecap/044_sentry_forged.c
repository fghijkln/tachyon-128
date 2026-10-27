/* -mpurecap (v6): a function pointer rebuilt from an integer address has no tag; the indirect call is a
   cjalr, which refuses an untagged target (cause 2) -- control flow cannot be redirected to an integer. */
#include <stdio.h>
#include <tx128.h>
typedef int (*op_t)(int, int);
static int add(int a, int b) { return a + b; }
int main(void) {
    op_t f = add;
    unsigned long addr = (unsigned long)f;           /* the address only */
    volatile unsigned long k = 0;
    op_t forged = (op_t)(addr + k);
    printf("add(1, 1) = %d; forged tag %lu, calling ", f(1, 1), __builtin_cheri_tag_get(forged));
    tx_hexout((unsigned __int128)addr);
    printf("%d\n", forged(1, 1));
    printf("NOT REACHED\n");
    return 0;
}
