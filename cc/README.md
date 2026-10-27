# tcc128 — a C compiler for TACHYON-128

`tcc128` is a small optimising C compiler written in Python that targets the TACHYON-128 ISA
(`SPEC.md`). It produces assembly for `tools/asm.py`, links its own freestanding libc, and can
run the result on the golden simulator (`tools/sim.py`) or on the Verilator RTL model.
The calling convention and data model are specified in [`ABI.md`](ABI.md).

## Usage

```sh
python3 cc/tcc128.py prog.c                     # -> prog.s (program + libc, ready to assemble)
python3 cc/tcc128.py prog.c -o out.s
python3 cc/tcc128.py a.c b.c --run              # compile, assemble, run on the golden simulator
python3 cc/tcc128.py prog.c --run --stats       # ... and print retired instructions / image size
python3 cc/tcc128.py prog.c --hex prog.hex      # 128-bit-word hex image for the RTL testbench
```

Options: `-I dir`, `-D name[=value]`, `-O0` (no IR optimisation), `--nolibc`, `--max N`
(simulator instruction limit), `--bin file`, `--hex file`. The exit status of `--run` is the
program's `exit()` code. Errors are reported as `file:line:col: message`.

From Python: `from tcc128 import compile_files, assemble, run_sim`.

## Pipeline

`compiler/preproc.py` (preprocessor) → `lexer.py` → `parser.py` (types, semantic checks,
constant expressions, initialisers) → `ir.py` (three-address IR on virtual registers; scalar locals
whose address is never taken live in vregs) → `opt.py` → `backend.py` (liveness, linear-scan
register allocation, emission) → `driver.py` (per-unit symbol mangling, linking with libc,
dead-function elimination).

### Optimisations (`-O`, the default)

* constant propagation into immediates, constant folding, algebraic simplification
* redundant sign/zero-extension removal (demanded-bits) and copy propagation, retargeting, DCE
* jump threading / unreachable-code removal
* block-local common-subexpression elimination (pure ops)
* loop-invariant constant/address hoisting (`li`/`la` moved to the loop preheader, duplicates merged)
* load-use bubble filling (an independent ALU op is moved between a load and its first use)
* register allocation: values that are *live* across a call (exact liveness, not interval
  overlap) get callee-saved registers, everything else caller-saved; short-lived values that
  only feed / come from an argument register are allocated directly in `a0`–`a7`, so the copies
  disappear

Effect on the benchmarks (golden-model instruction counts and RTL cycles, baseline = the compiler
before the last four items above):

| benchmark | retired before | retired after | RTL cycles before | RTL cycles after | speed-up |
|---|---:|---:|---:|---:|---:|
| coremark_lite | 377,907 | 310,593 | 488,738 | 418,333 | 1.17× |
| dhrystone | 357,578 | 328,654 | 437,943 | 405,284 | 1.08× |
| fib(20) | 515,285 | 438,671 | 537,844 | 461,281 | 1.17× |
| int128 | 100,485 | 69,003 | 205,758 | 174,248 | 1.18× |
| qsort (2000) | 488,141 | 439,689 | 586,513 | 533,928 | 1.10× |
| sieve (3×8190) | 954,178 | 641,488 | 999,072 | 682,543 | 1.46× |

## Language coverage

* All integer types: `_Bool`, `char` (signed), `short`, `int`, `long` and `long long` (64-bit),
  `__int128` / `unsigned __int128` (native register width), `enum`; full integer promotions and
  usual arithmetic conversions, wrapping arithmetic, truncation on store/convert.
* Pointers (16 bytes, plain 128-bit addresses), arrays, multi-dimensional arrays, pointer
  arithmetic and comparison, function pointers, arrays of function pointers, vtables.
* `struct` / `union` (nested, anonymous members, flexible array members, bit-fields with
  GCC/SysV layout), struct assignment, pass and return by value (any size), compound literals,
  designated and nested initialisers, `sizeof`, `_Alignof`, `offsetof`.
* All statements: `if`, `for`, `while`, `do`, `switch` (dense switches become jump tables),
  `break`/`continue`, `goto` and labels, `return`; block scopes and shadowing.
* Functions: prototypes, K&R definitions, implicit declarations, recursion, `static` locals and
  functions, variadic functions (`<stdarg.h>`: `va_start`, `va_arg` for every integer/pointer type
  incl. `__int128`, `va_copy`, `va_end`), more than 8 arguments (stack-passed).
* Qualifiers `const`, `volatile` (volatile accesses are never removed or merged), `typedef`,
  `extern`, `static`, `register`, `inline` (accepted).
