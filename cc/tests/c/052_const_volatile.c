#include <stdio.h>
const int K = 10;
static const char tbl[] = {3, 1, 4, 1, 5, 9, 2, 6};
int sum(const int *p, int n) { int s = 0; for (int i = 0; i < n; i++) s += p[i]; return s; }
int main(void) {
    volatile int v = 0;
    for (int i = 0; i < K; i++) v += i;
    printf("%d\n", v);
    const int arr[] = {1, 2, 3};
    printf("%d\n", sum(arr, 3));
    int s = 0; for (unsigned i = 0; i < sizeof tbl; i++) s = s * 10 + tbl[i];
    printf("%d\n", s);
    char *const cp = (char *)"abc"; printf("%c\n", cp[1]);
    volatile unsigned char buf[4] = {1, 2, 3, 4}; buf[2] += buf[3]; printf("%d\n", buf[2]);
    return 0;
}
