#ifndef _STDLIB_H
#define _STDLIB_H
#include <stddef.h>
#define EXIT_SUCCESS 0
#define EXIT_FAILURE 1
#define RAND_MAX 2147483647
void *malloc(size_t n);
void *calloc(size_t n, size_t m);
void *realloc(void *p, size_t n);
void free(void *p);
void exit(int code);
void abort(void);
int atoi(const char *s);
long atol(const char *s);
long strtol(const char *s, char **end, int base);
unsigned long strtoul(const char *s, char **end, int base);
int abs(int x);
long labs(long x);
long long llabs(long long x);
int rand(void);
void srand(unsigned seed);
void qsort(void *base, size_t n, size_t sz, int (*cmp)(const void *, const void *));
void *bsearch(const void *key, const void *base, size_t n, size_t sz, int (*cmp)(const void *, const void *));
#endif
