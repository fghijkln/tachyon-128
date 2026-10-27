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


# Performance expectations (RTL cycles, checked by run_tests.py after the differential check passes).
# Branch/return prediction is invisible to the ISA, so these bounds are what lets the suite (and the
# mutation check) notice a predictor that silently stopped working.
PERF_MAX = {
    "word_mulw_chain": 100,     # v5: 88 cycles, mulw is one multiplier pass (4-pass mul: ~148)
    "ras_nested": 412,          # v4 RAS: 403 cycles (430 without RAS)
    "ras_recursive": 6700,      # 6611 (7314 without RAS)
    "ras_sites": 176,           # 169 (220 without RAS)
    "ras_traps": 2740,          # 2713 (2978 without RAS)
}


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
    # v5 32-bit word ops: overflow wrap, sign/zero extension, shift-amount masking, divw corners,
    # mulw (one multiplier pass) next to full multiplies on the same operands (result cache kinds)
    wv = [0x7FFFFFFF, 0x80000000, 0xFFFFFFFF, 0x1_0000_0001, 0xDEADBEEF_7FFFFFFF, M, 1 << 127, 0x12345678]
    body = []
    for k, (x, y) in enumerate([(a_, b_) for a_ in wv for b_ in wv][::3]):
        body.append(f"        li r4, {x}\n        li r5, {y}")
        for j, mn in enumerate(["addw", "subw", "sllw", "srlw", "sraw", "addwu", "subwu", "sllwu"]):
            body.append(f"        {mn} r{20 + j}, r4, r5")
    T["word_alu_corners"] = PRE + "\n".join(body) + "\n" + POST
    T["word_md_corners"] = PRE + f"""
        li r4, 0x80000000
        li r5, -1
        divw r10, r4, r5         # INT_MIN / -1 -> INT_MIN
        remw r11, r4, r5         # -> 0
        li r6, 0x1_00000000      # low word 0: divide by zero
        divw r12, r4, r6
        remw r13, r4, r6
        li r7, 0xFFFF_FFF9       # -7 as a word (upper bits ignored)
        li r8, 0x5_00000002
        divw r14, r7, r8
        remw r15, r7, r8
        div r16, r7, r8          # full-width ops on the same registers must not hit a word result
        mulw r17, r7, r8
        mulwu r18, r7, r8
        mul r19, r7, r8          # full product after mulw: must not reuse the 1-pass value
        mulw r20, r7, r8
        mulhu r21, r7, r8
        li r9, 0xFFFFFFFF
        mulw r22, r9, r9         # (-1)*(-1) = 1
        mulwu r23, r4, r4        # 2^62 -> low word 0
        li r12, 0x7FFFFFFF
        mulw r24, r12, r12
        mulw r25, r24, r12       # dependent chain
        divw r26, r25, r12
        remw r27, r25, r7
""" + POST
    T["word_mulw_chain"] = PRE + "        li r4, 3\n        li r5, 0x10001\n" + \
        "".join(f"        mulw r4, r4, r5\n        addiw r4, r4, {k}\n" for k in range(20)) + POST
    # divider early-termination edges: |a| and |b| of every relative width (n odd/even, 0, 1, 128)
    r = random.Random(77)
    widths = [1, 2, 3, 4, 7, 8, 63, 64, 65, 126, 127, 128]
    for part in range(3):
        body = []
        for k, (wa, wb) in enumerate([(x, y) for x in widths for y in widths][part::3]):
            a = (1 << (wa - 1)) | r.getrandbits(wa - 1) if wa > 1 else 1
            b = (1 << (wb - 1)) | r.getrandbits(wb - 1) if wb > 1 else 1
            if k % 5 == 0:
                b = (1 << wb) - 1                  # all-ones divisor
            if k % 7 == 0:
                a = b                              # equal operands
            op = ["divu", "remu", "div", "rem"][k % 4]
            body.append(f"        li r4, {a}\n        li r5, {b}\n        {op} r{10 + k % 40}, r4, r5")
            body.append(f"        neg r6, r4\n        {['div', 'rem'][k % 2]} r{50 + k % 8}, r6, r5")
        T[f"md_div_widths{part}"] = PRE + "\n".join(body) + "\n" + POST
    # multiplier (v3, 4 passes of 128x32): operands whose 32-bit multiplier chunks hit edge patterns
    # (zero / all-ones chunks, carries rippling across every pass boundary), dependent chains,
    # mul<->mulhu result-cache pairs, and a mul aborted by an older trap / interrupted
    r = random.Random(91)
    chunks = [0, 1, 0xFFFFFFFF, 0x80000000, 0x7FFFFFFF]
    for part in range(2):
        body = []
        for k in range(18):
            a = r.choice([M, 1 << 127, r.getrandbits(128), (1 << 96) - 1, 0xFFFFFFFF, 3])
            b = sum(r.choice(chunks + [r.getrandbits(32)]) << (32 * j) for j in range(4))
            if k % 6 == 0:
                a, b = b, a
            op = ["mul", "mulhu"][k % 2]
            body.append(f"        li r4, {a}\n        li r5, {b}\n        {op} r{10 + k}, r4, r5")
            if k % 3 == 0:
                body.append(f"        {['mulhu', 'mul'][k % 2]} r{30 + k}, r4, r5")   # cache hit
            if k % 4 == 1:
                body.append(f"        mul r6, r{10 + k}, r5\n        mulhu r7, r6, r{10 + k}")  # dependent chain
        T[f"md_mul_passes{part}"] = PRE + "\n".join(body) + "\n" + POST
    for i, base in enumerate(SIMD_FUNCS):
        for suf in LANE_SUFFIX:
            if base == "vmul" and suf == "d":
                continue
            T[f"simd_{base}_{suf}"] = rtype_test(f"{base}.{suf}", base in SIMD_UNARY, 300 + 4 * i + LANE_SUFFIX[suf], n=8)
    # ---------------- immediate ALU
    for i, (mn, rng_) in enumerate([("addi", (-8192, 8191)), ("andi", (-8192, 8191)), ("ori", (-8192, 8191)),
                                    ("xori", (-8192, 8191)), ("slti", (-8192, 8191)), ("sltiu", (-8192, 8191)),
                                    ("slli", (0, 127)), ("srli", (0, 127)), ("srai", (0, 127)),
                                    ("addiw", (-8192, 8191)), ("addiwu", (-8192, 8191)), ("slliw", (0, 31)),
                                    ("srliw", (0, 31)), ("sraiw", (0, 31)), ("slliwu", (0, 31))]):
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
    T["haz_mul_abort"] = PRE + """
        la r4, handler
        csrw tvec, r4
        li r5, -1
        li r6, 0x123456789abcdef0123456789abcdef
        mul r8, r5, r6          # completes
        ld r7, 3(r0)            # misaligned: traps in MEM while the next mul is mid-flight in EX
        mul r9, r6, r6
        mulhu r10, r6, r6       # after the trap: must recompute, not see a stale half-finished product
        mul r11, r9, r10
        mul r12, r11, r11
        mulhu r13, r11, r11
        halt zero
handler: addi r53, r53, 1
        csrr r51, epc
        addi r51, r51, 4
        csrw epc, r51
        eret
"""
    # v4: shared multiplier array -- vmul lane boundaries (Booth closing digits) and scalar/SIMD sharing
    pats = [0x80808080808080808080808080808080, 0x7F7F7F7F7F7F7F7F7F7F7F7F7F7F7F7F, M,
            0x80008000800080008000800080008000, 0x7FFF7FFF7FFF7FFF7FFF7FFF7FFF7FFF, 0xFF00FF00FF00FF00FF00FF00FF00FF00,
            0x80000000800000008000000080000000, 0x7FFFFFFF7FFFFFFF7FFFFFFF7FFFFFFF, 0x00FF00FF00FF00FF00FF00FF00FF00FF,
            0xFFFF0000FFFF0000FFFF0000FFFF0000, 0x0123456789ABCDEF_FEDCBA9876543210, 0x01010101010101010101010101010101,
            0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA, 0x55555555555555555555555555555555]
    for part in range(2):
        body = []
        r = random.Random(900 + part)
        for k in range(20):
            x, y = r.choice(pats), r.choice(pats + [r.getrandbits(128)])
            body.append(f"        li r4, {x}\n        li r5, {y}")
            for suf in "bhw":
                body.append(f"        vmul.{suf} r{10 + (3 * k + 'bhw'.index(suf)) % 50}, r4, r5")
        T[f"simd_vmul_lanes{part}"] = PRE + "\n".join(body) + "\n" + POST
    T["mul_share_hazards"] = PRE + """
        la r4, handler
        csrw tvec, r4
        li r5, 0xFFFFFFFF80000000_7FFFFFFF00000001
        li r6, 0x80808080FFFF0000_7F7F7F7F00FF00FF
        vmul.b r7, r5, r6       # SIMD uses the array in the cycle before the mul claims it
        mul r8, r5, r6
        vmul.h r9, r8, r6       # needs the mul result (forwarded) and the array right after the last pass
        mulhu r10, r5, r6       # result-cache hit: the array is not borrowed
        vmul.w r11, r10, r5
        mul r12, r11, r9
        mul r13, r12, r12       # back-to-back multiplies
        vmul.b r14, r13, r12
        vmul.w r15, r14, r14
        ld r16, 3(r0)           # misaligned: traps in MEM while the next mul is mid-pass
        mul r17, r15, r6
        vmul.h r18, r15, r6     # after the abort the array must be back in SIMD mode
        mulhu r19, r15, r6
        vmul.b r20, r19, r19
        halt zero
handler: addi r53, r53, 1
        csrr r51, epc
        addi r51, r51, 4
        csrw epc, r51
        eret
"""
    # v4: return address stack
    nest = []
    for k in range(12):                     # 12-deep chain: overflows the 8-entry RAS
        nest.append(f"F{k}:     addi r{20 + k}, ra, 0\n        addi r40, r40, {k + 1}")
        if k < 11:
            nest.append(f"        call F{k + 1}")
        nest.append(f"        addi ra, r{20 + k}, 0\n        ret")
    T["ras_nested"] = PRE + """
        li r5, 3
again:  call F0
        call F6                 # enter mid-chain
        call F10
        addi r5, r5, -1
        bnez r5, again
        halt zero
""" + "\n".join(nest) + "\n"
    T["ras_recursive"] = PRE + """
        li sp, 0x8000
        li a0, 12
        call rfib               # recursive fib(12) with ra spilled to a memory stack
        mv r40, a0
        li a0, 9
        call rfib
        mv r41, a0
        halt zero
rfib:   li t0, 2
        bltu a0, t0, rbase
        addi sp, sp, -48
        sq ra, 0(sp)
        sq a0, 16(sp)
        addi a0, a0, -1
        call rfib
        sq a0, 32(sp)
        lq a0, 16(sp)
        addi a0, a0, -2
        call rfib
        lq t1, 32(sp)
        add a0, a0, t1
        lq ra, 0(sp)
        addi sp, sp, 48
rbase:  ret
"""
    T["ras_sites"] = PRE + """
        li r5, 6
loop:   call inc
        call inc
        addi r6, r6, 1
        call dbl
        call inc
        call empty              # function that is only a return
        call empty
        addi r5, r5, -1
        bnez r5, loop
        la ra, co1
        jalr ra, 0(ra)          # coroutine-style jalr ra, ra: a push, not a pop
back:   la t0, tail
        jalr zero, 0(t0)        # indirect jump not through ra: neither push nor pop
        halt zero
co1:    addi r8, r8, 1
        jalr r7, 0(ra)          # return-like jalr writing another register: pops (-> back), writes r7
tail:   call inc
        halt zero
inc:    addi r10, r10, 1
        ret
dbl:    add r10, r10, r10
        ret
empty:  ret
"""
    T["ras_traps"] = PRE + """
        la r4, handler
        csrw tvec, r4
        li r52, -0x10000
        li r51, 40
        sq r51, 0x40(r52)       # timer at mtime = 40
        li r51, 5
        csrw status, r51
        li r9, 25
loop:   call f1
        ld r7, 3(r0)            # misaligned trap right behind a return
        call f2                 # call in EX while an older instruction traps in MEM: push undone
        addi r9, r9, -1
        bnez r9, loop
        li r9, 20
loop2:  call outer              # the return popped speculatively behind a trapping load must be undone,
        addi r9, r9, -1         # or outer's return mispredicts
        bnez r9, loop2
        halt zero
outer:  addi r14, ra, 0
        call inner
        addi ra, r14, 0
        ret
inner:  ld r7, 3(r0)
        ret
f1:     addi r11, ra, 0
        call f2
        ecall                   # trap inside a call chain; the handler itself calls a function
        addi ra, r11, 0
        ret
f2:     addi r12, r12, 1
        ret
handler: addi r20, ra, 0
        csrr r62, cause
        bltz r62, hirq
        call hsub
        csrr r51, epc
        addi r51, r51, 4
        csrw epc, r51
        addi ra, r20, 0
        eret
hirq:   lq r51, 0x30(r52)
        addi r51, r51, 37
        sq r51, 0x40(r52)
        call hsub
        addi ra, r20, 0
        eret
hsub:   addi r13, r13, 1
        ret
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
    # ---------------- tagged memory: clc / csc (shadow tag per 16-byte granule)
    T["capmem_basic"] = PRE + setup + """
        li r6, 64
        csetaddr r10, rc, r5
        csetbnd r10, r10, r6     # cap A = [data, data+64)
        csc r10, 32(r5)          # spill cap via untagged base: tag + metadata preserved
        clc r11, 32(r5)          # reload -> tagged, same perms/bounds
        cgettag r12, r11
        cgetlen r13, r11
        lq r14, 8(r11)           # misaligned through reloaded cap -> trap
        lq r14, 16(r11)          # deref reloaded cap: ok
        lq r15, 32(r5)           # plain load of a capability granule: value only, untagged
        cgettag r16, r15
        sb r0, 33(r5)            # partial data store into the granule clears its tag
        clc r17, 32(r5)
        cgettag r18, r17
        csc r10, 48(r10)         # store through the cap itself (in bounds)
        clc r19, 48(r10)
        csc r6, 48(r10)          # csc of an untagged register clears the tag
        clc r20, 48(r10)
        cgettag r21, r20
        csc r10, 56(r10)         # misaligned csc -> trap
        csc r10, 64(r10)         # out of bounds -> trap
        clc r22, 64(r10)         # out of bounds -> trap
        csc rc, 16(r5)           # spill the root capability
        clc r23, 16(r5)
        cgetlen r24, r23
        addi r25, r23, 0         # integer copy of the reloaded cap: untagged
        cgettag r26, r25
        li r7, -0x10000
        csc r10, 0x20(r7)        # csc to MMIO (hexout): value only
        clc r27, 0(r7)           # clc from MMIO: 0, untagged
        li r8, 0x40000
        clc r28, 0(r8)           # past RAM -> access fault
        addi r20, r20, 1
