#include <stdio.h>
struct p { int x, y; };
int sum(int *a, int n) { int s = 0; for (int i = 0; i < n; i++) s += a[i]; return s; }
int dot(struct p a, struct p b) { return a.x * b.x + a.y * b.y; }
int main(void) {
    printf("%d\n", sum((int[]){1, 2, 3, 4}, 4));
    printf("%d\n", dot((struct p){2, 3}, (struct p){.y = 5, .x = 4}));
    struct p *pp = &(struct p){7, 8}; pp->x++;
    printf("%d %d\n", pp->x, pp->y);
    struct p q = {.y = 9}; printf("%d %d\n", q.x, q.y);
    struct { int a[3]; char c; } s = {{1, 2, 3}, 'k'};
    printf("%d %c\n", s.a[2], s.c);
    return 0;
}
