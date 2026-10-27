#include <stdio.h>
enum tok { NUM, PLUS, MINUS, MUL, LP, RP, END };
const char *src; int val;
enum tok next(void) {
    while (*src == ' ') src++;
    switch (*src) {
    case 0: return END;
    case '+': src++; return PLUS;
    case '-': src++; return MINUS;
    case '*': src++; return MUL;
    case '(': src++; return LP;
    case ')': src++; return RP;
    default: val = 0; while (*src >= '0' && *src <= '9') val = val * 10 + *src++ - '0'; return NUM;
    }
}
enum tok cur;
int expr(void);
int atom(void) { if (cur == LP) { cur = next(); int v = expr(); cur = next(); return v; } if (cur == MINUS) { cur = next(); return -atom(); } int v = val; cur = next(); return v; }
int term(void) { int v = atom(); while (cur == MUL) { cur = next(); v *= atom(); } return v; }
int expr(void) { int v = term(); while (cur == PLUS || cur == MINUS) { enum tok o = cur; cur = next(); int r = term(); v = o == PLUS ? v + r : v - r; } return v; }
int eval(const char *s) { src = s; cur = next(); return expr(); }
int main(void) {
    printf("%d\n", eval("1 + 2 * 3"));
    printf("%d\n", eval("(1 + 2) * 3 - -4"));
    printf("%d\n", eval("2 * (3 + 4) * (5 - 6 * 7)"));
    return 0;
}
