#include <stdio.h>
void bubble(int *a, int n) { for (int i = 0; i < n; i++) for (int j = 0; j + 1 < n - i; j++) if (a[j] > a[j + 1]) { int t = a[j]; a[j] = a[j + 1]; a[j + 1] = t; } }
void insertion(short *a, int n) { for (int i = 1; i < n; i++) { short v = a[i]; int j = i - 1; while (j >= 0 && a[j] > v) { a[j + 1] = a[j]; j--; } a[j + 1] = v; } }
void selection(unsigned char *a, int n) { for (int i = 0; i < n; i++) { int m = i; for (int j = i + 1; j < n; j++) if (a[j] < a[m]) m = j; unsigned char t = a[i]; a[i] = a[m]; a[m] = t; } }
int main(void) {
    int a[20]; short b[20]; unsigned char c[20];
    for (int i = 0; i < 20; i++) { a[i] = (i * 7919) % 31 - 15; b[i] = (short)(i * -3001); c[i] = (unsigned char)(i * 37); }
    bubble(a, 20); insertion(b, 20); selection(c, 20);
    for (int i = 0; i < 20; i++) printf("%d ", a[i]); printf("\n");
    for (int i = 0; i < 20; i++) printf("%d ", b[i]); printf("\n");
    for (int i = 0; i < 20; i++) printf("%d ", c[i]); printf("\n");
    return 0;
}
