# TACHYON-128 Instruction Set Architecture — v3.0

> *"Faster than light, wider than life."*  A 128-bit load/store architecture with hardware
> capabilities, in-register SIMD lanes and wide-immediate constant fusion.

---

## 中文摘要（Chinese summary）

**TACHYON-128（超光速子-128）** 是一个从零设计、真实可运行的 128 位 CPU 架构：

- **原生 128 位**：64 个 128 位通用寄存器（r0 恒为 0），128 位程序计数器，128 位虚拟地址空间。
- **定长 32 位指令编码**：6 位操作码 + 三个 6 位寄存器字段 + 8 位功能码。选 32 位而不是 64 位，是因为三个 6 位寄存器字段在 32 位里放得下，代码密度高一倍；128 位大常数很少见，用“宽立即数拼接”（`wli`/`wins`，每条装入 16 位、可选 8 个槽位）解决，最多 8 条、通常 1–3 条。
- **整数运算**：加减、逻辑、移位、比较、min/max、clz/ctz/popcnt；**128 位乘除**（`mul`/`mulhu`/`div`/`divu`/`rem`/`remu`，RISC-V 风格的除零/溢出语义）。
- **访存**：8/16/32/64/128 位 load/store（含有符号/无符号扩展），要求自然对齐。
- **三大“科幻但可靠”的特色（全部在 RTL 中实现并验证）**：
  1. **硬件能力指针（CHERI 风格）**：每个寄存器带隐藏的 tag 位 + 权限 + 基址 + 上界（“胖寄存器”）。经过带 tag 的指针访存时，硬件检查权限和边界；能力只能单调缩小（不能扩大边界、不能增加权限），普通整数运算会清除 tag，因此指针无法伪造。复位时 r63（`rc`）持有根能力。
     **v2 带标签内存**：每 16 字节粒度一个影子 tag 位 + 元数据，`csc`/`clc` 可把能力完整地存入/取出内存（需 STORE_CAP/LOAD_CAP 权限），任何普通数据写入都会清除该粒度的 tag。
     **v2 PCC**：取指受程序计数器能力（PCC）检查（越界或无 EXEC 权限即陷入），`cjalr` 通过能力寄存器跳转并设置 PCC，同时返回链接能力。
     **v2 密封能力**：`cseal`/`cunseal` 用带 SEAL/UNSEAL 权限的授权能力（其游标即 otype）密封/解封；密封后的能力不能解引用、不能修改、不能跳转。
  2. **寄存器内 SIMD 通道**：一个 128 位寄存器可视为 16×8 / 8×16 / 4×32 / 2×64 位通道，支持加减、饱和加减、min/max、比较掩码、乘法、广播、横向求和、通道移位。
  3. **宽立即数 / 常量拼接**：`wli`/`wins` 把 16 位立即数放到 8 个槽位中任意一个，汇编器的 `li` 伪指令自动选出最短序列。
- **异常**：非法指令、能力错误（tag/边界/权限/密封）、未对齐、访问错误；精确异常，写入 `epc/cause/tval`，跳到 `tvec`（若 `tvec=0` 则停机），`eret` 返回。
- **v2 定时器中断**：`mtime`（MMIO+0x30）= 已退休指令数（确定性时间基），`mtimecmp`（MMIO+0x40）；`status` CSR 的 IE/PIE/TIE 位；中断在“下一条指令之前”精确投递，黄金模型与 RTL 在同一退休点上一致。
- **MMIO**：位于 128 位地址空间最顶端 64 KiB，提供控制台输出、十六进制输出和退出（停机）寄存器。
- **实现**：Python 汇编器/反汇编器/黄金参考模拟器；SystemVerilog 五级流水线（前递、load-use 互锁、静态分支预测、迭代乘除法器带结果缓存），用 Verilator 与黄金模型逐条提交轨迹对比验证，用 Yosys 综合统计单元数。

---

## 1. Overview

