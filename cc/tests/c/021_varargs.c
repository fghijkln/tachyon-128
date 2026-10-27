#include <stdio.h>
#include <stdarg.h>
int sum(int n, ...) { va_list ap; va_start(ap, n); int s = 0; for (int i = 0; i < n; i++) s += va_arg(ap, int); va_end(ap); return s; }
long lsum(int n, ...) { va_list ap; va_start(ap, n); long s = 0; while (n--) s += va_arg(ap, long); va_end(ap); return s; }
void show(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    for (; *fmt; fmt++) {
        if (*fmt == 'i') printf("i:%d ", va_arg(ap, int));
        else if (*fmt == 's') printf("s:%s ", va_arg(ap, char *));
        else if (*fmt == 'l') printf("l:%lld ", va_arg(ap, long long));
        else if (*fmt == 'c') printf("c:%c ", va_arg(ap, int));
    }
    va_end(ap); printf("\n");
}
int my_printf(const char *f, ...) { va_list ap; va_start(ap, f); int r = vprintf(f, ap); va_end(ap); return r; }
int main(void) {
    printf("%d\n", sum(5, 1, 2, 3, 4, 5));
    printf("%d\n", sum(12, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12));
    printf("%ld\n", lsum(3, 10000000000L, -1L, 5L));
    show("isilc", 1, "two", 3, -4000000000000LL, 'Z');
    int n = my_printf("%s=%d\n", "x", 99);
    printf("%d\n", n);
    return 0;
}
