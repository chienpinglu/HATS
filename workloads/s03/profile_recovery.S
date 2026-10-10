/* Original ROB8 recovery witnesses, using public RV64I encodings.
   Kept separate from the ROB16/P36 witnesses: three dependent operations
   delay control resolution without filling the eight-entry ROB with NOPs.
   The unchanged RTL harness requires actual early target issue, nested
   resolved-branch squash, concurrent older retirement, and checkpoint stalls. */
.option norvc
.option norelax
.section .text.start,"ax",@progbits
.globl _start
_start:
#if APE_RECOVERY_TEST == 0
  li s0, 0x10000
  ld t0, 0(s0)
  li t1, 0
  addi t1, t1, 1
  addi t1, t1, 1
  beq t1, t1, target
  li a0, 999
  sd a0, 0(s0)
  ld a1, 8(s0)
  .word 0xffffffff
target:
  li a1, 55
  addi a0, t0, 35
#elif APE_RECOVERY_TEST == 1
  li s0, 0x10000
  ld t0, 0(s0)
  nop
  nop
  nop
  beq t0, t0, outer
  nop
  beq zero, zero, inner
  li a0, 999
  .word 0xffffffff
inner:
  li a0, 666
  addi a1, a0, 1
  beq zero, zero, inner_done
  sd a0, 0(s0)
inner_done:
  addi a0, a0, 1
  ebreak
outer:
  addi a0, t0, 35
#elif APE_RECOVERY_TEST == 2
  li s0, 0x10000
  ld t0, 0(s0)
  .rept 4
  nop
  .endr
  lla t1, target
  jalr ra, 0(t1) /* PC32, committed link is 36. */
  sd zero, 0(s0)
  .word 0xffffffff
target:
  addi a0, ra, 6
#elif APE_RECOVERY_TEST == 3
  li a0, 42
  li s0, 0x10000
  ld t0, 0(s0)
  li t1, 0
  addi t1, t1, 1
  addi t1, t1, 1
  beq t1, t1, target
  sd zero, 0(s0)
target:
  li a0, 777
#elif APE_RECOVERY_TEST == 4
  li a0, 42
  li s0, 0x10000
  ld t0, 0(s0)
  .rept 3
  nop
  .endr
  lla t1, target
  jalr a0, 2(t1)
  sd zero, 0(s0)
target:
  li a0, 777
#elif APE_RECOVERY_TEST == 5
  li s0, 0x10000
  ld t0, 0(s0)
  .rept 6
  bne t0, t0, wrong
  .endr
  addi a0, t0, 35
  ebreak
wrong:
  .word 0xffffffff
#endif
  ebreak