| Property | Value |
|---|---|
| Word / register width | 128 bits |
| General-purpose registers | 64 × 128-bit (`r0` hard-wired to zero), each with a hidden capability side-band |
| Program counter | 128 bits |
| Virtual address space | 2^128 bytes, byte addressed, little-endian |
| Instruction size | fixed 32 bits, 4-byte aligned |
| Memory access sizes | 8, 16, 32, 64, 128 bits; naturally aligned |
| Privilege | single (machine) level in v1 |
| Distinguishing features | capabilities, SIMD-in-GPR, wide immediates |

### 1.1 Why a fixed 32-bit encoding (and not 64-bit)

* **Three 6-bit register specifiers fit.** 64 registers need 6 bits each; `op6 + rd6 + rs1_6 + rs2_6 + func8 = 32`.
  Every three-operand operation in the ISA fits in 32 bits with room for 256 functions per major opcode.
* **Density.** A 64-bit encoding would double instruction-fetch bandwidth and I-cache footprint
  for every instruction in order to help the small minority that need wide constants.
* **Wide constants are cheap anyway.** Address arithmetic is base + simm14 (±8 KiB); large constants
  are built with *wide-immediate fusion* (`wli`/`wins`, §5.3): each instruction deposits 16 bits into
  one of eight 16-bit slots. A 32-bit constant costs 2 instructions, a full 128-bit constant at most 8,
  and the assembler's `li` picks the minimum automatically. The `wli`+`wins` pairs are trivially
  fusable by a wider front end (future work).
* **Simple, fast decode.** Register fields are always in the same bit positions; the destination is
  always `[11:6]`, `rs1` is always `[17:12]`.

### 1.2 Registers

| Register | ABI name | Use |
|---|---|---|
| r0 | `zero` | always reads 0 (untagged); writes ignored |
| r1 | `ra` | return address |
| r2 | `sp` | stack pointer |
| r3 | `gp` | global pointer |
| r4–r11 | `a0`–`a7` | arguments / results |
| r12–r27 | `t0`–`t15` | temporaries (caller-saved) |
| r28–r43 | `s0`–`s15` | callee-saved |
| r44–r62 | — | general |
| r63 | `rc` | **root capability** at reset |

Each GPR is a *fat register*: `{value[127:0], tag, otype[15:0], perm[6:0], base[127:0], top[128:0]}`.
The side-band is invisible to ordinary instructions. **Invariant:** when `tag = 0` the side-band is all zero.

At reset all registers read as zero and untagged, except `rc` (r63), which holds the root capability:
`tag=1, perm=all (0x7F), otype=0 (unsealed), base=0, top=2^128, value=0`. PC = 0. All CSRs = 0. Shadow tag memory is all clear.

## 2. Instruction formats

```
 31        24 23    18 17    12 11     6 5      0
+------------+--------+--------+--------+--------+
|   func8    |  rs2   |  rs1   |   rd   |  op6   |   R-type  (ALU / MULDIV / SIMD / CAP)
+------------+--------+--------+--------+--------+
|      imm14 (signed)  |  rs1   |   A    |  op6   |   I/S/B-type
+---------------------+--------+--------+--------+
|            imm20 (signed)    |   rd   |  op6   |   J-type  (JAL)
+------------------------------+--------+--------+
|      imm16     |k| slot|     |   rd   |  op6   |   K-type  (wide immediate)
+----------------+-+-----+-----+--------+--------+
  31           16 15 14 12
```

* **I-type:** `A` = rd.  **S-type (stores):** `A` = data register.  **B-type (branches):** `A` = second compare register.
  Sharing one layout keeps `rs1` and the second source in fixed positions.
* Branch and JAL offsets are in **instructions** (×4): branches reach ±32 KiB, JAL ±2 MiB.
* The all-zero word is permanently **illegal** (catches jumps into zeroed memory).
* Unused fields are reserved and should be zero; v1 hardware ignores them.

## 3. Opcode map

