/* -mpurecap: a pointer rebuilt from an integer has no tag; purecap code runs in user mode with an empty
   untagged window (ubase = ubound = 0), so dereferencing it is a privilege violation (cause 9) */
#include <stdio.h>
#include <stdint.h>
#include <tx128.h>
int secret = 1234;
int main(void) {
    int *p = &secret;
    uintptr_t addr = (uintptr_t)p;
    printf("through the real capability: %d (tag %lu)\n", *p, __builtin_cheri_tag_get(p));
    volatile uintptr_t k = 0;
    int *forged = (int *)(addr + k);   /* same address, but integer arithmetic dropped the tag */
    printf("forged tag %lu, dereferencing it at ", __builtin_cheri_tag_get(forged));
    tx_hexout((unsigned __int128)addr);
    printf("%d\n", *forged);
    printf("NOT REACHED\n");
    return 0;
}
