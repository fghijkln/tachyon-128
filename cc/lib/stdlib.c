/* tcc128 stdlib: bump-pointer heap, conversions, qsort, glibc-compatible rand() */
#include <stddef.h>
#include <string.h>
int printf(const char *, ...);
void abort(void);

extern char _end[];           /* end of the program image (emitted by the tcc128 linker) */
#ifdef __PURECAP__
#define STACK_RESERVE 0x20000  /* purecap: the stack capability covers exactly [RAM_TOP - 128 KiB, RAM_TOP) */
#else
#define STACK_RESERVE 0x4000   /* keep 16 KiB below the initial stack pointer free */
#endif
#define RAM_TOP 0x40000

#ifdef __PURECAP__
/* ---------------------------------------------------------------------------------------------------
   purecap heap with temporal safety (v6, cc/ABI.md section 8.2)

   Every block is a 16-byte header {size, state} followed by the payload; malloc returns a capability
   bounded to exactly the requested size, so user code can never reach a header (metadata protection by
   bounds). All allocator accesses go through heap_cap, a RAM capability whose base (0) is never revoked.

   free(p):  * probes p with a load: a stale, already-swept pointer is untagged (user mode -> cause 9) and a
               freed-but-not-yet-swept one is revoked (cause 10), so use after free and double free trap
               in hardware before the allocator looks at anything;
             * checks that p is exactly a live block (capability base == address, header magic, length) and
               aborts on an interior or foreign pointer;
             * marks the payload granules in the hardware revocation bitmap (from now on every access through
               any copy of p, in a register or in memory, traps with cause 10; copies still load tagged but
               are unusable) and puts the block in quarantine; nothing in quarantine is ever reused.
   When the quarantine reaches max(REV_QUARANTINE_MIN, heap/4) (or malloc runs out of memory) a revocation
   sweep runs: __tx_revoke_sweep (crt0_purecap.s) uses cloadtags to visit every tagged granule of the
   memory that can hold capabilities - the image and the heap [0, heap_top) and the stack region
   [RAM_TOP - 128 KiB, RAM_TOP) (the gap between them has never been written) - and rewrites each through
   crevtag (so capabilities into revoked memory lose their tag), then passes the callee-saved registers
   through crevtag. Only then are the quarantined blocks'
   bitmap bits cleared and the blocks moved to the free lists: a block is reused only after no capability to
   it survives anywhere (CHERIvoke / Cornucopia-style revocation with a CHERIoT-style load filter).

   -fno-revoke / TCC128_NO_REVOKE=1 (defines __TX_NO_REVOKE): same allocator without the probe, bitmap,
   quarantine and sweeps (freed blocks are reused at once) - the baseline for measuring the overhead.
   --------------------------------------------------------------------------------------------------- */
#ifndef REV_QUARANTINE_MIN
#define REV_QUARANTINE_MIN 16384     /* bytes; quarantine also grows with the heap (heap / 4) */
#endif
#define NBINS 64                       /* exact-size free lists for payloads of 16 .. 1024 bytes */
#define ST_LIVE 0x4C495645ul           /* header state words */
#define ST_QUAR 0x51554152ul
#define ST_FREE 0x46524545ul
extern volatile unsigned char *__tx_revmap;       /* crt0: capability for the revocation bitmap (MMIO) */
void __tx_revoke_sweep(unsigned long lo, unsigned long hi, unsigned long lo2, unsigned long hi2);
                                       /* crt0: sweep [lo, hi), [lo2, hi2) and the registers */
static char *heap_cap;                 /* allocator authority over RAM (base 0) */
static unsigned long heap_lo, heap_top; /* heap = [heap_lo, heap_top), grows up from _end */
static unsigned long bins[NBINS + 1];  /* header addresses; bins[0] = larger blocks, first fit */
static unsigned long quar_head, quar_bytes;
static unsigned long n_sweeps, n_freed;

static size_t *H(unsigned long a) { return (size_t *)__builtin_cheri_address_set(heap_cap, a); }
static unsigned long *L(unsigned long a) { return (unsigned long *)__builtin_cheri_address_set(heap_cap, a); }

static void heap_init(void) {
    heap_cap = _end;
    heap_lo = heap_top = (unsigned long)(unsigned __int128)_end;
}

static void bad_free(const char *what) {
    printf("*** %s(): invalid pointer\n", what);
    abort();
}
static volatile char probe_sink;

static void bin_push(unsigned long h, size_t sz) {
    int b = sz <= NBINS * 16 ? (int)(sz >> 4) : 0;
    H(h)[1] = ST_FREE;
    *L(h + 16) = bins[b];
    bins[b] = h;
}

static unsigned long bin_pop(size_t sz) {
    if (sz <= NBINS * 16) {
        unsigned long h = bins[sz >> 4];
        if (h) bins[sz >> 4] = *L(h + 16);
        return h;
    }
    unsigned long *link = &bins[0];
    for (unsigned long h = *link; h; h = *link) {
        size_t have = H(h)[0];
        if (have >= sz) {
            *link = *L(h + 16);
            if (have - sz >= 48) {               /* split: the tail becomes a free block of its own */
                unsigned long t = h + 16 + sz;
                H(t)[0] = have - sz - 16;
                bin_push(t, have - sz - 16);
                H(h)[0] = sz;
            }
            return h;
        }
        link = L(h + 16);
    }
    return 0;
}

