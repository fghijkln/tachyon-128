/* malloc_churn: allocator-heavy benchmark (v6, measures the cost of -mpurecap temporal safety:
   free() quarantine + revocation bitmap + revocation sweeps, against -fno-revoke).
   Three phases: LIFO linked lists, a binary search tree built and torn down, and a pool of 32 slots
   replaced at random with blocks of random size (non-LIFO, fragmenting). Footprint is kept small so the
   default-mode bump allocator (which only reclaims the most recent block) also fits. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

struct node { struct node *next; long v; char pad[32]; };
struct tree { struct tree *l, *r; long k; };

static unsigned seed = 2026;
static unsigned rnd(void) { seed = seed * 1103515245u + 12345u; return seed >> 8; }

static struct tree *insert(struct tree *t, long k) {
    if (!t) {
        t = malloc(sizeof *t);
        t->l = t->r = 0;
        t->k = k;
        return t;
    }
    if (k < t->k) t->l = insert(t->l, k);
    else t->r = insert(t->r, k);
    return t;
}
static long sum_tree(struct tree *t) { return t ? t->k + sum_tree(t->l) + sum_tree(t->r) : 0; }
static void free_tree(struct tree *t) {
    if (!t) return;
    free_tree(t->l);
    free_tree(t->r);
    free(t);
}

int main(void) {
    unsigned long check = 0;
    /* phase 1: LIFO lists */
    for (int round = 0; round < 40; round++) {
        struct node *head = 0;
        for (int i = 0; i < 32; i++) {
            struct node *n = malloc(sizeof *n);
            n->v = round * 37 + i;
            n->next = head;
            head = n;
        }
        for (struct node *n = head; n; n = n->next) check += n->v;
        while (head) {
            struct node *nx = head->next;
            free(head);
            head = nx;
        }
    }
    /* phase 2: a tree of 200 keys */
    struct tree *t = 0;
    for (int i = 0; i < 200; i++) t = insert(t, rnd() % 10000);
    check += sum_tree(t);
    free_tree(t);
    /* phase 3: random replacement in a 32-slot pool */
    char *slot[32];
    int len[32];
    for (int i = 0; i < 32; i++) { len[i] = 16; slot[i] = malloc(16); memset(slot[i], i, 16); }
    for (int it = 0; it < 500; it++) {
        int s = rnd() % 32;
        check += (unsigned char)slot[s][len[s] - 1];
        free(slot[s]);
        len[s] = 16 + rnd() % 96;
        slot[s] = malloc(len[s]);
        memset(slot[s], it & 0xFF, len[s]);
    }
    for (int i = 0; i < 32; i++) free(slot[i]);
    printf("malloc_churn check %lu\n", check);
    return check == 0;
}