| op6 | Mnemonic(s) | Format |
|---|---|---|
| 0x00 | *illegal* | — |
| 0x01 | ALU (func8 selects, §4.1) | R |
| 0x02 | MULDIV (§4.2) | R |
| 0x03 | SIMD (func8 = sop<<2 \| lane, §5.2) | R |
| 0x04 | CAP (§5.1) | R |
| 0x08–0x10 | `addi andi ori xori slti sltiu slli srli srai` | I |
| 0x11 | `cincaddri` | I |
| 0x12 | `csetbndi` (imm is **unsigned** 14-bit length) | I |
| 0x14 | `wli` (k=0) / `wins` (k=1) | K |
| 0x18–0x20 | `lb lh lw ld lq lbu lhu lwu ldu` | I |
| 0x21 | `clc` (capability load, §5.1.1) | I |
| 0x28–0x2C | `sb sh sw sd sq` | S |
| 0x2D | `csc` (capability store, §5.1.1) | S |
| 0x30–0x35 | `beq bne blt bge bltu bgeu` | B |
| 0x38 | `jal` | J |
| 0x39 | `jalr` | I |
| 0x3C | `halt rs1` | I |
| 0x3D | `csrr rd, csr` (csr in imm14) | I |
| 0x3E | `csrw csr, rs1` | I |
| 0x3F | `eret` | I |
| others | *illegal* | — |

## 4. Integer instructions

All arithmetic is modulo 2^128. Results written by these instructions are **untagged**.

### 4.1 ALU (op 0x01) and immediate forms

| func | Mnemonic | Semantics |
|---|---|---|
| 0 | `add rd, rs1, rs2` | rd = rs1 + rs2 |
| 1 | `sub` | rs1 − rs2 |
| 2/3/4 | `and` / `or` / `xor` | bitwise |
| 5 | `sll` | rs1 << rs2[6:0] |
| 6 | `srl` | logical right shift by rs2[6:0] |
| 7 | `sra` | arithmetic right shift by rs2[6:0] |
| 8 | `slt` | signed rs1 < rs2 ? 1 : 0 |
| 9 | `sltu` | unsigned compare |
| 10/11 | `min` / `max` | signed |
| 12/13 | `minu` / `maxu` | unsigned |
| 14 | `andn` | rs1 & ~rs2 |
| 15 | `seq` | rs1 == rs2 ? 1 : 0 |
| 16 | `clz rd, rs1` | leading zeros (0..128) |
| 17 | `ctz rd, rs1` | trailing zeros (0..128) |
| 18 | `popcnt rd, rs1` | population count |
| ≥19 | — | illegal |

Immediate forms (`addi andi ori xori slti sltiu`) sign-extend imm14 to 128 bits (`sltiu` compares against
the sign-extended value as unsigned). `slli srli srai` use imm[6:0] as the shift amount.

### 4.2 Multiply / divide (op 0x02)

| func | Mnemonic | Semantics |
|---|---|---|
| 0 | `mul` | low 128 bits of rs1 × rs2 |
| 1 | `mulhu` | high 128 bits of the unsigned 256-bit product |
| 2 | `div` | signed quotient, truncating toward zero |
| 3 | `divu` | unsigned quotient |
| 4 | `rem` | signed remainder (sign of dividend) |
| 5 | `remu` | unsigned remainder |

Division by zero: quotient = all ones, remainder = dividend. Signed overflow (−2^127 / −1): quotient = −2^127,
remainder = 0. No trap is raised (RISC-V convention).

### 4.3 Loads and stores

`ea = rs1.value + sext(imm14)` (mod 2^128). `lb/lh/lw/ld` sign-extend to 128 bits, `lbu/lhu/lwu/ldu` zero-extend,
`lq` loads 128 bits. `sb/sh/sw/sd/sq` store the low 1/2/4/8/16 bytes of the data register.

Access checks, in priority order (the first failing check raises its trap; `tval = ea`):

0. if `rs1` is **sealed** (§5.1.3) → *capability-sealed*
1. if `rs1` is **tagged**: permission (`LOAD` for loads, `STORE` for stores) → *capability-permission*
   (`csc` of a tagged value additionally needs `STORE_CAP`, §5.1.1)
2. if `rs1` is **tagged**: `base ≤ ea` and `ea + size ≤ top` → *capability-bounds*
3. `ea mod size = 0` → *misaligned*
4. `ea` in RAM or in the MMIO page → otherwise *access-fault*

Values loaded by these instructions are always untagged. Every successful store to RAM by these instructions
(any size, including a single byte) **clears the shadow tag** of the 16-byte granule it touches (§5.1.1).
Untagged base registers perform unchecked ("hybrid mode") accesses.

