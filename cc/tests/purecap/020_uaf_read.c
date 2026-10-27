/* use after free (read): the freed block's capability is revoked by free(), so reading through
   the dangling pointer traps (cause 10, capability-revoked) instead of returning stale data */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(void) {
    char *p = malloc(32);
    strcpy(p, "secret");
    printf("before free: %s\n", p);
    free(p);
    printf("after free: %c\n", p[0]);     /* traps here */
    printf("not reached\n");
    return 0;
}
