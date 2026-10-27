#include <stdio.h>
int main(void) {
    int si = -1; unsigned ui = 1; long sl = -1; unsigned long ul = 1; unsigned short us = 1; short ss = -1;
    printf("%d %d %d %d\n", si < ui, sl < ui, si < ul, ss < us);
    printf("%d %d\n", (unsigned char)200 > (signed char)-1, (signed char)-1 < (unsigned short)1);
    long long ll = -1; unsigned int u32 = 0xFFFFFFFFu; printf("%d\n", ll < u32);
    unsigned long long ull = 5; printf("%d\n", -1 > ull);
    int arr[] = {-5, 3, -1, 0, 7}; unsigned cnt = 0;
    for (unsigned k = 0; k < 5; k++) if (arr[k] >= 0) cnt++;
    printf("%u\n", cnt);
    for (unsigned k = 3; k < 10; k--) printf("%u ", k);
    printf("\n");
    unsigned char c = 255; int r = c == -1; printf("%d\n", r);
    char d = -1; printf("%d\n", d == 255);
    return 0;
}
