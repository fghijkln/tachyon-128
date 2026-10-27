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
* **v5 inlining** (`compiler/inline.py`, disable with `-fno-inline`): calls to small static
  functions in the same unit (≤ 40 IR instructions, ≤ 8 scalar parameters, scalar/void return, not
  variadic, not directly recursive, no jump tables) are spliced into the caller before optimisation —
  callee vregs and labels renamed, callee frame objects moved into a slot of the caller's frame,
  arguments and the return value passed directly instead of through `a0`–`a7` — so the caller's
  optimiser sees through them; callees inline bottom-up (nested), and a static function whose every
  call was inlined disappears at link time
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
| C tests (`cc/tests/c`, reference output from host gcc) | `python3 cc/tests/run_tests.py --both` | 86 programs × {`-O`, `-O0`} = 172/172 |
| differential fuzzing (random UB-free programs, `randprog.py`) | `python3 cc/tests/fuzz.py N [SEED] [-O0]` | see below |
| purecap C tests + capability-fault tests | `python3 cc/tests/run_tests.py --purecap [-O0] [--rtl]` | 96/96 (`-O`), 96/96 (`-O0`) |
| benchmarks (golden + RTL, commit-trace checked) | `python3 cc/bench/run_bench.py [--rtl] [--both] [--purecap]` | 6/6 |

`gen_expected.py` regenerates `cc/tests/expected/*.out` with the host compiler
(`-fsigned-char -fwrapv`); tests that depend on TACHYON-128 specifics ship a hand-written
`*.out.manual`. Test 085 cross-checks every pointer-free size/alignment/offset/bit-field layout of
`ABI.md` §1 against the host.

The fuzzer generates csmith-style programs over all 12 integer types (incl. `__int128`),
bit-field structs, pointers, helper functions with stack-passed arguments and loops, and prints
every global at exit; output and exit code must match host gcc exactly. Failing programs are
saved in `cc/tests/fuzz_failures/`.
Latest runs: 500/500 at `-O` with inlining (seeds 1001–1500); 200/200 at `-O0` (v5 stage 1).

## Benchmarks (`cc/bench`)

Cycles from the Verilator RTL model (5-stage pipeline, BTB + RAS, 6-cycle multiplier); every RTL
run is also checked commit-by-commit against the golden model. `-O`:

| benchmark | what | retired | cycles | CPI | image |
|---|---|---:|---:|---:|---:|
| fib | recursive `fib(20)` | 372,851 | 395,465 | 1.061 | 3.6 KB |
| sieve | Byte sieve, 8190 flags × 3 | 430,285 | 471,347 | 1.095 | 11.6 KB |
| qsort | quicksort of 2000 ints + checksum | 344,836 | 441,403 | 1.280 | 11.8 KB |
| dhrystone | Dhrystone-like (records, strings, enums) | 284,996 | 353,651 | 1.241 | 15.8 KB |
| coremark_lite | list/matrix/state-machine/CRC kernels | 281,681 | 393,223 | 1.396 | 8.5 KB |
| int128 | 128-bit factorial, mul/div/mod | 46,404 | 151,473 | 3.264 | 4.3 KB |

(v5 word ops + inlining, `results_inline.json`; earlier numbers in `results_baseline.json` /
`results_opt.json` / `results_word.json`.) Effect of inlining (RTL cycles, `-fno-inline` → default):

| benchmark | no inlining | inlining | change | call sites inlined |
|---|---:|---:|---:|---|
| fib | 395,591 | 395,465 | −0.03% | libc only (`fib` itself is recursive) |
| sieve | 471,447 | 471,347 | −0.02% | libc only |
| qsort | 441,851 | 441,403 | −0.10% | libc only |
| dhrystone | 392,389 | 353,651 | **−9.9% (1.11×)** | 10 (`Func_1`, `Func_3`, `Proc_2..7`) |
| coremark_lite | 397,861 | 393,223 | −1.2% | 8 (`crc16` ×6, `list_find`, `list_reverse`) |
| int128 | 171,545 | 151,473 | **−11.7% (1.13×)** | 6 (`mulmod` ×3, `powmod`, `put` ×2) |

Images grow by 0.5–1 KB, mostly from libc's static helpers inlined into `printf`.

`int128` is dominated by the iterative multiplier/divider; `coremark_lite` and `dhrystone` by
data-dependent branches and load-use pairs.

## Pure-capability mode (`-mpurecap`)

