"""Per-instruction directed tests.  Each test is a small assembly program; the oracle is the
golden simulator (commit trace + memory + console are diffed against the RTL)."""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
from isa import (ALU_FUNCS, ALU_UNARY, MULDIV_FUNCS, SIMD_FUNCS, SIMD_UNARY, LANE_SUFFIX,  # noqa: E402
                 CAP_FUNCS, LOAD_OPS, STORE_OPS, BRANCH_OPS)

M = (1 << 128) - 1
rng = random.Random(1234)
CORNER = [0, 1, 2, M, M - 1, 1 << 127, (1 << 127) - 1, 0x7F, 0x80, 0xFF, 0x8000, 0xFFFFFFFF,
          1 << 64, (1 << 64) - 1, 0x0123456789ABCDEF_FEDCBA9876543210, 10, 3, 127, 128, 64]
RAND = [rng.getrandbits(128) for _ in range(6)] + [rng.getrandbits(rng.randint(1, 127)) for _ in range(6)]
VALS = CORNER + RAND

PRE = "        .org 0\n"
POST = "        halt zero\n"
DATA = """
        .align 16
data:   .quad 0x0123456789abcdef_fedcba9876543210, 0x8091a2b3c4d5e6f7_08192a3b4c5d6e7f
        .quad 0xffffffffffffffff_ffffffffffffffff, 0
        .space 64
"""


def pairs(n, seed):
    r = random.Random(seed)
    out = [(r.choice(VALS), r.choice(VALS)) for _ in range(n)]
    return out


def rtype_test(mn, unary, seed, n=14):
    body = []
    for k, (x, y) in enumerate(pairs(n, seed)):
        rd = 20 + (k % 40)
        body.append(f"        li r4, {x}\n        li r5, {y}")
        if unary:
            body.append(f"        {mn} r{rd}, r4")
        else:
            body.append(f"        {mn} r{rd}, r4, r5")
            body.append(f"        {mn} r6, r{rd}, r5")         # dependent: EX->EX forwarding
    return PRE + "\n".join(body) + "\n" + POST


