# tcc128 start-up code for -mpurecap (see cc/ABI.md section 8)
#   gp = RAM capability [0, 256 KiB), no EXEC/SEAL/UNSEAL/CINVOKE: every data pointer descends from it
#   sp = stack capability [RAM_TOP - 128 KiB, RAM_TOP) with cursor at the top (stack objects get their own bounds when their address is taken)
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
# >>stack (removed by the linker under -fno-stack-bounds)
        li   t1, 0x20000          # stack capability = [RAM_TOP - 128 KiB, RAM_TOP): a stack overflow
        csetaddr sp, gp, t1       # traps (cause 3) instead of running into the heap or globals, and no
        li   t2, 0x20000          # stack-derived pointer can reach memory outside the stack
        csetbnd sp, sp, t2
        csetaddr sp, sp, t0
# <<stack
        la   t2, __tx_trap
        csrw tvec, t2
        cgetpcc t9                # code capability [0, __end), EXEC | LOAD | LOAD_CAP | GLOBAL: the PCC of the
        csetaddr t9, t9, zero     # user program and the root of every function pointer
        la   t2, __end
        csetbnd t9, t9, t2
        li   t2, 0x8D
        candperm t9, t9, t2
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
        csetaddr t7, t9, t3       # function: from the code capability (not the supervisor's root PCC)
        cincaddr t7, t7, t5
        csealentry t7, t7         # SENTRY (v6): function pointers are sealed entry capabilities
        j    __crset
__crdata:
        csetaddr t7, gp, t3
        beqz t4, __crinc
        csetbnd t7, t7, t4
__crinc:
        cincaddr t7, t7, t5
__crset:
        csetaddr t8, gp, t2
        csc  t7, 0(t8)
        cincaddri t0, t0, 64
        j    __crl
__crd:  li   t0, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000
        csetaddr t1, rc, t0       # MMIO capability: the device registers [MMIO, MMIO + 0x8000), LOAD | STORE | LOAD_CAP | STORE_CAP | GLOBAL (16-byte accesses are clc/csc in purecap)
        li   t2, 0x8000           # (v6: stops below the revocation bitmap, which only the allocator may write)
        csetbnd t1, t1, t2
        li   t2, 0x9B
        candperm t1, t1, t2
        la   t0, ___tx_mmio
        csetaddr t0, gp, t0
        csc  t1, 0(t0)
        li   t0, 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFF8000
        csetaddr t1, rc, t0       # v6: revocation bitmap capability (2 KiB at MMIO + 0x8000) for malloc/free
        csetbndi t1, t1, 2048
        li   t2, 0x9B
        candperm t1, t1, t2
        la   t0, ___tx_revmap
        csetaddr t0, gp, t0
        csc  t1, 0(t0)
        # enter user mode with an empty untagged window (ubase = ubound = 0): from here on every load or store
        # through an untagged (integer) base traps (cause 9), so the program can only touch memory through
        # capabilities. PCC = code capability [0, __end), EXEC | LOAD | LOAD_CAP | GLOBAL.
        csrw ubase, zero
        csrw ubound, zero
        csetepcc t9
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
        addi t4, t3, 48           # cause is 1..10: one or two decimal digits
        addi t6, zero, 10
        bltu t3, t6, __tt1
        addi t5, zero, 49         # '1'
        sb   t5, 0(t1)
        addi t4, t3, 38           # '0' + cause - 10
__tt1:  sb   t4, 0(t1)
        addi t4, zero, 32
        sb   t4, 0(t1)
        csrr t5, tval
        sq   t5, 32(t1)           # MMIO hex output: tval as 32 hex digits + newline
        addi t3, t3, 128
        sq   t3, 16(t1)           # MMIO exit: 128 + cause
        halt t3

# v6 revocation sweep, called by the purecap free/malloc (cc/lib/stdlib.c, cc/ABI.md section 8.2) as
#   void __tx_revoke_sweep(unsigned long lo, unsigned long hi, unsigned long lo2, unsigned long hi2)
#   (all 256-byte aligned; [lo2, hi2) is the stack region, swept after [lo, hi))
# 1. memory: cloadtags finds the tagged granules of each 256-byte block of the ranges; each capability is
#    reloaded with clc, passed through crevtag (tag dropped if its base granule is revoked) and written
#    back with csc, so no capability into revoked memory survives in RAM (frames of the callers included);
# 2. registers: the callee-saved registers (s0-s15, r44-r53) go through crevtag as well; the caller-saved
#    ones (dead across this call for compiled code) are cleared.
# Uses gp, the RAM capability set up above (never touched by compiled code).
___tx_revoke_sweep:
        csetaddr t0, gp, a0
__trs_blk:
        bgeu t0, a1, __trs_r2
__trs_bl:
        cloadtags t1, 0(t0)
        bnez t1, __trs_g
__trs_nx:
        cincaddri t0, t0, 256
        bltu t0, a1, __trs_bl
__trs_r2:
        bgeu a2, a3, __trs_regs   # second range (once): [a2, a3)
        csetaddr t0, gp, a2
        mv   a1, a3
        mv   a2, a3
        j    __trs_blk
__trs_g:
        cmove t2, t0
__trs_gl:
        andi t3, t1, 1
        beqz t3, __trs_gs
        clc  t4, 0(t2)
        crevtag t4, t4
        csc  t4, 0(t2)
__trs_gs:
        srli t1, t1, 1
        cincaddri t2, t2, 16
        bnez t1, __trs_gl
        j    __trs_nx
__trs_regs:
        crevtag s0, s0
        crevtag s1, s1
        crevtag s2, s2
        crevtag s3, s3
        crevtag s4, s4
        crevtag s5, s5
        crevtag s6, s6
        crevtag s7, s7
        crevtag s8, s8
        crevtag s9, s9
        crevtag s10, s10
        crevtag s11, s11
        crevtag s12, s12
        crevtag s13, s13
        crevtag s14, s14
        crevtag s15, s15
        crevtag r44, r44
        crevtag r45, r45
        crevtag r46, r46
        crevtag r47, r47
        crevtag r48, r48
        crevtag r49, r49
        crevtag r50, r50
        crevtag r51, r51
        crevtag r52, r52
        crevtag r53, r53
        mv   a0, zero
        mv   a1, zero
        mv   a2, zero
        mv   a3, zero
        mv   a4, zero
        mv   a5, zero
        mv   a6, zero
        mv   a7, zero
        mv   t0, zero
        mv   t1, zero
        mv   t2, zero
        mv   t3, zero
        mv   t4, zero
        mv   t5, zero
        mv   t6, zero
        mv   t7, zero
        mv   t8, zero
        mv   t9, zero
        mv   t10, zero
        mv   t11, zero
        mv   t12, zero
        mv   t13, zero
        mv   t14, zero
        mv   t15, zero
        mv   r54, zero
        mv   r55, zero
        mv   r56, zero
        mv   r57, zero
        mv   r58, zero
        mv   r59, zero
        mv   r60, zero
        mv   r61, zero
        mv   r62, zero
        ret

__tx_trap_msg:
        .asciz "\n*** capability trap (hardware): cause="
        .align 4
        .align 16
___tx_mmio:                        # the MMIO capability (C name __tx_mmio, see cc/include/tx128.h)
        .quad 0
___tx_revmap:                      # v6: the revocation-bitmap capability (C name __tx_revmap, malloc/free only)
        .quad 0
