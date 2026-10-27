/* tcc128 string and memory functions */
#include <stddef.h>

void *memcpy(void *d, const void *s, size_t n) {
    unsigned char *dp = d;
    const unsigned char *sp = s;
    if ((((unsigned long)(unsigned __int128)dp | (unsigned long)(unsigned __int128)sp) & 15) == 0) {
        while (n >= 16) {
            *(unsigned __int128 *)dp = *(const unsigned __int128 *)sp;
            dp += 16; sp += 16; n -= 16;
        }
    }
    while (n--) *dp++ = *sp++;
    return d;
}

void *memmove(void *d, const void *s, size_t n) {
    unsigned char *dp = d;
    const unsigned char *sp = s;
    if (dp == sp || n == 0) return d;
    if (dp < sp) { while (n--) *dp++ = *sp++; }
    else { dp += n; sp += n; while (n--) *--dp = *--sp; }
    return d;
}

void *memset(void *d, int c, size_t n) {
    unsigned char *p = d;
    if (((unsigned long)(unsigned __int128)p & 15) == 0 && n >= 16) {
        unsigned __int128 w = (unsigned char)c;
        w |= w << 8; w |= w << 16; w |= w << 32; w |= w << 64;
        while (n >= 16) { *(unsigned __int128 *)p = w; p += 16; n -= 16; }
    }
    while (n--) *p++ = (unsigned char)c;
    return d;
}

int memcmp(const void *a, const void *b, size_t n) {
    const unsigned char *p = a, *q = b;
    for (; n; n--, p++, q++)
        if (*p != *q) return *p - *q;
    return 0;
}

void *memchr(const void *s, int c, size_t n) {
    const unsigned char *p = s;
    for (; n; n--, p++)
        if (*p == (unsigned char)c) return (void *)p;
    return 0;
}

size_t strlen(const char *s) {
    const char *p = s;
    while (*p) p++;
    return p - s;
}

int strcmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}

int strncmp(const char *a, const char *b, size_t n) {
    for (; n; n--, a++, b++) {
        if (*a != *b) return (unsigned char)*a - (unsigned char)*b;
        if (!*a) return 0;
    }
    return 0;
}

char *strcpy(char *d, const char *s) {
    char *r = d;
    while ((*d++ = *s++)) ;
    return r;
}

char *strncpy(char *d, const char *s, size_t n) {
    char *r = d;
    for (; n && *s; n--) *d++ = *s++;
    for (; n; n--) *d++ = 0;
    return r;
}

char *strcat(char *d, const char *s) {
    char *r = d;
    while (*d) d++;
    while ((*d++ = *s++)) ;
    return r;
}

char *strncat(char *d, const char *s, size_t n) {
    char *r = d;
    while (*d) d++;
    while (n-- && *s) *d++ = *s++;
    *d = 0;
    return r;
}

char *strchr(const char *s, int c) {
    for (;; s++) {
        if (*s == (char)c) return (char *)s;
        if (!*s) return 0;
    }
}

char *strrchr(const char *s, int c) {
    const char *r = 0;
    for (;; s++) {
        if (*s == (char)c) r = s;
        if (!*s) return (char *)r;
    }
}

char *strstr(const char *h, const char *n) {
    if (!*n) return (char *)h;
    for (; *h; h++) {
        const char *a = h, *b = n;
        while (*a && *b && *a == *b) { a++; b++; }
        if (!*b) return (char *)h;
    }
    return 0;
}

size_t strspn(const char *s, const char *a) {
    size_t n = 0;
    for (; s[n]; n++) {
        const char *p = a;
        while (*p && *p != s[n]) p++;
        if (!*p) break;
    }
    return n;
}

size_t strcspn(const char *s, const char *r) {
    size_t n = 0;
    for (; s[n]; n++) {
        const char *p = r;
        while (*p && *p != s[n]) p++;
        if (*p) break;
    }
    return n;
}

int isdigit(int c) { return c >= '0' && c <= '9'; }
int isalpha(int c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
int isalnum(int c) { return isdigit(c) || isalpha(c); }
int isspace(int c) { return c == ' ' || (c >= 9 && c <= 13); }
int isupper(int c) { return c >= 'A' && c <= 'Z'; }
int islower(int c) { return c >= 'a' && c <= 'z'; }
int isxdigit(int c) { return isdigit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'); }
int isprint(int c) { return c >= 32 && c < 127; }
int ispunct(int c) { return isprint(c) && !isalnum(c) && c != ' '; }
int toupper(int c) { return islower(c) ? c - 32 : c; }
int tolower(int c) { return isupper(c) ? c + 32 : c; }
