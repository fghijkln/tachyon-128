#include <stdio.h>
#define N 5000
char comp[N + 1];
int main(void) {
    int cnt = 0, last = 0;
    for (int i = 2; i <= N; i++) {
        if (comp[i]) continue;
        cnt++; last = i;
        for (int j = i * i; j <= N; j += i) comp[j] = 1;
    }
    printf("%d primes <= %d, largest %d\n", cnt, N, last);
    return cnt % 256;
}
