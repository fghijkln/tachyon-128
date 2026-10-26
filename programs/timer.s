# timer.s - machine timer interrupt demo.  mtime counts retired instructions, so the tick
# points are fully deterministic: the golden model and the RTL take every interrupt between
# the same two instructions.  The handler prints '.', counts ticks and re-arms mtimecmp.
        .org 0
_start: li   sp, 0x40000
        j    main
        .include "lib.s"

        .equ MTIME,    0x30
        .equ MTIMECMP, 0x40
        .equ PERIOD,   250

handler:
        csrr t0, cause
        bltz t0, tick
        li   a0, 99                  # unexpected synchronous trap
        call exit
tick:   csrw scratch, ra
        li   t15, MMIO
        li   t14, '.'
        sb   t14, CONSOLE(t15)
        lq   t13, MTIME(t15)
        addi t13, t13, PERIOD
        sq   t13, MTIMECMP(t15)      # next tick
        addi s9, s9, 1
        csrr ra, scratch
        eret                         # resume exactly at epc (the interrupted instruction)

main:   la   t0, handler
        csrw tvec, t0
        li   s9, 0
        li   t15, MMIO
        li   t0, PERIOD
        sq   t0, MTIMECMP(t15)
        li   t0, 5                   # status: IE | TIE
        csrw status, t0
        # work: sum of i*i for i = 1..1000 (squares by running odd sums: (i+1)^2 = i^2 + 2i+1)
        li   s0, 0                   # sum
        li   s1, 1                   # i^2
        li   s3, 3                   # next odd number
        li   s2, 1000
loop:   add  s0, s0, s1
        add  s1, s1, s3
        addi s3, s3, 2
        addi s2, s2, -1
        bnez s2, loop
        csrw status, zero            # interrupts off
        call putnl
        la   a0, m_sum
        call puts
        mv   a0, s0
        call putu
        call putnl
        la   a0, m_t
        call puts
        mv   a0, s9
        call putu
        call putnl
        la   a0, m_now
        call puts
        li   t15, MMIO
        lq   a0, MTIME(t15)
        call putu
        call putnl
        li   a0, 0
        call exit

m_sum:  .asciz "sum(i^2, 1..1000) = "
m_t:    .asciz "timer ticks       = "
m_now:  .asciz "mtime             = "
