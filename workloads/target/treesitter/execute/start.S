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
2:  mv a0, t3
    call ape_main
.globl ape_exit
ape_exit:
    ebreak
    j ape_exit
