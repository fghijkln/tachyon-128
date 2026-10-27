/* -mpurecap: a stack buffer overflow is stopped by the capability bounds of the buffer */
#include <stdio.h>
#include <tx128.h>
static void fill(char *p, int n) { for (int i = 0; i < n; i++) p[i] = 'A' + i; }
int main(void) {
    char guard[16];
    char buf[16];
    guard[0] = 'G';
    fill(buf, 16);                     /* in bounds */
    printf("buf ok: %c..%c, length %d\n", buf[0], buf[15], (int)__builtin_cheri_length_get(buf));
    printf("first byte past the end: ");
    tx_hexout((unsigned __int128)(buf + 16));
    volatile int n = 17;
    fill(buf, n);                      /* writes buf[16] -> capability-bounds trap (cause 3) */
    printf("NOT REACHED guard=%c\n", guard[0]);
    return 0;
}
