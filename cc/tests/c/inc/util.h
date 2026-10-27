#ifndef UTIL_H
#define UTIL_H
#include "util_impl.h"
#define ARRAY_LEN(a) (sizeof(a) / sizeof((a)[0]))
static inline int clamp(int v, int lo, int hi) { return v < lo ? lo : v > hi ? hi : v; }
#endif
