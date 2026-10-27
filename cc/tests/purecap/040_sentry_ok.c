/* -mpurecap (v6): function pointers are sealed entry capabilities (sentries, otype 0xFFFF). They can be
   copied, stored in globals / heap / structs, passed through varargs and memcpy, compared, and called
   with cjalr (which unseals them into the PCC) -- everything a C program does with them legitimately. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
typedef int (*op_t)(int, int);
static int add(int a, int b) { return a + b; }
static int sub(int a, int b) { return a - b; }
static int mul(int a, int b) { return a * b; }
op_t ops[] = {add, sub, mul};                       /* static initialiser: rebuilt by crt0 as sentries */
struct shape_vt { const char *name; int (*area)(int); int (*sides)(void); };
static int sq_area(int s) { return s * s; }
static int sq_sides(void) { return 4; }
static int tri_area(int s) { return s * s / 2; }
static int tri_sides(void) { return 3; }
static const struct shape_vt vts[] = {{"square", sq_area, sq_sides}, {"triangle", tri_area, tri_sides}};
static int cmp(const void *a, const void *b) { return *(const int *)a - *(const int *)b; }
static int sum_calls(int n, ...) {
    va_list ap; int s = 0;
    va_start(ap, n);
    for (int i = 0; i < n; i++) { op_t f = va_arg(ap, op_t); s += f(10, 3); }
    va_end(ap);
    return s;
}
static op_t pick(int k) { return k == 0 ? add : k == 1 ? sub : mul; }
static int twice(op_t f, int x) { return f(f(x, 1), 1); }
int main(void) {
    op_t local = mul;
    printf("tag %lu type %lx (local)\n", __builtin_cheri_tag_get(local), __builtin_cheri_type_get(local));
    printf("tag %lu type %lx (static table)\n", __builtin_cheri_tag_get(ops[1]), __builtin_cheri_type_get(ops[1]));
    printf("tag %lu type %lx (vtable)\n", __builtin_cheri_tag_get(vts[1].area), __builtin_cheri_type_get(vts[1].area));
    int s = 0;
    for (int i = 0; i < 3; i++) s += ops[i](7, 5);
    printf("table: %d\n", s);
    for (int i = 0; i < 2; i++) printf("%s: area %d sides %d\n", vts[i].name, vts[i].area(6), vts[i].sides());
    op_t *heap = malloc(3 * sizeof(op_t));
    memcpy(heap, ops, 3 * sizeof(op_t));            /* tags (and the seal) survive memcpy */
    printf("heap: %d %d %d type %lx\n", heap[0](2, 3), heap[1](2, 3), heap[2](2, 3), __builtin_cheri_type_get(heap[2]));
    struct shape_vt copy = vts[0];                  /* struct copy keeps the sentries */
    printf("copy: %d\n", copy.area(9));
    printf("varargs: %d\n", sum_calls(3, add, sub, mul));
    printf("returned: %d %d\n", pick(2)(6, 7), twice(pick(0), 40));
    printf("compare: %d %d %d\n", local == mul, pick(1) == sub, ops[0] != ops[1]);
    op_t none = 0;
    printf("null: %d\n", none == 0 && !none);
    uintptr_t u = (uintptr_t)local;                 /* uintptr_t keeps the capability, still sealed */
    printf("via uintptr_t: %d type %lx\n", ((op_t)u)(5, 5), __builtin_cheri_type_get((void *)u));
    int a[6] = {9, 2, 7, 1, 8, 3};
    qsort(a, 6, sizeof a[0], cmp);
    printf("qsort: %d %d %d %d %d %d\n", a[0], a[1], a[2], a[3], a[4], a[5]);
    free(heap);
    return 0;
}
