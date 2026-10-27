/* tcc128 stdlib: bump-pointer heap, conversions, qsort, glibc-compatible rand() */
#include <stddef.h>
#include <string.h>

extern char _end[];           /* end of the program image (emitted by the tcc128 linker) */
static char *heap_cur;
#ifdef __PURECAP__
#define STACK_RESERVE 0x20000  /* purecap: the stack capability covers exactly [RAM_TOP - 128 KiB, RAM_TOP) */
#else
#define STACK_RESERVE 0x4000   /* keep 16 KiB below the initial stack pointer free */
#endif
#define RAM_TOP 0x40000

/* purecap: heap_cur is an unbounded RAM capability (from _end); malloc returns a capability bounded
   to exactly the requested size, so free/realloc re-derive the header address from heap_cur. */
static char *hdr_of(void *p) {
    return (char *)__builtin_cheri_address_set(heap_cur, (unsigned __int128)p) - 16;
}

void *malloc(size_t n) {
    if (!heap_cur) heap_cur = _end;
    size_t want = n;
    n = (n + 15) & ~(size_t)15;
    char *p = heap_cur;
    if ((unsigned long)(unsigned __int128)(p + 16 + n) > RAM_TOP - STACK_RESERVE) return 0;
    *(size_t *)p = n;          /* 16-byte header keeps the size for realloc */
    heap_cur = p + 16 + n;
    return __builtin_cheri_bounds_set(p + 16, want);
}

void free(void *p) {
    /* bump allocator: only the most recent block is actually released */
    if (p) {
        char *h = hdr_of(p);
        if (h + 16 + *(size_t *)h == heap_cur) heap_cur = h;
    }
}

void *calloc(size_t n, size_t m) {
    void *p = malloc(n * m);
    if (p) memset(p, 0, n * m);
    return p;
}

void *realloc(void *p, size_t n) {
    if (!p) return malloc(n);
    size_t old = *(size_t *)hdr_of(p);
    if (n <= old) return __builtin_cheri_bounds_set(hdr_of(p) + 16, n);
    void *q = malloc(n);
    if (q) memcpy(q, hdr_of(p) + 16, old);    /* p itself may be bounded below old */
    return q;
}

int abs(int x) { return x < 0 ? -x : x; }
long labs(long x) { return x < 0 ? -x : x; }
long long llabs(long long x) { return x < 0 ? -x : x; }

unsigned long strtoul(const char *s, char **end, int base) {
    unsigned long v = 0;
    while (*s == ' ' || (*s >= 9 && *s <= 13)) s++;
    int neg = 0;
    if (*s == '+' || *s == '-') neg = *s++ == '-';
    if ((base == 0 || base == 16) && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) { s += 2; base = 16; }
    else if (base == 0 && s[0] == '0') base = 8;
    else if (base == 0) base = 10;
    for (;; s++) {
        int d;
        if (*s >= '0' && *s <= '9') d = *s - '0';
        else if (*s >= 'a' && *s <= 'z') d = *s - 'a' + 10;
        else if (*s >= 'A' && *s <= 'Z') d = *s - 'A' + 10;
        else break;
        if (d >= base) break;
        v = v * base + d;
    }
    if (end) *end = (char *)s;
    return neg ? -v : v;
}

long strtol(const char *s, char **end, int base) { return (long)strtoul(s, end, base); }
int atoi(const char *s) { return (int)strtol(s, 0, 10); }
long atol(const char *s) { return strtol(s, 0, 10); }

/* glibc TYPE_3 additive feedback generator, so rand() sequences match a glibc host */
static int r_tab[34];
static unsigned int r_state[31];
static int r_f, r_r, r_init;

void srand(unsigned seed) {
    int i;
    if (seed == 0) seed = 1;
    r_tab[0] = (int)seed;
    for (i = 1; i < 31; i++) {
        long hi = r_tab[i - 1] / 127773, lo = r_tab[i - 1] % 127773;
        long w = 16807 * lo - 2836 * hi;
        if (w < 0) w += 2147483647;
        r_tab[i] = (int)w;
    }
    for (i = 0; i < 31; i++) r_state[i] = (unsigned)r_tab[i];
    r_f = 3; r_r = 0;
    r_init = 1;
    for (i = 0; i < 310; i++) {
        r_state[r_f] += r_state[r_r];
        if (++r_f >= 31) r_f = 0;
        if (++r_r >= 31) r_r = 0;
    }
}

int rand(void) {
    if (!r_init) srand(1);
    unsigned int v = r_state[r_f] += r_state[r_r];
    if (++r_f >= 31) r_f = 0;
    if (++r_r >= 31) r_r = 0;
    return (int)(v >> 1);
}

static void swap_bytes(char *a, char *b, size_t n) {
    if ((((unsigned long)(unsigned __int128)a | (unsigned long)(unsigned __int128)b | n) & 15) == 0) {
        /* whole 16-byte words (in purecap these moves keep capability tags) */
        for (; n; n -= 16, a += 16, b += 16) {
            unsigned __int128 t = *(unsigned __int128 *)a;
            *(unsigned __int128 *)a = *(unsigned __int128 *)b;
            *(unsigned __int128 *)b = t;
        }
        return;
    }
    while (n--) { char t = *a; *a++ = *b; *b++ = t; }
}

static void qsort_r(char *base, size_t n, size_t sz, int (*cmp)(const void *, const void *)) {
    while (n > 1) {
        if (n < 8) {
            for (size_t i = 1; i < n; i++)
                for (size_t j = i; j > 0 && cmp(base + (j - 1) * sz, base + j * sz) > 0; j--)
                    swap_bytes(base + (j - 1) * sz, base + j * sz, sz);
            return;
        }
        swap_bytes(base, base + (n / 2) * sz, sz);   /* middle element as pivot */
        size_t last = 0;
        for (size_t i = 1; i < n; i++)
            if (cmp(base + i * sz, base) < 0) swap_bytes(base + ++last * sz, base + i * sz, sz);
        swap_bytes(base, base + last * sz, sz);
        /* recurse into the smaller half, loop on the larger */
        if (last < n - last - 1) {
            qsort_r(base, last, sz, cmp);
            base += (last + 1) * sz;
            n -= last + 1;
        } else {
            qsort_r(base + (last + 1) * sz, n - last - 1, sz, cmp);
            n = last;
        }
    }
}

void qsort(void *base, size_t n, size_t sz, int (*cmp)(const void *, const void *)) {
    qsort_r(base, n, sz, cmp);
}

void *bsearch(const void *key, const void *base, size_t n, size_t sz, int (*cmp)(const void *, const void *)) {
    const char *b = base;
    while (n) {
        const char *m = b + (n / 2) * sz;
        int c = cmp(key, m);
        if (c == 0) return (void *)m;
        if (c > 0) { b = m + sz; n -= n / 2 + 1; }
        else n /= 2;
    }
    return 0;
}

char *strdup(const char *s) {
    size_t n = strlen(s) + 1;
    char *p = malloc(n);
    if (p) memcpy(p, s, n);
    return p;
}