#ifndef __TX_NO_REVOKE
/* mark the granules of [a, a + n) revoked, one 128-bit bitmap word (128 granules = 2 KiB) at a time */
static void rev_mark(unsigned long a, unsigned long n) {
    unsigned long g = a >> 4, e = (a + n) >> 4;
    while (g < e) {
        unsigned long b = g & 127, cnt = e - g;
        if (cnt > 128 - b) cnt = 128 - b;
        unsigned __int128 m = cnt == 128 ? ~(unsigned __int128)0 : (((unsigned __int128)1 << cnt) - 1) << b;
        volatile unsigned __int128 *w = (volatile unsigned __int128 *)(__tx_revmap + (g >> 7) * 16);
        *w = *w | m;
        g += cnt;
    }
}

static void revoke(void) {
    /* no capability into a quarantined block survives this */
    __tx_revoke_sweep(0, (heap_top + 255) & ~255ul, RAM_TOP - STACK_RESERVE, RAM_TOP);
    /* every marked granule belongs to a quarantined block, so the bitmap words covering the heap are
       simply zeroed (128 granules per 16-byte word) */
    for (unsigned long w = heap_lo >> 11; w <= (heap_top - 1) >> 11; w++)
        *(volatile unsigned __int128 *)(__tx_revmap + w * 16) = 0;
    for (unsigned long q = quar_head; q;) {
        unsigned long nx = *L(q + 16);
        bin_push(q, H(q)[0]);
        q = nx;
    }
    quar_head = quar_bytes = 0;
    n_sweeps++;
}
#endif

/* statistics for tests and benchmarks: number of revocation sweeps, number of blocks freed */
unsigned long __tx_revoke_sweeps(void) { return n_sweeps; }
unsigned long __tx_heap_frees(void) { return n_freed; }

void *malloc(size_t n) {
    if (!heap_cap) heap_init();
    size_t want = n ? n : 1;                 /* malloc(0): a unique 1-byte block (free can probe it) */
    if (want > RAM_TOP) return 0;
    size_t sz = (want + 15) & ~(size_t)15;
    unsigned long h = bin_pop(sz);
    if (!h) {
        if (heap_top + 16 + sz <= RAM_TOP - STACK_RESERVE) {
            h = heap_top;
            heap_top += 16 + sz;
            H(h)[0] = sz;
        } else {
#ifndef __TX_NO_REVOKE
            if (quar_head) {
                revoke();
                h = bin_pop(sz);
            }
#endif
            if (!h) return 0;
        }
    }
    H(h)[1] = ST_LIVE;
    return __builtin_cheri_bounds_set(__builtin_cheri_address_set(heap_cap, h + 16), want);
}

/* validate a pointer handed to free/realloc; returns its header address */
static unsigned long live_block(void *p, const char *what) {
#ifndef __TX_NO_REVOKE
    probe_sink = *(volatile char *)p;        /* hardware check: stale (untagged) -> cause 9, freed (revoked) -> cause 10 */
#endif
    unsigned long a = (unsigned long)(unsigned __int128)p;
    if (!__builtin_cheri_tag_get(p) || (unsigned long)__builtin_cheri_base_get(p) != a || (a & 15)
            || a < heap_lo + 16 || a >= heap_top)
        bad_free(what);
    unsigned long h = a - 16;
    if (H(h)[1] != ST_LIVE || __builtin_cheri_length_get(p) > H(h)[0]) bad_free(what);
    return h;
}

void free(void *p) {
    if (!p) return;
    unsigned long h = live_block(p, "free");
    size_t sz = H(h)[0];
    n_freed++;
#ifdef __TX_NO_REVOKE
    bin_push(h, sz);
#else
    H(h)[1] = ST_QUAR;
    rev_mark(h + 16, sz);                 /* every copy of p is dead from here on */
    *L(h + 16) = quar_head;
    quar_head = h;
    quar_bytes += sz + 16;
    if (quar_bytes >= REV_QUARANTINE_MIN && quar_bytes * 4 >= heap_top - heap_lo) revoke();
#endif
}

void *calloc(size_t n, size_t m) {
    void *p = malloc(n * m);
    if (p) memset(p, 0, n * m);
    return p;
}

void *realloc(void *p, size_t n) {
    if (!p) return malloc(n);
    unsigned long h = live_block(p, "realloc");
    size_t old = H(h)[0], want = n ? n : 1;
    if (want <= old) return __builtin_cheri_bounds_set(__builtin_cheri_address_set(heap_cap, h + 16), want);
    void *q = malloc(n);
    if (q) {
        memcpy(q, __builtin_cheri_address_set(heap_cap, h + 16), old);
        free(p);                             /* the old block is quarantined: stale copies of p now trap */
    }
    return q;
}

#else  /* default (hybrid) mode: bump allocator */
static char *heap_cur;

static char *hdr_of(void *p) {
    return (char *)p - 16;
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
    if (q) memcpy(q, hdr_of(p) + 16, old);
    return q;
}
#endif

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