### 4.4 Control transfer

* `beq/bne/blt/bge/bltu/bgeu rs1, rs2, label` — compare rs1 with the register in field A; taken target = pc + 4·imm14.
* `jal rd, label` — rd = pc + 4; pc = pc + 4·imm20.
* `jalr rd, rs1, imm` — pc = (rs1 + imm) & ~3; rd = old pc + 4. Low two bits of every register-sourced
  target (JALR, CJALR, ERET, trap vector) are ignored.
* `cjalr rd, rs1` — jump through a code capability, installing it as the PCC (§5.1.2).

### 4.5 System

* `halt rs1` — stop the machine; exit code = rs1[31:0].
* `csrr rd, csr` / `csrw csr, rs1` — read/write a 128-bit CSR (value only).
* `eret` — pc = epc & ~3; PCC ← EPCC; `status.IE ← status.PIE`, `status.PIE ← 1`.

| CSR | # | Meaning |
|---|---|---|
| `tvec` | 0 | trap vector; 0 means "halt on trap" |
| `epc` | 1 | PC of the trapping instruction |
| `cause` | 2 | trap cause code |
| `tval` | 3 | faulting address / instruction word / capability address |
| `scratch` | 4 | free for the handler |
| `status` | 5 | bit0 **IE** (global interrupt enable), bit1 **PIE** (IE before the last trap), bit2 **TIE** (timer interrupt enable); other bits read 0, writes to them are ignored |

## 5. Distinguishing features

### 5.1 Hardware capabilities (CHERI-inspired fat pointers)

A *capability* is a register whose hidden tag is set. It grants access to `[base, top)` with permissions
`perm` (bit0 LOAD, bit1 STORE, bit2 EXEC (instruction fetch, §5.1.2), bit3 LOAD_CAP, bit4 STORE_CAP, bit5 SEAL, bit6 UNSEAL) and an object type `otype` (0 = unsealed, §5.1.3). Its value is the current address (cursor),
a full 128-bit address — bounds are stored at full precision in the side-band, so no address bits are
sacrificed to compression, and a cursor may move out of bounds without losing the tag (it simply cannot
be dereferenced there).

**Unforgeability.** The only instructions that produce a tagged result are `csetaddr`, `cincaddr(i)`,
`csetbnd(i)` and `candperm` (only when their `rs1` is already tagged) and `clc` (only from a granule whose
shadow tag is set, which only `csc` of a tagged register can set); `cgetpcc` and the `cjalr` link copy the PCC,
which itself only ever comes from root, a tagged register (`cjalr`, `csetepcc`) or EPCC. Every other write — ALU, ordinary load,
`mv` (= `addi`), CSR read, link register — clears the tag, and every ordinary store clears the granule's
tag. Tags therefore descend only from the root capability in `rc` at reset.

**Monotonicity.** `csetbnd` may only shrink bounds, `candperm` may only remove permissions.

| func (op 0x04) | Mnemonic | Semantics |
|---|---|---|
| 0 | `csetaddr rd, rs1, rs2` | rd = rs1 with cursor := rs2.value (tag/bounds kept) |
| 1 | `cincaddr rd, rs1, rs2` | rd = rs1 with cursor += rs2.value |
| 2 | `csetbnd rd, rs1, rs2` | requires rs1 tagged (else *cap-tag*); new = [rs1.cursor, rs1.cursor + rs2) must lie within rs1's bounds (else *cap-bounds*); rd = tagged, same perms, base = cursor = rs1.cursor |
| 3 | `candperm rd, rs1, rs2` | perm := perm & rs2[6:0] (untagged rs1 → untagged result) |
| 4 | `cgetbase rd, rs1` | base (0 if untagged) |
| 5 | `cgetlen rd, rs1` | top − base, saturated to 2^128−1 |
| 6 | `cgetperm rd, rs1` | perm |
| 7 | `cgettag rd, rs1` | tag (0/1) |
| 8 | `cclrtag rd, rs1` | value of rs1, untagged |
| 9 | `cgetpcc rd` | rd = PCC (tagged) with cursor = pc of this instruction |
| 10 | `csetepcc rs1` | EPCC := rs1's capability; rs1 untagged → *cap-tag*; rd is not written |
| 11 | `cjalr rd, rs1` | capability jump, §5.1.2 |
| 12 | `cseal rd, rs1, rs2` | seal rs1 with otype = rs2.cursor (§5.1.3) |
| 13 | `cunseal rd, rs1, rs2` | unseal rs1 using authority rs2 (§5.1.3) |
| 14 | `cgettype rd, rs1` | otype (0 if unsealed or untagged) |
| — | `cincaddri rd, rs1, simm14` (op 0x11) | immediate form of `cincaddr` |
| — | `csetbndi rd, rs1, uimm14` (op 0x12) | immediate form of `csetbnd` |

