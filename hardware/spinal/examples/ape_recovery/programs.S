/* Original directed checkpoint witnesses, using public RV64I encodings. */
.option norvc
.option norelax
.section .text.start,"ax",@progbits
.globl _start
_start:
#if APE_RECOVERY_TEST == 0
  li s0, 0x10000
  ld t0, 0(s0)
  /* Delay control resolution until the older load has reached the bus, without
     consuming the P36 configuration's four speculative physical registers. */
  .rept 8
  nop
  .endr
  beq zero, zero, target
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
  /* Retain older completed instructions across single-CDB arbitration, so an
     older retirement overlaps pipelined resolve with either one or two lanes. */
  nop
  nop
  nop
  beq t0, t0, outer
  .rept 3
  nop
  .endr
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
  ld t0, 0(s0) /* Harness returns an error, after younger recovery. */
  .rept 8
  nop
  .endr
  beq zero, zero, target
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
  jalr a0, 2(t1) /* Misaligned target: must not write the link to a0. */
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
