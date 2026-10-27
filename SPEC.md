# TACHYON-128 Instruction Set Architecture — v4.0

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
     **v3 密封入口（sentry）与 `cinvoke`**：`csealentry` 生成只能被 `cjalr` 跳入的入口能力（跳转时原子解封进 PCC，返回链接也是 sentry）；`cinvoke` 用同 otype 密封的“代码+数据”能力对进入保护域，原子地解封代码到 PCC、解封数据到 rd。
     **v3 `clc` 权限衰减**：通过不带 STORE 权限的能力 `clc` 读出的（未密封）能力自动去掉 STORE/STORE_CAP——只读视图传递为深度只读。
     **v4 新权限位**：GLOBAL（无此位即“局部能力”）、LOAD_MUTABLE（`clc` 衰减改由它决定，取代 v3 的 STORE 规则）、PERMIT_CINVOKE（`cinvoke` 的代码与数据都必须具有）、STORE_LOCAL（只有带此权限的能力才能 `csc` 存入局部能力，例如栈指针不能被存进堆里）。
  2. **寄存器内 SIMD 通道**：一个 128 位寄存器可视为 16×8 / 8×16 / 4×32 / 2×64 位通道，支持加减、饱和加减、min/max、比较掩码、乘法、广播、横向求和、通道移位。
  3. **宽立即数 / 常量拼接**：`wli`/`wins` 把 16 位立即数放到 8 个槽位中任意一个，汇编器的 `li` 伪指令自动选出最短序列。
- **v3 两级特权（supervisor/user）**：`status.U/PU` 位，`eret` 才能进入用户态；用户态执行 CSR 读写、`eret`、`halt`、`csetepcc` 触发特权违例（cause 9）；用户态用非能力（无 tag）指针访存必须落在 `[ubase, ubound)` 窗口内，否则特权违例——MMIO 只能通过内核授予的能力访问；`ecall`（cause 8）陷入内核。示例 `programs/kernel.s`：两个用户任务、定时器抢占、ecall 打印。
- **异常**：非法指令、能力错误（tag/边界/权限/密封）、未对齐、访问错误；精确异常，写入 `epc/cause/tval`，跳到 `tvec`（若 `tvec=0` 则停机），`eret` 返回。
- **v2 定时器中断**：`mtime`（MMIO+0x30）= 已退休指令数（确定性时间基），`mtimecmp`（MMIO+0x40）；`status` CSR 的 IE/PIE/TIE 位；中断在“下一条指令之前”精确投递，黄金模型与 RTL 在同一退休点上一致。
- **MMIO**：位于 128 位地址空间最顶端 64 KiB，提供控制台输出、十六进制输出和退出（停机）寄存器。
- **v4 可读 EPCC**：`cgetepcc rd`（仅内核态）读出 EPCC（游标 = epc），内核可在抢占时保存任务的真实 PCC。
- **v4 原子操作**：128 位 `lr`/`sc`（单核语义，任何存储或陷入都会清除保留）以及 `amoswap/amoadd/amoand/amoor/amoxor`；`lr`/`sc`/`amoswap` 遵循 `clc`/`csc` 的标签规则，可原子地交换能力。
- **v4 微架构**：8 项返回地址栈（RAS，推测更新 + 提交副本在陷入时恢复）预测 `call`/`ret`；乘法器面积缩小——标量乘法的 128×32 部分积阵列与 SIMD `vmul` 共享一块“可拆分”的 4×(32×32) radix-4 Booth 乘法阵列（仍为 6 周期）。
- **实现**：Python 汇编器/反汇编器/黄金参考模拟器；SystemVerilog 五级流水线（前递、load-use 互锁、v3 BTB + 2 位计数器分支预测、v3 4 遍 6 周期乘法器、radix-4 除法器，带结果缓存），用 Verilator 与黄金模型逐条提交轨迹对比验证，用 Yosys 综合统计单元数。

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
| Privilege | **v3:** two levels, supervisor (reset) and user (§6.2) |
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

