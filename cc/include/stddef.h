#ifndef _STDDEF_H
#define _STDDEF_H
typedef unsigned long size_t;
typedef long ptrdiff_t;
typedef long ssize_t;
typedef int wchar_t;
#define NULL ((void *)0)
#define offsetof(T, m) ((size_t)&((T *)0)->m)
#endif
