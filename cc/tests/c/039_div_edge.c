#include <stdio.h>
#include <limits.h>
int main(void) {
    int v[] = {7, -7, 1, -1, INT_MAX, INT_MIN + 1, 100, -100};
    int d[] = {2, -2, 3, -3, 7, -7};
    for (int i = 0; i < 8; i++) { for (int j = 0; j < 6; j++) printf("%d,%d ", v[i] / d[j], v[i] % d[j]); printf("\n"); }
    long lv = LONG_MIN + 1; printf("%ld %ld\n", lv / 10, lv % 10);
    unsigned long u = ULONG_MAX; printf("%lu %lu\n", u / 7, u % 7);
    unsigned ux = 0x80000000u; printf("%u %u\n", ux / 3, ux % 3);
    printf("%d\n", INT_MIN % -1 == 0);
    return 0;
}