Each GPR is a *fat register*: `{value[127:0], tag, otype[15:0], perm[10:0], base[127:0], top[128:0]}` (v3: `perm[6:0]`).
The side-band is invisible to ordinary instructions. **Invariant:** when `tag = 0` the side-band is all zero.

At reset all registers read as zero and untagged, except `rc` (r63), which holds the root capability:
`tag=1, perm=all (0x7FF, v3: 0x7F), otype=0 (unsealed), base=0, top=2^128, value=0`. PC = 0. All CSRs = 0. Shadow tag memory is all clear.

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
| 0x05 | AMO (v4 atomics, §4.6): `lr sc amoswap amoadd amoand amoor amoxor` | R |
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
| 0x3B | `ecall` (v3) | I |
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

* `halt rs1` — stop the machine; exit code = rs1[31:0]. *(Privileged.)*
* `ecall` — environment call: always traps with cause 8 (`tval = 0`, `epc` = the ecall); the handler adds 4 to `epc`.
* `csrr rd, csr` / `csrw csr, rs1` — read/write a 128-bit CSR (value only).
* `eret` — pc = epc & ~3; PCC ← EPCC; `status.IE ← status.PIE`, `status.PIE ← 1`, **`status.U ← status.PU`,
  `status.PU ← 0`** (v3). *(Privileged.)*

| CSR | # | Meaning |
|---|---|---|
| `tvec` | 0 | trap vector; 0 means "halt on trap" |
| `epc` | 1 | PC of the trapping instruction |
| `cause` | 2 | trap cause code |
| `tval` | 3 | faulting address / instruction word / capability address |
| `scratch` | 4 | free for the handler |
| `status` | 5 | bit0 **IE** (global interrupt enable), bit1 **PIE** (IE before the last trap), bit2 **TIE** (timer interrupt enable), **v3:** bit3 **U** (current mode is user; read-only to `csrw`), bit4 **PU** (mode before the last trap was user); other bits read 0, writes to them are ignored |
| `ubase` | 6 | **v3:** lowest address user mode may reach through an untagged base (§6.2) |
| `ubound` | 7 | **v3:** end (exclusive) of the user window for untagged accesses (§6.2) |

### 4.6 Atomics (v4, op 0x05)

128-bit atomic memory operations for a single hart (the reference machine has one core, so "atomic" means
indivisible with respect to interrupts and traps). R-type: `rd`, `rs1` = address (no offset), `rs2` = data.

| func | Mnemonic | Semantics |
|---|---|---|
| 0 | `lr rd, (rs1)` | load-reserved: `rd` ← the 16-byte granule at `rs1`, **with `clc` tag rules** (tag kept only if the authority is untagged or has LOAD_CAP; LOAD_MUTABLE attenuation, §5.1.5); sets the reservation to that granule |
| 1 | `sc rd, rs2, (rs1)` | store-conditional: if the reservation is valid and names this granule, store `rs2` **with `csc` tag rules** and `rd ← 0`; otherwise no store and `rd ← 1`. The reservation is cleared either way |
| 2 | `amoswap rd, rs2, (rs1)` | `rd` ← old granule (clc tag rules), granule ← `rs2` (csc tag rules): an atomic **capability** exchange |
| 3–6 | `amoadd / amoand / amoor / amoxor rd, rs2, (rs1)` | `rd` ← old value (untagged), granule ← old op `rs2.value`; a data write, so the granule's tag is cleared |
| ≥7 | — | illegal |

