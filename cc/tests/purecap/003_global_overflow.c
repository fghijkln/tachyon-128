/* -mpurecap: globals and string literals carry their own bounds (also via static pointer tables) */
#include <stdio.h>
#include <tx128.h>
int table[4] = {10, 20, 30, 40};
const char *words[] = {"one", "two", "three"};
int sum(const int *p, int n) { int s = 0; for (int i = 0; i < n; i++) s += p[i]; return s; }
int main(void) {
    printf("sum = %d, words[2] = %s (length %d)\n", sum(table, 4), words[2], (int)__builtin_cheri_length_get(words[2]));
    volatile int k = 5;
    printf("reading words[1][%d] past the literal at ", k);
    tx_hexout((unsigned __int128)(words[1] + k));
    printf("%c\n", words[1][k]);       /* "two" has 4 bytes -> trap */
    printf("NOT REACHED %d\n", sum(table, 5));
    return 0;
}
