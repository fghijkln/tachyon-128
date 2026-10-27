#include <stdio.h>
int next_id(void) { static int id = 100; return id++; }
int *counter(void) { static int c; c++; return &c; }
const char *day(int i) { static const char *names[] = {"mon", "tue", "wed"}; return names[i % 3]; }
int main(void) {
    printf("%d %d %d\n", next_id(), next_id(), next_id());
    counter(); counter(); printf("%d\n", *counter());
    for (int i = 0; i < 4; i++) printf("%s ", day(i));
    printf("\n");
    return 0;
}
