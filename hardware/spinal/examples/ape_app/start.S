.option norvc
.option norelax
.section .text.start,"ax",@progbits
.globl _start
_start:
    la sp, __stack_top
    mv t3, a0
    la t0, __bss_start
    la t1, __bss_end
1:  bgeu t0, t1, 2f
    sd zero, 0(t0)
    addi t0, t0, 8
    j 1b
2:  addi sp, sp, -32
    sd t3, 16(sp)
    /* Call nine-argument C function: argument nine lives at 0(sp). */
    li a0, 1
    li a1, 2
    li a2, 3
    li a3, 4
    li a4, 5
    li a5, 6
    li a6, 7
    li a7, 8
    li t0, 9
    sd t0, 0(sp)
    call ape_abi_sum
    li t0, 45
    bne a0, t0, abi_fail
    /* Sentinels test preservation across compiled nested calls. */
    li s0, 100
    li s1, 101
    li s2, 102
    li s3, 103
    li s4, 104
    li s5, 105
    li s6, 106
    li s7, 107
    li s8, 108
    li s9, 109
    li s10, 110
    li s11, 111
    ld a0, 16(sp)
    call ape_main
    li t0, 100
    bne s0, t0, abi_fail
    addi t0, t0, 1
    bne s1, t0, abi_fail
    addi t0, t0, 1
    bne s2, t0, abi_fail
    addi t0, t0, 1
    bne s3, t0, abi_fail
    addi t0, t0, 1
    bne s4, t0, abi_fail
    addi t0, t0, 1
    bne s5, t0, abi_fail
    addi t0, t0, 1
    bne s6, t0, abi_fail
    addi t0, t0, 1
    bne s7, t0, abi_fail
    addi t0, t0, 1
    bne s8, t0, abi_fail
    addi t0, t0, 1
    bne s9, t0, abi_fail
    addi t0, t0, 1
    bne s10, t0, abi_fail
    addi t0, t0, 1
    bne s11, t0, abi_fail
    addi sp, sp, 32
    la t0, __stack_top
    bne sp, t0, abi_fail
.globl ape_exit
ape_exit:
    ebreak
abi_fail:
    li a0, 225
    ebreak
