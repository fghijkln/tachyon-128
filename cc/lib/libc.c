/* tcc128 minimal C library: console I/O, formatted output, strings, memory, heap. */
#include <stddef.h>
#include <stdarg.h>
#include <tx128.h>

struct __tx_file { int fd; };
static struct __tx_file __stdout_f = {1}, __stderr_f = {2};
struct __tx_file *stdout = &__stdout_f;
struct __tx_file *stderr = &__stderr_f;

void exit(int code) {
    *TX_EXIT = (unsigned)code;
    for (;;) ;
}

void abort(void) { exit(134); }

int putchar(int c) { *TX_CONSOLE = (unsigned char)c; return (unsigned char)c; }
int fputc(int c, struct __tx_file *f) { return putchar(c); }
int putc(int c, struct __tx_file *f) { return putchar(c); }
int fflush(struct __tx_file *f) { return 0; }
int getchar(void) { return -1; }

int puts(const char *s) {
    while (*s) putchar(*s++);
    putchar('\n');
    return 0;
}

int fputs(const char *s, struct __tx_file *f) {
    while (*s) putchar(*s++);
    return 0;
}

void __tx_assert_fail(const char *expr, const char *file, int line) {
    fputs("Assertion failed: ", stdout);
    fputs(expr, stdout);
    fputs(", file ", stdout);
    fputs(file, stdout);
    putchar('\n');
    exit(134);
}

/* ------------------------------------------------------------------ formatted output */
struct sink { char *buf; size_t n, pos; int to_console; };

static void sink_put(struct sink *s, int c) {
    if (s->to_console) putchar(c);
    else if (s->pos + 1 < s->n) s->buf[s->pos] = (char)c;
    s->pos++;
}

