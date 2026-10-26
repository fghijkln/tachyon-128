# simd.s - packed SIMD inside 128-bit GPRs (16x8, 8x16, 4x32, 2x64 lanes).
        .org 0
_start: li   sp, 0x40000
        j    main
        .include "lib.s"

show:   # a0 = label string, a1 = value
        addi sp, sp, -16
        sq   ra, 0(sp)
        call puts
        mv   a0, a1
        call puthex
        lq   ra, 0(sp)
        addi sp, sp, 16
        ret

main:   la   s0, data
        lq   s1, 0(s0)          # bytes 0x10,0x20,...,0xF0,0xFF
        lq   s2, 16(s0)         # bytes 0x80 x16
        # 1) wrapping vs saturating byte add (image brightening)
        vadd.b  t0, s1, s2
        la   a0, l_add
        mv   a1, t0
        call show
        vaddus.b t0, s1, s2
        la   a0, l_adds
        mv   a1, t0
        call show
        # 2) dot product of two int16 vectors: vmul.h then horizontal vsum.h
        lq   s3, 32(s0)         # 1..8
        lq   s4, 48(s0)         # 8..1
        vmul.h  t0, s3, s4
        vsum.h  t1, t0          # 1*8+2*7+...+8*1 = 120
        la   a0, l_dot
        mv   a1, t1
        call show
        # 3) per-lane max / compare mask (4 x int32)
        lq   s5, 64(s0)
        lq   s6, 80(s0)
        vmaxs.w t0, s5, s6
        la   a0, l_max
        mv   a1, t0
        call show
        vcmpgts.w t0, s5, s6
        la   a0, l_cmp
        mv   a1, t0
        call show
        # 4) splat + 64-bit lane shift
        li   t2, 0x1234
        vsplat.h t0, t2
        la   a0, l_spl
        mv   a1, t0
        call show
        li   t3, 4
        vsra.d  t0, s5, t3
        la   a0, l_sra
        mv   a1, t0
        call show
        # 5) SAD-like: sum of |a-b| over 16 bytes = vsum(vsubus(a,b) | vsubus(b,a))
        vsubus.b t0, s1, s2
        vsubus.b t1, s2, s1
        or       t0, t0, t1
        vsum.b   a1, t0
        la   a0, l_sad
        call show
        li   a0, 0
        call exit

l_add:  .asciz "vadd.b   (wrap) = "
l_adds: .asciz "vaddus.b (sat)  = "
l_dot:  .asciz "dot(1..8,8..1)  = "
l_max:  .asciz "vmaxs.w         = "
l_cmp:  .asciz "vcmpgts.w mask  = "
l_spl:  .asciz "vsplat.h        = "
l_sra:  .asciz "vsra.d by 4     = "
l_sad:  .asciz "SAD(16 bytes)   = "
        .align 16
data:   .byte 0x10,0x20,0x30,0x40,0x50,0x60,0x70,0x80,0x90,0xA0,0xB0,0xC0,0xD0,0xE0,0xF0,0xFF
        .byte 0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80,0x80
        .half 1,2,3,4,5,6,7,8
        .half 8,7,6,5,4,3,2,1
        .word -5, 100, 0x7fffffff, -2147483648
        .word 3, -100, 0x7ffffffe, 0