* Preprocessor: `#include` ("..." and <...>, `-I`), object/function-like macros, `#`, `##`,
  `__VA_ARGS__` (incl. GNU `, ## __VA_ARGS__`), `#if/#ifdef/#ifndef/#elif/#else/#endif`,
  `defined`, `#error`, `#pragma once`, `__LINE__`/`__FILE__`.
* Literals: decimal/hex/octal with `u`/`l`/`ll` suffixes, `i128`/`ui128` suffixes, character and
  string literals with escapes, adjacent string concatenation.

### libc (`cc/lib`, headers in `cc/include`)

`printf`/`fprintf`/`sprintf`/`snprintf`/`vprintf`/`vsprintf`/`vsnprintf` (`%d %i %u %x %X %o %c %s
%p %%`, length modifiers `hh h l ll z`, flags `- 0 + #`, width, precision), `putchar`, `puts`,
`getchar`, `malloc`/`calloc`/`realloc`/`free`, `qsort`, `bsearch`, `strtol`/`strtoul`/`atoi`/`atol`,
`abs`/`labs`/`llabs`, `rand`/`srand`, `exit`/`abort`, `assert`, the `<string.h>` and `<ctype.h>`
staples, and `tx128.h` (MMIO console, cycle/instret counters, `tx_put_u128`/`tx_put_i128`).

## Testing

| suite | command | result |
|---|---|---|
| C tests (`cc/tests/c`, reference output from host gcc) | `python3 cc/tests/run_tests.py --both` | 85 programs × {`-O`, `-O0`} = 170/170 |
| differential fuzzing (random UB-free programs, `randprog.py`) | `python3 cc/tests/fuzz.py N [SEED] [-O0]` | see below |
| benchmarks (golden + RTL, commit-trace checked) | `python3 cc/bench/run_bench.py [--rtl] [--both]` | 6/6 |

`gen_expected.py` regenerates `cc/tests/expected/*.out` with the host compiler
(`-fsigned-char -fwrapv`); tests that depend on TACHYON-128 specifics ship a hand-written
`*.out.manual`. Test 085 cross-checks every pointer-free size/alignment/offset/bit-field layout of
`ABI.md` §1 against the host.

The fuzzer generates csmith-style programs over all 12 integer types (incl. `__int128`),
bit-field structs, pointers, helper functions with stack-passed arguments and loops, and prints
every global at exit; output and exit code must match host gcc exactly. Failing programs are
saved in `cc/tests/fuzz_failures/`.

## Benchmarks (`cc/bench`)

Cycles from the Verilator RTL model (5-stage pipeline, BTB + RAS, 6-cycle multiplier); every RTL
run is also checked commit-by-commit against the golden model. `-O`:

| benchmark | what | retired | cycles | CPI | image |
|---|---|---:|---:|---:|---:|
| fib | recursive `fib(20)` | 438,671 | 461,281 | 1.052 | 3.0 KB |
| sieve | Byte sieve, 8190 flags × 3 | 641,488 | 682,543 | 1.064 | 11.3 KB |
| qsort | quicksort of 2000 ints + checksum | 439,689 | 533,928 | 1.214 | 11.5 KB |
| dhrystone | Dhrystone-like (records, strings, enums) | 328,654 | 405,284 | 1.233 | 15.7 KB |
| coremark_lite | list/matrix/state-machine/CRC kernels | 310,593 | 418,333 | 1.347 | 8.1 KB |
| int128 | 128-bit factorial, mul/div/mod | 69,003 | 174,248 | 2.525 | 3.9 KB |

`results_baseline.json` / `results_opt.json` hold the raw numbers.
`int128` is dominated by the iterative multiplier/divider; `coremark_lite` and `dhrystone` by
data-dependent branches and load-use pairs.

## Limitations

* No floating point (`float`/`double` are rejected), no `long double`, no complex.
* No variable-length arrays, no `alloca`, no `setjmp`/`longjmp`; `_Thread_local` is accepted and ignored (single-threaded).
* Capability (CHERI-style) pointers are not generated; pointers are plain integers in hybrid mode
  (`ABI.md` §8 sketches a future purecap mode).
* Brace elision in initialisers is supported only for the simple cases.
* `long long` is 64-bit (LP64 compatibility); 128-bit arithmetic needs `__int128`.
* One compilation per invocation produces a whole linked program (no separate object files).
* The optimiser is intra-procedural and simple: no inlining, no global value numbering, no loop
  induction-variable strength reduction; 32-bit `int` arithmetic needs a re-sign-extension
  (`slli`/`srai` pair) after operations that can overflow because the ISA has no 32-bit ops.
