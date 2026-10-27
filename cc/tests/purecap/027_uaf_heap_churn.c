/* no fault: a heap-heavy program (linked lists and a tree built, mutated and freed many times) runs
   correctly with quarantine + revocation sweeps; live pointers survive every sweep with their tags */
#include <stdio.h>
#include <stdlib.h>

unsigned long __tx_revoke_sweeps(void);

struct node { struct node *next; long v; char pad[40]; };
struct tree { struct tree *l, *r; long k; };

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
    struct tree *keep = 0;                /* long-lived structure, must survive all sweeps */
    unsigned x = 12345;
    for (int i = 0; i < 64; i++) {
        x = x * 1103515245u + 12345u;
        keep = insert(keep, (x >> 8) % 1000);
    }
    long total = 0;
    for (int round = 0; round < 30; round++) {
        struct node *head = 0;
        for (int i = 0; i < 40; i++) {
            struct node *n = malloc(sizeof *n);
            n->v = round * 100 + i;
            n->next = head;
            head = n;
        }
        for (struct node *n = head; n; n = n->next) total += n->v;
        while (head) {
            struct node *nx = head->next;
            free(head);
            head = nx;
        }
        char *s = malloc(100 + round * 10);
        for (int i = 0; i < 100 + round * 10; i++) s[i] = (char)i;
        s = realloc(s, 300 + round * 20);
        total += s[50];
        free(s);
    }
    printf("total %ld\n", total);
    printf("tree sum %ld\n", sum_tree(keep));
    printf("swept: %s\n", __tx_revoke_sweeps() > 0 ? "yes" : "no");
    free_tree(keep);
    return 0;
}
