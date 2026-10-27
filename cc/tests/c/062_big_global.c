#include <stdio.h>
#define N 20000
int big[N];
char buf[30000];
int main(void) {
    for (int i = 0; i < N; i++) big[i] = i ^ (i >> 3);
    long s = 0; for (int i = 0; i < N; i += 5) s += big[i];
    buf[29999] = 'z'; buf[0] = 'a';
    printf("%ld %c %c %d\n", s, buf[0], buf[29999], big[N - 1]);
    return 0;
}
