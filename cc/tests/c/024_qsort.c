#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static int cmp_int(const void *a, const void *b) { int x = *(const int *)a, y = *(const int *)b; return (x > y) - (x < y); }
static int cmp_str(const void *a, const void *b) { return strcmp(*(char *const *)a, *(char *const *)b); }
struct rec { int key; char name[8]; };
static int cmp_rec(const void *a, const void *b) { return ((const struct rec *)b)->key - ((const struct rec *)a)->key; }
int main(void) {
    int a[50]; unsigned x = 12345;
    for (int i = 0; i < 50; i++) { x = x * 1103515245u + 12345u; a[i] = (int)(x >> 16) % 1000 - 500; }
    qsort(a, 50, sizeof(int), cmp_int);
    for (int i = 0; i < 50; i++) printf("%d ", a[i]);
    printf("\n");
    char *w[] = {"pear", "apple", "fig", "banana", "cherry", "date"};
    qsort(w, 6, sizeof(char *), cmp_str);
    for (int i = 0; i < 6; i++) printf("%s ", w[i]);
    printf("\n");
    struct rec r[5] = {{3, "c"}, {1, "a"}, {5, "e"}, {2, "b"}, {4, "d"}};
    qsort(r, 5, sizeof r[0], cmp_rec);
    for (int i = 0; i < 5; i++) printf("%d%s ", r[i].key, r[i].name);
    printf("\n");
    int key = 3; int *found = bsearch(&key, (int[]){1, 2, 3, 4, 5}, 5, sizeof(int), cmp_int);
    printf("%d\n", found ? *found : -1);
    return 0;
}