With an untagged `rs1`, `csetaddr`/`cincaddr` behave as plain moves/adds (untagged result).
Capability faults set `tval` to rs1's cursor (for `csetbnd`) or the effective address (for memory accesses).

Typical use:
```
la        t1, buffer
csetaddr  s0, rc, t1        # cursor into the root capability
csetbndi  s0, s0, 64        # s0 may touch exactly buffer[0..63]
candperm  s1, s0, t4        # (t4 = 1) read-only view
sq        t2, 64(s0)        # -> capability-bounds trap, precise, tval = buffer+64
```

### 5.1.1 Tagged memory (v2): `clc` / `csc`

Memory is divided into 16-byte **granules**. Each RAM granule has an architecturally hidden **shadow
entry** `{tag, otype, perm, base, top}` (the same side-band a fat register carries). Because TACHYON-128 keeps
full-precision bounds instead of compressing them into the 128-bit word, the shadow entry holds the whole
metadata, not just the tag bit; ordinary loads cannot read it and ordinary stores cannot write it.

| Instruction | Semantics |
|---|---|
| `clc rd, imm(rs1)` | `ea = rs1 + sext(imm14)`; 16-byte access, checks as for `lq` (LOAD perm, bounds, 16-byte alignment, RAM/MMIO). `rd.value` = the 16 bytes; `rd` is **tagged with the granule's shadow metadata** if the granule's tag is set **and** (`rs1` is untagged **or** `rs1` has LOAD_CAP); otherwise `rd` is untagged (the tag is silently stripped, CHERI-style). MMIO reads return the MMIO register value (0 except the timer, §6.1), untagged. |
| `csc rA, imm(rs1)` | `ea = rs1 + sext(imm14)`; 16-byte store of `rA.value`. Checks in order: (1) tagged `rs1` lacks STORE → cap-permission; (2) tagged `rs1` lacks STORE_CAP **and** `rA` is tagged → cap-permission; (3) bounds; (4) alignment; (5) RAM/MMIO. In RAM the granule's shadow entry becomes `rA`'s metadata if `rA` is tagged, else it is cleared. Stores to MMIO behave like `sq` (value only). |

* Any successful `sb/sh/sw/sd/sq` to RAM clears the shadow tag of the granule written.
* Untagged base registers (hybrid mode) may `clc`/`csc` without checks; this cannot forge tags because a
  granule's tag can only be set by `csc` of a register that is already tagged.
* Reset: every shadow tag is clear.  The 256 KiB RAM has 16 384 granules.

Example (a linked list of capabilities, `programs/caplist.s`):
```
csc   s2, 0(t4)        # node.next = previous head (tag + bounds preserved)
clc   t0, 0(t0)        # follow next: comes back tagged, with that node's 32-byte bounds
sq    t6, 96(s0)       # overwrite a link with an integer -> granule tag cleared, list is cut
```

### 5.1.2 Program-counter capability (PCC) and `cjalr`

Every instruction is fetched under the **PCC**, a capability (perm, base, top) that is always tagged.
Reset: PCC = root (all permissions, `[0, 2^128)`). Before fetching the instruction at `pc` (checks in order;
the trap has `tval = epc = pc`):

1. PCC lacks EXEC → *capability-permission*
2. `pc < PCC.base` or `pc + 4 > PCC.top` → *capability-bounds*
3. `pc + 4 > RAM size` → *access-fault*

