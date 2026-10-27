# C compiler

TACHYON-128 has a C compiler, **tcc128** (Python): see [`cc/README.md`](cc/README.md) for usage,
features, test/fuzz/benchmark results and limitations, and [`cc/ABI.md`](cc/ABI.md) for the
calling convention and data model.

```sh
python3 cc/tcc128.py prog.c --run          # compile + run on the golden simulator
python3 cc/tests/run_tests.py --both       # C test suite (-O and -O0)
python3 cc/bench/run_bench.py --rtl        # benchmarks with RTL cycles/CPI
python3 cc/tcc128.py prog.c -mpurecap --run           # pure-capability code
python3 cc/tests/run_tests.py --purecap               # purecap suite + capability-fault tests
```

`-mpurecap` compiles every pointer as a bounded capability (stack objects, globals, string literals,
`malloc` blocks) and runs `main` in user mode with an empty untagged window, so buffer overflows,
writes through read-only views and dereferences of forged pointers trap in hardware. All 86 C tests
pass in purecap mode (93/93 with the 7 fault tests, `-O` and `-O0`); benchmark overhead is +0.005% to
+3.5% cycles. See `cc/README.md` and `cc/ABI.md` §8.

v6 purecap hardening (each on by default, with an opt-out flag): sub-object bounds (`&s.field` narrowed to
the member) and **function-pointer sentries** — every function pointer (`&f`, decay, static initialisers,
vtable-style tables) is a sealed entry capability (`csealentry`), indirect calls are `cjalr` (which unseals
it into the PCC), so offsetting, retargeting, dereferencing or writing through a function pointer, calling
a forged (integer) one, or calling a data pointer all trap (`cc/tests/purecap/04x_sentry_*`, `-fno-sentries`
to turn it off). The ISA gained a true `cmove` (CAP func 18) so sealed values can be copied between registers.

`-O` also inlines small static functions (`cc/compiler/inline.py`; `-fno-inline` turns it off):
dhrystone −9.9% and int128 −11.7% RTL cycles, coremark-lite −1.2%; 172/172 C tests, fuzz 500/500.
