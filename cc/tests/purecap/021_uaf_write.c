/* use after free (write): a store through the dangling pointer traps with cause 10 (capability-revoked),
   so it cannot corrupt the freed block (or whatever the allocator later puts there) */
#include <stdio.h>
#include <stdlib.h>

struct account { long id; long balance; };

int main(void) {
    struct account *a = malloc(sizeof *a);
    a->id = 7;
    a->balance = 100;
    printf("account %ld balance %ld\n", a->id, a->balance);
    free(a);
    a->balance = 1000000;                 /* traps here */
    printf("not reached\n");
    return 0;
}
