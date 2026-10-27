#include <stdio.h>
int main(void) {
    unsigned a = 4000000000u, b = 3;
    printf("%u %u %u %u %u\n", a + a, a * b, a / b, a % b, b - a);
    printf("%u %u\n", a >> 4, a << 1);
    unsigned x = 0; x--; printf("%u %x\n", x, x);
    int neg = -1; printf("%d\n", neg < 1u);
    printf("%d\n", -1 < 1);
    unsigned short us = 65535; us++; printf("%d\n", us);
    unsigned char uc = 250; uc += 10; printf("%d\n", uc);
    return 0;
}
