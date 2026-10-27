/* v6 perf passes: LICM, redundant loads, value-range ext elimination, strength reduction + LFTR */
#include <stdio.h>
int a[64]; short b[40]; char c[100]; unsigned char u8[300];
long g(int n, int s) { long acc = 0; for (int i = 0; i < n; i += s) acc += a[i]; return acc; }
int h(int n) { int i; for (i = 0; i < n; i++) c[i] = (char)i; return i; }
int k(int lo, int hi) { int s = 0; for (int i = hi; i >= lo; i--) s += b[i] * 3; return s; }
int m(int n) { int s = 0; for (int i = 0; i != n; i++) s += a[i * 2 + 1]; return s; }
int mat(int n, int stride) { int s = 0; for (int i = 0; i < n; i++) s += a[i * stride] * b[i]; return s; }
static unsigned short crc8(unsigned char d, unsigned short crc) {
    for (int i = 0; i < 8; i++) {
        unsigned char x = (unsigned char)((d & 1) ^ ((unsigned char)crc & 1));
        d >>= 1;
        if (x == 1) { crc ^= 0x4002; crc = (unsigned short)((crc >> 1) | 0x8000); } else crc >>= 1;
    }
    return crc;
}
signed char sc(signed char x, int y) { return (signed char)(x + y); }
unsigned char ub(unsigned char x, unsigned char y) { return (unsigned char)(x * y + 1); }
int dup(const char *p, const char *q) { int n = 0; while (*p && *p == *q) { p++; q++; n++; } return n * 100 + (*p - *q); }
int stores(int *p) { int x = *p; *p = x + 1; int y = *p; return x * 10 + y; }
int main(void) {
    for (int i = 0; i < 64; i++) a[i] = i * 7 - 3;
    for (int i = 0; i < 40; i++) b[i] = (short)(i * i - 50);
    for (int i = 0; i < 300; i++) u8[i] = (unsigned char)(i * 13);
    printf("%ld %ld %d %d %d %d %d\n", g(64, 3), g(0, 1), h(37), k(2, 39), k(5, 4), m(20), c[36]);
    printf("%d %d %d\n", mat(20, 3), mat(0, 5), mat(7, -1 + 2));
    unsigned short crc = 0xffff;
    for (int i = 0; i < 300; i++) crc = crc8(u8[i], crc);
    printf("crc %u %d %d %u %u\n", crc, sc(100, 100), sc(-100, -100), ub(200, 3), ub(15, 17));
    int v = 41;
    printf("%d %d %d\n", dup("hello", "help"), dup("abc", "abc"), stores(&v));
    return 0;
}
