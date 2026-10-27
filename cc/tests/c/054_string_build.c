#include <stdio.h>
#include <string.h>
void reverse(char *s) { int n = strlen(s); for (int i = 0; i < n / 2; i++) { char t = s[i]; s[i] = s[n - 1 - i]; s[n - 1 - i] = t; } }
void itoa_(long v, char *out) { char *p = out; int neg = v < 0; unsigned long u = neg ? -(unsigned long)v : v; do { *p++ = '0' + u % 10; u /= 10; } while (u); if (neg) *p++ = '-'; *p = 0; reverse(out); }
int is_pal(const char *s) { int i = 0, j = strlen(s) - 1; while (i < j) if (s[i++] != s[j--]) return 0; return 1; }
int count_words(const char *s) { int n = 0, in = 0; for (; *s; s++) { if (*s == ' ') in = 0; else if (!in) { in = 1; n++; } } return n; }
int main(void) {
    char buf[32];
    long vals[] = {0, 7, -123, 9223372036854775807L, -9223372036854775807L - 1};
    for (int i = 0; i < 5; i++) { itoa_(vals[i], buf); printf("%s ", buf); }
    printf("\n%d %d %d\n", is_pal("racecar"), is_pal("abca"), is_pal(""));
    printf("%d\n", count_words("  the quick  brown fox "));
    char line[64] = ""; for (int i = 0; i < 5; i++) { char t[8]; sprintf(t, "[%d]", i * i); strcat(line, t); } puts(line);
    return 0;
}
