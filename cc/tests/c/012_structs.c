#include <stdio.h>
struct point { int x, y; };
struct rect { struct point a, b; char name[8]; };
struct point mk(int x, int y) { struct point p; p.x = x; p.y = y; return p; }
int area(struct rect r) { return (r.b.x - r.a.x) * (r.b.y - r.a.y); }
void grow(struct rect *r, int d) { r->b.x += d; r->b.y += d; }
int main(void) {
    struct rect r = {{1, 2}, {5, 7}, "box"};
    printf("%d %s\n", area(r), r.name);
    grow(&r, 3);
    printf("%d %d %d\n", area(r), r.b.x, r.b.y);
    struct point p = mk(3, 4), q;
    q = p; q.x++;
    printf("%d %d %d %d\n", p.x, p.y, q.x, q.y);
    struct rect copy = r; copy.a = mk(0, 0);
    printf("%d %d\n", area(copy), area(r));
    printf("%lu\n", sizeof(struct rect));
    struct point arr[3] = {{1, 1}, {2, 2}, {3, 3}};
    int s = 0; for (int i = 0; i < 3; i++) s += arr[i].x * arr[i].y;
    printf("%d\n", s);
    struct point *pp = arr; pp++; printf("%d\n", pp->y);
    return 0;
}
