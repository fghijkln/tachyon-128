#include <stdio.h>
union u { int i; unsigned char b[4]; short s[2]; };
enum color { RED, GREEN = 5, BLUE, LAST = BLUE + 10 };
typedef enum { A, B, C } abc;
int main(void) {
    union u x; x.i = 0x11223344;
    printf("%x %x %x\n", x.b[0], x.b[3], x.s[1]);
    printf("%lu\n", sizeof(union u));
    enum color c = BLUE;
    printf("%d %d %d %d\n", RED, GREEN, c, LAST);
    abc v = C; printf("%d\n", v);
    switch (c) { case RED: puts("red"); break; case BLUE: puts("blue"); break; default: puts("other"); }
    return 0;
}
