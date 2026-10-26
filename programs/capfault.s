# capfault.s - hardware-checked capabilities.  Derive a bounded pointer from the root
# capability (rc), use it, then show three faults being caught by the trap handler.
        .org 0
_start: li   sp, 0x40000
        j    main
        .include "lib.s"

# trap handler: print cause + faulting address, skip the instruction, resume
handler:
        csrw scratch, ra
        la   a0, t_msg
        call puts
        csrr a0, cause
        call putu
        la   a0, t_at
        call puts
        csrr a0, tval
        call puthex
        csrr t0, epc
        addi t0, t0, 4
        csrw epc, t0
        addi s9, s9, 1          # fault counter
        csrr ra, scratch
        eret

main:   la   t0, handler
        csrw tvec, t0
        li   s9, 0
        # derive buf = [buffer, buffer+64) with load+store permission
        la   t1, buffer
        csetaddr s0, rc, t1     # pointer into root, full bounds
        csetbndi s0, s0, 64     # shrink: base=buffer, top=buffer+64
        la   a0, m_len
        call puts
        cgetlen a0, s0
        call putu
        call putnl
        # in-bounds use works
        li   t2, 0xC0FFEE
        sq   t2, 48(s0)
        lq   t3, 48(s0)
        la   a0, m_ok
        call puts
        mv   a0, t3
        call puthex
        # fault 1: one past the end (bounds)
        sq   t2, 64(s0)
        # fault 2: try to widen the capability (monotonicity)
        csetbndi s1, s0, 65
        # fault 3: read-only view, then store (permission)
        li   t4, 1              # PERM_LOAD only
        candperm s2, s0, t4
        lq   t5, 0(s2)          # ok
        sq   t2, 0(s2)          # store -> fault
        # forging is impossible: integer copy drops the tag
        mv   s3, s0
        cgettag t6, s3
        la   a0, m_tag
        call puts
        mv   a0, t6
        call putu
        call putnl
        la   a0, m_n
        call puts
        mv   a0, s9
        call putu
        call putnl
        li   a0, 0
        call exit

m_len:  .asciz "bounded cap length = "
m_ok:   .asciz "in-bounds load     = "
t_msg:  .asciz "  !! trap cause="
t_at:   .asciz " addr="
m_tag:  .asciz "tag after mv (forge attempt) = "
m_n:    .asciz "faults caught = "
        .align 16
buffer: .space 64