```sh
python3 cc/tcc128.py prog.c -mpurecap --run           # every pointer a bounded capability
python3 cc/tests/run_tests.py --purecap [--rtl]       # 86 C tests + 7 capability-fault tests
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
| 008_subobject_overflow | copy 10 bytes into an 8-byte member array (would overwrite the next field) | cause 3 |
| 009_va_overread | `va_arg` past the arguments actually passed (9 claimed, 2 passed) | cause 3 |
| 010_stack_exhaustion | unbounded recursion reaches the bottom of the 128 KiB stack region | cause 3 |

Results: `run_tests.py --purecap` **93/93 at `-O` and 93/93 at `-O0`** — all 86 normal C tests pass
unmodified in purecap mode (none excluded) plus the 7 fault tests; every purecap test also matches the
RTL model commit-by-commit (`--rtl`). The runner additionally audits the golden model and fails a test
on any RAM access through an untagged base (none occur). Purecap fuzzing: 350/350 at `-O`
(seeds 2001–2350) and 200/200 at `-O0` (seeds 2001–2200).

Overhead (`-O` without inlining, as measured for stage 2, RTL cycles, `results_purecap.json`):

| benchmark | default | purecap | overhead | image |
|---|---:|---:|---:|---:|
| fib | 395,591 | 395,700 | +0.03% | +464 B |
| sieve | 471,447 | 471,548 | +0.02% | +480 B |
| qsort | 441,851 | 442,156 | +0.07% | +512 B |
| dhrystone | 392,389 | 405,978 | +3.46% | +848 B |
| coremark_lite | 397,861 | 397,880 | +0.005% | +640 B |
| int128 | 171,545 | 172,331 | +0.46% | +512 B |

With inlining on both sides (`results_purecap_inline.json`): fib 395,585 (+0.03%), sieve 471,456
(+0.02%), qsort 441,692 (+0.07%), dhrystone 363,336 (+2.7%), coremark_lite 392,748 (−0.1%), int128
152,206 (+0.5%). Purecap fuzzing with inlining: 100/100 (seeds 2351–2450).

The overhead is small because the data model does not change (pointers are already 128 bits) and the
capability instructions are single-cycle ALU ops; the cost is the `csetbnd` at each address-taking
site and the bounded `la` sequence for globals (dhrystone takes many global/record addresses).

### Purecap hardening (v6)

Each is on by default under `-mpurecap` and has an opt-out flag (also an environment variable, as
used by the test scripts). Exact rules: [`ABI.md`](ABI.md) §8.1.

* **Sub-object bounds** (`-fno-subobject-bounds` / `TCC128_NO_SUBOBJECT=1`): `&s.field`, `&p->m`
  and a member array that decays to a pointer (`s.name`, `p->buf`) are narrowed with `csetbnd(i)` to
  the member itself, so overflowing a member array into the next field traps (cause 3) instead of
  corrupting it. Not narrowed: flexible array members (`char data[]`, bounded by the allocation), the
  `offsetof` idiom `&((T *)0)->m` (an integer, not a capability) and constant in-bounds indexing
  `s.arr[3]` (statically safe, so no `csetbnd` is emitted). `container_of`-style code that steps back
  from a member to its enclosing struct now traps; `073_ptr_arith_struct` does exactly that, so its
  purecap expectation (`cc/tests/expected/073_ptr_arith_struct.out.purecap`) is the cause-3 trap, and
  it passes unchanged with `-fno-subobject-bounds`. Test: `purecap/008_subobject_overflow`.
* **Bounded stack** (`-fno-stack-bounds` / `TCC128_NO_STACK=1`): `sp` is a capability for the
  128 KiB stack region `[0x20000, 0x40000)` only (was all of RAM), so stack exhaustion traps at the
  region's bottom instead of overwriting the heap, and no stack-derived pointer reaches globals or
  the heap; the purecap heap is limited to below the region. **va_list bounds**: the caller of a
  variadic function passes its stack-argument byte count in scratch `r62`, and the callee bounds its
  va_list to exactly the passed arguments, so a format/argument mismatch traps instead of reading
  the caller's frame. Tests: `purecap/009_va_overread`, `purecap/010_stack_exhaustion`.
  Per-frame narrowing of `sp` itself is deliberately not done (every escaping stack pointer is
  already bounded to its object; see `ABI.md` §8.1).

## Limitations

* No floating point (`float`/`double` are rejected), no `long double`, no complex.
* No variable-length arrays, no `alloca`, no `setjmp`/`longjmp`; `_Thread_local` is accepted and ignored (single-threaded).
* Pointers are plain integers in the default (hybrid) mode; `-mpurecap` makes them capabilities but has
  the v6 hardening limits are listed in "Purecap hardening (v6)" above.
* Brace elision in initialisers is supported only for the simple cases.
* `long long` is 64-bit (LP64 compatibility); 128-bit arithmetic needs `__int128`.
* One compilation per invocation produces a whole linked program (no separate object files).
* The optimiser is simple: inlining only of small static functions in the same unit (no
  cross-unit or heuristic/profile-driven inlining), no global value numbering, no loop
  induction-variable strength reduction. (v5: 32-bit `int` arithmetic uses the ISA's word ops;
  8/16-bit types still re-normalise with a shift pair.)