static int fmt_core(struct sink *s, const char *fmt, va_list ap) {
    char tmp[48];
    while (*fmt) {
        char c = *fmt++;
        if (c != '%') { sink_put(s, c); continue; }
        int left = 0, zero = 0, plus = 0, space = 0, alt = 0;
        for (;;) {
            if (*fmt == '-') left = 1;
            else if (*fmt == '0') zero = 1;
            else if (*fmt == '+') plus = 1;
            else if (*fmt == ' ') space = 1;
            else if (*fmt == '#') alt = 1;
            else break;
            fmt++;
        }
        int width = 0, prec = -1;
        if (*fmt == '*') { width = va_arg(ap, int); if (width < 0) { left = 1; width = -width; } fmt++; }
        else while (*fmt >= '0' && *fmt <= '9') width = width * 10 + (*fmt++ - '0');
        if (*fmt == '.') {
            fmt++;
            prec = 0;
            if (*fmt == '*') { prec = va_arg(ap, int); fmt++; }
            else while (*fmt >= '0' && *fmt <= '9') prec = prec * 10 + (*fmt++ - '0');
        }
        int len = 0;   /* 0 int, 1 long, 2 long long, 3 int128, -1 short, -2 char */
        for (;;) {
            if (*fmt == 'l') len = len >= 1 ? 2 : 1;
            else if (*fmt == 'h') len = len == -1 ? -2 : -1;
            else if (*fmt == 'z' || *fmt == 't' || *fmt == 'j') len = 1;
            else if (*fmt == 'L' || *fmt == 'q') len = 3;
            else break;
            fmt++;
        }
        c = *fmt++;
        if (c == 0) break;
        char *str = tmp;
        int n = 0;
        char sign = 0;
        if (c == 'd' || c == 'i' || c == 'u' || c == 'x' || c == 'X' || c == 'o' || c == 'p' || c == 'b') {
            unsigned __int128 v;
            int base = 10;
            if (c == 'p') { v = (unsigned __int128)va_arg(ap, void *); base = 16; alt = 1; }
            else if (c == 'd' || c == 'i') {
                __int128 sv;
                if (len == 3) sv = va_arg(ap, __int128);
                else if (len >= 1) sv = va_arg(ap, long);
                else sv = va_arg(ap, int);
                if (len == -1) sv = (short)sv;
                if (len == -2) sv = (signed char)sv;
                if (sv < 0) { sign = '-'; v = -(unsigned __int128)sv; }
                else { v = sv; if (plus) sign = '+'; else if (space) sign = ' '; }
            } else {
                if (len == 3) v = va_arg(ap, unsigned __int128);
                else if (len >= 1) v = va_arg(ap, unsigned long);
                else v = va_arg(ap, unsigned int);
                if (len == -1) v = (unsigned short)v;
                if (len == -2) v = (unsigned char)v;
                if (c == 'x' || c == 'X') base = 16;
                else if (c == 'o') base = 8;
                else if (c == 'b') base = 2;
            }
            const char *digits = c == 'X' ? "0123456789ABCDEF" : "0123456789abcdef";
            char *end = tmp + sizeof(tmp);
            char *p = end;
            if (base == 10 && (v >> 64) == 0) {
                unsigned long w = (unsigned long)v;
                do { *--p = (char)('0' + w % 10); w /= 10; } while (w);
            } else if (base == 16) {
                do { *--p = digits[(int)(v & 15)]; v >>= 4; } while (v);
            } else {
                do { *--p = digits[(int)(v % base)]; v /= base; } while (v);
            }
            n = (int)(end - p);
            if (prec == 0 && n == 1 && *p == '0' && c != 'p') n = 0;
            int zeros = prec > n ? prec - n : 0;
            if (c == 'o' && alt && zeros == 0 && !(n == 1 && p[0] == '0')) zeros = 1;
            int pre = (sign ? 1 : 0) + (((c == 'x' || c == 'X') && alt && !(n == 1 && p[0] == '0')) || c == 'p' ? 2 : 0);
            int total = pre + zeros + n;
            if (zero && !left && prec < 0 && width > total) { zeros += width - total; total = width; }
            if (!left) for (int i = total; i < width; i++) sink_put(s, ' ');
            if (sign) sink_put(s, sign);
            if (pre >= 2) { sink_put(s, '0'); sink_put(s, c == 'X' ? 'X' : 'x'); }
            for (int i = 0; i < zeros; i++) sink_put(s, '0');
            for (int i = 0; i < n; i++) sink_put(s, p[i]);
            if (left) for (int i = total; i < width; i++) sink_put(s, ' ');
            continue;
        }
        if (c == 'c') { tmp[0] = (char)va_arg(ap, int); str = tmp; n = 1; }
        else if (c == 's') {
            str = va_arg(ap, char *);
            if (!str) str = "(null)";
            n = 0;
            while (str[n] && (prec < 0 || n < prec)) n++;
        } else if (c == '%') { tmp[0] = '%'; n = 1; str = tmp; }
        else if (c == 'n') { *va_arg(ap, int *) = (int)s->pos; continue; }
        else { tmp[0] = '%'; tmp[1] = c; n = 2; str = tmp; }
        if (!left) for (int i = n; i < width; i++) sink_put(s, ' ');
        for (int i = 0; i < n; i++) sink_put(s, str[i]);
        if (left) for (int i = n; i < width; i++) sink_put(s, ' ');
    }
    return (int)s->pos;
}

int vprintf(const char *fmt, va_list ap) {
    struct sink s = {0, 0, 0, 1};
    return fmt_core(&s, fmt, ap);
}

int vsnprintf(char *buf, size_t n, const char *fmt, va_list ap) {
    struct sink s = {buf, n, 0, 0};
    int r = fmt_core(&s, fmt, ap);
    if (n) buf[s.pos < n ? s.pos : n - 1] = 0;
    return r;
}

int vsprintf(char *buf, const char *fmt, va_list ap) { return vsnprintf(buf, (size_t)-1 >> 1, fmt, ap); }

int printf(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int r = vprintf(fmt, ap);
    va_end(ap);
    return r;
}

int fprintf(struct __tx_file *f, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int r = vprintf(fmt, ap);
    va_end(ap);
    return r;
}

int sprintf(char *buf, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int r = vsprintf(buf, fmt, ap);
    va_end(ap);
    return r;
}

int snprintf(char *buf, size_t n, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int r = vsnprintf(buf, n, fmt, ap);
    va_end(ap);
    return r;
}

void tx_put_u128(unsigned __int128 v) { printf("%Lu", v); }
void tx_put_i128(__int128 v) { printf("%Ld", v); }
