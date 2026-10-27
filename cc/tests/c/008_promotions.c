#include <stdio.h>
int main(void) {
    unsigned char a = 200, b = 100;
    printf("%d\n", a + b);
    printf("%d\n", (unsigned char)(a + b));
    unsigned short s = 60000;
    printf("%d\n", s * s > 0);
    printf("%u\n", s * s);
    int i = -1; unsigned u = 1;
    printf("%d\n", i > u);
    long l = -1; printf("%d\n", l > u);
    printf("%lu\n", sizeof(a + b));
    printf("%lu %lu %lu %lu %lu\n", sizeof(char), sizeof(short), sizeof(int), sizeof(long), sizeof(long long));
    char c = 'A'; printf("%lu %lu\n", sizeof(c), sizeof(c + 0));
    printf("%d\n", (char)-1 == -1);
    printf("%d\n", ~(unsigned char)0);
    printf("%d\n", -1 / 2u > 0);
    return 0;
}
