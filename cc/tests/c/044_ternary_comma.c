#include <stdio.h>
int side;
int f(int x) { side += x; return x; }
int main(void) {
    int a = 5, b = 10;
    int m = a > b ? a : b < 20 ? b * 2 : -1;
    printf("%d\n", m);
    int x = (f(1), f(2), f(3));
    printf("%d %d\n", x, side);
    int i, j;
    for (i = 0, j = 10; i < j; i++, j--) ;
    printf("%d %d\n", i, j);
    unsigned u = 1; long l = -2;
    long r = 1 ? u : l; printf("%ld\n", r);
    printf("%d\n", (a ? 0 : 1) ? 2 : 3);
    const char *s = a & 1 ? "odd" : "even"; printf("%s\n", s);
    int *p = 0; int v = 3; int *q = p ? p : &v; printf("%d\n", *q);
    return 0;
}
