#include <stdio.h>
void swap(int *a, int *b) { int t = *a; *a = *b; *b = t; }
int main(void) {
    int a = 1, b = 2;
    swap(&a, &b);
    printf("%d %d\n", a, b);
    int arr[5] = {10, 20, 30, 40, 50};
    int *p = arr;
    printf("%d %d %d\n", *p, *(p + 2), p[4]);
    p += 3; printf("%d %d\n", *p, p[-1]);
    printf("%ld\n", (long)(p - arr));
    int *q = &arr[4];
    printf("%d %d\n", q > p, q - p);
    int **pp = &p; **pp = 99; printf("%d\n", arr[3]);
    char *cp = (char *)arr; printf("%d\n", cp[4]);
    void *vp = arr; int *ip = vp; printf("%d\n", ip[1]);
    printf("%d\n", p == &arr[3]);
    int *np = 0; printf("%d\n", np == 0);
    return 0;
}
