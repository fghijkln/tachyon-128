#include <stdio.h>
int counter;
int initd = 5;
static int hidden = 7;
const char *msg = "global string";
int table[] = {1, 1, 2, 3, 5, 8, 13};
int *ptr = &table[3];
struct cfg { int a; char b; long c; const char *s; } conf = {1, 'x', 3000000000L, "cfg"};
char letters[] = "abc";
long big = -1;
unsigned char bytes[] = {255, 128, 0};
void bump(void) { counter++; hidden += 2; }
int main(void) {
    bump(); bump();
    printf("%d %d %d\n", counter, initd, hidden);
    printf("%s %d %d\n", msg, table[6], *ptr);
    printf("%d %c %ld %s\n", conf.a, conf.b, conf.c, conf.s);
    printf("%s %ld %d %d\n", letters, big, bytes[0], bytes[1]);
    ptr[1] = 100; printf("%d\n", table[4]);
    static int st = 10; st++; printf("%d\n", st);
    return 0;
}
