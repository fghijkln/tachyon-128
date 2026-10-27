# kernel.s - a tiny two-level (supervisor / user) kernel.
#  * Two user tasks run in user mode under their own PCC (code capability) and user window
#    (ubase/ubound for untagged accesses); the kernel preempts them with the deterministic timer
#    (round-robin, QUANTUM retired instructions) and serves ecalls: 1 = putc(a1), 2 = exit.
#  * Task A prints through ecall and keeps a counter in its own window.
#  * Task B prints straight to the console MMIO register through a capability the kernel gave it
#    (r10: STORE only, 16 bytes), then tries an untagged MMIO store: privilege-violation -> killed.
#  * Trap entry saves all 63 registers (with capability tags) to a fixed frame with csc via r0
#    (supervisor untagged accesses are unchecked), so user tasks may hold capabilities.
        .org 0
_start: j    kmain
        .include "lib.s"

        .equ FRAME,    0x1C00            # trap frame: 64 x 16 B, reachable as imm14(r0)
        .equ KSTACK,   0x40000
        .equ QUANTUM,  200
        .equ MTIME,    0x30
        .equ MTIMECMP, 0x40
        .equ T_PC,     0x400             # TCB layout: regs[64] at +0, then:
        .equ T_PCC,    0x410             #   PCC (capability)
        .equ T_UBASE,  0x420
        .equ T_UBOUND, 0x430
        .equ T_ALIVE,  0x440
        .equ TCBSZ,    0x480
        .equ ST_USER,  0x16              # status for user tasks: PU | TIE | PIE

# ------------------------------------------------------------------ trap entry
ktrap:
        csc  r1, FRAME+16(zero)
        csc  r2, FRAME+32(zero)
        csc  r3, FRAME+48(zero)
        csc  r4, FRAME+64(zero)
        csc  r5, FRAME+80(zero)
        csc  r6, FRAME+96(zero)
        csc  r7, FRAME+112(zero)
        csc  r8, FRAME+128(zero)
        csc  r9, FRAME+144(zero)
        csc  r10, FRAME+160(zero)
        csc  r11, FRAME+176(zero)
        csc  r12, FRAME+192(zero)
        csc  r13, FRAME+208(zero)
        csc  r14, FRAME+224(zero)
        csc  r15, FRAME+240(zero)
        csc  r16, FRAME+256(zero)
        csc  r17, FRAME+272(zero)
        csc  r18, FRAME+288(zero)
        csc  r19, FRAME+304(zero)
        csc  r20, FRAME+320(zero)
        csc  r21, FRAME+336(zero)
        csc  r22, FRAME+352(zero)
        csc  r23, FRAME+368(zero)
        csc  r24, FRAME+384(zero)
        csc  r25, FRAME+400(zero)
        csc  r26, FRAME+416(zero)
        csc  r27, FRAME+432(zero)
        csc  r28, FRAME+448(zero)
        csc  r29, FRAME+464(zero)
        csc  r30, FRAME+480(zero)
        csc  r31, FRAME+496(zero)
        csc  r32, FRAME+512(zero)
        csc  r33, FRAME+528(zero)
        csc  r34, FRAME+544(zero)
        csc  r35, FRAME+560(zero)
        csc  r36, FRAME+576(zero)
        csc  r37, FRAME+592(zero)
        csc  r38, FRAME+608(zero)
        csc  r39, FRAME+624(zero)
        csc  r40, FRAME+640(zero)
        csc  r41, FRAME+656(zero)
        csc  r42, FRAME+672(zero)
        csc  r43, FRAME+688(zero)
        csc  r44, FRAME+704(zero)
        csc  r45, FRAME+720(zero)
        csc  r46, FRAME+736(zero)
        csc  r47, FRAME+752(zero)
        csc  r48, FRAME+768(zero)
        csc  r49, FRAME+784(zero)
        csc  r50, FRAME+800(zero)
        csc  r51, FRAME+816(zero)
        csc  r52, FRAME+832(zero)
        csc  r53, FRAME+848(zero)
        csc  r54, FRAME+864(zero)
        csc  r55, FRAME+880(zero)
        csc  r56, FRAME+896(zero)
        csc  r57, FRAME+912(zero)
        csc  r58, FRAME+928(zero)
        csc  r59, FRAME+944(zero)
        csc  r60, FRAME+960(zero)
        csc  r61, FRAME+976(zero)
        csc  r62, FRAME+992(zero)
        csc  r63, FRAME+1008(zero)
        li   sp, KSTACK
        la   s1, cur
        ld   s1, 0(s1)                   # s1 = current task index
        la   s2, tcbs
        li   t0, TCBSZ
        mul  t0, t0, s1
        add  s2, s2, t0                  # s2 = &tcb[cur]
        csrr s0, cause
        bltz s0, k_irq
        li   t0, 8
        beq  s0, t0, k_ecall
        # any other trap from a user task: report and kill it
        la   a0, m_kill
        call puts
        mv   a0, s1
        call putu
        la   a0, m_cause
        call puts
        mv   a0, s0
        call putu
        la   a0, m_tval
        call puts
        csrr a0, tval
        call puthex
        sd   zero, T_ALIVE(s2)
        j    k_next

