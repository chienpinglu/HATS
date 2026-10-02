// Real A64 encodings assembled by Clang. MMIO is the task ABI, not a new ISA.
.section .text.fork_join,"ax"
    movz x7, #0xff00
    movz x1, #0x80
    str x1, [x7]           // child inherits original x0; parent receives slot
    movz x3, #1, lsl #16
    ldr x4, [x3]           // parent HBM read overlaps child activity
    ldr x2, [x7, #8]       // suspend until child returns
    add x0, x2, x4
    brk #0
.org 0x80
    add x5, x0, #0
    cbz x0, 2f
1:  sub x0, x0, #1
    cbnz x0, 1b
2:  movz x3, #0x10, lsl #16
    ldr x2, [x3]
    add x0, x2, x5
    movz x3, #5, lsl #16
    str x0, [x3]           // local domain LPDDR
    brk #0

.section .text.recursive,"ax"
    cbz x0, 1f
    sub x0, x0, #1
    movz x7, #0xff00
    movz x1, #0
    str x1, [x7]
    ldr x0, [x7, #8]
    add x0, x0, #1
    brk #0
1:  movz x0, #1
    brk #0

.section .text.reuse,"ax"
    movz x7, #0xff00
    movz x1, #0x80
    str x1, [x7]
    ldr x0, [x7, #8]
    str x1, [x7]
    ldr x0, [x7, #8]
    brk #0
.org 0x80
    add x0, x0, #1
    brk #0

.section .text.load,"ax"
    ldr x0, [x0]
    brk #0

.section .text.store,"ax"
    str x0, [x0]
    brk #0

.section .text.loop,"ax"
1:  b 1b

.section .text.bad_instruction,"ax"
    .word 0xffffffff

.section .text.join_without_child,"ax"
    movz x7, #0xff00
    ldr x0, [x7, #8]
    brk #0

.section .text.unjoined_child,"ax"
    movz x7, #0xff00
    movz x1, #0x80
    str x1, [x7]
    brk #0
.org 0x80
1:  b 1b

.section .text.arithmetic,"ax"
    movz x0, #0xffff
    movk x0, #0xffff, lsl #16
    movk x0, #0xffff, lsl #32
    movk x0, #0xffff, lsl #48
    add x0, x0, #1         // wrap to zero
    cbnz x0, 1f
    movz xzr, #123
    add x0, xzr, xzr
    add x0, x0, #1, lsl #12
    sub x0, x0, #1
    brk #0
1:  .word 0xffffffff

.section .text.multi_memory,"ax"
    movz x7, #0xff00
    movz x1, #0x80
    str x1, [x7]
    movz x3, #1, lsl #16
    ldr x4, [x3]
    ldr x2, [x7, #8]
    add x0, x2, x4
    brk #0
.org 0x80
    movz x3, #2, lsl #16
    ldr x0, [x3]
    brk #0
