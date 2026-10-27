/* -mpurecap (v6): calling a data pointer (injected "code" in a buffer) -- the capability is tagged but has
   no EXEC permission (data capabilities descend from gp), so the cjalr traps with cause 4. */
#include <stdio.h>
#include <tx128.h>
typedef int (*op_t)(int, int);
unsigned shellcode[4] = {0x00000013u, 0x00000013u, 0x00000013u, 0x00000013u};
int main(void) {
    op_t f = (op_t)(void *)shellcode;
    printf("tag %lu type %lx perms %lx, calling ", __builtin_cheri_tag_get(f), __builtin_cheri_type_get(f),
           __builtin_cheri_perms_get(f));
    tx_hexout((unsigned __int128)(unsigned long)f);
    printf("%d\n", f(1, 2));
    printf("NOT REACHED\n");
    return 0;
}
