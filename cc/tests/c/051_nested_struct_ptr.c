#include <stdio.h>
#include <stdlib.h>
struct inner { int vals[4]; struct inner *link; };
struct outer { char name[12]; struct inner in; struct inner *ptrs[3]; long count; };
int main(void) {
    struct outer o = {"outer", {{1, 2, 3, 4}, 0}, {0, 0, 0}, 0};
    struct inner extra[3];
    for (int i = 0; i < 3; i++) { for (int j = 0; j < 4; j++) extra[i].vals[j] = i * 10 + j; extra[i].link = i ? &extra[i - 1] : &o.in; o.ptrs[i] = &extra[i]; }
    long s = 0;
    for (struct inner *p = o.ptrs[2]; p; p = p->link) { for (int j = 0; j < 4; j++) s += p->vals[j]; o.count++; }
    printf("%s %ld %ld\n", o.name, s, o.count);
    printf("%d %d\n", o.ptrs[1]->link->vals[3], (*o.ptrs[0]).link->vals[0]);
    struct outer *op = &o; op->in.vals[op->in.vals[0]] = 77; printf("%d\n", o.in.vals[1]);
    return 0;
}