k_ecall:
        csrr t0, epc
        addi t0, t0, 4
        csrw epc, t0
        la   t0, n_ecall
        ld   t1, 0(t0)
        addi t1, t1, 1
        sd   t1, 0(t0)
        lq   t0, FRAME+16*4(zero)        # a0 = service number
        li   t1, 1
        bne  t0, t1, k_ec2
        lq   a0, FRAME+16*5(zero)        # putc(a1)
        call putc
        j    k_resume
k_ec2:  li   t1, 2
        bne  t0, t1, k_resume            # unknown service: ignored
        la   a0, m_exit
        call puts
        mv   a0, s1
        call putu
        call putnl
        sd   zero, T_ALIVE(s2)
        j    k_next

k_irq:  la   t0, n_preempt               # timer: switch to the other task
        ld   t1, 0(t0)
        addi t1, t1, 1
        sd   t1, 0(t0)
        mv   a0, s2                      # save the interrupted task: frame -> tcb, epc -> tcb.pc
        li   a1, FRAME
        call copy64
        csrr t0, epc
        sq   t0, T_PC(s2)

k_next: li   t3, 2                       # pick the next alive task (round robin over 2)
k_nl:   addi s1, s1, 1
        andi s1, s1, 1
        la   s2, tcbs
        li   t0, TCBSZ
        mul  t0, t0, s1
        add  s2, s2, t0
        ld   t0, T_ALIVE(s2)
        bnez t0, k_load
        addi t3, t3, -1
        bnez t3, k_nl
        j    k_done                      # nobody left
k_load: la   t0, cur
        sd   s1, 0(t0)
        li   a0, FRAME                   # tcb -> frame, pc -> epc, PCC -> EPCC, user window
        mv   a1, s2
        call copy64
        lq   t0, T_PC(s2)
        csrw epc, t0
        clc  t0, T_PCC(s2)
        csetepcc t0
        lq   t0, T_UBASE(s2)
        csrw ubase, t0
        lq   t0, T_UBOUND(s2)
        csrw ubound, t0
        li   t15, MMIO                   # new time slice: QUANTUM retired instructions from here
        lq   t0, MTIME(t15)
        addi t0, t0, QUANTUM
        sq   t0, MTIMECMP(t15)
k_resume:
        clc  r1, FRAME+16(zero)
        clc  r2, FRAME+32(zero)
        clc  r3, FRAME+48(zero)
        clc  r4, FRAME+64(zero)
        clc  r5, FRAME+80(zero)
        clc  r6, FRAME+96(zero)
        clc  r7, FRAME+112(zero)
        clc  r8, FRAME+128(zero)
        clc  r9, FRAME+144(zero)
        clc  r10, FRAME+160(zero)
        clc  r11, FRAME+176(zero)
        clc  r12, FRAME+192(zero)
        clc  r13, FRAME+208(zero)
        clc  r14, FRAME+224(zero)
        clc  r15, FRAME+240(zero)
        clc  r16, FRAME+256(zero)
        clc  r17, FRAME+272(zero)
        clc  r18, FRAME+288(zero)
        clc  r19, FRAME+304(zero)
        clc  r20, FRAME+320(zero)
        clc  r21, FRAME+336(zero)
        clc  r22, FRAME+352(zero)
        clc  r23, FRAME+368(zero)
        clc  r24, FRAME+384(zero)
        clc  r25, FRAME+400(zero)
        clc  r26, FRAME+416(zero)
        clc  r27, FRAME+432(zero)
        clc  r28, FRAME+448(zero)
        clc  r29, FRAME+464(zero)
        clc  r30, FRAME+480(zero)
        clc  r31, FRAME+496(zero)
        clc  r32, FRAME+512(zero)
        clc  r33, FRAME+528(zero)
        clc  r34, FRAME+544(zero)
        clc  r35, FRAME+560(zero)
        clc  r36, FRAME+576(zero)
        clc  r37, FRAME+592(zero)
        clc  r38, FRAME+608(zero)
        clc  r39, FRAME+624(zero)
        clc  r40, FRAME+640(zero)
        clc  r41, FRAME+656(zero)
        clc  r42, FRAME+672(zero)
        clc  r43, FRAME+688(zero)
        clc  r44, FRAME+704(zero)
        clc  r45, FRAME+720(zero)
        clc  r46, FRAME+736(zero)
        clc  r47, FRAME+752(zero)
        clc  r48, FRAME+768(zero)
        clc  r49, FRAME+784(zero)
        clc  r50, FRAME+800(zero)
        clc  r51, FRAME+816(zero)
        clc  r52, FRAME+832(zero)
        clc  r53, FRAME+848(zero)
        clc  r54, FRAME+864(zero)
        clc  r55, FRAME+880(zero)
        clc  r56, FRAME+896(zero)
        clc  r57, FRAME+912(zero)
        clc  r58, FRAME+928(zero)
        clc  r59, FRAME+944(zero)
        clc  r60, FRAME+960(zero)
        clc  r61, FRAME+976(zero)
        clc  r62, FRAME+992(zero)
        clc  r63, FRAME+1008(zero)
        eret

