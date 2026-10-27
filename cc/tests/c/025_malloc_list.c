#include <stdio.h>
#include <stdlib.h>
struct node { int v; struct node *next; };
struct node *push(struct node *h, int v) { struct node *n = malloc(sizeof *n); n->v = v; n->next = h; return n; }
struct node *reverse(struct node *h) { struct node *p = 0; while (h) { struct node *n = h->next; h->next = p; p = h; h = n; } return p; }
int main(void) {
    struct node *h = 0;
    for (int i = 1; i <= 10; i++) h = push(h, i * i);
    for (struct node *p = h; p; p = p->next) printf("%d ", p->v);
    printf("\n");
    h = reverse(h);
    int s = 0; for (struct node *p = h; p; p = p->next) { printf("%d ", p->v); s += p->v; }
    printf("\n%d\n", s);
    int *arr = calloc(100, sizeof(int));
    for (int i = 0; i < 100; i++) arr[i] += i;
    arr = realloc(arr, 200 * sizeof(int));
    for (int i = 100; i < 200; i++) arr[i] = i;
    long t = 0; for (int i = 0; i < 200; i++) t += arr[i];
    printf("%ld\n", t);
    return 0;
}
