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

Options: `-I dir`, `-D name[=value]`, `-O0` (no IR optimisation), `-mpurecap` (pure-capability code,
see below), `--nolibc`, `--max N`
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
* **v5 word ops**: `int`/`unsigned` arithmetic whose result must be re-normalised is emitted as one
  32-bit word instruction (`addw`/`addiw`/`subw`/`mulw`/`sllw`/`slliw`/`divw`, zero-extending
  `addwu`/`subwu`/`mulwu`/`sllwu` for `unsigned`) instead of the operation plus a `slli`/`srai` pair
  (`opt.fuse_word_ops`, run last; `sll` by a register and `div` only fuse when the C operation itself is
  32-bit); any remaining 32-bit sign/zero extension is a single `sext.w`/`zext.w`
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
| purecap C tests + capability-fault tests | `python3 cc/tests/run_tests.py --purecap [-O0] [--rtl]` | 92/92 (`-O`), 92/92 (`-O0`) |
| benchmarks (golden + RTL, commit-trace checked) | `python3 cc/bench/run_bench.py [--rtl] [--both] [--purecap]` | 6/6 |

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
| fib | recursive `fib(20)` | 372,986 | 395,591 | 1.061 | 2.8 KB |
| sieve | Byte sieve, 8190 flags × 3 | 430,393 | 471,447 | 1.095 | 10.8 KB |
| qsort | quicksort of 2000 ints + checksum | 345,340 | 441,851 | 1.279 | 11.0 KB |
| dhrystone | Dhrystone-like (records, strings, enums) | 316,298 | 392,389 | 1.241 | 15.1 KB |
| coremark_lite | list/matrix/state-machine/CRC kernels | 286,704 | 397,861 | 1.388 | 7.6 KB |
| int128 | 128-bit factorial, mul/div/mod | 66,362 | 171,545 | 2.585 | 3.6 KB |

(after v5 word ops; earlier numbers in `results_baseline.json` / `results_opt.json` /
`results_word.json`.)

`int128` is dominated by the iterative multiplier/divider; `coremark_lite` and `dhrystone` by
data-dependent branches and load-use pairs.

## Pure-capability mode (`-mpurecap`)

```sh
python3 cc/tcc128.py prog.c -mpurecap --run           # every pointer a bounded capability
python3 cc/tests/run_tests.py --purecap [--rtl]       # 85 C tests + 7 capability-fault tests
python3 cc/tests/fuzz.py 200 2001 -mpurecap [-O0]
python3 cc/bench/run_bench.py --rtl --purecap
```

Every pointer is a tagged capability: stack objects whose address is taken, globals, string
literals and `malloc` blocks get exact bounds (`csetbnd`), static pointer initialisers are rebuilt by
crt0 from a capability relocation table, pointer arithmetic is `cincaddr`, and all 16-byte accesses
are `clc`/`csc`. `main` runs in **user mode with an empty untagged window**, so even a pointer forged
from an integer cannot be dereferenced. Details and the exact rules: [`ABI.md`](ABI.md) §8.
`__builtin_cheri_{bounds_set,address_set,perms_and,tag_get,length_get,base_get,perms_get}` are
available in both modes.

Hardware-caught violations (`cc/tests/purecap/`, expected output with addresses as `<A>` placeholders;
the trap handler prints the cause and faulting address, exit code 128 + cause):

| test | violation | trap |
|---|---|---|
| 001_stack_overflow | write `buf[16]` of a 16-byte stack array | cause 3 (bounds) |
| 002_heap_overflow | `memset(malloc(20), …, 21)` (block is 32 bytes, capability 20) | cause 3 |
| 003_global_overflow | read past a string literal reached via a static pointer table | cause 3 |
| 004_readonly | store through a view with `PERM_STORE` removed | cause 4 (permission) |
| 005_provenance | out-of-bounds cursor keeps its tag, int arithmetic clears it, `memcpy`/`qsort` keep tags | no trap |
| 006_forged_pointer | dereference a pointer rebuilt from its integer address | cause 9 (untagged access in user mode) |
| 007_use_after_bounds | write `arr[-1]` (underflow) | cause 3 |

Results: `run_tests.py --purecap` **92/92 at `-O` and 92/92 at `-O0`** — all 85 normal C tests pass
unmodified in purecap mode (none excluded) plus the 7 fault tests; every purecap test also matches the
RTL model commit-by-commit (`--rtl`). The runner additionally audits the golden model and fails a test
on any RAM access through an untagged base (none occur). Purecap fuzzing: 350/350 at `-O`
(seeds 2001–2350) and 200/200 at `-O0` (seeds 2001–2200).

Overhead (`-O`, RTL cycles, `results_purecap.json`):

| benchmark | default | purecap | overhead | image |
|---|---:|---:|---:|---:|
| fib | 395,591 | 395,700 | +0.03% | +464 B |
| sieve | 471,447 | 471,548 | +0.02% | +480 B |
| qsort | 441,851 | 442,156 | +0.07% | +512 B |
| dhrystone | 392,389 | 405,978 | +3.46% | +848 B |
| coremark_lite | 397,861 | 397,880 | +0.005% | +640 B |
| int128 | 171,545 | 172,331 | +0.46% | +512 B |

The overhead is small because the data model does not change (pointers are already 128 bits) and the
capability instructions are single-cycle ALU ops; the cost is the `csetbnd` at each address-taking
site and the bounded `la` sequence for globals (dhrystone takes many global/record addresses).

## Limitations

* No floating point (`float`/`double` are rejected), no `long double`, no complex.
* No variable-length arrays, no `alloca`, no `setjmp`/`longjmp`; `_Thread_local` is accepted and ignored (single-threaded).
* Pointers are plain integers in the default (hybrid) mode; `-mpurecap` makes them capabilities but has
  no sub-object bounds, no temporal safety (`free` does not revoke) and an all-RAM stack capability
  (only address-taken stack objects are bounded).
* Brace elision in initialisers is supported only for the simple cases.
* `long long` is 64-bit (LP64 compatibility); 128-bit arithmetic needs `__int128`.
* One compilation per invocation produces a whole linked program (no separate object files).
* The optimiser is intra-procedural and simple: no inlining, no global value numbering, no loop
  induction-variable strength reduction. (v5: 32-bit `int` arithmetic uses the ISA's word ops;
  8/16-bit types still re-normalise with a shift pair.)
