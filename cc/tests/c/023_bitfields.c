#include <stdio.h>
struct flags { unsigned a : 1; unsigned b : 3; int c : 5; unsigned d : 7; int e : 16; };
struct packed { unsigned char x : 4, y : 4; };
int main(void) {
    struct flags f = {1, 5, -3, 100, -1234};
    printf("%u %u %d %u %d\n", f.a, f.b, f.c, f.d, f.e);
    f.b = 9; f.c = 15; f.c++; f.d += 30; f.e = 40000;
    printf("%u %d %u %d\n", f.b, f.c, f.d, f.e);
    printf("%lu %lu\n", sizeof(struct flags), sizeof(struct packed));
    struct packed p; p.x = 3; p.y = 12;
    unsigned char raw = *(unsigned char *)&p;
    printf("%d %d %d\n", p.x, p.y, raw);
    int s = 0; for (int i = 0; i < 40; i++) { f.c = i; s += f.c; }
    printf("%d\n", s);
    return 0;
}
