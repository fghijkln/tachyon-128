# recurse.s - call-heavy workload (v4, exercises the return address stack): naive recursive fib with
# ra/a0 spilled to a memory stack, Ackermann's function, and a recursive binary-tree sum whose node
# links are capabilities (clc) -- returns go to many different call sites at many depths.
        .org 0
_start: li   sp, 0x40000
        j    main
        .include "lib.s"
        .equ NNODE, 63

# rfib(a0) -> a0, naive double recursion
rfib:   li   t0, 2
        bltu a0, t0, rfib_b
        addi sp, sp, -32
        sq   ra, 0(sp)
        sq   a0, 16(sp)
        addi a0, a0, -1
        call rfib
        lq   t1, 16(sp)
        sq   a0, 16(sp)
        addi a0, t1, -2
        call rfib
        lq   t1, 16(sp)
        add  a0, a0, t1
        lq   ra, 0(sp)
        addi sp, sp, 32
rfib_b: ret

# ack(a0 = m, a1 = n) -> a0
ack:    bnez a0, ack_1
        addi a0, a1, 1
        ret
ack_1:  addi sp, sp, -32
        sq   ra, 0(sp)
        bnez a1, ack_2
        addi a0, a0, -1
        li   a1, 1
        call ack
        j    ack_r
ack_2:  sq   a0, 16(sp)
        addi a1, a1, -1
        call ack                     # ack(m, n-1)
        mv   a1, a0
        lq   a0, 16(sp)
        addi a0, a0, -1
        call ack                     # ack(m-1, ack(m, n-1))
ack_r:  lq   ra, 0(sp)
        addi sp, sp, 32
        ret

# tsum(a0 = node capability or untagged null) -> a0 = sum of payloads; node = {left, right, value}
tsum:   cgettag t0, a0
        bnez t0, tsum_1
        li   a0, 0
        ret
tsum_1: addi sp, sp, -48
        sq   ra, 0(sp)
        csc  a0, 16(sp)
        clc  a0, 0(a0)               # left subtree
        call tsum
        sq   a0, 32(sp)
        clc  a0, 16(sp)
        clc  a0, 16(a0)              # right subtree
        call tsum
        lq   t1, 32(sp)
        add  a0, a0, t1
        clc  t2, 16(sp)
        lq   t2, 32(t2)              # own value
        add  a0, a0, t2
        lq   ra, 0(sp)
        addi sp, sp, 48
        ret

# build(a0 = index i of a complete tree stored as an array of 63 nodes) -> a0 = node capability
build:  li   t0, NNODE
        bltu a0, t0, build_1
        li   a0, 0
        ret
build_1: addi sp, sp, -48
        sq   ra, 0(sp)
        sq   a0, 16(sp)
        slli a0, a0, 1
        addi a0, a0, 1
        call build                   # left = 2i+1
        csc  a0, 32(sp)
        lq   a0, 16(sp)
        slli a0, a0, 1
        addi a0, a0, 2
        call build                   # right = 2i+2
        lq   t1, 16(sp)              # node i at nodes + 48*i, a 48-byte capability
        li   t2, 48
        mul  t2, t2, t1
        la   t3, nodes
        add  t3, t3, t2
        csetaddr t4, rc, t3
        csetbndi t4, t4, 48
        csc  a0, 16(t4)              # right
        clc  t5, 32(sp)
        csc  t5, 0(t4)               # left
        addi t1, t1, 1
        sq   t1, 32(t4)              # value = i + 1
        cmove a0, t4                 # (mv = addi would clear the tag)
        lq   ra, 0(sp)
        addi sp, sp, 48
        ret

main:   la   a0, m_fib
        call puts
        li   a0, 18
        call rfib
        call putu
        call putnl
        la   a0, m_ack
        call puts
        li   a0, 2
        li   a1, 3
        call ack
        call putu
        call putnl
        li   a0, 0
        call build
        call tsum
        mv   s0, a0
        la   a0, m_tree
        call puts
        mv   a0, s0
        call putu
        call putnl
        li   a0, 0
        call exit

m_fib:  .asciz "rfib(18)    = "
m_ack:  .asciz "ack(2, 3)   = "
m_tree: .asciz "tree sum    = "
        .align 16
nodes:  .space 48*63
