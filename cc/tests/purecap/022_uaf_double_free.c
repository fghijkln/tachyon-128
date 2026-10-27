/* double free: free() probes its argument with a load before touching any allocator state, so the
   second free of the same block traps in hardware (cause 10, the capability was revoked by the first) */
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    int *p = malloc(4 * sizeof(int));
    int *q = malloc(4 * sizeof(int));
    p[0] = 1;
    q[0] = 2;
    free(p);
    printf("first free ok, q[0] = %d\n", q[0]);
    free(p);                              /* traps inside free() */
    printf("not reached\n");
    return 0;
}