* **Access checks** (first failing raises, `tval = ea`): sealed base → *cap-sealed*; tagged base lacking the needed
  permissions → *cap-permission* (`lr`: LOAD; `sc`: STORE; `amoswap` and arithmetic: LOAD **and** STORE); `sc`/`amoswap`
  of a tagged `rs2` without STORE_CAP, or of a local `rs2` without STORE_LOCAL (§5.1.6) → *cap-permission*; bounds →
  *cap-bounds*; user-mode untagged base outside `[ubase, ubound)` → *privilege-violation*; `ea mod 16 ≠ 0` →
  *misaligned*; `ea` not in RAM → *access-fault* (atomics are **RAM-only**: the MMIO page faults too).
  `sc` performs every check before it looks at the reservation, so a faulting `sc` traps (and the trap clears the
  reservation) even when it would have failed.
* **Reservation:** one per hart, `{valid, granule}`. Set by a successful `lr`; cleared by **every** completed store
  (`sb … sq`, `csc`, `sc` successful or not, any AMO, stores to MMIO included) and by **every trap or interrupt**. Loads,
  CSR accesses and `eret` leave it alone. Clearing on any store (not only to the reserved granule) and on every trap
  keeps the rule simple and deterministic, and guarantees that an `lr`/`sc` pair separated by a preemption fails, so
  the usual retry loop is correct across context switches without a dummy `sc` in the kernel.
* `rd = rs2` is allowed (`amoswap r6, r6, (r5)` exchanges a register with memory); with `rd = r0` the memory side
  effect still happens.

```
spin:  lr    t0, (a0)          # 128-bit counter or capability slot
       addi  t0, t0, 1
       sc    t1, t0, (a0)
       bnez  t1, spin
       amoswap t2, s1, (a1)    # atomically publish capability s1, get the old one back (tags preserved)
```

## 5. Distinguishing features

### 5.1 Hardware capabilities (CHERI-inspired fat pointers)

A *capability* is a register whose hidden tag is set. It grants access to `[base, top)` with permissions
`perm` (bit0 LOAD, bit1 STORE, bit2 EXEC (instruction fetch, §5.1.2), bit3 LOAD_CAP, bit4 STORE_CAP, bit5 SEAL, bit6 UNSEAL,
**v4:** bit7 GLOBAL, bit8 LOAD_MUTABLE, bit9 PERMIT_CINVOKE, bit10 STORE_LOCAL — §5.1.6) and an object type `otype` (0 = unsealed, §5.1.3). Its value is the current address (cursor),
a full 128-bit address — bounds are stored at full precision in the side-band, so no address bits are
sacrificed to compression, and a cursor may move out of bounds without losing the tag (it simply cannot
be dereferenced there).

**Unforgeability.** The only instructions that produce a tagged result are `csetaddr`, `cincaddr(i)`,
`csetbnd(i)` and `candperm` (only when their `rs1` is already tagged), `clc`, `lr` and `amoswap` (v4; only
from a granule whose shadow tag is set, which only `csc`, `sc` or `amoswap` of a tagged register can set, each under
the STORE_CAP / STORE_LOCAL rules); `cgetpcc` and the `cjalr` link copy the PCC, which itself only ever comes from
root, a tagged register (`cjalr`, `csetepcc`) or EPCC, and `cgetepcc` (v4, supervisor-only) copies EPCC, which only
ever comes from root at reset, the PCC at a trap, or a tagged register (`csetepcc`). Every other write — ALU, ordinary load, arithmetic AMO,
`mv` (= `addi`), CSR read, link register — clears the tag, and every ordinary store (and arithmetic AMO) clears the granule's
tag. Tags therefore descend only from the root capability in `rc` at reset.

**Monotonicity.** `csetbnd` may only shrink bounds, `candperm` may only remove permissions.