""" + POST + handler + DATA
    T["capmem_perms"] = PRE + setup + """
        li r6, 64
        csetaddr r10, rc, r5
        csetbnd r10, r10, r6
        csc r10, 0(r5)           # granule 0 of data holds a tagged cap
        li r7, 0x17              # LOAD|STORE|EXEC|STORE_CAP (no LOAD_CAP)
        candperm r11, r10, r7
        clc r12, 0(r11)          # loads the value, tag stripped (no LOAD_CAP)
        cgettag r13, r12
        li r7, 0x0F              # no STORE_CAP
        candperm r14, r10, r7
        csc r10, 16(r14)         # storing a tagged cap without STORE_CAP -> cap-permission trap
        csc r6, 16(r14)          # storing an untagged value is fine
        clc r15, 0(r14)          # LOAD_CAP present: tagged
        cgetperm r16, r15
        li r7, 2
        candperm r17, r10, r7    # store-only
        clc r18, 0(r17)          # no LOAD -> cap-permission trap
        li r7, 1
        candperm r19, r10, r7    # load-only
        csc r6, 0(r19)           # no STORE -> cap-permission trap
        cgetperm r20, rc
        addi r21, r21, 1
""" + POST + handler + DATA
    T["capmem_hazards"] = PRE + setup + """
        li r6, 48
        csetaddr r10, rc, r5
        csetbnd r11, r10, r6     # produced in EX ...
        csc r11, 0(r5)           # ... forwarded EX/MEM -> csc data (metadata too)
        clc r12, 0(r5)
        lq r13, 16(r12)          # clc -> load-use interlock on a capability base
        clc r14, 0(r5)
        csc r14, 16(r5)          # clc -> csc data (load-use)
        clc r15, 16(r5)
        cincaddri r16, r15, 16   # clc -> cap op (load-use)
        sq r16, 32(r16)          # bounds: 16+32+16 > 48 -> trap
        sq r16, 16(r16)          # ok, data store into granule data+32
        clc r17, 32(r5)          # untagged (data store)
        cgettag r18, r17
        csc r16, 0(r5)
        sd r0, 8(r5)             # sub-granule store clears tag
        clc r19, 0(r5)
        cgettag r20, r19
        csc r16, 0(r5)
        clc r21, 0(r5)
        csetbndi r22, r21, 16
        cgetbase r23, r22
