#include <stdio.h>
union w { unsigned __int128 q; unsigned long d[2]; unsigned int s[4]; unsigned short h[8]; unsigned char b[16]; };
int main(void) {
    union w x; x.q = 0;
    for (int i = 0; i < 16; i++) x.b[i] = (unsigned char)(i * 17 + 1);
    printf("%lx %lx\n", x.d[0], x.d[1]);
    printf("%x %x %x %x\n", x.s[0], x.s[1], x.s[2], x.s[3]);
    printf("%x %x\n", x.h[0], x.h[7]);
    x.q <<= 8; printf("%lx %lx\n", x.d[0], x.d[1]);
    x.d[1] = ~0UL; x.q += 1; printf("%lx %lx\n", x.d[0], x.d[1]);
    return 0;
}