| func (op 0x04) | Mnemonic | Semantics |
|---|---|---|
| 0 | `csetaddr rd, rs1, rs2` | rd = rs1 with cursor := rs2.value (tag/bounds kept) |
| 1 | `cincaddr rd, rs1, rs2` | rd = rs1 with cursor += rs2.value |
| 2 | `csetbnd rd, rs1, rs2` | requires rs1 tagged (else *cap-tag*); new = [rs1.cursor, rs1.cursor + rs2) must lie within rs1's bounds (else *cap-bounds*); rd = tagged, same perms, base = cursor = rs1.cursor |
| 3 | `candperm rd, rs1, rs2` | perm := perm & rs2[10:0] (untagged rs1 → untagged result) |
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
| 14 | `cgettype rd, rs1` | otype (0 if unsealed or untagged; `0xFFFF` for a sentry) |
| 15 | `csealentry rd, rs1` | **v3:** seal rs1 as a sealed entry capability (sentry), §5.1.4 |
| 16 | `cinvoke rd, rs1, rs2` | **v3:** domain call through a sealed code (rs1) + data (rs2) pair, §5.1.4 |
| 17 | `cgetepcc rd` | **v4:** rd = EPCC (tagged) with cursor = `epc`. *Privileged* (user mode → *privilege-violation*) |
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

`cgetpcc rd` reads the PCC. EPCC is reset to root. **v4:** `cgetepcc rd` reads EPCC (cursor = `epc`, so the pair
`{epc, EPCC}` comes back as one capability); it is supervisor-only, like `csetepcc`. A kernel can now save the
interrupted task's exact PCC on every trap (`cgetepcc` + `csc` into the task control block) and restore it with
`csetepcc` before `eret`, instead of tracking each task's PCC itself; `programs/kernel.s` does this on preemption.
(In the pipeline `cgetepcc` reads EPCC and `epc` in MEM, after every older `csetepcc`/`csrw epc`, with the
CSR-read-use interlock.) A pure-capability code region is entered with e.g.
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
* Every derivation that produces a tagged result from an unsealed capability yields `otype = 0`; the PCC is never
  sealed. **v3:** `cseal` can use otypes `1 … 0xFFFE`; otype `0xFFFF` is reserved for sentries (§5.1.4), so a
  sealing authority whose cursor is `0xFFFF` raises *cap-bounds* in `cseal`, and `cunseal` of a sentry always raises
  *cap-sealed* (a sentry can only be "unsealed" by jumping to it).

### 5.1.4 Sealed entry capabilities (v3): sentries and `cinvoke`

**Sentries.** `csealentry rd, rs1` turns an executable capability into an opaque *entry point*: checks in order
(`tval` = rs1 cursor) rs1 untagged → *cap-tag*; rs1 sealed → *cap-sealed*; rs1 lacks EXEC → *cap-perm*. Result: rs1
with `otype = 0xFFFF` (`OTYPE_SENTRY`). A sentry obeys every rule of §5.1.3 (no dereference, no modification), with
one exception: **`cjalr` accepts it** and atomically unseals it into the PCC:

* `cjalr rd, rs1` with rs1 a sentry: `pc ← rs1.cursor & ~3`, PCC ← rs1 with `otype = 0`, and the link capability in
  `rd` is **itself sealed as a sentry** (old PCC, cursor `pc + 4`, `otype = 0xFFFF`). The callee can return through it
  (`cjalr zero, ra`) but cannot read or alter the caller's code or forge a different return point.
* `cjalr` through a capability sealed with any other otype still raises *cap-sealed*; `cjalr` through an unsealed
  capability is unchanged (unsealed link).
* So a library can hand out sentries to its entry points: callers can only enter at that exact address, under the
  library's own PCC bounds.

**`cinvoke rd, rs1, rs2`** — call into a protection domain represented by a *pair*: a sealed code capability
(rs1) and a sealed data capability (rs2) sealed with the same otype by the domain's owner. Checks in order:

