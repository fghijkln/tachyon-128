#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct val { int kind; union { long i; const char *s; struct { short a, b; }; }; };
struct buf { int len; char data[]; };
void show(struct val v) { if (v.kind == 0) printf("int %ld\n", v.i); else if (v.kind == 1) printf("str %s\n", v.s); else printf("pair %d %d\n", v.a, v.b); }
int main(void) {
    struct val v; v.kind = 0; v.i = -77; show(v);
    v.kind = 1; v.s = "hello"; show(v);
    v.kind = 2; v.a = 3; v.b = -4; show(v);
    struct buf *b = malloc(sizeof(struct buf) + 10); b->len = 9; memcpy(b->data, "flexible", 9);
    printf("%d %s %lu\n", b->len, b->data, sizeof(struct buf));
    return 0;
}
