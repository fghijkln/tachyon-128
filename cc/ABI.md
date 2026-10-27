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
r28–r53 for values that do (or when the caller-saved pool is exhausted). A value whose whole
lifetime is a short staging window inside one basic block (an argument computed for the next call,
an incoming argument or call result consumed before anything else touches that register) may also
live directly in `a0`–`a7`; this is invisible at call boundaries. Leaving `rc` untouched
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

## 8. Pure-capability mode (`-mpurecap`)

The default ABI never creates tagged values, so programs run identically whether or not the
kernel restricts `rc`. `-mpurecap` (predefines `__PURECAP__` and `__CHERI_PURE_CAPABILITY__`) keeps the
same data model, register roles and frame layout (pointers were already 16 bytes), but every pointer is
a tagged capability and every memory access goes through one:

* **Roots** (`cc/lib/crt0_purecap.s`): `gp` = RAM capability `[0, 256 KiB)` derived from `rc` with
  `PERM_ALL & ~(EXEC|SEAL|UNSEAL|CINVOKE)` (0x59B); `sp` = the stack-region capability `[0x20000, 0x40000)`
  with its cursor at the top of RAM (v6, §8.1; whole-RAM `gp` under `-fno-stack-bounds`); the
  PCC is narrowed to the code image `[0, __end)` with EXEC|LOAD|LOAD_CAP|GLOBAL. `__tx_mmio` holds a
  capability for the 64 KiB MMIO page (`tx128.h` builds `TX_CONSOLE`/`TX_EXIT`/... from it).
* **User mode, empty untagged window**: crt0 sets `ubase = ubound = 0` and enters `main` with `eret`
  (status.PU), so any load/store through an *untagged* base (a pointer rebuilt from an integer) is a
  privilege violation (cause 9). Hardware therefore enforces that purecap code touches memory only via
  capabilities.
* **Bounds** (`csetbndi`/`csetbnd`): `&local` / arrays on the stack are bounded to the frame object;
  globals and string literals to the object (`la` → `csetaddr gp` → `csetbnd`); `malloc(n)` returns a
  capability of exactly `n` bytes (`realloc`/`free` re-derive the header from the allocator's own
  capability); jump tables are read through a capability bounded to the table. Initialised pointer
  slots in static data (`const char *words[] = {...}`) are rebuilt at start-up from the linker's
  `__cap_relocs` table `{slot, target, size, addend}` (size −1 = function, derived from the user code
  capability and sealed as a sentry, §8.1).
* **Code generation**: pointer arithmetic is `cincaddr`/`cincaddri` (keeps the tag; integer `add`
  would clear it); every 16-byte load/store is `clc`/`csc` so pointers, `uintptr_t` and struct copies
  keep their tags (word-aligned `memcpy`/`qsort` swaps move whole 16-byte granules); register moves are
  `cmove` (v6: a real instruction that copies sealed capabilities too); function pointers come from
  `cgetpcc` + `csetaddr` and are sealed as sentries (§8.1); indirect calls are `cjalr ra, fp`.
* **Intrinsics** (also accepted, as no-ops/plain values, in the default mode):
  `__builtin_cheri_bounds_set(p, n)`, `address_set(p, a)`, `perms_and(p, m)`, `tag_get(p)`,
  `length_get(p)`, `base_get(p)`, `perms_get(p)`.
* **Faults**: `tvec = __tx_trap` prints `*** capability trap (hardware): cause=N <tval>` and exits
  with `128 + cause` (3 = bounds, 4 = permission, 9 = untagged access in user mode).
* **Hardening** (v6, §8.1): sub-object bounds, bounded stack region, va_list bounds, function-pointer sentries.

### 8.1 Purecap hardening (v6)

**Sub-object bounds** (default; `-fno-subobject-bounds` / `TCC128_NO_SUBOBJECT=1` turns it off).
The address of a struct/union member — `&s.m`, `&p->m`, `&s.a.b`, and a member *array* used as a
value (array-to-pointer decay of `s.arr`) — is the enclosing object's capability narrowed with
`csetbnd(i)` to `[member, member + sizeof member)`. Exceptions: a member of size 0 (flexible array
member) keeps the enclosing bounds; an expression rooted at an integer constant (`&((T *)0)->m`, the
`offsetof` macro) is not a capability and is not narrowed; `s.arr[k]` with a constant `k` inside the
array is addressed directly from the enclosing object (no `csetbnd`, it cannot go out of bounds).
Consequences: indexing a member array out of range traps (cause 3) even when the access would land
inside the enclosing struct, and `container_of` (stepping back from a member pointer to the struct)
traps; code that needs it is compiled with `-fno-subobject-bounds`.

