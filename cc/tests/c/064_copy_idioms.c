#include <stdio.h>
void cpy(char *d, const char *s) { while ((*d++ = *s++)) ; }
int main(void) {
    char a[32], b[32];
    cpy(a, "idiomatic copy");
    char *p = b; const char *q = a; while (*q) *p++ = *q++; *p = 0;
    printf("%s|%s\n", a, b);
    int x[5] = {1, 2, 3, 4, 5}, y[5]; int *px = x, *py = y; for (int i = 0; i < 5; i++) *py++ = *px++ * 2;
    for (int i = 0; i < 5; i++) printf("%d ", y[i]); printf("\n");
    int *e = x + 5; int n = 0; for (int *it = x; it != e; ++it) n += *it; printf("%d\n", n);
    int v = 5; int *pv = &v; (*pv)++; ++*pv; *pv += 10; printf("%d\n", v);
    int arr[4] = {0}; int i = 0; arr[i] = i; i++; arr[i++] = 7; printf("%d %d %d\n", arr[0], arr[1], i);
    return 0;
}
