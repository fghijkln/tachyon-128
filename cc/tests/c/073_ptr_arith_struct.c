#include <stdio.h>
#include <stddef.h>
struct item { char tag; long val; short s[3]; };
int main(void) {
    struct item items[5];
    for (int i = 0; i < 5; i++) { items[i].tag = 'a' + i; items[i].val = i * 1000L; for (int j = 0; j < 3; j++) items[i].s[j] = (short)(i - j); }
    struct item *p = items + 4, *q = &items[1];
    printf("%ld %c %ld\n", (long)(p - q), (p - 2)->tag, q[2].val);
    char *base = (char *)items;
    struct item *r = (struct item *)(base + 2 * sizeof(struct item));
    printf("%c %d\n", r->tag, r->s[2]);
    long *lp = &items[3].val; struct item *back = (struct item *)((char *)lp - offsetof(struct item, val));
    printf("%c\n", back->tag);
    short *sp = items[0].s; sp += 2; printf("%d\n", *sp);
    printf("%d %d\n", &items[4] > &items[0], &items[1].s[1] - &items[1].s[0]);
    return 0;
}