| # | Condition | Trap (`tval`) |
|---|---|---|
| 1 | rs1 untagged / rs2 untagged | *cap-tag* (rs1 / rs2 cursor) |
| 2 | rs1 unsealed or a sentry | *cap-sealed* (rs1) |
| 3 | rs2 unsealed or a sentry, or `rs2.otype ≠ rs1.otype` | *cap-sealed* (rs2) |
| 4 | **v4:** rs1 lacks PERMIT_CINVOKE / rs2 lacks PERMIT_CINVOKE | *cap-perm* (rs1 / rs2) |
| 5 | rs1 lacks EXEC | *cap-perm* (rs1) |
| 6 | rs2 has EXEC | *cap-perm* (rs2) |

Effect, atomically: `pc ← rs1.cursor & ~3`, **PCC ← rs1 unsealed**, **rd ← rs2 unsealed** (the domain's data
capability, now usable by the domain's code only). No link is written: the caller passes a return capability,
typically a sentry built with `cgetpcc` + `cincaddri` + `csealentry`, in an argument register and the callee returns
with `cjalr zero, ra`. Neither half of the pair is usable by the caller: the code cannot be jumped to with `cjalr`
(not a sentry) and the data cannot be dereferenced, so the only way in is through `cinvoke`, which only unseals the
data while transferring control to the matching code. **v4:** both halves must also carry **PERMIT_CINVOKE**
(bit 9), as in CHERI: a domain owner can seal capabilities that may be passed around and unsealed by `cunseal` but
never used as a `cinvoke` pair (clear the bit before sealing). v3 had no such bit (otype match + EXEC split only).

```
cgetpcc    t0                 # return sentry
cincaddri  t0, t0, ret - here
csealentry ra, t0
cinvoke    a0, s1, s2         # s1/s2 = sealed (code, data) of a counter object; callee sees a0 = its data
ret: ...
```

### 5.1.5 `clc` permission attenuation: deep immutability via LOAD_MUTABLE (v4; v3 used STORE)

A capability loaded with `clc` through a tagged authority that **lacks LOAD_MUTABLE** (bit 8) has STORE, STORE_CAP,
STORE_LOCAL and LOAD_MUTABLE removed (`perm &= ~0x512`) if it is unsealed. Because LOAD_MUTABLE itself is removed,
everything reached through the loaded capability is attenuated in turn: an immutable view of a data structure gives
immutable views of everything reachable from it, transitively. Sealed capabilities (including sentries) are loaded
unchanged: they are opaque, and their owner unseals them with full rights. Untagged (hybrid) bases load capabilities
unchanged. Together with the LOAD_CAP rule (no LOAD_CAP → tag stripped), the `clc` result is:

| authority (rs1) | granule tagged | result |
|---|---|---|
| untagged | yes | shadow capability, unchanged |
| tagged, no LOAD_CAP | yes | value only, **untagged** |
| tagged, LOAD_CAP, LOAD_MUTABLE | yes | shadow capability, unchanged |
| tagged, LOAD_CAP, no LOAD_MUTABLE | yes | unsealed: perms minus STORE/STORE_CAP/STORE_LOCAL/LOAD_MUTABLE; sealed: unchanged |
| any | no | value only, untagged |

**Change from v3:** v3 had no LOAD_MUTABLE bit and let STORE play its role (no STORE → strip STORE/STORE_CAP). v4
decouples the two, as CHERI does: an authority may be read-only for data yet hand out mutable capabilities (LOAD_MUTABLE
without STORE), or writable itself yet hand out only immutable ones (STORE without LOAD_MUTABLE). A v3 read-only view
built with `candperm` (e.g. mask 0x09) has no LOAD_MUTABLE either, so it still attenuates exactly as before.

### 5.1.6 Local capabilities (v4): GLOBAL and STORE_LOCAL

A tagged capability **without GLOBAL** (bit 7) is *local*. Local capabilities behave like any other capability except
where they may be stored in memory:

* `csc rA, imm(rs1)` with `rA` tagged and local, through a **tagged** `rs1` that lacks **STORE_LOCAL** (bit 10) →
  *capability-permission* (`tval = ea`). The check comes after the STORE and STORE_CAP checks and before bounds:
  (1) no STORE, (2) tagged `rA` and no STORE_CAP, (3) local `rA` and no STORE_LOCAL, (4) bounds, (5) alignment, (6) RAM/MMIO.
* Sealing does not change locality (a sealed local capability is still local). Untagged `rA` values are never local.
* An **untagged (hybrid) base** is unchecked, exactly as for every other capability rule; user mode's hybrid accesses are
  confined to `[ubase, ubound)` anyway (§6.2).
* GLOBAL and STORE_LOCAL are otherwise ordinary permissions: inherited by derivation, removable by `candperm`, kept in
  shadow memory. The root capability has both.

Typical use: the kernel hands a task a *local* stack capability with STORE_LOCAL (so the task can spill it and other
local capabilities to its own stack) and only *global* capabilities without STORE_LOCAL for heap or shared memory. A
pointer to the stack can then never be stored into the heap or a shared buffer and outlive the call (CHERI's rule for
stack-derived capabilities), without any per-store address-range check. `programs/caplist.s` shows both cases.

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
| 1 | illegal-instruction | undefined opcode/func, `vmul.d`, CSR number ≥ 8, the zero word (`tval` = instruction word) |
| 2 | capability-tag | `csetbnd(i)`, `cjalr`, `csetepcc`, `cseal`, `cunseal` on an untagged register |
| 3 | capability-bounds | out-of-bounds access through a capability; non-monotonic `csetbnd(i)` |
| 4 | capability-permission | load/store through a capability lacking LOAD/STORE; `csc` of a tagged value through a capability lacking STORE_CAP, **v4:** of a local value through one lacking STORE_LOCAL; `cinvoke` without PERMIT_CINVOKE |
| 5 | misaligned | access not naturally aligned |
| 6 | access-fault | data access outside RAM and MMIO; **v4:** an atomic outside RAM (MMIO included); instruction fetch outside RAM (`tval` = pc) |
| 7 | capability-sealed | use or modification of a sealed capability; `cseal` of a sealed one; `cunseal` of an unsealed one, a sentry, or with the wrong otype; `cjalr` through a non-sentry sealed capability; `cinvoke` operand checks (§5.1.4) |
| 8 | environment-call | `ecall` (`tval` = 0) |
| 9 | privilege-violation | user mode: privileged instruction (`tval` = instruction word), untagged-base access outside `[ubase, ubound)` (`tval` = ea) |

Capability faults on instruction fetch (PCC lacks EXEC / pc outside PCC) use causes 4 / 3 with `tval` = pc;
`cjalr` raises 2 / 4 for an untagged / non-executable target.

Traps are **precise**: the trapping instruction has no architectural effect, everything older has completed.
On a trap: `epc ← pc`, `cause`, `tval` are written, EPCC ← PCC and PCC ← root, `status.PIE ← status.IE`,
`status.IE ← 0`, `status.PU ← status.U`, `status.U ← 0` (every trap and interrupt enters supervisor mode); if `tvec ≠ 0` then `pc ← tvec & ~3`, otherwise the machine halts reporting the cause.
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

### 6.2 Privilege levels (v3): supervisor and user

The machine runs in **supervisor** mode (`status.U = 0`, reset) or **user** mode (`status.U = 1`). The mode only
changes at a trap/interrupt (→ supervisor, old mode saved in PU) and at `eret` (U ← PU); `csrw status` can set PU but
never U, so the only way into user mode is `eret` with PU = 1, which also installs the EPCC chosen by the kernel.

In user mode:

1. **Privileged instructions** raise *privilege-violation* (cause 9, `tval` = instruction word): `csrr`/`csrw` of
   any implemented CSR (an unimplemented CSR number is still *illegal-instruction*), `eret`, `halt`, `csetepcc`,
   **v4:** `cgetepcc`.
   The privilege check comes before the instruction's own operand checks (e.g. `csetepcc r0` is cause 9, not 2).
2. **Untagged (hybrid) data accesses** must satisfy `ubase ≤ ea` and `ea + size ≤ ubound`, otherwise
   *privilege-violation* with `tval = ea`. This check replaces the misaligned/access-fault checks for such accesses
   (it is evaluated right after the capability checks, which do not apply to untagged bases). Consequently user mode
   cannot touch the MMIO page, the timer, or kernel memory through a plain integer pointer.
3. **Tagged bases are checked by the capability only.** A kernel grants device or memory access by handing the
   task a bounded capability (e.g. 16 bytes over the console register with STORE only) — authority is explicit and
   unforgeable, and the window is only the "legacy" path.
4. `ecall` traps with cause 8 in either mode; the kernel distinguishes callers by `status.PU`.
5. Instruction fetch is governed by the PCC as before; a kernel bounds each task's code with the EPCC it installs.
   Every trap still enters the handler with PCC = root, so the kernel can recover full authority with `cgetpcc`
   even after it has cleared `rc` from user-visible registers.

Timer interrupts preempt user code exactly as in §6.1 (delivery is precise; PU records that the interrupted code was
user mode, so the handler's `eret` returns to it). A kernel entering user mode should clear `status.IE` before
writing `epc` (an interrupt between `csrw epc` and `eret` would overwrite `epc`), and set PIE so that `eret`
re-enables interrupts.

Example (`programs/kernel.s`): two user tasks with their own PCC and window, round-robin preemption every 200
retired instructions, `ecall` services putc/exit, one task printing through a console capability and then being
killed for an untagged MMIO store (cause 9).

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
* Atomics (v4): `lr rd, (rs1)`, `sc rd, rs2, (rs1)`, `amoadd rd, rs2, (rs1)` (no offset allowed).
* Pseudo-ops: `nop li la mv cmove not neg seqz snez j call ret jr beqz bnez bltz bgez bgtz blez bgt ble bgtu bleu`,
  `halt` (no operand = `halt zero`), `jal label` (= `jal ra, label`).

## 9. Known limitations (deliberate)

* v4 has GLOBAL / STORE_LOCAL / LOAD_MUTABLE / PERMIT_CINVOKE (§5.1.5, §5.1.6), but no CHERI LOAD_GLOBAL
  (capabilities loaded through any authority keep their GLOBAL bit) and no PERMIT_SET_CID / compartment IDs.
* Two privilege levels only; no per-mode CSR views (user mode cannot read any CSR); `rc` is the only root of
  authority after reset. (v4: EPCC is readable by the supervisor with `cgetepcc`; `ubase`/`ubound` were already
  readable CSRs, so a kernel saves the whole per-task context.)
* No virtual memory/MMU — the 128-bit address space is flat; RAM is small and physical.
* One interrupt source (the deterministic machine timer); no external/software interrupts, no wall-clock time base.
* No FPU, no fence for self-modifying code. Atomics (§4.6) are single-hart only: no multi-core coherence, the
  reservation is cleared conservatively on any store or trap, and there are no AMO min/max or sub-word atomics.

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
* **Branch prediction (v3):** a 16-entry direct-mapped **branch target buffer** in IF (index `pc[5:2]`, tag
  `pc[17:6]` — together they identify every word of the 256 KiB RAM — 16-bit word target, 2-bit saturating counter).
  A hit with counter ≥ 2 redirects fetch to the target with no bubble. Entries are allocated in EX by taken
  branches (counter 2), `jal` and `jalr` (last target, counter 3); every branch trains its counter. Without a BTB hit,
  ID falls back to the v2 static rule (backward branches and `jal` redirect with 1 bubble). Each instruction carries
  its predicted next pc; EX compares it with the actual next pc and redirects on any difference (2-cycle penalty),
  so stale targets, aliasing outside RAM, or a pattern change can only cost cycles. `cjalr`/`cinvoke` are never
  predicted (they also switch the fetch PCC) and always redirect from EX. `+define+TX_NO_BTB` restores the static
  front end. Prediction is invisible to software: the golden model has no notion of it.
* **Return address stack (v4):** 8 entries of 16-bit word targets. A *call* is `jal`/`jalr` with `rd = ra` (push
  `pc + 4`); a *return* is `jalr` with `rs1 = ra` and `rd ≠ ra` (pop) — the `call`/`ret` pseudo-ops produce exactly
  these; `jalr ra, 0(ra)` is a call, `cjalr`/`cinvoke` are neither. BTB entries carry a *return* bit: a BTB hit on a
  return takes its target from the RAS top instead of the stored last target, so a function called from many sites
  is predicted correctly. A return the BTB has not seen yet is predicted from the RAS in ID (1 bubble). The
  speculative stack is updated when a call/return advances from ID to EX (IF sees the update of the instruction in ID
  through a bypass, so an empty function `f: ret` is predicted too); a second, committed copy is updated in MEM and
  copied back on every MEM redirect (trap, interrupt, `eret`, `halt`) — exactly the events that flush younger
  instructions whose speculative pushes/pops must be undone (a branch misprediction in EX never has wrong-path
  calls/returns past ID). Overflow wraps (the oldest entry is overwritten), underflow mispredicts; every prediction is
  still verified in EX, so the RAS can only cost cycles. `+define+TX_NO_RAS` removes it. Like the BTB it is invisible
  to software and absent from the golden model; `tests/unit_tests.py` therefore carries cycle bounds (`PERF_MAX`) for
  the RAS tests so that a predictor that silently stops working fails the suite.
* **Multiplier (v3):** radix-2^32 multi-pass multiplier. Each cycle one 128 × 32 partial-product array (reduced
  carry-save by synthesis) is added to the upper half of a 256-bit accumulator, which then shifts right by 32;
  four passes produce the full 256-bit product and the last pass writes the result cache directly.
  Latency = 6 cycles in EX (1 issue + 4 passes + 1 result), v2's radix-16 shift-add needed 35. `mul`/`mulhu` on
  the same operands still share one computation (result cache: the second one costs 0 extra cycles).
  `+define+TX_MUL_BITS=4` rebuilds the v2 radix-16 datapath (any divisor of 128 is a legal pass width).
* **Shared multiplier array (v4):** the 128 × 32 pass array no longer lives in the multiply/divide unit. The core has
  one `tx_mul32x4` block: four *fracturable* 32 × 32 multipliers, each computing either one unsigned 32 × 32 product
  (64 bits), two 16 × 16 or four 8 × 8 exact lane products. A scalar multiply pass uses mode 32 with the same 32-bit
  multiplier chunk on all four (`Σ pᵢ·2^(32i)` = multiplicand × chunk) and only the final 3-operand add into the
  accumulator stays in the mul/div unit; SIMD `vmul.b/.h/.w` use modes 8/16/32 and take the low half of each lane
  product. The two users never collide: while a `mul` iterates EX holds it, so no SIMD instruction can be in EX.
  Each multiplier uses **radix-4 Booth recoding** (digits in {−2,−1,0,+1,+2} from overlapping bit triplets, 17 digit rows
  instead of 32 AND rows). Fracturing: a digit whose low bit would come from the lane below drops it, the multiplicand of
  each row is masked to the lane its digit belongs to, and every lane gets a closing digit (0 or +1, its top bit) so the
  unsigned lane product is exact — exact non-negative lane products cannot carry into the next lane, so the lanes stay
  independent despite the two's-complement rows. Latency is unchanged (6 cycles for `mul`/`mulhu`, 1 for `vmul`).
  `+define+TX_MUL_ANDARRAY` swaps in a masked AND-array implementation of the same function (used to measure the Booth
  saving); `tests/test_mul32x4.sh` checks both against C arithmetic in all three modes.
