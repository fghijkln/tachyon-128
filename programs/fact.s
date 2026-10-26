# fact.s - exact factorials with 128-bit MUL; 34! is the largest that fits in 128 bits.
        .org 0
_start: li   sp, 0x40000
        j    main
        .include "lib.s"

main:   li   s0, 1          # i
        li   s1, 1          # acc = i!
        li   s2, 35
loop:   mul  s1, s1, s0
        li   t0, 30
        blt  s0, t0, skip   # print 30! .. 34!
        mv   a0, s0
        call putu
        la   a0, msg
        call puts
        mv   a0, s1
        call putu
        call putnl
skip:   addi s0, s0, 1
        bne  s0, s2, loop
        # 35! overflows: show mulhu catching the carry-out of 34! * 35
        la   a0, ovf
        call puts
        li   t0, 35
        mulhu a0, s1, t0
        call putu
        call putnl
        # check: 34! / 33! == 34 using signed+unsigned division
        mv   a0, s1
        li   t1, 34
        divu a0, a0, t1     # 33!
        div  t2, s1, a0     # back to 34 (signed div: 34! has bit127 set -> negative!)
        la   a0, chk
        call puts
        mv   a0, t2
        call puthex
        li   a0, 0
        call exit

msg:    .asciz "! = "
ovf:    .asciz "high word of 34!*35 (mulhu) = "
chk:    .asciz "signed (34!)/(33!) = "
