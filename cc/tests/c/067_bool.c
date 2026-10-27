#include <stdio.h>
#include <stdbool.h>
bool is_prime(int n) { if (n < 2) return false; for (int d = 2; d * d <= n; d++) if (n % d == 0) return false; return true; }
int main(void) {
    int c = 0; for (int i = 0; i < 100; i++) c += is_prime(i);
    printf("%d\n", c);
    bool b = 5; b += 1; printf("%d\n", b);
    bool z = 0; z++; printf("%d\n", z);
    bool w = 1; w--; printf("%d\n", w);
    _Bool arr[3] = {2, 0, -1}; printf("%d %d %d %lu\n", arr[0], arr[1], arr[2], sizeof(arr));
    bool t = (long)1 << 40; printf("%d\n", t);
    return 0;
}
