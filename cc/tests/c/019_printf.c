#include <stdio.h>
int main(void) {
    printf("[%5d][%-5d][%05d][%+d][% d]\n", 42, 42, 42, 42, 42);
    printf("[%x][%X][%#x][%o][%#o]\n", 3054, 3054, 3054, 8, 8);
    printf("[%s][%10s][%-10s][%.3s]\n", "abc", "abc", "abc", "abcdef");
    printf("[%c][%%][%u]\n", 'Q', 4294967295u);
    printf("[%ld][%lu][%lx]\n", -1L, 18446744073709551615UL, 0xdeadbeefcafeL);
    printf("[%lld][%llu]\n", -9223372036854775807LL - 1, 12345678901234567890ULL);
    printf("[%hd][%hhd][%hu]\n", 70000, 300, 70000);
    printf("[%.5d][%8.3d][%-8.3d]\n", 42, 7, 7);
    printf("[%*d][%-*d]\n", 6, 1, 6, 2);
    printf("[%d][%d]\n", 0, -2147483647 - 1);
    char b[32]; int n = sprintf(b, "%d-%s", 12, "ab"); printf("%s %d\n", b, n);
    n = snprintf(b, 5, "%s", "truncate"); printf("%s %d\n", b, n);
    return 0;
}
