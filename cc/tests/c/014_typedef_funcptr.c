#include <stdio.h>
typedef int (*binop)(int, int);
static int add(int a, int b) { return a + b; }
static int sub(int a, int b) { return a - b; }
static int mul(int a, int b) { return a * b; }
int apply(binop f, int a, int b) { return f(a, b); }
struct ops { const char *name; binop fn; };
int main(void) {
    binop t[3] = {add, sub, mul};
    for (int i = 0; i < 3; i++) printf("%d ", t[i](7, 3));
    printf("\n%d\n", apply(mul, 6, 7));
    struct ops o[] = {{"add", add}, {"sub", &sub}};
    for (int i = 0; i < 2; i++) printf("%s=%d\n", o[i].name, (*o[i].fn)(10, 4));
    int (*fp)(int, int) = add;
    printf("%d\n", fp(1, 2));
    return 0;
}
