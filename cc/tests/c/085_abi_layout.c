/* ABI.md section 1 cross-check against the host (pointer-free types only, since pointers are
   16 bytes on TACHYON-128 and 8 on the host): sizes, alignments, offsets, bit-field packing */
#include <stdio.h>
#include <stddef.h>
#define SA(T) printf("%-22s size %2d align %2d\n", #T, (int)sizeof(T), (int)_Alignof(T))
struct s1 { char c; int i; };
struct s2 { char c; long l; short s; };
struct s3 { char c; __int128 x; char d; };
struct s4 { short a; char b[3]; };
struct s5 { long long a; char b; };
union u1 { char c[5]; int i; };
union u2 { short s; __int128 x; };
struct bf1 { unsigned a : 3, b : 5, c : 9; };
struct bf2 { char a; int b : 7; int c : 30; };
struct bf3 { unsigned a : 4; unsigned : 0; unsigned b : 4; };
struct bf4 { unsigned char a : 3, b : 6; short c : 9; };
struct nest { char a; struct s3 in; char z; };
enum e { E0, E1 = 1000 };
int main(void) {
    SA(_Bool); SA(char); SA(short); SA(int); SA(long); SA(long long); SA(__int128);
    SA(enum e); SA(size_t); SA(ptrdiff_t);
    SA(struct s1); SA(struct s2); SA(struct s3); SA(struct s4); SA(struct s5);
    SA(union u1); SA(union u2); SA(struct bf1); SA(struct bf2); SA(struct bf3); SA(struct bf4);
    SA(struct nest);
    printf("offs %d %d %d %d %d %d\n", (int)offsetof(struct s2, l), (int)offsetof(struct s2, s),
           (int)offsetof(struct s3, x), (int)offsetof(struct s3, d), (int)offsetof(struct nest, in),
           (int)offsetof(struct nest, z));
    union { struct bf1 b; unsigned u; } p1 = {{0}};
    p1.b.a = 5; p1.b.b = 17; p1.b.c = 300;
    printf("bf1 %08x\n", p1.u);
    union { struct bf3 b; unsigned u[2]; } p3 = {{0}};
    p3.b.a = 9; p3.b.b = 6;
    printf("bf3 %x %x\n", p3.u[0], p3.u[1]);
    union { struct bf4 b; unsigned char c[4]; } p4 = {{0}};
    p4.b.a = 7; p4.b.b = 33; p4.b.c = -2;
    printf("bf4 %02x %02x %02x %02x\n", p4.c[0], p4.c[1], p4.c[2], p4.c[3]);
    return 0;
}
