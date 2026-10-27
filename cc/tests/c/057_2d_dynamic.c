#include <stdio.h>
#include <stdlib.h>
int **alloc2(int r, int c) { int **m = malloc(r * sizeof(int *)); for (int i = 0; i < r; i++) m[i] = malloc(c * sizeof(int)); return m; }
int main(void) {
    int R = 6, C = 7;
    int **m = alloc2(R, C);
    for (int i = 0; i < R; i++) for (int j = 0; j < C; j++) m[i][j] = (i + 1) * (j + 2);
    /* Pascal triangle in place */
    int **p = alloc2(10, 10);
    for (int i = 0; i < 10; i++) { p[i][0] = p[i][i] = 1; for (int j = 1; j < i; j++) p[i][j] = p[i - 1][j - 1] + p[i - 1][j]; }
    int s = 0; for (int i = 0; i < R; i++) for (int j = 0; j < C; j++) s += m[i][j];
    printf("%d\n", s);
    for (int j = 0; j <= 9; j++) printf("%d ", p[9][j]);
    printf("\n");
    return 0;
}
