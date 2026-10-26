# TACHYON-128 tiny runtime: console output through MMIO.
# Calling convention: args/results a0-a7, temporaries t0-t15 (caller-saved),
# s0-s15 callee-saved, ra = link, sp = stack (grows down, 16-byte aligned).
        .equ MMIO,      (1 << 128) - 0x10000
        .equ CONSOLE,   0x00
        .equ EXITREG,   0x10
        .equ HEXOUT,    0x20
        .equ RAMTOP,    0x40000

# putc(a0 = char)
putc:   li   t15, MMIO
        sb   a0, CONSOLE(t15)
        ret

# puts(a0 = address of NUL-terminated string)
puts:   li   t15, MMIO
puts_l: lbu  t14, 0(a0)
        beqz t14, puts_d
        sb   t14, CONSOLE(t15)
        addi a0, a0, 1
        j    puts_l
puts_d: ret

# puthex(a0) - 32 hex digits + newline (hardware formatter)
puthex: li   t15, MMIO
        sq   a0, HEXOUT(t15)
        ret

# putu(a0) - unsigned 128-bit decimal; uses divu+remu pair (divider result cache)
putu:   addi sp, sp, -64          # digit buffer (max 39 digits)
        mv   t13, sp
        li   t12, 10
putu_l: divu t11, a0, t12
        remu t10, a0, t12
        addi t10, t10, '0'
        sb   t10, 0(t13)
        addi t13, t13, 1
        mv   a0, t11
        bnez a0, putu_l
        li   t15, MMIO
putu_o: addi t13, t13, -1
        lbu  t10, 0(t13)
        sb   t10, CONSOLE(t15)
        bne  t13, sp, putu_o
        addi sp, sp, 64
        ret

# putnl()
putnl:  li   t15, MMIO
        li   t14, 10
        sb   t14, CONSOLE(t15)
        ret

# exit(a0 = code)
exit:   li   t15, MMIO
        sw   a0, EXITREG(t15)
exit_h: j    exit_h               # never reached
