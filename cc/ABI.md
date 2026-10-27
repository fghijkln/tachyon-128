# tcc128 C ABI for TACHYON-128

This document defines how C maps onto TACHYON-128 for code produced by `cc/tcc128.py` and for
hand-written assembly that wants to call, or be called by, it. It follows the register roles
already named in `SPEC.md` §1.2 and adds what a compiler needs.

## 1. Data model

| C type | size (bytes) | alignment | in a register |
|---|---|---|---|
| `_Bool` | 1 | 1 | 0 or 1 |
| `char` (signed), `signed char`, `unsigned char` | 1 | 1 | sign/zero-extended to 128 bits |
| `short`, `unsigned short` | 2 | 2 | sign/zero-extended |
| `int`, `unsigned int`, `enum` | 4 | 4 | sign/zero-extended |
| `long`, `unsigned long` | 8 | 8 | sign/zero-extended |
| `long long`, `unsigned long long` | 8 | 8 | sign/zero-extended |
| `__int128`, `unsigned __int128` | 16 | 16 | the whole register |
| any pointer (data or function) | 16 | 16 | the whole register (zero-extended address) |
| `size_t` = `unsigned long`, `ptrdiff_t` = `long`, `intptr_t`/`uintptr_t` = `(unsigned) __int128` | | | |

* Plain `char` is **signed**. Byte order is little-endian. There is no floating point.
* Pointers are **plain 128-bit integers** (untagged, hybrid mode, `SPEC.md` §4.3): the whole
  128-bit address space is reachable, e.g. the MMIO page at `2^128 - 0x10000` is simply a pointer
  constant (`cc/include/tx128.h`). Capability pointers are not used by default (see §8).
* `long` and `long long` are both 64-bit so that ordinary C code that assumes LP64 keeps working;
  the native 128-bit integer is `__int128`. Literals with the suffix `i128` / `ui128` have that type.
* Struct and union members are laid out in order at their natural alignment; the aggregate's
  alignment is its strictest member's, its size a multiple of that. Bit-fields are allocated
  LSB-first inside a storage unit of the declared type's size; a field that would straddle a unit
  starts a new one; `: 0` aligns to the next unit (GCC/SysV compatible for the int-sized cases).
* **Canonical register form.** Every integer value narrower than 128 bits is kept in its register
  sign-extended (signed types) or zero-extended (unsigned types, pointers, `_Bool`) to 128 bits.
  Callers and callees may rely on this for arguments and return values, which lets comparisons,
  divisions and right shifts use the native 128-bit instructions directly.

## 2. Registers

| Register | ABI name | Role | Saved by |
|---|---|---|---|
| r0 | `zero` | constant 0 | — |
| r1 | `ra` | return address (`call` = `jal ra`, return = `jalr zero, ra`) | caller |
| r2 | `sp` | stack pointer, 16-byte aligned at every call | callee (restored) |
| r3 | `gp` | reserved (unused by tcc128; never touched) | — |
| r4–r11 | `a0`–`a7` | arguments 1–8; `a0` holds the return value | caller |
| r12–r27 | `t0`–`t15` | temporaries | caller |
| r28–r43 | `s0`–`s15` | saved registers | **callee** |
| r44–r53 | (`s16`–`s25`) | additional saved registers | **callee** |
| r54–r58 | (`t16`–`t20`) | additional temporaries | caller |
| r59–r62 | — | compiler scratch (spill reloads, large offsets, jump tables); clobbered freely | caller |
| r63 | `rc` | root capability; **never written or read by compiled code** | — |

The register allocator uses r12–r27 and r54–r58 for values that do not live across a call and
r28–r53 for values that do (or when the caller-saved pool is exhausted). Leaving `rc` untouched
means a C program can be run under a kernel that later revokes or narrows it.

## 3. Calls

* Arguments are assigned, left to right, to `a0`…`a7`; the 9th and later arguments go on the
  stack, one **16-byte slot** each, at `0(sp)`, `16(sp)`, … at the moment of the call (the caller
  reserves this area at the bottom of its frame).
