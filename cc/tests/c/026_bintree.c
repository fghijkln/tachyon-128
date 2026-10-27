#include <stdio.h>
#include <stdlib.h>
typedef struct tree { int key; struct tree *l, *r; } tree;
tree *insert(tree *t, int k) {
    if (!t) { t = malloc(sizeof(tree)); t->key = k; t->l = t->r = NULL; return t; }
    if (k < t->key) t->l = insert(t->l, k); else if (k > t->key) t->r = insert(t->r, k);
    return t;
}
int height(tree *t) { if (!t) return 0; int a = height(t->l), b = height(t->r); return 1 + (a > b ? a : b); }
void inorder(tree *t) { if (!t) return; inorder(t->l); printf("%d ", t->key); inorder(t->r); }
int count(tree *t) { return t ? 1 + count(t->l) + count(t->r) : 0; }
int main(void) {
    tree *t = NULL; unsigned s = 7;
    for (int i = 0; i < 60; i++) { s = s * 69069u + 1u; t = insert(t, (int)(s >> 20) % 200); }
    inorder(t); printf("\n%d %d\n", count(t), height(t));
    return 0;
}
