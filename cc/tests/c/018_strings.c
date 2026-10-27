#include <stdio.h>
#include <string.h>
int main(void) {
    char buf[64];
    strcpy(buf, "hello");
    strcat(buf, ", world");
    printf("%s %lu\n", buf, strlen(buf));
    printf("%d %d %d\n", strcmp("abc", "abd") < 0, strcmp("b", "a") > 0, strcmp("x", "x"));
    printf("%d\n", strncmp("abcdef", "abcxyz", 3));
    char *p = strchr(buf, 'w'); printf("%s\n", p);
    printf("%s\n", strrchr(buf, 'o'));
    printf("%s\n", strstr(buf, "lo, w"));
    memset(buf, 'x', 5); printf("%s\n", buf);
    char d[20]; memcpy(d, "0123456789", 11); memmove(d + 2, d, 5); printf("%s\n", d);
    printf("%d\n", memcmp("abc", "abd", 3) < 0);
    const char *s = "string literal"; int n = 0; while (s[n]) n++; printf("%d\n", n);
    printf("%c%c\n", "xyz"[1], *("abc" + 2));
    char esc[] = "tab\there\\ \"q\" \x41\101\n"; printf("%s", esc);
    return 0;
}
