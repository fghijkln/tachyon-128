#include <stdio.h>
struct shape;
struct vt { int (*area)(struct shape *); const char *(*name)(void); };
struct shape { const struct vt *vt; int w, h; };
static int rect_area(struct shape *s) { return s->w * s->h; }
static int tri_area(struct shape *s) { return s->w * s->h / 2; }
static const char *rn(void) { return "rect"; }
static const char *tn(void) { return "tri"; }
static const struct vt RV = {rect_area, rn}, TV = {tri_area, tn};
int main(void) {
    struct shape s[4] = {{&RV, 3, 4}, {&TV, 6, 5}, {&RV, 10, 10}, {&TV, 7, 3}};
    int tot = 0;
    for (int i = 0; i < 4; i++) { int a = s[i].vt->area(&s[i]); printf("%s:%d ", s[i].vt->name(), a); tot += a; }
    printf("\n%d\n", tot);
    return 0;
}
