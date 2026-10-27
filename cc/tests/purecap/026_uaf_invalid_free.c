/* allocator hardening: free() of a pointer that is not the start of a live block (here an interior
   pointer, still a valid capability) is detected from the capability itself (base != address) and the
   program aborts before the allocator's metadata could be confused */
#include <stdio.h>
#include <stdlib.h>

int main(void) {
    char *p = malloc(64);
    printf("freeing p + 16\n");
    free(p + 16);                         /* aborts */
    printf("not reached\n");
    return 0;
}
