#include <stdio.h>
#include <stdlib.h>
int main(void) {
    for (int i = 0; i < 5; i++) printf("%d ", rand());
    printf("\n");
    srand(42);
    for (int i = 0; i < 5; i++) printf("%d ", rand() % 1000);
    printf("\n");
    srand(1);
    printf("%d\n", rand());
    long s = 0; srand(12345); for (int i = 0; i < 1000; i++) s += rand() & 0xFF; printf("%ld\n", s);
    return 0;
}
