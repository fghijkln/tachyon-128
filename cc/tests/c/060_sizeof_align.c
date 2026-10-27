#include <stdio.h>
#include <stddef.h>
struct a { char c; int i; };
struct b { char c; long l; char d; };
struct c { short s; char c[3]; };
struct d { char c; __int128 q; };
union e { char c[5]; int i; };
struct f { int x; struct a in; char tail; };
int main(void) {
    printf("%lu %lu %lu %lu %lu %lu\n", sizeof(struct a), sizeof(struct b), sizeof(struct c), sizeof(struct d), sizeof(union e), sizeof(struct f));
    printf("%lu %lu %lu %lu\n", offsetof(struct a, i), offsetof(struct b, d), offsetof(struct d, q), offsetof(struct f, tail));
    int arr[10]; printf("%lu %lu\n", sizeof arr, sizeof arr[0]);
    printf("%lu\n", sizeof(__int128));
    printf("%lu\n", _Alignof(long));
    return 0;
}
