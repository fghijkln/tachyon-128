/* -mpurecap: one field's capability cannot reach its neighbour; a struct member array is bounded by the
   enclosing object (sub-object bounds are not narrowed), but writing below a local array traps (cause 3) */
#include <stdio.h>
#include <string.h>
#include <tx128.h>
struct rec { char name[8]; int id; };
static void wipe(char *p, int lo, int hi) { for (int i = lo; i < hi; i++) p[i] = 0; }
int main(void) {
    struct rec r;
    strcpy(r.name, "alice");
    r.id = 7;
    wipe(r.name, 0, 8);
    printf("record of %d bytes, length via member %d, id %d\n", (int)sizeof r, (int)__builtin_cheri_length_get(r.name), r.id);
    char arr[8];
    volatile int lo = -1;
    printf("underflow write at ");
    tx_hexout((unsigned __int128)(arr + lo));
    wipe(arr, lo, 8);
    printf("NOT REACHED\n");
    return 0;
}
