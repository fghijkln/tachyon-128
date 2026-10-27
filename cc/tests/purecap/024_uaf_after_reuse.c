/* use after free after the memory was reused: enough frees to fill the quarantine trigger a revocation
   sweep, which strips the tag of every remaining copy of the freed pointers (here: one kept in a global)
   before the blocks go back to the free lists. malloc then hands the same address to a new object, but the
   stale pointer is no longer a capability, so it cannot touch the new owner's data: the access traps
   (cause 9, untagged access in user mode) instead of silently aliasing */
#include <stdio.h>
#include <stdlib.h>

unsigned long __tx_revoke_sweeps(void);
char *stale;

int main(void) {
    char *victim = malloc(48);
    victim[0] = 'v';
    stale = victim;
    free(victim);
    for (int i = 0; i < 200; i++)         /* churn: 200 x 64 bytes through the quarantine */
        free(malloc(48));
    printf("sweeps %lu, stale tag %d\n", __tx_revoke_sweeps(), (int)__builtin_cheri_tag_get(stale));
    char *mine = 0;                       /* keep churning until malloc hands out the stale address */
    for (int i = 0; i < 2000 && !mine; i++) {
        char *fresh = malloc(48);
        if ((unsigned long)(unsigned __int128)fresh == (unsigned long)(unsigned __int128)stale) mine = fresh;
        else free(fresh);
    }
    printf("address reused: %s\n", mine ? "yes" : "no");
    mine[0] = 'n';
    printf("new owner wrote %c\n", mine[0]);
    stale[0] = 'X';                       /* traps here: the stale pointer was revoked before reuse */
    printf("not reached\n");
    return 0;
}
