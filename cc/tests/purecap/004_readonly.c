/* -mpurecap: a read-only view (STORE permission removed) can be read but a store traps (cause 4) */
#include <stdio.h>
#include <tx128.h>
static void scribble(int *p) { p[1] = 99; }
int main(void) {
    int data[2] = {1, 2};
    const int *ro = __builtin_cheri_perms_and(data, ~2u);        /* clear PERM_STORE */
    printf("perms %lx -> %lx, ro[1] = %d\n", __builtin_cheri_perms_get(data), __builtin_cheri_perms_get(ro), ro[1]);
    scribble(data);
    printf("data[1] = %d after a write through the full capability\n", data[1]);
    printf("writing through the read-only view at ");
    tx_hexout((unsigned __int128)(ro + 1));
    scribble((int *)ro);
    printf("NOT REACHED\n");
    return 0;
}
