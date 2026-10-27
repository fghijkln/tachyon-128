/* Byte-magazine sieve of Eratosthenes (8190 flags), 3 iterations */
#include <stdio.h>
#define SIZE 8190
static char flags[SIZE + 1];
int main(void) {
    int count = 0;
    for (int iter = 0; iter < 3; iter++) {
        count = 0;
        for (int i = 0; i <= SIZE; i++) flags[i] = 1;
        for (int i = 0; i <= SIZE; i++) {
            if (flags[i]) {
                int prime = i + i + 3;
                for (int k = i + prime; k <= SIZE; k += prime) flags[k] = 0;
                count++;
            }
        }
    }
    printf("%d primes\n", count);
    return count == 1899 ? 0 : 1;
}
