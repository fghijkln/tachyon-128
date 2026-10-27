#ifndef _TX128_H
#define _TX128_H
/* TACHYON-128 machine access (MMIO page at the top of the 128-bit address space, SPEC.md section 7) */
#define TX_MMIO_BASE   (~(unsigned __int128)0 - 0xFFFF)
#define TX_CONSOLE     ((volatile unsigned char *)(TX_MMIO_BASE + 0x00))
#define TX_EXIT        ((volatile unsigned int *)(TX_MMIO_BASE + 0x10))
#define TX_HEXOUT      ((volatile unsigned __int128 *)(TX_MMIO_BASE + 0x20))
#define TX_MTIME       ((volatile unsigned __int128 *)(TX_MMIO_BASE + 0x30))
/* instructions retired so far (deterministic time base) */
static unsigned long tx_instret(void) { return (unsigned long)*TX_MTIME; }
static void tx_hexout(unsigned __int128 v) { *TX_HEXOUT = v; }
void tx_put_u128(unsigned __int128 v);
void tx_put_i128(__int128 v);
#endif
