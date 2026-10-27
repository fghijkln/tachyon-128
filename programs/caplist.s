# caplist.s - tagged memory demo: a singly linked list whose "next" pointers are
# capabilities spilled to memory with csc and reloaded with clc.  Each node is its own
# 32-byte capability: [0] next (capability granule), [16] 128-bit payload.
# Then: an integer overwrite of a next-pointer clears the granule's tag (the list is cut,
# the forged pointer is unusable as a capability), and bounds/permissions still hold.
# v4: a local (non-GLOBAL) stack capability can be spilled to the stack but not into the heap.
        .org 0
_start: li   sp, 0x40000
        j    main
        .include "lib.s"

        .equ NNODES, 6
        .equ VSTEP,  0x1000000000000000000000001     # payload of node i = (i+1) * VSTEP

handler:
        csrw scratch, ra
        la   a0, t_msg
        call puts
        csrr a0, cause
        call putu
        call putnl
        csrr t0, epc
        addi t0, t0, 4
        csrw epc, t0
        addi s9, s9, 1
        csrr ra, scratch
        eret

# walk(a0 = slot capability holding the head) -> a0 = node count, a1 = payload sum
walk:   clc  t0, 0(a0)              # head capability
        li   a0, 0
        li   a1, 0
walk_l: cgettag t1, t0              # end of list = untagged link
        beqz t1, walk_d
        lq   t2, 16(t0)             # payload through the node's own capability
        add  a1, a1, t2
        addi a0, a0, 1
        clc  t0, 0(t0)              # next link (tag + bounds come back from shadow memory)
        j    walk_l
walk_d: ret

main:   la   t0, handler
        csrw tvec, t0
        li   s9, 0
        # heap capability: [heap, heap+512), LOAD|STORE|LOAD_CAP|STORE_CAP|GLOBAL|LOAD_MUTABLE
        la   t1, heap
        csetaddr s0, rc, t1
        csetbndi s0, s0, 512
        li   t2, 0x19B
        candperm s0, s0, t2
        # root slot (one granule) that holds the list head
        la   t1, slot
        csetaddr s1, rc, t1
        csetbndi s1, s1, 16
        # build the list: push nodes 0..5 (head ends up at node 5)
        li   s2, 0                  # head = null (untagged)
        li   s3, 0                  # i
        li   s4, VSTEP
        li   s5, 0                  # payload
build:  slli t3, s3, 5              # node i at heap + 32*i
        cgetbase t5, s0
        add  t5, t5, t3
        csetaddr t4, s0, t5
        csetbndi t4, t4, 32         # node capability: exactly 32 bytes
        csc  s2, 0(t4)              # node.next = old head (tagged, or null)
        add  s5, s5, s4
        sq   s5, 16(t4)             # node.payload
        cmove s2, t4                # head = node
        addi s3, s3, 1
        li   t6, NNODES
        bne  s3, t6, build
        csc  s2, 0(s1)              # publish the head capability

        mv   a0, s1
        call walk
        mv   s6, a0
        mv   s7, a1
        la   a0, m_n
        call puts
        mv   a0, s6
        call putu
        call putnl
        la   a0, m_sum
        call puts
        mv   a0, s7
        call puthex
        clc  t0, 0(s1)
        la   a0, m_len
        call puts
        cgetlen a0, t0
        call putu
        call putnl

        # forge attempt: overwrite node 3's next field (which points to node 2) with
        # node 2's address as a plain integer.  The data store clears the granule tag.
        cgetbase t5, s0
        addi t6, t5, 64             # address of node 2
        sq   t6, 96(s0)             # node 3 lives at heap+96
        mv   a0, s1
        call walk
        mv   s6, a0
        mv   s7, a1
        la   a0, m_f
        call puts
        mv   a0, s6
        call putu
        call putnl
        la   a0, m_sum
        call puts
        mv   a0, s7
        call puthex
        # the reloaded "pointer" is just an integer: cannot be turned back into a capability
        lq   t0, 96(s0)
        csetbndi t1, t0, 32         # fault 1: capability-tag
        # a node capability cannot reach its neighbour
        clc  t0, 0(s1)
        lq   t2, 32(t0)             # fault 2: capability-bounds
        # a load-only view of the list can be walked but not used to store capabilities
        li   t3, 0x09               # LOAD | LOAD_CAP
        candperm t4, s1, t3
        mv   a0, t4
        call walk
        mv   s8, a0
        csc  s2, 0(t4)              # fault 3: capability-permission (no STORE)
        # v4: a local (non-GLOBAL) capability, e.g. one for the stack, can only be stored through an
        # authority with STORE_LOCAL: the stack capability has it, the heap node capabilities do not
        addi t1, sp, -64
        csetaddr t5, rc, t1
        csetbndi t5, t5, 64
        li   t3, 0x51B              # LOAD|STORE|LOAD_CAP|STORE_CAP|LOAD_MUTABLE|STORE_LOCAL, not GLOBAL
        candperm t5, t5, t3
        csc  t5, 0(t5)              # spill into its own stack region: allowed
        clc  t6, 0(t5)
        clc  t0, 0(s1)              # head node capability (no STORE_LOCAL)
        csc  t5, 0(t0)              # fault 4: capability-permission (local capability into the heap)
        la   a0, m_loc
        call puts
        cgettag a0, t6
        call putu
        call putnl
        la   a0, m_ro
        call puts
        mv   a0, s8
        call putu
        call putnl
        la   a0, m_fc
        call puts
        mv   a0, s9
        call putu
        call putnl
        li   a0, 0
        call exit

m_n:    .asciz "nodes walked        = "
m_sum:  .asciz "payload sum         = "
m_len:  .asciz "head node cap length = "
m_f:    .asciz "nodes after forge   = "
m_ro:   .asciz "nodes via read-only = "
t_msg:  .asciz "  !! trap cause="
m_loc:  .asciz "local cap reloaded from stack, tag = "
m_fc:   .asciz "faults caught = "
        .align 16
slot:   .space 16
heap:   .space 512
