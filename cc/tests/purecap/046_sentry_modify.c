/* -mpurecap (v6): the capability intrinsics cannot retarget or re-bound a sentry (cause 7), and a sealed
   function pointer stored in a struct is still sealed when it comes back out. */
#include <stdio.h>
#include <tx128.h>
typedef int (*op_t)(int, int);
static int add(int a, int b) { return a + b; }
static int mul(int a, int b) { return a * b; }
struct obj { int x; op_t method; } o = {3, add};
int main(void) {
    printf("method(3, 4) = %d, type %lx\n", o.method(o.x, 4), __builtin_cheri_type_get(o.method));
    unsigned long target = (unsigned long)mul;
    printf("retargeting the sentry at ");
    tx_hexout((unsigned __int128)(unsigned long)o.method);
    op_t evil = __builtin_cheri_address_set(o.method, target);
    printf("%d\n", evil(3, 4));
    printf("NOT REACHED\n");
    return 0;
}
