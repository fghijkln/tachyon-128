#include <stdio.h>
int add();
int add(a, b) int a; int b; { return a + b; }
int twice(int x) { return 2 * x; }
int main() {
    printf("%d\n", add(2, 3));
    printf("%d\n", twice(21));
    return 0;
}