def tests():
    T = {}
    # ---------------- integer ALU / MULDIV / SIMD / CAP R-type
    for i, mn in enumerate(ALU_FUNCS):
        T[f"alu_{mn}"] = rtype_test(mn, mn in ALU_UNARY, 100 + i)
    for i, mn in enumerate(MULDIV_FUNCS):
        T[f"md_{mn}"] = rtype_test(mn, False, 200 + i, n=10)
    # signed-division corner cases + result-cache pairs
    T["md_corners"] = PRE + f"""
        li r4, {1 << 127}
        li r5, -1
        div r10, r4, r5
        rem r11, r4, r5
        li r6, 0
        div r12, r4, r6
        rem r13, r4, r6
        divu r14, r4, r6
        remu r15, r4, r6
        li r7, -7
        li r8, 2
        div r16, r7, r8
        rem r17, r7, r8
        divu r18, r7, r8
        remu r19, r7, r8
        mul r20, r7, r7
        mulhu r21, r7, r7
        mulhu r22, r4, r4
        li r9, 0
        divu r23, r9, r8
        remu r24, r9, r8
        divu r25, r8, r7
        mul r26, r4, r9
""" + POST
    for i, base in enumerate(SIMD_FUNCS):
        for suf in LANE_SUFFIX:
            if base == "vmul" and suf == "d":
                continue
            T[f"simd_{base}_{suf}"] = rtype_test(f"{base}.{suf}", base in SIMD_UNARY, 300 + 4 * i + LANE_SUFFIX[suf], n=8)
    # ---------------- immediate ALU
    for i, (mn, rng_) in enumerate([("addi", (-8192, 8191)), ("andi", (-8192, 8191)), ("ori", (-8192, 8191)),
                                    ("xori", (-8192, 8191)), ("slti", (-8192, 8191)), ("sltiu", (-8192, 8191)),
                                    ("slli", (0, 127)), ("srli", (0, 127)), ("srai", (0, 127))]):
        r = random.Random(400 + i)
        body = []
        for k in range(12):
            x = r.choice(VALS)
            imm = r.choice([rng_[0], rng_[1], 0, 1, -1 if rng_[0] < 0 else 1, r.randint(*rng_)])
            body.append(f"        li r4, {x}\n        {mn} r{20 + k}, r4, {imm}\n        {mn} r{40 + k}, r{20 + k}, {imm}")
        T[f"imm_{mn}"] = PRE + "\n".join(body) + "\n" + POST
    # ---------------- wide immediates / li constant fusion
    body = []
    for k, v in enumerate(VALS[:24]):
        body.append(f"        li r{10 + k}, {v}")
    body.append("        wli r40, 0xBEEF, 7\n        wins r40, 0xCAFE, 3\n        wins r40, 0x1234, 0\n        wli r41, 0xFFFF, 0")
    T["wide_li"] = PRE + "\n".join(body) + "\n" + POST
    # ---------------- loads (all sizes / extensions / offsets)
    body = ["        la r4, data"]
    k = 0
    for mn, (_, size, _) in LOAD_OPS.items():
        for off in range(0, 32, size if size >= 4 else 4):
            body.append(f"        {mn} r{10 + (k % 50)}, {off}(r4)")
            k += 1
    body.append("        addi r5, r4, 48\n        lq r6, -16(r5)\n        lb r7, -1(r5)")
    T["load_all"] = PRE + "\n".join(body) + "\n" + POST + DATA
    # ---------------- stores (all sizes, partial overwrite, read-back)
    body = ["        la r4, data", f"        li r5, {VALS[14]}", f"        li r6, {M}"]
    off = 32
    for mn, (_, size) in STORE_OPS.items():
        body.append(f"        {mn} r5, {off}(r4)\n        lq r{20 + size}, {off - off % 16}(r4)")
        body.append(f"        {mn} r6, {off + 16}(r4)")
        off += 16
    body.append("        sb r5, 3(r4)\n        sh r5, 6(r4)\n        sw r5, 12(r4)\n        lq r30, 0(r4)")
    T["store_all"] = PRE + "\n".join(body) + "\n" + POST + DATA
    # ---------------- branches: taken/not taken, forward/backward, signed/unsigned
    for i, mn in enumerate(BRANCH_OPS):
        r = random.Random(500 + i)
        body = []
        for k in range(10):
            x, y = r.choice(VALS[:12]), r.choice(VALS[:12])
            if k % 3 == 0:
                y = x
            body.append(f"""        li r4, {x}
        li r5, {y}
        addi r20, r20, 1
        {mn} r4, r5, f{k}
        addi r21, r21, 1
f{k}:   li r6, 2
b{k}:   addi r6, r6, -1
        addi r22, r22, 1
        {mn} r4, r5, c{k}
        j d{k}
c{k}:   bnez r6, b{k}
d{k}:   addi r23, r23, 1""")
        T[f"br_{mn}"] = PRE + "\n".join(body) + "\n" + POST
    # ---------------- jumps
    T["jal_jalr"] = PRE + """
        li r30, 0
        call f1
        addi r30, r30, 1
        la r4, f2
        jalr r5, r4, 0
        addi r30, r30, 1
        la r4, f3
        jalr r6, r4, 3          # low bits ignored
        addi r30, r30, 1
        jal r0, end
f1:     addi r30, r30, 10
        ret
f2:     addi r30, r30, 100
        jr r5
f3:     addi r30, r30, 1000
        jalr r0, r6, 0
end:
""" + POST
    # ---------------- capability ops
    body = ["        la r4, data", "        li r5, 64", "        li r6, 3", "        li r7, 100"]
    body.append("""        csetaddr r10, rc, r4
        csetbnd r11, r10, r5
        csetbndi r12, r11, 32
        cincaddr r13, r12, r6
        cincaddri r14, r13, -3
        candperm r15, r14, r6
        li r8, 1
        candperm r16, r15, r8
        cgetbase r20, r16
        cgetlen r21, r16
        cgetperm r22, r16
        cgettag r23, r16
        cclrtag r24, r16
        cgettag r25, r24
        cgetlen r26, rc
        cgetbase r27, r5
        cgettag r28, r5
        csetaddr r29, r5, r7
        cincaddr r30, r5, r7
        candperm r31, r5, r6
        lq r32, 16(r16)
        sq r7, 16(r15)
        lq r33, 16(r15)
        mv r34, r15
        cgettag r35, r34
        cmove r36, r15
        cgetlen r37, r36
        add r38, r15, r0
        cgettag r39, r38
        cincaddri r40, r11, 1000
        cgettag r41, r40
        lq r42, -992(r40)""")
    T["cap_ops"] = PRE + "\n".join(body) + "\n" + POST + DATA
    # ---------------- CSRs and ERET
    T["csr_eret"] = PRE + """
        li r4, 0x123456789abcdef0123
        csrw scratch, r4
        csrr r5, scratch
        addi r6, r5, 1          # csrr-use interlock
        la r7, tgt
        csrw epc, r7
        csrr r8, epc
        eret
        addi r9, r9, 1          # skipped
tgt:    csrw cause, r6
        csrr r10, cause
        csrw tval, r10
        csrr r11, tval
        csrr r12, tvec
""" + POST
    # ---------------- traps
    handler = """
handler: csrr r50, cause
        csrr r51, epc
        csrr r52, tval
        addi r53, r53, 1
        addi r51, r51, 4
        csrw epc, r51
        eret
"""
    setup = "        la r4, handler\n        csrw tvec, r4\n        la r5, data\n"
    T["trap_illegal"] = PRE + setup + """
        .word 0x00000000
        addi r20, r20, 1
        .word 0xff000001        # bad ALU func
        .word 0xff000002        # bad muldiv func
        .word 0x37000003        # vmul.d (illegal)
        .word 0xff000004        # bad cap func
        .word 0x00000006        # unassigned opcode
        .word 0x0040003d        # csrr csr 16 (bad)
        addi r21, r21, 1
""" + POST + handler + DATA
    T["trap_mem"] = PRE + setup + """
        lw r10, 2(r5)           # misaligned
        lq r11, 8(r5)           # misaligned
        sh r10, 1(r5)
        li r6, 0x40000
        lb r12, 0(r6)           # past RAM -> access fault
        li r7, 0x1000000000000000000000
        sq r12, 0(r7)
        li r8, -0x10000
        lq r13, 0(r8)           # MMIO read -> 0
        sb r0, 0x40(r8)         # unmapped MMIO offset: ignored
        addi r20, r20, 1
""" + POST + handler + DATA
    T["trap_cap"] = PRE + setup + """
        li r6, 32
        csetaddr r10, rc, r5
        csetbnd r10, r10, r6
        lq r11, 32(r10)         # bounds
        lq r11, -16(r10)        # bounds (below)
        lb r11, 31(r10)         # ok
        lh r11, 31(r10)         # misaligned beats? no: bounds first (31+2 > 32)
        li r7, 2
        candperm r12, r10, r7   # store-only
        lq r13, 0(r12)          # perm
        sq r6, 0(r12)           # ok
        csetbndi r14, r10, 33   # widen -> bounds
        csetbnd r15, r6, r6     # untagged -> tag fault
        cincaddri r16, r10, -1
        csetbndi r17, r16, 1    # below base -> bounds
        candperm r18, r10, r0
        lb r19, 0(r18)          # no perms -> perm
        addi r20, r20, 1
""" + POST + handler + DATA
    T["trap_nohandler"] = PRE + """
        li r4, 5
        addi r5, r4, 1
        lw r6, 1(r0)            # misaligned, tvec=0 -> machine halts with cause
        addi r7, r7, 1
""" + POST
    T["trap_fetch"] = PRE + """
        la r4, handler
        csrw tvec, r4
        li r5, 0x40000
        jalr r1, r5, 0          # jump past RAM -> fetch access fault, epc = 0x40000
        addi r20, r20, 1
        halt zero
handler: csrr r50, cause
        csrr r51, epc
        addi r53, r53, 1
        la r6, back
        csrw epc, r6
        eret
back:   addi r21, r21, 1
""" + POST
    # ---------------- hazards / pipeline corner cases
    T["haz_loaduse"] = PRE + """
        la r4, data
        lq r5, 0(r4)
        add r6, r5, r5          # load-use
        lq r7, 16(r4)
        sq r7, 64(r4)           # load -> store data
        lq r8, 64(r4)
        beq r8, r7, ok          # load -> branch
        addi r9, r9, 1
ok:     ld r10, 0(r4)
        addi r11, r10, 0
        lbu r12, 0(r4)
        add r12, r12, r12
        add r12, r12, r12
        la r13, data
        lq r14, 0(r13)
        lq r15, 0(r13)
        add r16, r14, r15
        addi r17, r4, 16
        lq r18, 0(r17)          # ALU -> address
        lq r19, 0(r4)
        csetaddr r20, rc, r4
        lq r21, 0(r20)          # cap -> address with checks
        lq r22, 0(r21)          # value-dependent address (r21 small? no: faults guarded below)
""".replace("        lq r22, 0(r21)          # value-dependent address (r21 small? no: faults guarded below)\n", "") + POST + DATA
    T["haz_fwd_chain"] = PRE + """
        li r4, 1
        add r4, r4, r4
        add r4, r4, r4
        add r4, r4, r4
        sll r5, r4, r4
        mul r6, r5, r4          # mul uses fresh forwarded operands
        add r7, r6, r6          # mul -> alu
        divu r8, r7, r4
        remu r9, r7, r4         # cache hit
        divu r10, r7, r4        # cache hit again
        add r11, r8, r9
        mul r12, r11, r11
        mulhu r13, r11, r11     # cache hit
        li r14, 9
        mul r15, r14, r14
        mul r16, r15, r14
        addi r0, r16, 5         # write to r0 discarded
        add r17, r0, r16
        vadd.b r18, r17, r16
        vsum.b r19, r18
""" + POST
    T["haz_mul_flush"] = PRE + """
        la r4, handler
        csrw tvec, r4
        li r5, 1234567
        li r6, 89
        lw r7, 2(r0)            # trap in MEM while the next one is a mul in EX
        mul r8, r5, r6
        divu r9, r5, r6
        beq r0, r0, skip        # branch after divide
        addi r10, r10, 1
skip:   divu r11, r5, r0        # divide by zero (instant)
        rem r12, r5, r0
        halt zero
handler: addi r53, r53, 1
        csrr r51, epc
        addi r51, r51, 4
        csrw epc, r51
        eret
"""
    T["haz_branch_dense"] = PRE + """
        li r4, 20
loop:   addi r4, r4, -1
        andi r5, r4, 1
        beqz r5, even
        addi r6, r6, 1
        j next
even:   addi r7, r7, 1
next:   bnez r4, loop           # backward: predicted taken
        bnez r0, never          # forward not taken
        jal r1, sub
        beq r0, r0, end         # forward taken (mispredict)
never:  addi r8, r8, 1
sub:    addi r9, r9, 1
        ret
end:    nop
""" + POST
    T["mmio_exit"] = PRE + """
        li r4, -0x10000
        li r5, 'H'
        sb r5, 0(r4)
        li r5, 'i'
        sw r5, 0(r4)
        li r6, 0xdeadbeefcafe
        sq r6, 0x20(r4)
        sd r6, 0x20(r4)
        li r7, 42
        sd r7, 0x10(r4)         # exit(42)
        addi r8, r8, 1          # never executes
""" + POST
    T["halt_code"] = PRE + """
        li r4, 0x1234567
        halt r4
        addi r5, r5, 1
"""
    return T


if __name__ == "__main__":
    print(len(tests()), "tests")
