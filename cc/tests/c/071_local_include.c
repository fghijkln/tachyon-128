#include <stdio.h>
#include "inc/util.h"
#include "inc/util.h"
int main(void) {
    int v[] = {-5, 3, 99, 50};
    for (unsigned i = 0; i < ARRAY_LEN(v); i++) printf("%d ", clamp(v[i], 0, 50));
    printf("\n");
    frac s = frac_make(0, 1);
    for (int k = 1; k <= 10; k++) s = frac_add(s, frac_make(1, k * (k + 1)));
    printf("%d/%d\n", s.num, s.den);
    return 0;
}
