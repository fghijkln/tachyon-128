# sort.s - insertion sort of 128-bit unsigned keys in memory, then verify + checksum.
        .org 0
_start: li   sp, 0x40000
        j    main
        .include "lib.s"

        .equ N, 24
main:   # generate keys with a 128-bit LCG: x = x*A + C  (mod 2^128)
        la   s0, arr
        li   s1, 0x0123456789abcdef0fedcba987654321
        li   s2, 0x2360ed051fc65da44385df649fccf645   # multiplier
        li   s3, 0x5851f42d4c957f2d14057b7ef767814f   # increment
        li   t0, 0
gen:    mul  s1, s1, s2
        add  s1, s1, s3
        slli t1, t0, 4
        add  t1, t1, s0
        sq   s1, 0(t1)
        addi t0, t0, 1
        li   t2, N
        blt  t0, t2, gen
        # insertion sort
        li   t0, 1                  # i
outer:  slli t1, t0, 4
        add  t1, t1, s0
        lq   t3, 0(t1)              # key
        mv   t4, t1                 # j pointer
inner:  beq  t4, s0, place
        lq   t5, -16(t4)
        bleu t5, t3, place
        sq   t5, 0(t4)
        addi t4, t4, -16
        j    inner
place:  sq   t3, 0(t4)
        addi t0, t0, 1
        li   t2, N
        blt  t0, t2, outer
        # verify ascending and xor-checksum
        li   s4, 0                  # checksum
        li   s5, 0                  # errors
        li   t0, 0
        li   t6, 0                  # prev
ver:    slli t1, t0, 4
        add  t1, t1, s0
        lq   t3, 0(t1)
        xor  s4, s4, t3
        sltu t2, t3, t6
        add  s5, s5, t2
        mv   t6, t3
        addi t0, t0, 1
        li   t2, N
        blt  t0, t2, ver
        la   a0, m1
        call puts
        lq   a0, 0(s0)
        call puthex
        la   a0, m2
        call puts
        lq   a0, (N-1)*16(s0)
        call puthex
        la   a0, m3
        call puts
        mv   a0, s4
        call puthex
        la   a0, m4
        call puts
        mv   a0, s5
        call putu
        call putnl
        mv   a0, s5
        call exit

m1:     .asciz "min      = "
m2:     .asciz "max      = "
m3:     .asciz "checksum = "
m4:     .asciz "inversions = "
        .align 16
arr:    .space N*16