""" + POST + handler + DATA
    # ---------------- PCC: capability-checked instruction fetch, cjalr
    T["pcc_call"] = PRE + setup + """
        cgetpcc r10              # root PCC, cursor = pc
        cgetlen r11, r10
        cgetperm r12, r10
        la r6, func
        csetaddr r13, rc, r6
        csetbndi r13, r13, 32    # code capability: exactly func's 8 instructions
        li r7, 0x05              # LOAD | EXEC
        candperm r13, r13, r7
        cjalr r1, r13            # call: PCC := r13, r1 = link capability
        cgetpcc r14              # back under the root PCC
        cgetlen r15, r14
        cjalr r1, r13            # call again (link cap reused)
        mv r16, r20
        j after
func:   cgetpcc r20              # PCC = [func, func+32), cursor = func
        addi r21, r21, 1
        cgetbase r22, r20
        cgetlen r23, r20
        beq r0, r0, f2           # branch inside the region
        addi r24, r24, 1
f2:     cgetperm r25, r20
        cjalr r0, r1             # return through the link capability
after:  addi r26, r26, 1
""" + POST + handler + DATA
    T["pcc_faults"] = PRE + """
        la r4, phandler
        csrw tvec, r4
        la r6, short
        csetaddr r10, rc, r6
        csetbndi r10, r10, 8     # covers only 2 of short's instructions
        cjalr r1, r10            # -> runs 2 instructions, then fetch cap-bounds fault at short+8
        addi r30, r30, 1
        li r7, 0x03              # LOAD|STORE, no EXEC
        candperm r11, r10, r7
        cjalr r1, r11            # cap-permission trap at the cjalr (tval = target)
        cjalr r1, r6             # untagged -> cap-tag trap
        la r6, region
        csetaddr r12, rc, r6
        csetbndi r12, r12, 16
        cjalr r1, r12            # region jumps out of its PCC with plain jalr -> fetch fault at target
        addi r31, r31, 1
        csetbndi r13, r12, 64    # widening -> cap-bounds trap (r13 stays untagged)
        cjalr r1, r13            # -> cap-tag trap
        addi r32, r32, 1
        halt zero
short:  addi r20, r20, 1
        addi r21, r21, 1
        addi r22, r22, 1         # fetch fault here (outside PCC)
        cjalr r0, r1
region: addi r23, r23, 1
        la r8, outside
        jalr r0, r8, 0           # target outside PCC: next fetch traps (epc = outside)
        nop
outside: addi r24, r24, 1
        cjalr r0, r1
phandler:
        csrr r50, cause
        csrr r51, epc
        csrr r52, tval
        addi r53, r53, 1
        cgetpcc r54              # handler always runs under the root PCC
        cgetlen r55, r54
        bne r52, r51, notfetch   # fetch fault (tval == epc): continue under the root PCC
        csetepcc rc
        j  out
notfetch: addi r51, r51, 4
        csrw epc, r51
out:    eret
"""
    T["pcc_eret_restore"] = PRE + """
        la r4, h2
        csrw tvec, r4
        la r6, body
        csetaddr r10, rc, r6
        csetbndi r10, r10, 32
        cjalr r1, r10
        cgetpcc r30
        cgetlen r31, r30
        csetepcc r5              # untagged -> cap-tag trap
        halt zero
body:   .word 0                  # illegal inside the restricted region
        cgetpcc r20              # eret restored the restricted PCC
        cgetlen r21, r20
        j bout                   # leaves the 32-byte region: the restored fetch PCC must trap
        nop
        nop
        nop
        nop
bout:   addi r22, r22, 1         # (skipped: fetch cap-bounds fault, then resumes under root)
        addi r23, r23, 1
        cjalr r0, r1
h2:     addi r53, r53, 1
        cgetpcc r54
        csrr r51, epc
        csrr r52, tval
        bne r51, r52, h2n
        csetepcc rc              # fetch fault: continue under the root PCC
h2n:    addi r51, r51, 4
        csrw epc, r51
        eret
"""
    # ---------------- sealed capabilities
    T["seal_ops"] = PRE + setup + """
        li r6, 64
        csetaddr r10, rc, r5
        csetbnd r10, r10, r6     # data capability
        li r6, 0x60              # SEAL | UNSEAL
        candperm r11, rc, r6     # sealing root
        li r7, 42
        csetaddr r12, r11, r7    # sealing authority for otype 42
        cseal r13, r10, r12      # r13 = sealed (otype 42)
        cgettype r14, r13
        cgettag r15, r13
        cgetlen r16, r13
        lq r17, 0(r13)           # deref sealed -> cap-sealed
        sq r7, 0(r13)            # -> cap-sealed
        clc r17, 0(r13)          # -> cap-sealed
        csc r7, 0(r13)           # -> cap-sealed
        cincaddri r18, r13, 16   # modify sealed -> cap-sealed
        csetaddr r18, r13, r7
        cincaddr r18, r13, r7
        csetbndi r18, r13, 8
        candperm r18, r13, r7
        cjalr r1, r13            # jump through sealed -> cap-sealed
        csetepcc r13             # -> cap-sealed
        csc r13, 0(r5)           # sealed caps can be stored ...
        clc r19, 0(r5)           # ... and reloaded, still sealed
        cgettype r20, r19
        cunseal r21, r19, r12    # unseal with matching authority
        cgettype r22, r21
        lq r23, 16(r21)          # usable again
        cclrtag r24, r13
        li r8, 43
        csetaddr r25, r11, r8
        cunseal r26, r13, r25    # wrong otype -> cap-sealed
        cseal r26, r13, r12      # already sealed -> cap-sealed
        cseal r26, r10, r13      # sealed authority -> cap-sealed
        cunseal r26, r10, r12    # not sealed -> cap-sealed
        li r9, 0x40
        candperm r27, r12, r9    # UNSEAL only
        cseal r26, r10, r27      # no SEAL -> cap-permission
        cunseal r28, r13, r27    # ok
        li r9, 0x20
        candperm r29, r12, r9    # SEAL only
        cunseal r26, r13, r29    # no UNSEAL -> cap-permission
        cseal r26, r10, r0       # untagged authority -> cap-tag
        cseal r26, r5, r12       # untagged rs1 -> cap-tag
        cunseal r26, r5, r12     # untagged rs1 -> cap-tag
        csetaddr r30, r11, r0
        cseal r26, r10, r30      # otype 0 -> cap-bounds
        li r7, 0x10000
        csetaddr r30, r11, r7
        cseal r26, r10, r30      # otype > 0xFFFF -> cap-bounds
        li r7, 100
        csetaddr r31, r11, r7
        csetbndi r31, r31, 10    # authority for otypes [100, 110)
        cseal r32, r10, r31      # ok: otype 100
        cincaddri r33, r31, 10
        cseal r26, r10, r33      # cursor == top -> cap-bounds
        cunseal r26, r32, r33    # cursor out of bounds -> cap-bounds
        cgettype r34, r32
        cgettype r35, rc
        cgettype r36, r5
        cgetperm r37, rc
        addi r38, r38, 1
