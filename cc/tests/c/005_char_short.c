#include <stdio.h>
int main(void) {
    char c = 127; c++; printf("%d\n", c);
    signed char sc = -128; sc--; printf("%d\n", sc);
    short s = 32767; s++; printf("%d\n", s);
    short t = -32768; t = t - 1; printf("%d\n", t);
    unsigned char u = 255; printf("%d %d\n", u, (char)u);
    int i = 0x12345678; printf("%d %d %d\n", (char)i, (short)i, (unsigned char)i);
    char arr[4] = {-1, -2, 3, 4};
    int sum = 0; for (int k = 0; k < 4; k++) sum += arr[k];
    printf("%d\n", sum);
    printf("%d\n", (unsigned short)-1);
    printf("%d\n", (signed char)200 + (unsigned char)200);
    return 0;
}
