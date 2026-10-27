#include <stdio.h>
struct pt { int x, y; };
struct line { struct pt a, b; const char *label; };
struct poly { int n; struct pt v[4]; };
static struct line lines[] = { {{0, 0}, {3, 4}, "first"}, {{1, 1}, {4, 5}, "second"}, {.label = "third", .b = {9, 9}} };
static struct poly sq = {4, {{0, 0}, {2, 0}, {2, 2}, {0, 2}}};
int main(void) {
    for (int i = 0; i < 3; i++) printf("%s: (%d,%d)-(%d,%d)\n", lines[i].label, lines[i].a.x, lines[i].a.y, lines[i].b.x, lines[i].b.y);
    int area2 = 0; for (int i = 0; i < sq.n; i++) { struct pt p = sq.v[i], q = sq.v[(i + 1) % sq.n]; area2 += p.x * q.y - q.x * p.y; }
    printf("%d\n", area2 / 2);
    struct line local = {{5, 6}, {7, 8}, "local"}; struct line copy = local; copy.a.x = 50;
    printf("%d %d %s\n", local.a.x, copy.a.x, copy.label);
    struct poly lp = {.n = 2, .v = {[1] = {7, 8}}}; printf("%d %d %d %d\n", lp.n, lp.v[0].x, lp.v[1].x, lp.v[1].y);
    return 0;
}