""" + POST + handler + DATA
    # ---------------- v3: sealed entry capabilities (sentries) and cinvoke
    T["sentry_ops"] = PRE + setup + """
        la r6, func
        csetaddr r10, rc, r6
        csetbndi r10, r10, tail - func + 4   # code capability for func only
        csealentry r11, r10      # sentry
        cgettype r12, r11        # 0xFFFF
        cgettag r13, r11
        lq r14, 0(r11)           # deref a sentry -> cap-sealed
        cincaddri r14, r11, 4    # modify -> cap-sealed
        csetaddr r14, r11, r6    # -> cap-sealed
        cjalr r1, r11            # call through the sentry: unsealed into PCC, r1 = sentry link
        cgettype r15, r1         # link stayed a sentry in the caller too
        cjalr r1, r10            # plain call: plain (unsealed) link
        li r7, 0xFFFF
        csetaddr r16, rc, r7
        cseal r17, r10, r16      # otype 0xFFFF is reserved -> cap-bounds
        li r7, 9
        csetaddr r16, rc, r7
        cseal r17, r10, r16      # ordinary sealed code cap (otype 9)
        cjalr r1, r17            # sealed but not a sentry -> cap-sealed
        csealentry r18, r17      # already sealed -> cap-sealed
        csealentry r18, r6       # untagged -> cap-tag
        li r7, 3
        candperm r19, r10, r7    # no EXEC
        csealentry r18, r19      # -> cap-permission
        li r7, 0xFFFF
        csetaddr r16, rc, r7
        cunseal r18, r11, r16    # sentries cannot be cunseal'ed -> cap-sealed
        csc r11, 0(r5)           # sentries survive tagged memory
        clc r20, 0(r5)
        cjalr r1, r20            # call through the reloaded sentry
        csealentry r21, r10
        li r1, 0
        cjalr r0, r21            # sentry jump without link (tail call): func halts via 'tail'
back:   addi r40, r40, 1
        halt zero
func:   cgetpcc r30              # unsealed PCC, bounds = func
        cgettype r31, r30
        cgettype r32, r1
        addi r33, r33, 1
        lq r34, 0(r1)            # callee cannot read through the sentry link -> cap-sealed
        beqz r1, tail
fend:   cjalr r0, r1             # return through the (sentry or plain) link
tail:   halt zero
""" + handler + DATA
    T["sentry_hazards"] = PRE + setup + """
        la r6, f2
        csetaddr r10, rc, r6
        csetbndi r10, r10, 16
        csealentry r11, r10      # sentry consumed by the very next instruction (EX->EX forwarding)
        cjalr r1, r11
        csealentry r12, r10
        nop
        cjalr r1, r12            # MEM->EX forwarding
        csc r12, 16(r5)
        clc r13, 16(r5)
        cjalr r1, r13            # load-use into a sentry jump
        halt zero
f2:     addi r20, r20, 1
        cgettype r21, r1
        cjalr r0, r1
        addi r22, r22, 1         # never
""" + handler + DATA
    T["cinvoke_ops"] = PRE + setup + """
        la r6, method
        csetaddr r10, rc, r6
        csetbndi r10, r10, mend - method + 4    # code: EXEC, method only
        li r7, 64
        csetaddr r11, rc, r5
        csetbnd r11, r11, r7
        li r7, 0x21B             # data: LOAD|STORE|LOAD_CAP|STORE_CAP|PERMIT_CINVOKE, no EXEC
        candperm r11, r11, r7
        li r7, 0x60
        candperm r12, rc, r7
        li r7, 77
        csetaddr r12, r12, r7    # sealing authority, otype 77
        cseal r13, r10, r12      # sealed code
        cseal r14, r11, r12      # sealed data
        li r7, 0x5555
        sq r7, 0(r5)
p1:     cgetpcc r9
        cincaddri r9, r9, ret1 - p1
        csealentry r1, r9        # return sentry
        cinvoke r20, r13, r14    # call: PCC = unsealed code, r20 = unsealed data
ret1:   cgettype r21, r20        # data stays in r20 for the caller to inspect
        cgetperm r22, r20
        cinvoke r20, r14, r13    # code/data swapped: data operand lacks... code has no EXEC -> cap-permission
        cinvoke r20, r13, r13    # data has EXEC -> cap-permission
        cinvoke r20, r10, r14    # code unsealed -> cap-sealed
        cinvoke r20, r13, r11    # data unsealed -> cap-sealed
        csealentry r15, r10
        cinvoke r20, r15, r14    # sentry as code -> cap-sealed
        li r7, 78
        csetaddr r16, r12, r7
        cseal r17, r11, r16      # data sealed with otype 78
        cinvoke r20, r13, r17    # otype mismatch -> cap-sealed
        cinvoke r20, r6, r14     # untagged code -> cap-tag
        cinvoke r20, r13, r5     # untagged data -> cap-tag
        csc r13, 16(r5)
        csc r14, 32(r5)
        clc r23, 16(r5)
        clc r24, 32(r5)
p2:     cgetpcc r9
        cincaddri r9, r9, ret2 - p2
        csealentry r1, r9
        cinvoke r0, r23, r24     # invoke reloaded pair, rd = r0 (data discarded)
ret2:   addi r40, r40, 1
        halt zero
method: cgetpcc r30
        cgetlen r31, r30
        lq r32, 0(r20)           # method sees its data through r20 (unsealed)
        addi r32, r32, 1
        sq r32, 0(r20)
        cgettype r33, r20
