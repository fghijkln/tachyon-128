#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define NB 31
struct ent { char *key; int val; struct ent *next; };
struct ent *tab[NB];
unsigned hash(const char *s) { unsigned h = 0; while (*s) h = h * 31 + (unsigned char)*s++; return h % NB; }
void put(const char *k, int v) {
    unsigned h = hash(k);
    for (struct ent *e = tab[h]; e; e = e->next) if (!strcmp(e->key, k)) { e->val = v; return; }
    struct ent *e = malloc(sizeof *e); e->key = strdup(k); e->val = v; e->next = tab[h]; tab[h] = e;
}
int get(const char *k) { for (struct ent *e = tab[hash(k)]; e; e = e->next) if (!strcmp(e->key, k)) return e->val; return -1; }
int main(void) {
    const char *words[] = {"alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa"};
    for (int i = 0; i < 10; i++) put(words[i], i * i);
    put("gamma", 1000);
    for (int i = 0; i < 10; i++) printf("%s=%d ", words[i], get(words[i]));
    printf("\n%d\n", get("omega"));
    char buf[16]; int tot = 0;
    for (int i = 0; i < 100; i++) { sprintf(buf, "k%d", i); put(buf, i); }
    for (int i = 0; i < 100; i += 7) { sprintf(buf, "k%d", i); tot += get(buf); }
    printf("%d\n", tot);
    return 0;
}
