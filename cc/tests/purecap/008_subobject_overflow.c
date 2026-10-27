/* -mpurecap sub-object bounds: overflowing a struct member array into the next field traps (cause 3).
   Without -fno-subobject-bounds the member's capability spans only the member; the in-bounds accesses,
   &s.field, nested members, the offsetof idiom and a flexible array member keep working. */
#include <stdio.h>
#include <stddef.h>
#include <string.h>
#include <tx128.h>
struct inner { int a, b; };
struct acct { char name[8]; long balance; struct inner in; };
struct pkt { int len; char data[]; };
static void copy_name(char *dst, const char *src) { while ((*dst++ = *src++)) ; }
int main(void) {
    struct acct s;
    s.balance = 100;
    s.in.a = 1; s.in.b = 2;
    copy_name(s.name, "bob");                       /* fits */
    printf("%s %ld len(name)=%d len(&s.balance)=%d len(&s.in)=%d len(&s.in.b)=%d\n", s.name, s.balance,
           (int)__builtin_cheri_length_get(s.name), (int)__builtin_cheri_length_get(&s.balance),
           (int)__builtin_cheri_length_get(&s.in), (int)__builtin_cheri_length_get(&s.in.b));
    printf("offsetof(balance)=%d offsetof(in.b)=%d\n", (int)offsetof(struct acct, balance), (int)offsetof(struct acct, in.b));
    static __int128 buf[4];
    struct pkt *p = (struct pkt *)buf;
    p->len = 5;
    memcpy(p->data, "hello", 6);                    /* flexible array member: bounded by the allocation */
    printf("%d %s len(data)=%d\n", p->len, p->data, (int)__builtin_cheri_length_get(p->data));
    int *ip = &s.in.a;
    printf("&s.in.a[0]=%d\n", ip[0]);
    printf("overflowing s.name into s.balance at ");
    tx_hexout((unsigned __int128)(s.name + 8));
    copy_name(s.name, "mallory!!");                 /* 10 bytes into an 8-byte member -> trap */
    printf("NOT REACHED balance=%ld\n", s.balance);
    return 0;
}
