/* CoreMark-style kernels (not the EEMBC source): linked-list find/reverse/merge-sort,
   integer matrix multiply/add/bit-extract, a string-scanning state machine, CRC-16 over all results. */
#include <stdio.h>
#include <stdint.h>
static uint16_t crcu8(uint8_t data, uint16_t crc) {
    for (int i = 0; i < 8; i++) {
        uint8_t x16 = (uint8_t)((data & 1) ^ ((uint8_t)crc & 1));
        data >>= 1;
        if (x16 == 1) { crc ^= 0x4002; crc = (uint16_t)((crc >> 1) | 0x8000); }
        else crc >>= 1;
    }
    return crc;
}
static uint16_t crc16(int16_t v, uint16_t crc) { crc = crcu8((uint8_t)v, crc); return crcu8((uint8_t)((uint16_t)v >> 8), crc); }

/* ---- list */
typedef struct node { struct node *next; int16_t data, idx; } node;
static node pool[64];
static node *list_init(int n, uint16_t seed) {
    node *head = 0;
    for (int i = n - 1; i >= 0; i--) {
        seed = (uint16_t)(seed * 25173u + 13849u);
        pool[i].data = (int16_t)(seed & 0x7fff); pool[i].idx = (int16_t)i; pool[i].next = head; head = &pool[i];
    }
    return head;
}
static node *list_reverse(node *l) { node *p = 0; while (l) { node *n = l->next; l->next = p; p = l; l = n; } return p; }
static node *list_find(node *l, int16_t idx) { while (l && l->idx != idx) l = l->next; return l; }
static node *list_sort(node *l, int by_data) {   /* merge sort */
    if (!l || !l->next) return l;
    node *slow = l, *fast = l->next;
    while (fast && fast->next) { slow = slow->next; fast = fast->next->next; }
    node *b = slow->next; slow->next = 0;
    node *a = list_sort(l, by_data); b = list_sort(b, by_data);
    node head, *t = &head;
    while (a && b) {
        int ka = by_data ? a->data : a->idx, kb = by_data ? b->data : b->idx;
        if (ka <= kb) { t->next = a; a = a->next; } else { t->next = b; b = b->next; }
        t = t->next;
    }
    t->next = a ? a : b;
    return head.next;
}
static uint16_t bench_list(uint16_t crc, uint16_t seed) {
    node *l = list_init(64, seed);
    for (int k = 0; k < 8; k++) {
        node *f = list_find(l, (int16_t)(k * 7 % 64));
        crc = crc16(f ? f->data : -1, crc);
        l = list_reverse(l);
    }
    l = list_sort(l, 1);
    for (node *p = l; p; p = p->next) crc = crc16(p->data, crc);
    l = list_sort(l, 0);
    crc = crc16(l->data, crc);
    return crc;
}
/* ---- matrix */
#define MN 10
static int16_t A[MN][MN], B[MN][MN];
static int32_t C[MN][MN];
static uint16_t bench_matrix(uint16_t crc, int16_t seed) {
    for (int i = 0; i < MN; i++) for (int j = 0; j < MN; j++) { A[i][j] = (int16_t)((seed * (i + 1) + j) & 0xff); B[i][j] = (int16_t)(((seed ^ j) * (j + 2) + i) & 0xff); }
    for (int i = 0; i < MN; i++) for (int j = 0; j < MN; j++) A[i][j] += 3;
    for (int i = 0; i < MN; i++) for (int j = 0; j < MN; j++) { int32_t s = 0; for (int k = 0; k < MN; k++) s += (int32_t)A[i][k] * B[k][j]; C[i][j] = s; }
    int32_t acc = 0;
    for (int i = 0; i < MN; i++) for (int j = 0; j < MN; j++) { acc += (C[i][j] >> 2) & 0xf; if (C[i][j] > 4000) acc += 7; }
    crc = crc16((int16_t)acc, crc);
    for (int i = 0; i < MN; i++) crc = crc16((int16_t)C[i][i], crc);
    return crc;
}
/* ---- state machine: classify comma-separated tokens */
enum { S_START, S_INT, S_FLOAT, S_EXP, S_SCI, S_INVALID };
static uint16_t bench_state(uint16_t crc) {
    static const char *input = "5012,1.25e3,-874,+122,7.3.5,0x1F,3.14159,1e10,abc,-.5,99,2e-3,";
    unsigned counts[6] = {0};
    for (int rep = 0; rep < 6; rep++) {
        const char *p = input; int st = S_START;
        while (*p) {
            char c = *p++;
            if (c == ',') { counts[st]++; st = S_START; continue; }
            switch (st) {
            case S_START: st = (c >= '0' && c <= '9') || c == '+' || c == '-' ? S_INT : c == '.' ? S_FLOAT : S_INVALID; break;
            case S_INT: if (c == '.') st = S_FLOAT; else if (c < '0' || c > '9') st = S_INVALID; break;
            case S_FLOAT: if (c == 'e' || c == 'E') st = S_EXP; else if (c < '0' || c > '9') st = S_INVALID; break;
            case S_EXP: st = (c >= '0' && c <= '9') || c == '+' || c == '-' ? S_SCI : S_INVALID; break;
            case S_SCI: if (c < '0' || c > '9') st = S_INVALID; break;
            default: break;
            }
        }
    }
    for (int i = 0; i < 6; i++) crc = crc16((int16_t)counts[i], crc);
    return crc;
}
int main(void) {
    uint16_t crc = 0;
    for (int it = 0; it < 4; it++) {
        crc = bench_list(crc, (uint16_t)(0x1234 + it));
        crc = bench_matrix(crc, (int16_t)(it + 1));
        crc = bench_state(crc);
    }
    printf("coremark-lite crc = 0x%04x\n", crc);
    return 0;
}
