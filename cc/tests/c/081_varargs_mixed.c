/* stdarg with mixed widths, va_copy, forwarding through a va_list, sentinel lists */
#include <stdio.h>
#include <stdarg.h>
static long long sum_ll(int n, ...) {
    va_list ap; va_start(ap, n);
    long long s = 0;
    for (int i = 0; i < n; i++) s += va_arg(ap, long long);
    va_end(ap);
    return s;
}
static unsigned mix(const char *fmt, ...) {
    va_list ap, cp; va_start(ap, fmt); va_copy(cp, ap);
    unsigned h = 17;
    for (const char *p = fmt; *p; p++) {
        if (*p == 'i') h = h * 31 + (unsigned)va_arg(ap, int);
        else if (*p == 'u') h = h * 31 + va_arg(ap, unsigned);
        else if (*p == 'l') h = h * 31 + (unsigned)va_arg(ap, long);
        else if (*p == 'c') h = h * 31 + (unsigned)(char)va_arg(ap, int);
        else if (*p == 's') { const char *s = va_arg(ap, const char *); while (*s) h = h * 31 + *s++; }
    }
    int first = va_arg(cp, int);   /* re-read from the copy */
    va_end(cp); va_end(ap);
    return h ^ (unsigned)first;
}
static int count_until_zero(int first, ...) {
    va_list ap; va_start(ap, first);
    int n = 0, v = first;
    while (v) { n++; v = va_arg(ap, int); }
    va_end(ap);
    return n;
}
static void vlog(const char *tag, const char *fmt, va_list ap) {
    printf("[%s] ", tag);
    vprintf(fmt, ap);
}
static void logf(const char *tag, const char *fmt, ...) {
    va_list ap; va_start(ap, fmt); vlog(tag, fmt, ap); va_end(ap);
}
static __int128 sum128(int n, ...) {
    va_list ap; va_start(ap, n);
    __int128 s = 0;
    for (int i = 0; i < n; i++) s += va_arg(ap, __int128);
    va_end(ap);
    return s;
}
int main(void) {
    printf("%lld\n", sum_ll(3, 1LL, -2LL, 3000000000000LL));
    printf("%lld\n", sum_ll(10, 1LL, 2LL, 3LL, 4LL, 5LL, 6LL, 7LL, 8LL, 9LL, 10LL));
    printf("%u\n", mix("iulcs", -5, 4000000000u, -7L, 'x', "hey"));
    printf("%u\n", mix("i", 42));
    printf("%d %d\n", count_until_zero(1, 2, 3, 0), count_until_zero(9, 8, 7, 6, 5, 4, 3, 2, 1, 0));
    logf("info", "%d items, %s, %c%c\n", 12, "ok", 'A', 'Z');
    logf("warn", "%5d|%-5d|%05d\n", 42, 42, 42);
    __int128 s = sum128(9, (__int128)1 << 100, (__int128)-1, (__int128)2, (__int128)3, (__int128)4,
                        (__int128)5, (__int128)6, (__int128)7, (__int128)1 << 64);
    printf("%llx %llx\n", (unsigned long long)(s >> 64), (unsigned long long)s);
    return 0;
}