**Bounded stack** (default; `-fno-stack-bounds` / `TCC128_NO_STACK=1` turns it off).

* *Stack region*: crt0 derives `sp` as a capability for exactly `[RAM_TOP − 128 KiB, RAM_TOP)` =
  `[0x20000, 0x40000)` instead of the whole-RAM `gp`. Every stack-derived capability (frame objects,
  spill/save slots, va_list) is therefore confined to the stack: runaway recursion traps (cause 3) at
  the bottom of the region instead of running into the heap, and no stack pointer can reach a global
  or a heap block. The purecap allocator keeps the heap below `RAM_TOP − 128 KiB` (default mode:
  16 KiB reserve, unchanged). The linker removes the crt0 block under `-fno-stack-bounds`.
* *va_list bounds*: a call to a variadic (or unprototyped) function sets compiler-scratch `r62` to
  the number of stack-argument bytes it passes (`16 × (nargs − 8)`, or 0) right before the `call`/`jalr`.
  The variadic callee's prologue builds a capability for `[save area, incoming sp + r62)` — the 128-byte
  `a0..a7` save area plus exactly the caller's stack arguments — and keeps it in a 16-byte frame slot
  directly below the save area (the variadic frame grows from 128 to 144 bytes); `va_start` is a cursor
  into it. Reading more arguments than were passed (a format/argument mismatch) traps (cause 3) instead
  of walking into the caller's frame. Calling a variadic function through a non-variadic prototype
  is undefined behaviour in C and leaves `r62` unset (the bounds are then garbage and normally trap).
* *Per-frame `sp` narrowing* (top of `sp` lowered to the frame on every entry) is **not** done: every
  stack pointer that can leave compiler-generated code (`&local`, arrays, struct-argument copies,
  `sret` buffers, va_list) already carries the exact bounds of its object, so narrowing `sp` itself
  would only guard the compiler's own fixed-offset accesses, at the price of saving/restoring `sp`
  around every call (CHERI-RISC-V purecap ABIs likewise bound the stack region, not each frame).

**Function-pointer sentries** (default; `-fno-sentries` / `TCC128_NO_SENTRY=1` turns it off). Every C function
pointer is a *sealed entry capability* (`SPEC.md` §5.1.4, otype `0xFFFF`):

* **Creation.** Taking a function's address (`&f`, or `f` decaying to a pointer, including arguments such as
  `qsort(..., cmp)`) is `cgetpcc` → `csetaddr` → `csealentry`. Static initialisers (`op_t ops[] = {add, sub}`,
  vtable-style `struct { int (*area)(int); } vt[] = {...}`) are capability relocations with size −1; crt0
  derives them from the **user code capability** `[0, __end)` with EXEC|LOAD|LOAD_CAP|GLOBAL (not from the
  supervisor's root PCC it runs under), adds the addend and seals them with `csealentry`.
* **Bounds and permissions.** A sentry carries the bounds and permissions of the program's PCC (the whole code
  image), because compiled code calls other functions with PC-relative `jal`; narrowing a sentry to its own
  function would make those calls fault at fetch. The protection comes from the seal, not from the bounds.
* **Calls.** An indirect call is `cjalr ra, fp`: it accepts a sentry (unsealing it into the PCC) or an unsealed
  code capability, so `ra` receives a sentry link (callees save/restore it with `csc`/`clc` like any 16-byte
  value). Returns stay `ret` (`jalr zero, ra`, address only) because direct `jal` calls produce an untagged link;
  the PCC does not change across a return since every function shares the one code capability.
* **Moves.** Function pointers are copied with `cmove` (CAP func 18), which copies sealed capabilities exactly;
  memory copies (`memcpy`, struct assignment, `qsort` swaps, varargs) use `clc`/`csc` and keep the seal too.
  `uintptr_t` holds the sealed capability unchanged; casting to a narrower integer keeps only the address.
* **What traps** (fault tests `012`–`017`, `011` = legitimate uses): offsetting a function pointer (`(char *)fp + 4`) or retargeting it
  with `__builtin_cheri_address_set` / re-bounding it — modification of a sealed capability, cause 7; loading
  or storing through it as if it were data — dereference of a sealed capability, cause 7; calling a function
  pointer rebuilt from an integer — `cjalr` of an untagged value, cause 2; calling a data pointer cast to a
  function pointer (e.g. "shellcode" in a buffer) — no EXEC permission, cause 4. Comparing, testing for NULL,
  printing (`%p`) and storing function pointers work as before. `__builtin_cheri_type_get(p)` (new) returns
  the otype (`0xFFFF` for a sentry).
