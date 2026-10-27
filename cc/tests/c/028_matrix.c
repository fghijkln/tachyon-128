#include <stdio.h>
#define N 8
void matmul(long a[N][N], long b[N][N], long c[N][N]) {
    for (int i = 0; i < N; i++) for (int j = 0; j < N; j++) { long s = 0; for (int k = 0; k < N; k++) s += a[i][k] * b[k][j]; c[i][j] = s; }
}
int main(void) {
    long a[N][N], b[N][N], c[N][N];
    for (int i = 0; i < N; i++) for (int j = 0; j < N; j++) { a[i][j] = i + j; b[i][j] = i - 2 * j; }
    matmul(a, b, c);
    for (int r = 0; r < 3; r++) { matmul(c, a, b); matmul(b, a, c); }
    long tr = 0; for (int i = 0; i < N; i++) tr += c[i][i];
    printf("%ld %ld %ld\n", c[0][0], c[N - 1][N - 1], tr);
    return 0;
}
