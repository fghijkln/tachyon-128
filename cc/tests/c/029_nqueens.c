#include <stdio.h>
int n, cnt, cols[16];
int ok(int r, int c) { for (int i = 0; i < r; i++) { int d = cols[i] - c; if (d == 0 || d == r - i || d == i - r) return 0; } return 1; }
void solve(int r) { if (r == n) { cnt++; return; } for (int c = 0; c < n; c++) if (ok(r, c)) { cols[r] = c; solve(r + 1); } }
int main(void) { for (n = 1; n <= 7; n++) { cnt = 0; solve(0); printf("%d:%d ", n, cnt); } printf("\n"); return 0; }
