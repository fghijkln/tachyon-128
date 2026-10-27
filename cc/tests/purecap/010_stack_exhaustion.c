/* -mpurecap bounded stack: the stack capability spans only [RAM_TOP - 128 KiB, RAM_TOP), so runaway
   recursion traps (cause 3) when it reaches the bottom of the stack region instead of silently
   running into the heap below it. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int depth;
static int dive(int n) {
    volatile char pad[256];
    pad[0] = (char)n;
    depth = n;
    if (n % 64 == 0) printf("depth %d\n", n);
    return dive(n + 1) + pad[0];
}
int main(void) {
    char *heap = malloc(64);
    strcpy(heap, "heap intact");
    printf("%s\n", heap);
    return dive(0);
}
