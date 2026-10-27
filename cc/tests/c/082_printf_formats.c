/* printf conversions and flags */
#include <stdio.h>
#include <limits.h>
int main(void) {
    printf("[%d] [%i] [%u] [%x] [%X] [%o]\n", -123, 77, 3000000000u, 0xbeefu, 0xbeefu, 8u);
    printf("[%ld] [%lu] [%lx]\n", -9000000000L, 18000000000000000000UL, 0xdeadbeefcafeUL);
    printf("[%lld] [%llu] [%llx]\n", LLONG_MIN, ULLONG_MAX, 0x123456789abcdefULL);
    printf("[%d] [%d] [%u]\n", INT_MIN, INT_MAX, UINT_MAX);
    printf("[%c%c%c] [%s] [%%]\n", 'a', 'b', 'c', "str");
    printf("[%8d] [%-8d] [%08d] [%+d] [%+d]\n", 123, 123, 123, 5, -5);
    printf("[%8x] [%-8x] [%08x] [%#x] [%#o]\n", 255u, 255u, 255u, 255u, 8u);
    printf("[%10s] [%-10s] [%.2s] [%5c]\n", "hi", "hi", "hello", 'q');
    printf("[%hd] [%hu] [%hhd] [%hhu]\n", (short)-2, (unsigned short)65535, (signed char)-3, (unsigned char)250);
    printf("[%zu] [%d]\n", sizeof(int), (int)sizeof(long long));
    char buf[64];
    int n = sprintf(buf, "%d-%s-%x", 7, "x", 31u);
    printf("%s %d\n", buf, n);
    n = snprintf(buf, 6, "%d", 1234567);
    printf("%s %d\n", buf, n);
    return 0;
}
