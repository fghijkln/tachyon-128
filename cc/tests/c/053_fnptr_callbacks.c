#include <stdio.h>
typedef void (*visit_fn)(int, void *);
void each(int *a, int n, visit_fn f, void *ctx) { for (int i = 0; i < n; i++) f(a[i], ctx); }
void add(int v, void *c) { *(int *)c += v; }
void maxf(int v, void *c) { if (v > *(int *)c) *(int *)c = v; }
int (*pick(int k))(int) ;
int dbl(int x) { return 2 * x; }
int sq(int x) { return x * x; }
int (*pick(int k))(int) { return k ? sq : dbl; }
int compose(int (*f)(int), int (*g)(int), int x) { return f(g(x)); }
int main(void) {
    int a[] = {4, -2, 9, 3}; int s = 0, m = -100;
    each(a, 4, add, &s); each(a, 4, maxf, &m);
    printf("%d %d\n", s, m);
    printf("%d %d\n", pick(0)(5), pick(1)(5));
    printf("%d\n", compose(dbl, sq, 3));
    int (*tab[2])(int) = {dbl, sq};
    printf("%d\n", tab[1](tab[0](4)));
    void (*vf)(int, void *) = add; vf(100, &s); printf("%d\n", s);
    return 0;
}