mend:   cjalr r0, r1             # return through the caller's sentry
""" + handler + DATA
    # ---------------- v3: clc permission attenuation (read-only authority => loaded caps are read-only)
    T["clc_attenuate"] = PRE + setup + """
        li r6, 64
        csetaddr r10, rc, r5
        csetbnd r10, r10, r6     # RW data cap (all perms)
        csc r10, 0(r5)           # spill it
        li r7, 9                 # LOAD | LOAD_CAP: read-only view that may load capabilities (no LOAD_MUTABLE)
        candperm r11, r10, r7
        clc r12, 0(r11)          # loaded through a read-only view
        cgetperm r13, r12        # STORE and STORE_CAP gone
        cgettag r14, r12
        sq r7, 16(r12)           # -> cap-permission (deep read-only)
        lq r15, 16(r12)          # loads still fine
        csc r10, 16(r12)         # -> cap-permission
        clc r16, 0(r10)          # through the RW view: full permissions kept
        cgetperm r17, r16
        clc r18, 0(r5)           # untagged (hybrid) base: unchanged
        cgetperm r19, r18
        li r7, 3                 # LOAD | STORE (no LOAD_CAP): tag stripped as before
        candperm r20, r10, r7
        clc r21, 0(r20)
        cgettag r22, r21
        li r7, 0x60
        candperm r23, rc, r7
        li r7, 5
        csetaddr r23, r23, r7
        cseal r24, r10, r23
        csc r24, 32(r5)          # sealed capability spilled
        clc r25, 32(r11)         # sealed caps are not attenuated (opaque)
        cunseal r26, r25, r23
        cgetperm r27, r26
        li r7, 0x1D              # LOAD|EXEC|LOAD_CAP|STORE_CAP (no STORE)
        candperm r28, r10, r7
        clc r29, 0(r28)
        cgetperm r30, r29        # STORE_CAP also removed
        clc r31, 0(r11)
        sq r7, 0(r31)            # load-use of an attenuated cap -> cap-permission
        candperm r32, r31, r7
        cgetperm r33, r32
""" + POST + handler + DATA
    # ---------------- v4: GLOBAL / STORE_LOCAL, LOAD_MUTABLE, PERMIT_CINVOKE
    T["perm_local"] = PRE + setup + """
        li r6, 64
        csetaddr r10, rc, r5
        csetbnd r10, r10, r6     # all permissions: GLOBAL and STORE_LOCAL
        li r7, 0x77F             # everything but GLOBAL
        candperm r11, r10, r7    # a local capability
        li r8, 0x3FF             # everything but STORE_LOCAL
        candperm r12, r10, r8    # global authority without STORE_LOCAL
        csc r10, 0(r12)          # global cap through it: fine
        csc r11, 16(r12)         # local cap -> cap-permission (tval = ea)
        csc r11, 16(r10)         # authority with STORE_LOCAL: fine
        csc r11, 32(r5)          # untagged (hybrid) base: unchecked, fine
        clc r13, 16(r10)         # the local cap round-trips and stays local
        cgetperm r14, r13
        cgetperm r15, r11
        li r9, 0x60
        candperm r16, rc, r9
        li r9, 9
        csetaddr r16, r16, r9
        cseal r17, r11, r16      # sealing does not make it global
        csc r17, 48(r12)         # -> cap-permission
        csc r17, 48(r10)         # fine
        csc r6, 0(r12)           # untagged value: no local rule
        candperm r18, r10, r7
        csc r18, 0(r12)          # local cap produced by the previous instruction (forwarded) -> cap-permission
        li r9, 0x37F             # neither GLOBAL nor STORE_LOCAL
        candperm r19, r10, r9
        csc r19, 0(r19)          # a local cap cannot even store itself without STORE_LOCAL
        candperm r20, r10, r7    # local but with STORE_LOCAL
        csc r20, 0(r20)          # fine
        li r9, 0x7EF             # no STORE_CAP: that check comes first
        candperm r21, r10, r9
        csc r11, 0(r21)          # -> cap-permission (STORE_CAP)
        clc r22, 0(r10)
        cgetperm r23, r22
        sq r6, 16(r12)           # plain store through the authority clears the local cap's tag
        clc r24, 16(r10)
        cgettag r25, r24
""" + POST + handler + DATA
    T["perm_load_mutable"] = PRE + setup + """
        li r6, 64
        csetaddr r10, rc, r5
        csetbnd r10, r10, r6     # all permissions
        csc r10, 0(r5)           # granule 0: cap A (cursor = data, so A can reload itself)
        li r7, 0x6FF             # everything but LOAD_MUTABLE (STORE kept)
        candperm r11, r10, r7
        clc r12, 0(r11)          # v4: attenuated (v3 kept STORE because the authority had it)
        cgetperm r13, r12        # STORE, STORE_CAP, STORE_LOCAL, LOAD_MUTABLE gone
        sq r7, 32(r12)           # -> cap-permission
        lq r14, 16(r12)          # loads fine
        clc r15, 0(r12)          # transitive: loaded through the attenuated cap -> attenuated again
        cgetperm r16, r15
        li r7, 0x109             # LOAD|LOAD_CAP|LOAD_MUTABLE, no STORE
        candperm r17, r10, r7
        clc r18, 0(r17)          # v4: NOT attenuated (v3 stripped STORE here)
        cgetperm r19, r18
        sq r7, 32(r18)           # fine: the loaded cap still has STORE
        li r7, 0x60
        candperm r20, rc, r7
        li r7, 6
        csetaddr r20, r20, r7
        cseal r21, r10, r20
        csc r21, 16(r5)
        clc r22, 16(r11)         # sealed: loaded unchanged
        cunseal r23, r22, r20
        cgetperm r24, r23
        clc r25, 0(r11)
        csc r10, 48(r25)         # load-use of an attenuated cap -> cap-permission
        clc r26, 0(r5)           # hybrid base: unchanged
        cgetperm r27, r26
        li r7, 0x7F7             # no LOAD_CAP: tag stripped (LOAD_CAP rule first)
        candperm r28, r10, r7
        clc r29, 0(r28)
        cgettag r30, r29
""" + POST + handler + DATA
    T["perm_cinvoke"] = PRE + setup + """
        la r6, meth
        csetaddr r10, rc, r6
        csetbndi r10, r10, mend2 - meth + 4
        li r7, 64
        csetaddr r11, rc, r5
        csetbnd r11, r11, r7
        li r7, 0x21B
        candperm r11, r11, r7    # data with PERMIT_CINVOKE
        li r7, 0x5FF
        candperm r12, r10, r7    # code without PERMIT_CINVOKE
        li r7, 0x01B
        candperm r13, r11, r7    # data without PERMIT_CINVOKE
        li r7, 0x60
        candperm r14, rc, r7
        li r7, 99
        csetaddr r14, r14, r7
        cseal r15, r10, r14      # good code
        cseal r16, r11, r14      # good data
        cseal r17, r12, r14      # code, no PERMIT_CINVOKE
        cseal r18, r13, r14      # data, no PERMIT_CINVOKE
        cinvoke r20, r17, r16    # -> cap-permission, tval = code cursor
        cinvoke r20, r15, r18    # -> cap-permission, tval = data cursor
        cinvoke r20, r17, r18    # both missing: code reported first
        li r7, 64
        csetaddr r19, rc, r5
        csetbnd r19, r19, r7
        li r7, 0x3FF             # data with PERMIT_CINVOKE and EXEC
        candperm r19, r19, r7
        cseal r19, r19, r14
        cinvoke r20, r17, r19    # PERMIT_CINVOKE check comes before the EXEC checks
        cinvoke r20, r15, r19    # -> cap-permission (data has EXEC)
pc1:    cgetpcc r9
        cincaddri r9, r9, rt1 - pc1
        csealentry r1, r9
        cinvoke r20, r15, r16    # succeeds
rt1:    cgetperm r21, r20
        halt zero
meth:   lq r32, 0(r20)
        addi r32, r32, 3
        sq r32, 0(r20)
