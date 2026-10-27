#include <stdio.h>
int x = 1;
int f(void) { return x; }
int main(void) {
    int x = 2;
    { int x = 3; printf("%d ", x); { extern int x; printf("%d ", x); } }
    printf("%d %d\n", x, f());
    for (int x = 10; x < 12; x++) printf("%d ", x);
    printf("%d\n", x);
    typedef int T; T t = 5; { typedef long T; T u = 6; printf("%lu ", sizeof(u)); } printf("%lu %d\n", sizeof(t), t);
    struct s { int a; } s1 = {1}; { struct s { long b, c; } s2 = {2, 3}; printf("%ld ", s2.b + s2.c); } printf("%d\n", s1.a);
    return 0;
}
