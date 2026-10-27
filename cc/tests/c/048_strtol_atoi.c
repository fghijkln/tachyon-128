#include <stdio.h>
#include <stdlib.h>
int main(void) {
    printf("%d %d %d\n", atoi("123"), atoi("  -42xyz"), atoi("+7"));
    char *end;
    long v = strtol("0x1fZ", &end, 16); printf("%ld %s\n", v, end);
    printf("%ld\n", strtol("0777", 0, 0));
    printf("%ld\n", strtol("0x10", 0, 0));
    printf("%lu\n", strtoul("4294967296", 0, 10));
    printf("%ld\n", strtol("-zz", 0, 36));
    printf("%d %ld %lld\n", abs(-5), labs(-50000000000L), llabs(-3LL));
    return 0;
}
