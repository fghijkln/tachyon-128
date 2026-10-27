/* -mpurecap: what keeps a tag and what does not (no trap expected) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
struct node { struct node *next; int v; };
static int cmp(const void *a, const void *b) { return strcmp(*(char *const *)a, *(char *const *)b); }
int main(void) {
    char buf[32];
    char *far = buf + 1000;            /* cursor far out of bounds: still tagged, just not usable there */
    char *back = far - 1000;
    back[3] = 'z';
    printf("out-of-bounds cursor keeps tag: %lu, back in bounds works: %c\n", __builtin_cheri_tag_get(far), buf[3]);
    uintptr_t u = (uintptr_t)buf;
    char *forged = (char *)(u + 0);    /* integer arithmetic clears the tag */
    printf("pointer rebuilt from integer arithmetic: tag %lu\n", __builtin_cheri_tag_get((char *)(u * 1 + 1)));
    (void)forged;
    struct node *a = malloc(sizeof *a), *b = malloc(sizeof *b), c;
    a->next = b; a->v = 1; b->next = 0; b->v = 2;
    memcpy(&c, a, sizeof c);           /* capability-aware memcpy keeps the tag of c.next */
    printf("list via memcpy'd node: %d -> %d, tag %lu\n", c.v, c.next->v, __builtin_cheri_tag_get(c.next));
    const char *names[] = {"delta", "alpha", "charlie", "bravo"};
    qsort(names, 4, sizeof names[0], cmp);
    printf("sorted:");
    for (int i = 0; i < 4; i++) printf(" %s(len %d, tag %lu)", names[i], (int)__builtin_cheri_length_get(names[i]), __builtin_cheri_tag_get(names[i]));
    printf("\n");
    return 0;
}
