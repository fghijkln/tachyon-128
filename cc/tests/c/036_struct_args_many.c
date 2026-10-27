#include <stdio.h>
struct v { int x, y, z; };
int f(struct v a, int k, struct v b, struct v c, long l, struct v d, int m, int n, int o, struct v e, int p) {
    return a.x + b.y + c.z + d.x + e.y + k + (int)l + m + n + o + p;
}
void mod(struct v a) { a.x = 1000; }
int main(void) {
    struct v a = {1, 2, 3}, b = {4, 5, 6};
    printf("%d\n", f(a, 1, b, a, 2L, b, 3, 4, 5, a, 6));
    mod(a); printf("%d\n", a.x);
    return 0;
}
