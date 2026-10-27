#include <stdio.h>
#include <string.h>
int main(void) {
    char a[100], b[100];
    for (int i = 0; i < 100; i++) a[i] = (char)(i * 3);
    memcpy(b, a, 100); printf("%d\n", memcmp(a, b, 100));
    memcpy(b + 1, a, 50); printf("%d %d\n", b[1], b[50]);
    memmove(a + 10, a, 60); printf("%d %d %d\n", a[10], a[69], a[9]);
    memmove(a, a + 5, 30); printf("%d %d\n", a[0], a[29]);
    memset(a + 3, 0x7f, 17); printf("%d %d %d\n", a[2], a[3], a[19]);
    long l[8]; memset(l, 0xff, sizeof l); printf("%ld\n", l[7]);
    char *p = memchr("hello world", 'w', 11); printf("%s\n", p);
    printf("%lu %lu\n", strspn("aabbcd", "ab"), strcspn("hello, world", ", "));
    char d[32] = "abc"; strncat(d, "defghi", 3); printf("%s\n", d);
    char e[8]; strncpy(e, "xy", 8); printf("%s %d\n", e, e[7]);
    return 0;
}
