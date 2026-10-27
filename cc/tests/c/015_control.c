#include <stdio.h>
int main(void) {
    int i, s = 0;
    for (i = 0; i < 100; i++) { if (i % 3 == 0) continue; if (i > 50) break; s += i; }
    printf("%d %d\n", s, i);
    i = 0; while (i < 10) i += 3; printf("%d\n", i);
    i = 100; do { i++; } while (i < 5); printf("%d\n", i);
    int n = 0;
    for (int a = 0; a < 5; a++) for (int b = 0; b < 5; b++) { if (b == a) break; n++; }
    printf("%d\n", n);
    i = 0;
again:
    i++;
    if (i < 7) goto again;
    printf("%d\n", i);
    int x = 5;
    x = x > 3 ? x * 2 : x / 2;
    printf("%d\n", x);
    printf("%d %d\n", 0 && (x = 1), 1 || (x = 2));
    printf("%d\n", x);
    return 0;
}
