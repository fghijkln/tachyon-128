#include <stdio.h>
#include <string.h>
unsigned crc32(const unsigned char *p, unsigned long n) {
    unsigned c = 0xFFFFFFFFu;
    while (n--) { c ^= *p++; for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & -(c & 1)); }
    return ~c;
}
unsigned fnv1a(const char *s) { unsigned h = 2166136261u; while (*s) { h ^= (unsigned char)*s++; h *= 16777619u; } return h; }
unsigned long djb2(const char *s) { unsigned long h = 5381; int c; while ((c = *s++)) h = ((h << 5) + h) + c; return h; }
int main(void) {
    const char *s = "The quick brown fox jumps over the lazy dog";
    printf("%08x\n", crc32((const unsigned char *)s, strlen(s)));
    printf("%08x %lu\n", fnv1a(s), djb2(s));
    return 0;
}
