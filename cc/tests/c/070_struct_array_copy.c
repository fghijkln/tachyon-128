#include <stdio.h>
struct m { int a[3][3]; };
struct m transpose(struct m x) { struct m r; for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) r.a[i][j] = x.a[j][i]; return r; }
struct m mul(struct m x, struct m y) { struct m r = {{{0}}}; for (int i = 0; i < 3; i++) for (int j = 0; j < 3; j++) for (int k = 0; k < 3; k++) r.a[i][j] += x.a[i][k] * y.a[k][j]; return r; }
int main(void) {
    struct m a = {{{1, 2, 3}, {4, 5, 6}, {7, 8, 9}}};
    struct m t = transpose(a), p = mul(a, t);
    for (int i = 0; i < 3; i++) { for (int j = 0; j < 3; j++) printf("%d ", p.a[i][j]); printf("\n"); }
    struct m arr[3]; arr[0] = a; arr[1] = t; arr[2] = arr[0];
    printf("%d %d\n", arr[2].a[2][0], arr[1].a[2][0]);
    return 0;
}
