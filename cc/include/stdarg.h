#ifndef _STDARG_H
#define _STDARG_H
/* every argument occupies one 16-byte slot (see cc/ABI.md) */
typedef __builtin_va_list va_list;
#define va_start(ap, last) __builtin_va_start(ap, last)
#define va_arg(ap, T) __builtin_va_arg(ap, T)
#define va_end(ap) __builtin_va_end(ap)
#define va_copy(d, s) __builtin_va_copy(d, s)
#endif