* Every scalar argument occupies a full register/slot in canonical form (§1), after the usual C
  conversions to the parameter type (or the default argument promotions for unprototyped and
  variadic arguments).
* **Structs and unions are passed by invisible reference**: the caller makes a private copy in its
  own frame and passes the copy's address as the argument; the callee may modify it freely.
* **Struct return**: the caller passes the address of a result buffer as a hidden first argument
  in `a0` (shifting the visible arguments by one); the callee writes the result there and returns
  the same address in `a0`. Scalars are returned in `a0`.
* **Variadic functions** use the same convention as ordinary calls. A variadic callee stores
  `a0`–`a7` into a 128-byte save area directly below its incoming stack arguments, so all
  arguments form one contiguous array of 16-byte slots; `va_list` is a `char *` into that array
  and `va_arg(ap, T)` reads `T` from the current slot and advances by 16. (Struct arguments
  to variadic functions are not supported.)

## 4. Stack frame

The stack grows down from the top of RAM (`crt0` sets `sp = 0x40000`). A function's frame,
from the incoming `sp` downwards (all offsets 16-byte aligned):

```
 incoming sp + 16*k   stack argument k+8 (caller's outgoing area)
 ---------------------------------------- incoming sp
   va save area (a0..a7), variadic functions only  (128 bytes)
   ra (if the function makes calls)
   callee-saved registers used by the function (16 bytes each)
   spill slots (16 bytes each)
   local variables (arrays, structs, address-taken scalars, struct-argument copies)
   outgoing stack-argument area (16 bytes per argument beyond the 8th)
 ---------------------------------------- sp (after the prologue)
```

The prologue is `addi sp, sp, -F` followed by `sq` of `ra` and the used callee-saved registers;
the epilogue reverses it and returns with `ret`. There is no frame pointer (frames have a fixed
size; VLAs/`alloca` are not supported). Scalars whose address is never taken live only in
registers.

## 5. Program start-up, exit and memory map

* `cc/lib/crt0.s` is placed at address 0 (reset PC): it sets `sp`, calls `main(0, NULL)` and then
  `exit(return value)`.
* `exit(code)` stores `code` to the EXIT MMIO register (`2^128 - 0x10000 + 0x10`), which halts the
  machine with that exit code; the simulator and the RTL testbench report it.
* Image layout: start-up code, text, read-only and initialised data, zero-initialised data (emitted
  as zero bytes), then the linker label `_end`. `malloc` is a bump allocator growing up from `_end`
  to `0x40000 - 16 KiB`; the stack grows down from `0x40000`.

## 6. Symbols

C identifier `foo` becomes assembly label `_foo`; file-scope `static` objects/functions get
`_S<unit>_foo`, block-scope statics `_L<unit>_<n>_foo`, string literals `_A<unit>_<n>`, compiler
labels `__L<unit>_<fn>_<n>`. (These keep every label a valid `tools/asm.py` expression symbol.)
Because `tools/asm.py` assembles one source file, the driver links by concatenating the start-up
code with every *reachable* function and object of all translation units and the C library.

## 7. Console and library

`putchar` stores a byte to the CONSOLE MMIO register. `printf` supports `%d %i %u %x %X %o %c %s %p %%`
with flags `- 0 + space #`, width, precision, `*`, and the length modifiers `hh h l ll z t j`, plus
`L`/`q` for 128-bit integers (`%Ld`, `%Lu`, `%Lx`) — an extension, since there is no `long double`.

## 8. Capabilities (future mode)

The default ABI never creates tagged values, so programs run identically whether or not the
kernel restricts `rc`. A pure-capability mode (pointers as tagged 128-bit capabilities derived
from `rc`, `clc`/`csc` for pointer loads/stores, bounds set by `csetbnd` at `malloc`/`&` sites)
would keep the same register roles and frame layout; it is not implemented yet.
