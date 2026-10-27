#include <stdio.h>
#define SQR(x) ((x) * (x))
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define STR(x) #x
#define XSTR(x) STR(x)
#define CAT(a, b) a##b
#define VERSION 3
#define DEBUG_PRINT(fmt, ...) printf("dbg: " fmt "\n", ##__VA_ARGS__)
#if VERSION >= 3 && defined(SQR)
#define FEATURE "new"
#elif VERSION == 2
#define FEATURE "mid"
#else
#define FEATURE "old"
#endif
#ifndef UNDEFINED_THING
#define HAVE_NOT 1
#endif
#undef VERSION
#ifdef VERSION
#error should not happen
#endif
int CAT(my, var) = 17;
int main(void) {
    printf("%d %d %s %s\n", SQR(3 + 1), MAX(4, 9), STR(a + b), XSTR(__LINE__));
    printf("%s %d %d\n", FEATURE, HAVE_NOT, myvar);
    DEBUG_PRINT("plain");
    DEBUG_PRINT("args %d %s", 5, "x");
#if 0
    this is not compiled
#endif
#if (1 << 4) == 16 && 'A' == 65 && -1 < 0
    puts("if-arith ok");
#endif
    return 0;
}
