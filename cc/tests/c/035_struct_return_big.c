#include <stdio.h>
struct big { long a[6]; char tag; };
struct big make(int k) { struct big b; for (int i = 0; i < 6; i++) b.a[i] = k * (i + 1); b.tag = 'A' + k; return b; }
struct big twice(struct big b) { for (int i = 0; i < 6; i++) b.a[i] *= 2; b.tag++; return b; }
long total(struct big b) { long s = 0; for (int i = 0; i < 6; i++) s += b.a[i]; return s; }
struct small { char c; short s; };
struct small sm(char c) { struct small r = {c, (short)(c * 100)}; return r; }
int main(void) {
    struct big b = make(3);
    struct big c = twice(twice(b));
    printf("%ld %ld %c %c\n", total(b), total(c), b.tag, c.tag);
    printf("%ld\n", total(make(5)));
    printf("%d %d\n", sm(7).c, sm(7).s);
    struct big arr[2]; arr[1] = make(2); printf("%ld\n", arr[1].a[5]);
    return 0;
}