mend2:  cjalr r0, r1
""" + handler + DATA
    # ---------------- v4: atomics
    body = ["        la r5, data"]
    r = random.Random(950)
    for k in range(10):
        x, y = r.choice(VALS), r.choice(VALS)
        fn = ["amoadd", "amoand", "amoor", "amoxor", "amoswap"][k % 5]
        off = 16 * (k % 4)
        body.append(f"        li r6, {x}\n        li r7, {y}\n        sq r6, {off}(r5)\n        addi r8, r5, {off}")
        body.append(f"        {fn} r{10 + k}, r7, (r8)\n        lq r{30 + k}, {off}(r5)")
    body.append("        li r6, 77\n        amoswap r6, r6, (r5)      # rd == rs2: old value out, register value in")
    body.append("        amoadd r0, r6, (r5)        # rd = r0: memory still updated\n        lq r40, 0(r5)")
    body.append("        amoadd r5, r6, (r5)        # rd == rs1\n        la r5, data\n        lq r41, 0(r5)")
    T["amo_ops"] = PRE + "\n".join(body) + "\n" + POST + DATA
    T["amo_lrsc"] = PRE + setup + """
        li r6, 100
        sq r6, 0(r5)
        lr r7, (r5)
        addi r7, r7, 1
        sc r8, r7, (r5)          # success: 0
        sc r9, r7, (r5)          # reservation consumed: 1
        lr r10, (r5)
        sq r0, 64(r5)            # any store clears the reservation (even to another granule)
        sc r11, r7, (r5)         # 1
        lr r12, (r5)
        addi r13, r5, 16
        sc r14, r7, (r13)        # different granule: 1, no store
        lr r15, (r13)
        lr r16, (r5)             # a second lr moves the reservation
        sc r17, r7, (r13)        # 1
        lr r18, (r5)
        ecall                    # a trap clears the reservation
        sc r19, r7, (r5)         # 1
        lr r20, (r5)
        amoadd r21, r7, (r13)    # an AMO is a store: clears it
        sc r22, r7, (r5)         # 1
        lr r23, (r5)
        lq r24, 0(r5)            # loads do not
        csrr r25, scratch        # neither do CSR reads
        sc r26, r7, (r5)         # 0
        li r30, 10               # lr/sc increment loop
spin:   lr r31, (r5)
        addi r31, r31, 3
        sc r32, r31, (r5)
        bnez r32, spin
        addi r30, r30, -1
        bnez r30, spin
        lq r33, 0(r5)
        lr r34, (r5)
        sc r35, r34, (r5)
        sc r36, r34, (r5)        # back-to-back: second fails
""" + POST + handler + DATA
    T["amo_faults"] = PRE + setup + """
        addi r6, r5, 8
        lr r10, (r6)             # misaligned -> 5
        amoadd r11, r6, (r6)     # misaligned -> 5
        li r7, -0x10000
        lr r12, (r7)             # MMIO -> access fault (atomics are RAM-only)
        sc r13, r7, (r7)         # -> 6
        li r7, 0x40000
        amoswap r14, r7, (r7)    # past RAM -> 6
        li r8, 64
        csetaddr r20, rc, r5
        csetbnd r20, r20, r8     # [data, data+64)
        li r8, 0x7FD             # no STORE
        candperm r21, r20, r8
        lr r15, (r21)            # fine (LOAD)
        sc r16, r8, (r21)        # -> 4
        amoadd r17, r8, (r21)    # -> 4 (needs LOAD and STORE)
        li r8, 0x7FE             # no LOAD
        candperm r22, r20, r8
        lr r18, (r22)            # -> 4
        sc r19, r8, (r22)        # store-only authority: sc allowed (no reservation -> 1)
        amoswap r23, r8, (r22)   # -> 4
        addi r9, r5, 64
        csetaddr r24, r20, r9
        amoor r25, r8, (r24)     # one past the end -> 3
        li r8, 0x60
        candperm r26, rc, r8
        li r8, 3
        csetaddr r26, r26, r8
        cseal r27, r20, r26
        amoxor r28, r8, (r27)    # sealed base -> 7
        lr r29, (r5)
        sc r30, r8, (r21)        # faulting sc (no STORE): trap, and the trap clears the reservation
        sc r31, r8, (r5)         # 1
        .word 0x07000005         # OP_AMO func 7: illegal
""" + POST + handler + DATA
    T["amo_caps"] = PRE + setup + """
        li r8, 64
        csetaddr r20, rc, r5
        csetbnd r20, r20, r8     # all perms
        csc r20, 0(r5)
        amoswap r10, r20, (r5)   # capability swap: old cap out (tagged), new cap in
        cgettag r11, r10
        lr r12, (r5)             # lr returns the tagged cap (clc rules)
        cgettag r13, r12
        csetaddr r14, r12, r5
        cincaddri r14, r14, 16
        sc r15, r14, (r5)        # sc stores a capability (tag kept)
        clc r16, 0(r5)
        cgetbase r17, r16
        li r8, 0x7F7             # no LOAD_CAP: the old value comes back untagged
        candperm r21, r20, r8
        amoswap r18, r20, (r21)
        cgettag r19, r18
        li r8, 0x7EF             # no STORE_CAP: swapping a cap in -> 4
        candperm r22, r20, r8
        amoswap r23, r20, (r22)
        amoswap r24, r8, (r22)   # swapping an integer in is fine (granule tag cleared)
        clc r25, 0(r5)
        cgettag r26, r25
        csc r20, 0(r5)
        li r8, 0x6FF             # no LOAD_MUTABLE: old cap attenuated
        candperm r27, r20, r8
        amoswap r28, r20, (r27)
        cgetperm r29, r28
        lr r30, (r27)
        cgetperm r31, r30
        li r8, 0x77F
        candperm r32, r20, r8    # local cap
        li r8, 0x3FF
        candperm r33, r20, r8    # authority without STORE_LOCAL
        amoswap r34, r32, (r33)  # -> 4
        lr r35, (r33)
        sc r36, r32, (r33)       # -> 4 (checks come before the reservation test)
        sc r37, r32, (r20)       # reservation was cleared by the trap: 1
        lr r38, (r20)
        sc r39, r32, (r20)       # STORE_LOCAL authority: 0, local cap stored
        clc r40, 0(r5)
        cgetperm r41, r40
        amoadd r42, r8, (r5)     # arithmetic on a tagged granule: old value untagged, tag cleared
        cgettag r43, r42
        clc r44, 0(r5)
        cgettag r45, r44
        amoor r46, r20, (r5)     # a tagged rs2 is used as data only: the granule stays untagged
        clc r47, 0(r5)
        cgettag r48, r47
""" + POST + handler + DATA
    T["amo_hazards"] = PRE + setup + """
        li r6, 5
        sq r6, 0(r5)
        lr r7, (r5)
        addi r8, r7, 1           # load-use on lr
        sc r9, r8, (r5)
        beqz r9, ok1             # sc result consumed by the next instruction
        addi r40, r40, 1
ok1:    amoadd r10, r8, (r5)
        add r11, r10, r10        # load-use on amoadd
        amoadd r12, r11, (r5)    # back-to-back AMOs on one address
        amoswap r13, r12, (r5)
        lq r14, 0(r5)            # load right after an AMO
        sq r14, 16(r5)
        addi r15, r5, 16
        lr r16, (r15)            # store then lr of the same granule
        add r17, r16, r16
        sc r18, r17, (r15)       # data forwarded from the previous instruction
        lq r19, 16(r5)
        amoxor r20, r19, (r15)
        amoxor r21, r20, (r15)
        lq r22, 16(r5)
        li r23, -1
        amoadd r24, r23, (r15)   # 128-bit wraparound
        amoadd r25, r23, (r15)
        lq r26, 16(r5)