Ordinary control transfers (`jal`, `jalr`, branches, sequential flow) keep the PCC: jumping or falling off the end
of the PCC region traps at the next fetch. Only these change it:

| Event | PCC effect |
|---|---|
| `cjalr rd, rs1` | rs1 untagged → *cap-tag*; rs1 lacks EXEC → *cap-permission* (both `tval` = rs1 cursor, nothing changes). Otherwise `pc ← rs1.cursor & ~3`, **PCC ← rs1's capability**, and `rd ←` a *link capability*: the old PCC with cursor `pc + 4`. `cjalr zero, ra` returns. The new target is bounds-checked by the next fetch. |
| any trap (§6) | **EPCC ← PCC**, PCC ← root (handlers run with full authority) |
| `eret` | PCC ← EPCC |
| `csetepcc rs1` | EPCC ← rs1 (lets a handler choose the PCC it returns under) |

`cgetpcc rd` reads the PCC. EPCC is reset to root. A pure-capability code region is entered with e.g.
```
la        t0, func
csetaddr  t0, rc, t0
csetbndi  t0, t0, 32       # func may only execute its own 8 instructions
cjalr     ra, t0           # ra = link capability back into the caller's PCC
...
func: ...  cjalr zero, ra
```

### 5.1.3 Sealed capabilities (minimal)

A tagged capability with `otype ≠ 0` is **sealed**: an opaque token that can be stored, copied, loaded and
passed around, but not used or changed until it is unsealed by whoever holds the matching authority.

* **Sealing authority** is any tagged, unsealed capability with SEAL (bit5) / UNSEAL (bit6) whose **cursor is
  the otype** and lies within its bounds (`base ≤ cursor < top`). Bounding an authority (`csetbnd`) limits which
  otypes its holder can use.
