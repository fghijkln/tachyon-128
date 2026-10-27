# C compiler

TACHYON-128 has a C compiler, **tcc128** (Python): see [`cc/README.md`](cc/README.md) for usage,
features, test/fuzz/benchmark results and limitations, and [`cc/ABI.md`](cc/ABI.md) for the
calling convention and data model.

```sh
python3 cc/tcc128.py prog.c --run          # compile + run on the golden simulator
python3 cc/tests/run_tests.py --both       # C test suite (-O and -O0)
python3 cc/bench/run_bench.py --rtl        # benchmarks with RTL cycles/CPI
```
