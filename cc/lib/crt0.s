# tcc128 start-up code (see cc/ABI.md)
        .org 0
_start: li   sp, 0x40000          # stack grows down from the top of the 256 KiB RAM
        mv   a0, zero             # argc = 0
        mv   a1, zero             # argv = NULL
        call _main
        call _exit                # exit(main's return value); never returns
        halt a0
