# fib.s - 128-bit Fibonacci: prints fib(n) for several n up to fib(180), exact.
        .org 0
_start: li   sp, 0x40000
        j    main
        .include "lib.s"

# fib(a0) -> a0, iterative, 128-bit adds
fib:    li   t0, 0          # f(i)
        li   t1, 1          # f(i+1)
fib_l:  beqz a0, fib_d
        add  t2, t0, t1
        mv   t0, t1
        mv   t1, t2
        addi a0, a0, -1
        j    fib_l
fib_d:  mv   a0, t0
        ret

main:   la   s0, ns
loop:   lhu  s1, 0(s0)
        beqz s1, done
        la   a0, msg1
        call puts
        mv   a0, s1
        call putu
        la   a0, msg2
        call puts
        mv   a0, s1
        call fib
        mv   s2, a0
        call putu
        call putnl
        addi s0, s0, 2
        j    loop
done:   mv   a0, s2         # also show the last one in hex
        call puthex
        li   a0, 0
        call exit

msg1:   .asciz "fib("
msg2:   .asciz ") = "
        .align 2
ns:     .half 10, 50, 93, 94, 100, 150, 180, 0
