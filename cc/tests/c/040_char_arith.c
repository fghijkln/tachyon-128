#include <stdio.h>
#include <ctype.h>
void caesar(char *s, int k) { for (; *s; s++) if (isalpha(*s)) { char b = isupper(*s) ? 'A' : 'a'; *s = (char)(b + (*s - b + k) % 26); } }
int main(void) {
    char s[] = "Hello, World! xyz";
    caesar(s, 3); printf("%s\n", s);
    caesar(s, 23); printf("%s\n", s);
    int digits = 0, alpha = 0; for (const char *p = "a1b2c3 d4!"; *p; p++) { digits += isdigit(*p) != 0; alpha += isalpha(*p) != 0; }
    printf("%d %d\n", digits, alpha);
    char up[16]; int i = 0; for (const char *p = "MiXeD"; *p; p++) up[i++] = toupper(*p); up[i] = 0; printf("%s\n", up);
    char c = 'z'; c += 10; printf("%d\n", c);
    return 0;
}
