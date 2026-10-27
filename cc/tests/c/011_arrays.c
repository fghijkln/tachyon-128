#include <stdio.h>
int g[3][4];
int main(void) {
    int m[3][4];
    for (int i = 0; i < 3; i++) for (int j = 0; j < 4; j++) { m[i][j] = i * 10 + j; g[i][j] = m[i][j] * 2; }
    int s = 0;
    for (int i = 0; i < 3; i++) for (int j = 0; j < 4; j++) s += m[i][j] + g[i][j];
    printf("%d\n", s);
    printf("%lu %lu\n", sizeof(m), sizeof(m[0]));
    int (*row)[4] = m + 1; printf("%d\n", (*row)[2]);
    int a[] = {1, 2, 3, 4, 5, 6, 7};
    printf("%lu\n", sizeof(a) / sizeof(a[0]));
    char str[] = "hello"; printf("%lu %s\n", sizeof(str), str);
    int z[10] = {1, 2}; printf("%d %d %d\n", z[0], z[1], z[9]);
    int d[5] = {[2] = 7, [4] = 9}; printf("%d %d %d\n", d[1], d[2], d[4]);
    return 0;
}
