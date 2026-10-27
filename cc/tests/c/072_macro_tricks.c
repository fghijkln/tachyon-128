#include <stdio.h>
#define LIST(X) X(red, 1) X(green, 2) X(blue, 4)
#define AS_ENUM(n, v) C_##n = v,
#define AS_STR(n, v) #n,
#define AS_CASE(n, v) case C_##n: return #n;
enum colors { LIST(AS_ENUM) C_END };
const char *names[] = { LIST(AS_STR) };
const char *cname(int c) { switch (c) { LIST(AS_CASE) } return "?"; }
#define PASTE3(a, b, c) a##b##c
#define EVAL(x) x
#define EMPTY()
#define COUNT_ARGS(...) COUNT_(__VA_ARGS__, 5, 4, 3, 2, 1)
#define COUNT_(a, b, c, d, e, n, ...) n
#define MIN3(a, b, c) ((a) < (b) ? ((a) < (c) ? (a) : (c)) : ((b) < (c) ? (b) : (c)))
#define SWAP(t, a, b) do { t tmp_ = (a); (a) = (b); (b) = tmp_; } while (0)
int PASTE3(x, y, z) = 123;
int main(void) {
    printf("%s %s %s %d\n", names[0], names[2], cname(C_green), C_END);
    printf("%d %d %d\n", xyz, COUNT_ARGS(a, b, c), COUNT_ARGS(1));
    printf("%d\n", MIN3(5, 2, 8));
    int a = 1, b = 2; SWAP(int, a, b); printf("%d %d\n", a, b);
    printf("%s\n", __func__);
    printf("line %d\n", __LINE__);
    return EVAL(0) EMPTY();
}