# copy64(a0 = dst, a1 = src): 64 granules with their tags (clc/csc through untagged bases)
copy64: li   t2, 64
c64_l:  clc  t0, 0(a1)
        csc  t0, 0(a0)
        addi a0, a0, 16
        addi a1, a1, 16
        addi t2, t2, -1
        bnez t2, c64_l
        ret

k_done: la   a0, m_done
        call puts
        la   t0, n_preempt
        ld   a0, 0(t0)
        call putu
        la   a0, m_ec
        call puts
        la   t0, n_ecall
        ld   a0, 0(t0)
        call putu
        la   a0, m_cnt
        call puts
        la   t0, adata
        ld   a0, 0(t0)
        call putu
        call putnl
        li   a0, 0
        call exit

# ------------------------------------------------------------------ boot
kmain:  li   sp, KSTACK
        la   a0, m_hello
        call puts
        la   t0, ktrap
        csrw tvec, t0
        # task 0 (A): PCC = its code, EXEC|LOAD; gp = its data word, user window = that word
        la   s2, tcbs
        la   t0, taskA
        sq   t0, T_PC(s2)
        csetaddr t1, rc, t0
        csetbndi t1, t1, taskA_end - taskA
        li   t2, 5
        candperm t1, t1, t2
        csc  t1, T_PCC(s2)
        la   t0, adata
        sq   t0, 16*3(s2)                # regs[gp]
        sq   t0, T_UBASE(s2)
        addi t0, t0, 16
        sq   t0, T_UBOUND(s2)
        li   t0, 1
        sd   t0, T_ALIVE(s2)
        # task 1 (B): PCC = its code; r10 = console capability (STORE only, 16 bytes); empty window
        addi s2, s2, TCBSZ
        la   t0, taskB
        sq   t0, T_PC(s2)
        csetaddr t1, rc, t0
        csetbndi t1, t1, taskB_end - taskB
        li   t2, 5
        candperm t1, t1, t2
        csc  t1, T_PCC(s2)
        li   t0, MMIO
        csetaddr t1, rc, t0
        csetbndi t1, t1, 16
        li   t2, 2
        candperm t1, t1, t2
        csc  t1, 16*10(s2)               # regs[r10]
        li   t0, 1
        sd   t0, T_ALIVE(s2)
        # start: status = PU|TIE|PIE so eret enters user mode with interrupts on (k_load arms the timer)
        li   t0, ST_USER
        csrw status, t0
        li   s1, 1                       # k_next advances to task 0
        j    k_next

# ------------------------------------------------------------------ user task A
taskA:  li   s0, 0
ta_l:   li   a0, 1
        li   a1, 'A'
        ecall
        li   a0, 1
        addi a1, s0, '0'
        ecall
        li   a0, 1
        li   a1, ' '
        ecall
        li   t0, 12                      # some work
ta_b:   addi t0, t0, -1
        bnez t0, ta_b
        addi s0, s0, 1
        sd   s0, 0(gp)                   # counter in the task's own window
        li   t1, 10
        blt  s0, t1, ta_l
        li   a0, 1
        li   a1, 10
        ecall
        li   a0, 2                       # exit
        ecall
taskA_end:

# ------------------------------------------------------------------ user task B
taskB:  li   s0, 'a'
tb_l:   sb   s0, 0(r10)                  # console through the capability the kernel granted
        li   t0, 15
tb_b:   addi t0, t0, -1
        bnez t0, tb_b
        addi s0, s0, 1
        li   t1, 'a' + 14
        blt  s0, t1, tb_l
        li   t2, MMIO
        sb   s0, 0(t2)                   # untagged MMIO store from user mode -> privilege-violation
        j    tb_l                        # never reached
taskB_end:

        .align 16
cur:       .quad 0
n_preempt: .quad 0
n_ecall:   .quad 0
adata:     .quad 0
m_hello:   .asciz "TACHYON-128 kernel: 2 user tasks, timer quantum 200\n"
m_kill:    .asciz "\n[kernel] task "
m_cause:   .asciz " killed: cause="
m_tval:    .asciz " tval="
m_exit:    .asciz "[kernel] exit from task "
m_done:    .asciz "[kernel] all tasks finished. preemptions="
m_ec:      .asciz " ecalls="
m_cnt:     .asciz " taskA counter="
        .align 16
tcbs:      .space 2 * 0x480
