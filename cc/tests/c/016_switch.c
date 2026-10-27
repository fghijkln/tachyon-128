#include <stdio.h>
const char *name(int d) {
    switch (d) {
    case 0: return "zero";
    case 1: case 2: return "small";
    case 10: return "ten";
    case -5: return "neg";
    default: return "?";
    }
}
int dense(int x) {
    switch (x) {
    case 1: return 11; case 2: return 22; case 3: return 33; case 4: return 44;
    case 5: return 55; case 6: return 66; case 7: return 77; case 9: return 99;
    }
    return -1;
}
int sparse(long x) {
    switch (x) {
    case 100: return 1; case 2000: return 2; case 30000: return 3; case 400000: return 4;
    case 5000000: return 5; case 7: return 6; case -9: return 7; case 123456789: return 8;
    case 99: return 9; default: return 0;
    }
}
int main(void) {
    for (int i = -6; i < 12; i++) printf("%s ", name(i));
    printf("\n");
    for (int i = 0; i < 11; i++) printf("%d ", dense(i));
    printf("\n");
    long v[] = {100, 2000, 30000, 400000, 5000000, 7, -9, 123456789, 99, 5, -1};
    for (int i = 0; i < 11; i++) printf("%d ", sparse(v[i]));
    printf("\n");
    int f = 0;
    switch (3) { case 3: f += 1; case 4: f += 10; break; case 5: f += 100; }
    printf("%d\n", f);
    return 0;
}
