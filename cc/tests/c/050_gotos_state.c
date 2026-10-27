#include <stdio.h>
int parse(const char *s) {
    int n = 0, sign = 1;
start:
    if (*s == ' ') { s++; goto start; }
    if (*s == '-') { sign = -1; s++; }
digits:
    if (*s >= '0' && *s <= '9') { n = n * 10 + (*s++ - '0'); goto digits; }
    if (*s == 0) goto done;
    return -999;
done:
    return sign * n;
}
int main(void) {
    printf("%d %d %d %d\n", parse("  123"), parse("-45"), parse("12x"), parse(""));
    int i = 0, s = 0;
loop:
    if (i >= 10) goto out;
    s += i++;
    goto loop;
out:
    printf("%d\n", s);
    return 0;
}
