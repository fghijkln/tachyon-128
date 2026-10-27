#include <stdio.h>
#include <tx128.h>
int main(void) {
    unsigned long t0 = tx_instret();
    volatile int s = 0; for (int i = 0; i < 100; i++) s += i;
    unsigned long t1 = tx_instret();
    printf("sum %d, instret advanced: %d\n", s, t1 > t0 + 100);
    tx_put_u128(~(unsigned __int128)0); putchar('\n');
    tx_put_i128(-(((__int128)1) << 127)); putchar('\n');
    *TX_CONSOLE = 'O'; *TX_CONSOLE = 'K'; *TX_CONSOLE = '\n';
    return 7;
}
