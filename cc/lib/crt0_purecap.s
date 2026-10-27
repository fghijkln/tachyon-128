# tcc128 start-up code for -mpurecap (see cc/ABI.md section 8)
#   gp = RAM capability [0, 256 KiB), no EXEC/SEAL/UNSEAL/CINVOKE: every data pointer descends from it
#   sp = gp with cursor at the top of RAM (stack objects get their own bounds when their address is taken)
#   __cap_relocs: initialised pointer slots in static data are rebuilt as bounded capabilities
#   user mode with ubase = ubound = 0: untagged (integer-address) accesses trap with cause 9
#   ___tx_mmio = capability for the MMIO page (console, exit, hexout, mtime)
#   tvec = __tx_trap: a capability (or any other) fault prints its cause and tval and exits 128 + cause
        .org 0
_start: li   t0, 0x40000
        csetbnd gp, rc, t0        # rc's cursor is 0 at reset
        li   t1, 0x59B            # PERM_ALL & ~(EXEC | SEAL | UNSEAL | PERMIT_CINVOKE)
        candperm gp, gp, t1
        csetaddr sp, gp, t0
        la   t2, __tx_trap
        csrw tvec, t2
        la   t0, __cap_relocs
        la   t1, __cap_relocs_end
        csetaddr t0, gp, t0       # the table itself is read through the RAM capability
__crl:  bgeu t0, t1, __crd
        lq   t2, 0(t0)            # slot address
        lq   t3, 16(t0)           # target address
        lq   t4, 32(t0)           # target size (0 = unknown, -1 = function)
        lq   t5, 48(t0)           # addend
        addi t6, zero, -1
        bne  t4, t6, __crdata
        cgetpcc t7
        csetaddr t7, t7, t3
        j    __crset
__crdata:
        csetaddr t7, gp, t3
        beqz t4, __crset
        csetbnd t7, t7, t4
__crset:
        cincaddr t7, t7, t5
        csetaddr t8, gp, t2
        csc  t7, 0(t8)
        cincaddri t0, t0, 64
        j    __crl
__crd:  li   t0, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000
        csetaddr t1, rc, t0       # MMIO capability: the 64 KiB device page, LOAD | STORE | LOAD_CAP | STORE_CAP | GLOBAL (16-byte accesses are clc/csc in purecap)
        li   t2, 0x10000
        csetbnd t1, t1, t2
        li   t2, 0x9B
        candperm t1, t1, t2
        la   t0, ___tx_mmio
        csetaddr t0, gp, t0
        csc  t1, 0(t0)
        # enter user mode with an empty untagged window (ubase = ubound = 0): from here on every load or store
        # through an untagged (integer) base traps (cause 9), so the program can only touch memory through
        # capabilities. PCC = code capability [0, __end), EXEC | LOAD | LOAD_CAP | GLOBAL.
        csrw ubase, zero
        csrw ubound, zero
        cgetpcc t1
        csetaddr t1, t1, zero
        la   t2, __end
        csetbnd t1, t1, t2
        li   t2, 0x8D
        candperm t1, t1, t2
        csetepcc t1
        la   t0, __crt_user
        csrw epc, t0
        li   t0, 0x10             # status.PU: eret enters user mode (interrupts stay off)
        csrw status, t0
        eret
__crt_user:
        mv   a0, zero             # argc = 0
        mv   a1, zero             # argv = NULL
        call _main
        call _exit                # exit(main's return value) via the MMIO capability; never returns
__crt_spin:
        j    __crt_spin

__tx_trap:
        la   t0, __tx_trap_msg
        csetaddr t0, gp, t0
        li   t1, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000     # MMIO console
__ttl:  lbu  t2, 0(t0)
        beqz t2, __ttd
        sb   t2, 0(t1)
        cincaddri t0, t0, 1
        j    __ttl
__ttd:  csrr t3, cause
        addi t4, t3, 48           # cause is 1..9: one decimal digit
        sb   t4, 0(t1)
        addi t4, zero, 32
        sb   t4, 0(t1)
        csrr t5, tval
        sq   t5, 32(t1)           # MMIO hex output: tval as 32 hex digits + newline
        addi t3, t3, 128
        sq   t3, 16(t1)           # MMIO exit: 128 + cause
        halt t3
__tx_trap_msg:
        .asciz "\n*** capability trap (hardware): cause="
        .align 4
        .align 16
___tx_mmio:                        # the MMIO capability (C name __tx_mmio, see cc/include/tx128.h)
        .quad 0
