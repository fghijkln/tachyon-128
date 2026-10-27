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
writes through read-only views and dereferences of forged pointers trap in hardware. All 87 C tests
pass in purecap mode (112/112 with the 25 fault tests, `-O` and `-O0`, also trace-matched on the RTL). See `cc/README.md` and `cc/ABI.md` §8.

v6 purecap hardening (each on by default, with an opt-out flag): sub-object bounds (`&s.field` narrowed to
the member) and **function-pointer sentries** — every function pointer (`&f`, decay, static initialisers,
vtable-style tables) is a sealed entry capability (`csealentry`), indirect calls are `cjalr` (which unseals
it into the PCC), so offsetting, retargeting, dereferencing or writing through a function pointer, calling
a forged (integer) one, or calling a data pointer all trap (`cc/tests/purecap/011_sentry_*`–`017_sentry_*`, `-fno-sentries`
to turn it off). The ISA gained a true `cmove` (CAP func 18) so sealed values can be copied between registers.
**Bounded stack** (`-fno-stack-bounds`): `sp` covers only the stack region and `va_list` only the passed
arguments (`purecap/009`, `010`). **Heap temporal safety** (`-fno-revoke`): `free` marks the block in a
hardware revocation bitmap (any access through a capability to it traps with cause 10) and quarantines it;
a full quarantine triggers a sweep (`cloadtags`/`crevtag`) that clears every stale capability before the
memory is reused, so use-after-free, double free, invalid free and stale aliases trap (`purecap/020`–`027`,
`cc/ABI.md` §8.2).

`-O` also inlines small static functions (`cc/compiler/inline.py`; `-fno-inline` turns it off):
dhrystone −9.9% and int128 −11.7% RTL cycles, coremark-lite −1.2%; 172/172 C tests, fuzz 500/500.

v6 optimisation passes 1–8 (default `-O`; `TCC128_DISABLE=<name>` turns one off): base+offset folding,
return-block duplication + shrink-wrapping, local copy propagation + liveness DCE, loop-invariant code
motion, redundant-load elimination, value-range extension elimination, loop strength reduction, and
register-step strength reduction + linear-function test replacement (`cc/tests/c/090_v6_loop_opts`).
Final RTL cycles, v5 → v6 (`python3 cc/bench/run_bench.py --rtl [--purecap]`):

| benchmark | v5 | v6 | change | v6 `-mpurecap` |
|---|---:|---:|---:|---:|
| fib | 395,465 | 296,931 | -24.9% | 297,063 |
| sieve | 471,347 | 406,082 | -13.8% | 471,453 |
| qsort | 441,403 | 420,204 | -4.8% | 429,201 |
| dhrystone | 353,651 | 291,898 | -17.5% | 353,925 |
| coremark_lite | 393,223 | 273,932 | -30.3% | 350,871 |
| int128 | 151,473 | 142,082 | -6.2% | 143,032 |
| malloc_churn | — | 283,091 | — | 907,682 |

Purecap gains less because LICM, value ranges and strength reduction run in default mode only;
`malloc_churn` with revocation costs +40.0% vs `-mpurecap -fno-revoke`. Full tables: README.md "v6 summary".
