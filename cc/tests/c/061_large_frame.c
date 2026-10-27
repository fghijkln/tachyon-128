#include <stdio.h>
int work(int n) {
    int big[3000]; char pad[5000]; long tail = 7;
    for (int i = 0; i < 3000; i++) big[i] = i * n;
    for (int i = 0; i < 5000; i++) pad[i] = (char)i;
    long s = tail; for (int i = 0; i < 3000; i += 3) s += big[i];
    return (int)(s + pad[4999] + pad[1234]);
}
int main(void) { printf("%d %d\n", work(1), work(3)); return 0; }
