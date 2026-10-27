#include <stdio.h>
int main(void) {
    int x = -100;
    printf("%d %d %d\n", x >> 2, x << 2, (unsigned)x >> 28);
    unsigned long y = 0x8000000000000000UL;
    printf("%lu %lu\n", y >> 63, y >> 1);
    long z = (long)y; printf("%ld\n", z >> 62);
    for (int s = 0; s < 32; s += 7) printf("%u ", 0xDEADBEEFu >> s);
    printf("\n");
    for (int s = 0; s < 64; s += 13) printf("%llx ", 0x0123456789ABCDEFULL << s);
    printf("\n");
    short sh = -1; printf("%d\n", sh << 4);
    unsigned char c = 0x81; printf("%d %d\n", c << 1, c >> 1);
    return 0;
}
