#pragma once
typedef struct { int num, den; } frac;
static int gcd_(int a, int b) { while (b) { int t = a % b; a = b; b = t; } return a < 0 ? -a : a; }
static frac frac_make(int n, int d) { int g = gcd_(n, d); frac f = {n / g, d / g}; if (f.den < 0) { f.num = -f.num; f.den = -f.den; } return f; }
static frac frac_add(frac a, frac b) { return frac_make(a.num * b.den + b.num * a.den, a.den * b.den); }