""" + POST + handler + DATA
    # ---------------- v4: readable EPCC
    T["epcc_read"] = PRE + """
        la r4, eh
        csrw tvec, r4
        cgetepcc r10             # reset: root, cursor = epc = 0
        cgetperm r11, r10
        la r5, data
        li r6, 64
        csetaddr r12, rc, r5
        csetbnd r12, r12, r6
        csetepcc r12
        cgetepcc r13             # right behind csetepcc (EPCC written in MEM): sees the new EPCC
        cgetbase r14, r13        # load-use style interlock on the cgetepcc result
        csrw epc, r5
        cgetepcc r15             # right behind csrw epc: cursor = new epc
        add r16, r15, r15
        la r6, fn
        csetaddr r17, rc, r6
        csetbndi r17, r17, fend - fn
        li r7, 0x1A5             # EXEC|LOAD|SEAL|GLOBAL|LM
        candperm r17, r17, r7
        csealentry r18, r17
        cjalr r1, r18            # sentry call into a bounded region that traps
        cgetepcc r30             # after eret: EPCC = the region's (unsealed) PCC
        cgetlen r31, r30
        cgettype r32, r30
        li r7, 0x10
        csrw status, r7          # PU: eret drops to user mode
        la r6, uc
        csrw epc, r6
        csetepcc rc
        eret
uc:     cgetepcc r33             # user mode: privilege-violation
        ecall
        halt zero
fn:     addi r20, r20, 1
        ecall                    # trap inside the sentry-entered region
        cjalr r0, r1
fend:
eh:     cgetepcc r40             # handler: the trapping instruction's PCC, cursor = epc
        cgetbase r41, r40
        cgetlen r42, r40
        cgetperm r43, r40
        csrr r44, cause
        csrr r45, epc
        addi r45, r45, 4
        csrw epc, r45
        csrr r46, status
        andi r46, r46, -17       # back to supervisor
        csrw status, r46
        eret
""" + DATA
    # ---------------- v3: user / supervisor privilege
    phandler = """
phandler: csrr r50, cause
        csrr r51, epc
        csrr r52, tval
        csrr r49, status
        addi r53, r53, 1
        bltz r50, pirq
        addi r51, r51, 4
        csrw epc, r51
        li r48, 8
        bne r50, r48, pret
        andi r49, r49, -17       # ecall: return to supervisor mode (PU <- 0)
        csrw status, r49
pret:   eret
pirq:   addi r47, r47, 1         # timer: re-arm, resume where interrupted (same mode)
        li r46, -0x10000
        lq r45, 0x30(r46)
        addi r45, r45, 7
        sq r45, 0x40(r46)
        eret
"""
    psetup = "        la r4, phandler\n        csrw tvec, r4\n        la r5, data\n"
    def enter_user(lbl, st=0x10):
        return f"        la r6, {lbl}\n        csrw epc, r6\n        li r7, {st}\n        csrw status, r7\n        eret\n"
    T["priv_basic"] = PRE + psetup + """
        li r7, 0x1F
        csrw status, r7          # U is read-only to csrw: reads back 0x17
        csrr r8, status
        csrw status, r0
""" + enter_user("user1") + """
user1:  csrr r21, status         # first user instruction is privileged -> privilege-violation (tval = word)
        addi r20, r20, 1
        csrw scratch, r20        # -> privilege-violation
        .word 0x0024003d         # csrr of CSR 9: illegal-instruction beats privilege
        halt zero                # -> privilege-violation (does not stop the machine)
        csetepcc rc              # -> privilege-violation
        csetepcc r0              # privilege beats cap-tag
        eret                     # -> privilege-violation
        cgetpcc r22              # unprivileged capability ops still work
        mv r23, r50
        ecall                    # -> cause 8, handler returns in supervisor mode
        csrr r24, status         # supervisor again
        ecall                    # ecall from supervisor: cause 8, PU = 0
        csrr r25, cause
        csrw status, r0
        li r7, 0x10
        csrw status, r7          # PU set, then eret right behind it (CSR write in MEM -> eret)
        la r6, user2
        csrw epc, r6
        eret
user2:  lq r26, 0(r5)            # hybrid access with an empty user window -> privilege-violation
        addi r27, r26, 1         # load-use after the faulting load
        ecall
        halt zero
""" + phandler + DATA
    T["priv_mem"] = PRE + psetup + """
        addi r6, r5, 32
        csrw ubase, r6           # user window for untagged bases = [data+32, data+64)
        addi r6, r5, 64
        csrw ubound, r6
        csrr r7, ubase
        csrr r8, ubound
        li r9, -0x10000
        csetaddr r10, rc, r9
        csetbndi r10, r10, 16    # capability to the console register only
        csetaddr r11, rc, r5
        li r12, 96
        csetbnd r11, r11, r12    # capability to the data area
        lq r13, 0(r5)            # supervisor: window does not apply
""" + enter_user("u2") + """
u2:     lq r20, 32(r5)           # in window
        ld r21, 56(r5)           # ends exactly at ubound
        lq r22, 16(r5)           # below ubase -> privilege-violation (tval = ea)
        lq r23, 64(r5)           # at ubound -> privilege-violation
        ld r24, 60(r5)           # straddles ubound and misaligned: privilege wins
        lw r25, 34(r5)           # misaligned inside the window -> misaligned
        sq r20, 48(r5)           # store in window
        sq r21, 16(r5)           # store outside -> privilege-violation, must not happen
        lq r22, 16(r5)
        sb r20, 0(r9)            # console through an untagged base -> privilege-violation
        li r26, 85
        sb r26, 0(r10)           # console through a capability: allowed ('U')
        sb r26, 16(r10)          # capability bounds -> cap-bounds
        lq r27, 0(r11)           # tagged base outside the window: capability-checked only
        lq r28, 0x30(r9)         # mtime through an untagged base -> privilege-violation
        csc r11, 48(r5)
        clc r29, 48(r5)          # tagged memory in the window
        lq r30, 4096(r0)
        sd r20, 0x10(r9)         # EXIT through an untagged base -> privilege-violation, no halt
        li r31, 77
        ecall
        csrw ubound, r0
        lq r32, 48(r5)
        halt zero
""" + phandler + DATA
    T["priv_irq"] = PRE + psetup + """
        li r9, -0x10000
        li r6, 30
        sq r6, 0x40(r9)          # mtimecmp
""" + enter_user("u3", 0x16) + """
u3:     li r20, 25               # user loop, preempted by the timer every few instructions
uloop:  addi r21, r21, 3
        add r22, r22, r21
        addi r20, r20, -1
        bnez r20, uloop
        csrr r23, status         # still user after the interrupts -> privilege-violation
        ecall
        csrr r24, status
        halt zero
""" + phandler + DATA
    # ---------------- v3: branch target buffer + 2-bit predictor (architecturally invisible; every
    #                  prediction must be verified: stale targets, aliasing, pattern changes, traps)
    T["btb_patterns"] = PRE + """
        li r4, 40
outer:  andi r5, r4, 1
        beqz r5, even            # alternates T/NT: the 2-bit counter keeps mispredicting one way
        addi r6, r6, 1
even:   andi r5, r4, 7
        bnez r5, skip8           # taken 7 of 8
        addi r7, r7, 1
skip8:  li r8, 3
inner:  addi r9, r9, 1           # short inner loop: exit mispredict every time
        addi r8, r8, -1
        bnez r8, inner
        beq r0, r0, fwd          # always-taken forward branch (static says not taken; BTB learns)
        addi r10, r10, 1         # never
fwd:    bne r0, r0, fwd2         # never taken
        beq r4, r4, fwd2         # taken to the very next instruction (target == pc + 4)
fwd2:   jal r1, nxt              # jal to the next instruction
nxt:    addi r4, r4, -1
        bnez r4, outer
        halt zero
"""
    T["btb_jalr_targets"] = PRE + """
        li r20, 6
