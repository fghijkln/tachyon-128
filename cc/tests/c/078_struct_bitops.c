#include <stdio.h>
#include <stdint.h>
typedef struct { uint32_t h[4]; } state;
static uint32_t rotl(uint32_t x, int k) { return (x << k) | (x >> (32 - k)); }
static void mix(state *s, uint32_t w) {
    s->h[0] += w; s->h[1] ^= rotl(s->h[0], 7); s->h[2] += s->h[1] * 0x9E3779B9u; s->h[3] = rotl(s->h[3] ^ s->h[2], 13) + 0x7F4A7C15u;
    uint32_t t = s->h[0]; s->h[0] = s->h[3]; s->h[3] = s->h[2]; s->h[2] = s->h[1]; s->h[1] = t;
}
uint64_t splitmix(uint64_t *x) { uint64_t z = (*x += 0x9E3779B97F4A7C15ULL); z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL; z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL; return z ^ (z >> 31); }
int main(void) {
    state s = {{1, 2, 3, 4}};
    for (uint32_t i = 0; i < 1000; i++) mix(&s, i * i);
    printf("%08x %08x %08x %08x\n", s.h[0], s.h[1], s.h[2], s.h[3]);
    uint64_t seed = 42; for (int i = 0; i < 3; i++) printf("%016llx\n", (unsigned long long)splitmix(&seed));
    int8_t a = -128; uint8_t b = 255; int16_t c = -1; uint16_t d = 65535; int64_t e = INT64_MIN;
    printf("%d %d %d %d %lld\n", a, b, c, d, (long long)e);
    return 0;
}