* `cseal rd, rs1, rs2`, checks in order (`tval` = the offending operand's cursor): rs1 untagged → *cap-tag*;
  rs2 untagged → *cap-tag*; rs1 sealed → *cap-sealed*; rs2 sealed → *cap-sealed*; rs2 lacks SEAL → *cap-perm*;
  rs2.cursor outside rs2's bounds, `= 0` or `> 0xFFFF` → *cap-bounds*. Result: rs1 with `otype = rs2.cursor`.
* `cunseal rd, rs1, rs2`: rs1 untagged → *cap-tag*; rs2 untagged → *cap-tag*; rs1 **not** sealed → *cap-sealed*;
  rs2 sealed → *cap-sealed*; rs2 lacks UNSEAL → *cap-perm*; rs2.cursor out of bounds → *cap-bounds*;
  rs2.cursor ≠ rs1.otype → *cap-sealed*. Result: rs1 with `otype = 0`.
* A sealed capability **cannot be dereferenced**: a load, store, `clc` or `csc` through a sealed base raises
  *cap-sealed* (checked right after the tag, before permissions; `tval` = ea).
* A sealed capability **cannot be modified**: `csetaddr`, `cincaddr(i)`, `csetbnd(i)`, `candperm` with a sealed
  `rs1` raise *cap-sealed* (`tval` = cursor). `cjalr` and `csetepcc` through a sealed capability raise *cap-sealed*
  (after the tag check). `cget*`, `cclrtag`, `csc` *of* a sealed value and `clc` back are allowed; the shadow
  memory keeps the otype.
* Every derivation that produces a tagged result from an unsealed capability yields `otype = 0`; the PCC and the
  `cjalr` link are never sealed. (No sealed-entry "sentry" jumps in this minimal version.)

### 5.2 SIMD lanes inside a GPR

`func8 = (sop << 2) | lane`, lane 0/1/2/3 = 8/16/32/64-bit lanes (assembler suffix `.b .h .w .d`).

| sop | Mnemonic | Per-lane semantics |
|---|---|---|
| 0 / 1 | `vadd` / `vsub` | wrapping |
| 2 / 3 | `vaddss` / `vaddus` | signed / unsigned saturating add |
| 4 / 5 | `vsubss` / `vsubus` | signed / unsigned saturating subtract |
| 6 / 7 / 8 / 9 | `vmins` `vminu` `vmaxs` `vmaxu` | min / max |
| 10 / 11 / 12 | `vcmpeq` `vcmpgts` `vcmpgtu` | lane = all-ones if true else 0 |
| 13 | `vmul` | low half of lane product (8/16/32-bit lanes; `vmul.d` is illegal) |
| 14 | `vsplat rd, rs1` | broadcast lane 0 of rs1 |
| 15 | `vsum rd, rs1` | horizontal unsigned sum of all lanes → 128-bit integer |
| 16 / 17 / 18 | `vsll` `vsrl` `vsra` | shift every lane by rs2 mod lane-width |
| ≥19 | — | illegal |

### 5.3 Wide immediates (constant fusion)

`wli rd, imm16, slot` : rd = imm16 << (16·slot)  
`wins rd, imm16, slot`: rd = (rd & ~(0xFFFF << 16·slot)) | (imm16 << 16·slot)

The assembler pseudo-op `li rd, C` chooses the shortest of: `addi` (simm14); `wli` + `wins` over the non-zero
slots; or `addi rd, zero, -1 / low14` followed by `wins` for the slots that differ. `la` always emits a fixed
2-instruction `wli`/`wins` pair (addresses < 2^32) so label addresses are stable between passes.

## 6. Traps

| cause | Name | Raised by |
|---|---|---|
| 1 | illegal-instruction | undefined opcode/func, `vmul.d`, CSR number ≥ 6, the zero word (`tval` = instruction word) |
| 2 | capability-tag | `csetbnd(i)`, `cjalr`, `csetepcc`, `cseal`, `cunseal` on an untagged register |
| 3 | capability-bounds | out-of-bounds access through a capability; non-monotonic `csetbnd(i)` |
| 4 | capability-permission | load/store through a capability lacking LOAD/STORE; `csc` of a tagged value through a capability lacking STORE_CAP |
| 5 | misaligned | access not naturally aligned |
| 6 | access-fault | data access outside RAM and MMIO; instruction fetch outside RAM (`tval` = pc) |
| 7 | capability-sealed | use or modification of a sealed capability; `cseal` of a sealed one; `cunseal` of an unsealed one or with the wrong otype |

Capability faults on instruction fetch (PCC lacks EXEC / pc outside PCC) use causes 4 / 3 with `tval` = pc;
`cjalr` raises 2 / 4 for an untagged / non-executable target.

Traps are **precise**: the trapping instruction has no architectural effect, everything older has completed.
On a trap: `epc ← pc`, `cause`, `tval` are written, EPCC ← PCC and PCC ← root, `status.PIE ← status.IE` and
`status.IE ← 0`; if `tvec ≠ 0` then `pc ← tvec & ~3`, otherwise the machine halts reporting the cause.
A handler resumes with `eret` (adding 4 to `epc` first to skip the instruction).

### 6.1 Machine timer interrupt

The timer is **deterministic**: `mtime` (MMIO + 0x30, read-only) is the number of instructions retired since
reset — every instruction that completes without trapping counts once (traps and interrupts do not retire).
`mtimecmp` (MMIO + 0x40, read/write) resets to all ones.

* **Pending** ⇔ `status.IE ∧ status.TIE ∧ mtime ≥ mtimecmp` (unsigned 128-bit compare).
* **Delivery point:** the condition is evaluated *before each instruction* (before its fetch), using the state
  left by all older instructions. If pending, the interrupt is taken instead of that instruction:
  `epc ←` its pc, `cause ← 2^127 | 1` (bit 127 = interrupt, code 1 = timer), `tval ← 0`, then the common trap
  entry above (EPCC, PCC ← root, PIE ← IE, IE ← 0, `pc ← tvec`, or halt when `tvec = 0`).
  An interrupt therefore lands between two retirements at a point both the ISA model and any implementation
  agree on — e.g. right after the `csrw status` that enables it, or right after the store that lowers
  `mtimecmp`. Interrupts have priority over every synchronous trap of the same instruction (including fetch faults).
* The handler returns with `eret` **without** adding 4 (`epc` is the instruction that has not run yet), and
  re-arms by writing `mtimecmp` (typically `mtime + period`), or clears TIE/IE.
* `mtime` / `mtimecmp` are 16-byte registers: a load of any size at `base + k` returns bytes `k…` of the
  register (natural alignment rules apply); `clc` returns the value untagged. A store (any size) to exactly
  MMIO + 0x40 sets `mtimecmp` to the stored data zero-extended from its size; other stores to these two
  registers are ignored.
* Commit traces record an interrupt as `I 1 <epc>` (synchronous traps: `T cause epc tval`).

## 7. Memory map (reference implementation)

| Address | Size | Region |
|---|---|---|
| `0x0` | 256 KiB | RAM (code + data; reset PC = 0) |
| `2^128 − 0x10000` | 64 KiB | MMIO page |
| `MMIO + 0x00` | | CONSOLE: write → low byte to console |
| `MMIO + 0x10` | | EXIT: write → halt, exit code = value[31:0] |
| `MMIO + 0x20` | | HEXOUT: write → value as 32 hex digits + newline |
| `MMIO + 0x30` | | MTIME: read → instructions retired so far (§6.1); writes ignored |
| `MMIO + 0x40` | | MTIMECMP: read/write timer compare, reset all ones (§6.1) |

Other MMIO offsets ignore writes and read 0. Self-modifying code is not supported (no fence).

## 8. Assembler syntax

```
label:  op operands      # comment   (';' also starts a comment)
```
* Registers: `r0..r63` or ABI names. Immediates: C-like expressions over integers, labels and `.equ`
  symbols (`+ - * / % << >> & | ^ ~`, char literals `'A'`).
* Directives: `.org .align .space .equ/.set .byte .half .word .dword .quad .ascii .asciz .include`.
* Pseudo-ops: `nop li la mv cmove not neg seqz snez j call ret jr beqz bnez bltz bgez bgtz blez bgt ble bgtu bleu`,
  `halt` (no operand = `halt zero`), `jal label` (= `jal ra, label`).

## 9. Known limitations (deliberate)

* Sealing is minimal: no sealed entry points ("sentries"/`CInvoke`), no global/local or LOAD_MUTABLE permissions.
* Single privilege level; `rc` is the only root of authority after reset.
* No virtual memory/MMU — the 128-bit address space is flat; RAM is small and physical.
* One interrupt source (the deterministic machine timer); no external/software interrupts, no wall-clock time base.
* No FPU, no atomics, no fence for self-modifying code.

## 10. Reference implementation notes (non-architectural)

These describe `rtl/` timing only; software must not depend on them.

* **Divider (v2):** radix-4 restoring divider on magnitudes. Each radix-4 step compares `4R+d` against `B`, `2B`
  and `3B` in parallel and retires two quotient bits; the default build chains `DIV_STEPS = 2` steps per cycle
  (4 quotient bits/cycle; `+define+TX_DIV_STEPS=1` gives plain radix-4, 2 bits/cycle). **Early termination:**
  only `n = sig(|a|) − sig(|b|) + 1` quotient bits are computed (rounded up to a multiple of the bits per
  cycle); the remainder register is preloaded with the top bits of `|a|` that cannot yet yield a quotient 1.
  Latency = `ceil(n / bits_per_cycle) + 2` cycles (2 when `|a| < 2^(sig(|b|)−1)`), instant for divide-by-zero,
  0 extra for the paired `rem`/`div` on the same operands (result cache). v1 was radix-2 with dividend-only
  leading-zero skipping (up to 129 cycles).
* **Multiplier (v3):** radix-2^32 multi-pass multiplier. Each cycle one 128 × 32 partial-product array (reduced
  carry-save by synthesis) is added to the upper half of a 256-bit accumulator, which then shifts right by 32;
  four passes produce the full 256-bit product and the last pass writes the result cache directly.
  Latency = 6 cycles in EX (1 issue + 4 passes + 1 result), v2's radix-16 shift-add needed 35. `mul`/`mulhu` on
  the same operands still share one computation (result cache: the second one costs 0 extra cycles).
  `+define+TX_MUL_BITS=4` rebuilds the v2 radix-16 datapath (any divisor of 128 is a legal pass width).