loop:   jal r1, sub              # three call sites: the return jalr's BTB target is stale each time
        addi r21, r21, 1
        jal r1, sub
        addi r22, r22, 2
        jal r1, sub
        addi r23, r23, 3
        andi r24, r20, 3         # indirect jump through a table: target changes every iteration
        slli r24, r24, 2
        la r25, jtab
        add r25, r25, r24
        jalr r0, r25, 0
back:   addi r20, r20, -1
        bnez r20, loop
        halt zero
sub:    addi r26, r26, 1
        ret
jtab:   j t0
        j t1
        j t2
        j t3
t0:     addi r30, r30, 1
        j back
t1:     addi r31, r31, 1
        j back
t2:     addi r32, r32, 1
        j back
t3:     addi r33, r33, 1
        j back
"""
    T["btb_alias"] = PRE + """
        li r4, 12
a_top:  addi r5, r5, 1           # a branch and the instruction 64 bytes later share a BTB index
        bnez r5, a_b1            # (always taken)
a_b1:   nop
""" + "        nop\n" * 13 + """
        andi r6, r4, 1           # 64 bytes after the branch above: same index, different tag
        beqz r6, a_b2
        addi r7, r7, 1
a_b2:   addi r4, r4, -1
        bnez r4, a_top
        halt zero
"""
    T["btb_traps"] = PRE + setup + """
        li r20, 8
        li r21, -0x10000
tloop:  addi r20, r20, -1
        beqz r20, tdone
        andi r22, r20, 1
        bnez r22, tfault         # learned taken, then a trap right at the target
        lw r23, 0(r5)
        j tloop
tfault: lw r23, 2(r5)            # misaligned: trap at a predicted target
        jal r1, tsub             # call, return predicted from the BTB ...
        j tloop
tsub:   la r24, tfn              # ... and a cjalr at a BTB-trained pc (cjalr is never predicted)
        csetaddr r24, rc, r24
        csetbndi r24, r24, 8
        cjalr r25, r24
        ret
tfn:    addi r26, r26, 1
        cjalr r0, r25
tdone:  halt zero
""" + handler + DATA
    T["seal_hazards"] = PRE + setup + """
        li r6, 7
        csetaddr r11, rc, r6
        csetaddr r10, rc, r5
        cseal r12, r10, r11      # EX/MEM forwarding of both capability operands
        cgettype r13, r12
        lq r14, 0(r12)           # forwarded sealed base -> cap-sealed
        csc r12, 16(r5)
        clc r15, 16(r5)
        cunseal r16, r15, r11    # load-use on a sealed capability
        lq r17, 0(r16)
        sb r0, 16(r5)            # data store clears the sealed granule's tag
        clc r18, 16(r5)
        cgettag r19, r18
""" + POST + handler + DATA
    # ---------------- machine timer interrupt (mtime = retired-instruction count)
    ihandler = """
ihandler:
        csrr r50, cause
        bltz r50, isirq          # cause bit 127 = interrupt
        csrr r51, epc
        addi r51, r51, 4         # synchronous trap: skip the instruction
        csrw epc, r51
        addi r49, r49, 1
        eret
isirq:  csrr r51, epc            # interrupt: resume at epc itself
        csrr r48, status         # IE = 0, PIE = 1 inside the handler
        addi r47, r47, 1
        lq r45, 0(r5)            # observe memory written by the mainline
        li r52, -0x10000
        lq r46, 0x30(r52)        # mtime
        addi r46, r46, IDELTA
        sq r46, 0x40(r52)        # re-arm mtimecmp
        eret
"""
    isetup = """        la r4, ihandler
        csrw tvec, r4
        la r5, data
        li r52, -0x10000
        li r6, ICMP
        sq r6, 0x40(r52)
        li r7, 5                 # IE | TIE
        csrw status, r7
"""
    def irq(body, cmp, delta):
        return (PRE + f"        .equ ICMP, {cmp}\n        .equ IDELTA, {delta}\n" + isetup + body + POST
                + ihandler + DATA)
    T["irq_periodic"] = irq("""
        li r20, 40
iloop:  addi r21, r21, 3
        add r22, r22, r21
        sq r22, 0(r5)            # an interrupted store must not happen before the handler runs
        addi r20, r20, -1
        bnez r20, iloop
        csrw status, r0          # disable
        li r23, 99
""", 15, 8)                     # 4 mainline instructions per tick: the tick walks over every loop slot
    T["irq_mixed"] = irq("""
        li r20, 12
mloop:  ld r10, 0(r5)            # loads, load-use
        add r11, r10, r10
        sq r11, 32(r5)           # stores
        li r12, 0x123456789abcdef0123456789
        li r13, 77
        divu r14, r12, r13       # long divide in EX when the interrupt hits
        remu r15, r12, r13
        mul r16, r12, r13
        lw r17, 2(r5)            # misaligned -> sync trap (interrupt may land right before it)
        beq r0, r0, mfwd         # forward taken: mispredict
        addi r18, r18, 1
mfwd:   csetaddr r24, rc, r5
        csetbndi r24, r24, 64
        clc r25, 0(r5)
        csc r24, 16(r5)
        addi r20, r20, -1
        bnez r20, mloop
        csrw status, r0
""", 20, 7)
    T["irq_pcc"] = irq("""
        la r6, ireg
        csetaddr r30, rc, r6
        csetbndi r30, r30, 40
        li r20, 8
ploop:  cjalr r1, r30            # interrupt may land on the cjalr itself (EPCC must be the caller's PCC)
        addi r20, r20, -1
        bnez r20, ploop
        csrw status, r0
        j pdone
ireg:   cgetpcc r31              # inside the region: PCC restored by eret after an interrupt
        cgetlen r32, r31
        addi r33, r33, 1
        addi r34, r34, 2
        add r35, r35, r33
        nop
        nop
        nop
        nop
        cjalr r0, r1
pdone:  cgetpcc r36
        cgetlen r37, r36
""", 12, 5)
    T["irq_enable_pending"] = irq("""
        csrw status, r0          # disable before the deadline
        li r20, 30
eloop:  addi r20, r20, -1        # mtime passes mtimecmp while disabled
        bnez r20, eloop
        li r7, 1
        csrw status, r7          # IE only: still masked (TIE = 0)
        addi r21, r21, 1
        li r7, 4
        csrw status, r7          # TIE only: still masked (IE = 0)
        addi r21, r21, 1
        li r7, 7
        csrw status, r7          # both -> interrupt right after this csrw retires
        addi r22, r22, 1
        csrr r23, status
        csrw status, r0
        csrr r24, status
""", 25, 1000)
    T["irq_mmio_regs"] = irq("""
        csrw status, r0
        lq r20, 0x30(r52)        # mtime = retired count
        ld r21, 0x30(r52)
        lbu r22, 0x30(r52)
        lb r23, 0x31(r52)
        lq r24, 0x40(r52)        # mtimecmp readback
        li r6, -1
        sd r6, 0x40(r52)         # sd: mtimecmp = zero-extended 64 bits
        lq r25, 0x40(r52)
        sq r0, 0x30(r52)         # mtime is read-only
        lq r26, 0x30(r52)
        sd r0, 0x48(r52)         # not the register base address: ignored
        lq r27, 0x40(r52)
        lw r28, 0x44(r52)
        clc r29, 0x30(r52)       # clc from MMIO: value, untagged
        csrw status, r6          # only bits [2:0] are writable
        csrr r30, status
        csrw status, r0
""", 1 << 100, 1)
    T["irq_nohandler"] = PRE + """
        li r52, -0x10000
        li r6, 6
        sq r6, 0x40(r52)
        li r7, 5
        csrw status, r7
        addi r10, r10, 1
        addi r10, r10, 1
        addi r10, r10, 1         # tvec = 0: the interrupt halts the machine
        addi r10, r10, 1
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
