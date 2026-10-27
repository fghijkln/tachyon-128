/* -mpurecap: malloc returns a capability bounded to exactly the requested size */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tx128.h>
int main(void) {
    char *a = malloc(20);
    char *b = malloc(20);
    strcpy(b, "neighbour");
    memset(a, 'x', 20);                /* in bounds */
    printf("a: tag %lu length %d, b = %s\n", __builtin_cheri_tag_get(a), (int)__builtin_cheri_length_get(a), b);
    printf("a + 20 = ");
    tx_hexout((unsigned __int128)(a + 20));
    memset(a, 'y', 21);                /* one byte too many (the heap block itself is 32 bytes) */
    printf("NOT REACHED b = %s\n", b);
    return 0;
}
