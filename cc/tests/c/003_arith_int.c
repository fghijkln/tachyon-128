#include <stdio.h>
int main(void) {
    int a = 7, b = -3, c = 2147483647, d = -2147483647 - 1;
    printf("%d %d %d %d %d\n", a + b, a - b, a * b, a / b, a % b);
    printf("%d %d %d\n", -a / 2, -a % 2, a / -2);
    printf("%d %d\n", c + 1, d - 1);
    printf("%d %d\n", c * 2, d * -1);
    printf("%d %d %d\n", a << 3, b >> 1, -1 >> 31);
    printf("%d %d %d %d\n", a & b, a | b, a ^ b, ~a);
    printf("%d %d %d\n", !a, !0, -(-a));
    return 0;
}
