/* Dhrystone-like synthetic benchmark (structure modelled on Dhrystone 2.1: record copies,
   string compare/copy, enums, global arrays, procedure calls); not the official source. */
#include <stdio.h>
#include <string.h>
typedef enum { Ident_1, Ident_2, Ident_3, Ident_4, Ident_5 } Enumeration;
typedef struct record {
    struct record *Ptr_Comp;
    Enumeration Discr;
    Enumeration Enum_Comp;
    int Int_Comp;
    char Str_Comp[31];
} Rec_Type, *Rec_Pointer;

static Rec_Type Rec_A, Rec_B;
static Rec_Pointer Ptr_Glob, Next_Ptr_Glob;
static int Int_Glob;
static int Bool_Glob;
static char Ch_1_Glob, Ch_2_Glob;
static int Arr_1_Glob[50];
static int Arr_2_Glob[50][50];

static int Func_3(Enumeration e) { return e == Ident_3; }
static Enumeration Func_1(char c1, char c2) { char a = c1, b = a; if (b != c2) return Ident_1; Ch_1_Glob = a; return Ident_2; }
static int Func_2(const char *s1, const char *s2) {
    int i = 2; char c = 0;
    while (i <= 2) if (Func_1(s1[i], s2[i + 1]) == Ident_1) { c = 'A'; i += 1; }
    if (c >= 'W' && c < 'Z') i = 7;
    if (c == 'R') return 1;
    if (strcmp(s1, s2) > 0) { i += 7; Int_Glob = i; return 1; }
    return 0;
}
static void Proc_7(int a, int b, int *out) { *out = b + a + 2; }
static void Proc_6(Enumeration e, Enumeration *out) {
    *out = e;
    if (!Func_3(e)) *out = Ident_4;
    switch (e) {
    case Ident_1: *out = Ident_1; break;
    case Ident_2: *out = Int_Glob > 100 ? Ident_1 : Ident_4; break;
    case Ident_3: *out = Ident_2; break;
    case Ident_4: break;
    case Ident_5: *out = Ident_3; break;
    }
}
static void Proc_8(int a1[50], int a2[50][50], int i1, int i2) {
    int loc = i1 + 5;
    a1[loc] = i2; a1[loc + 1] = a1[loc]; a1[loc + 30] = loc;
    for (int k = loc; k <= loc + 1; ++k) a2[loc][k] = loc;
    a2[loc][loc - 1] += 1;
    a2[loc + 20][loc] = a1[loc];
    Int_Glob = 5;
}
static void Proc_3(Rec_Pointer *p) { if (Ptr_Glob) *p = Ptr_Glob->Ptr_Comp; Proc_7(10, Int_Glob, &Ptr_Glob->Int_Comp); }
static void Proc_1(Rec_Pointer p) {
    Rec_Pointer next = p->Ptr_Comp;
    *p->Ptr_Comp = *Ptr_Glob;
    p->Int_Comp = 5;
    next->Int_Comp = p->Int_Comp;
    next->Ptr_Comp = p->Ptr_Comp;
    Proc_3(&next->Ptr_Comp);
    if (next->Discr == Ident_1) {
        next->Int_Comp = 6;
        Proc_6(p->Enum_Comp, &next->Enum_Comp);
        next->Ptr_Comp = Ptr_Glob->Ptr_Comp;
        Proc_7(next->Int_Comp, 10, &next->Int_Comp);
    } else *p = *p->Ptr_Comp;
}
static void Proc_2(int *p) { int loc = *p + 10; Enumeration e = Ident_2; for (;;) { if (Ch_1_Glob == 'A') { loc -= 1; *p = loc - Int_Glob; e = Ident_1; } if (e == Ident_1) break; } }
static void Proc_4(void) { int b = Ch_1_Glob == 'A'; Bool_Glob = b | Bool_Glob; Ch_2_Glob = 'B'; }
static void Proc_5(void) { Ch_1_Glob = 'A'; Bool_Glob = 0; }

int main(void) {
    int Int_1, Int_2, Int_3 = 0; char Ch; Enumeration Enum; char Str_1[31], Str_2[31];
    const int RUNS = 400;
    Next_Ptr_Glob = &Rec_B; Ptr_Glob = &Rec_A;
    Ptr_Glob->Ptr_Comp = Next_Ptr_Glob; Ptr_Glob->Discr = Ident_1; Ptr_Glob->Enum_Comp = Ident_3; Ptr_Glob->Int_Comp = 40;
    strcpy(Ptr_Glob->Str_Comp, "DHRYSTONE PROGRAM, SOME STRING");
    strcpy(Str_1, "DHRYSTONE PROGRAM, 1'ST STRING");
    Arr_2_Glob[8][7] = 10;
    for (int run = 1; run <= RUNS; ++run) {
        Proc_5(); Proc_4();
        Int_1 = 2; Int_2 = 3;
        strcpy(Str_2, "DHRYSTONE PROGRAM, 2'ND STRING");
        Enum = Ident_2;
        Bool_Glob = !Func_2(Str_1, Str_2);
        while (Int_1 < Int_2) { Int_3 = 5 * Int_1 - Int_2; Proc_7(Int_1, Int_2, &Int_3); Int_1 += 1; }
        Proc_8(Arr_1_Glob, Arr_2_Glob, Int_1, Int_3);
        Proc_1(Ptr_Glob);
        for (Ch = 'A'; Ch <= Ch_2_Glob; ++Ch) if (Enum == Func_1(Ch, 'C')) { Proc_6(Ident_1, &Enum); strcpy(Str_2, "DHRYSTONE PROGRAM, 3'RD STRING"); Int_2 = run; Int_Glob = run; }
        Int_2 = Int_2 * Int_1; Int_1 = Int_2 / Int_3; Int_2 = 7 * (Int_2 - Int_3) - Int_1;
        Proc_2(&Int_1);
    }
    printf("Int_Glob=%d Bool_Glob=%d Ch_1=%c Ch_2=%c Arr_1[8]=%d Arr_2[8][7]=%d\n", Int_Glob, Bool_Glob, Ch_1_Glob, Ch_2_Glob, Arr_1_Glob[8], Arr_2_Glob[8][7]);
    printf("Ptr_Glob: %d %d %d %s\n", Ptr_Glob->Discr, Ptr_Glob->Enum_Comp, Ptr_Glob->Int_Comp, Ptr_Glob->Str_Comp);
    printf("Int_1=%d Int_2=%d Int_3=%d Enum=%d Str_2=%s\n", Int_1, Int_2, Int_3, Enum, Str_2);
    printf("runs=%d\n", RUNS);
    return 0;
}
