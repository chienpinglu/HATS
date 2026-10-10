/* APE directed programs for the public RV64I ISA. Each image links at PC zero. */
.option norvc
.option norelax
.section .text.start,"ax",@progbits
.globl _start
_start:
#if APE_TEST == 0
  li t0, -17
  li t1, 5
  add t2, t0, t1
  sub t3, t1, t0
  and t4, t0, t3
  or t5, t4, t1
  xor t6, t5, t3
  slt a1, t0, t1
  sltu a2, t0, t1
  slli a3, t1, 35
  srli a4, a3, 32
  srai a5, t0, 3
  sll a6, t1, t1
  srl a7, a3, t1
  sra a0, t0, t1
  xori a0, a0, 31
  ori a0, a0, 2
  andi a0, a0, 255
  slti t0, a0, 42
  sltiu t1, a0, -1
  add a0, a0, t0
  add a0, a0, t1
#elif APE_TEST == 1
  li s0, 0x10000
  ld t0, 0(s0)
  add t1, t0, t0
  addi t2, zero, 17
  addi t0, zero, 9
  add t3, t1, t2
  add a0, t3, t0
#elif APE_TEST == 2
  li s0, 0x10000
  li s1, 0x18000
  ld t0, 0(s0)
  bne t0, zero, 1f
  addi a0, zero, 999
  sd a0, 0(s1) /* simulated task doorbell: must never become externally visible */
  ld a1, 8(s1) /* no wrong-path MMIO read either */
  .word 0xffffffff
1:
  addi a0, t0, 35
#elif APE_TEST == 3
  li t0, -1
  li t1, 1
  blt t0, t1, 1f
  .word 0xffffffff
1:
  bgeu t0, t1, 2f
  .word 0xffffffff
2:
  bge t1, t0, 3f
  .word 0xffffffff
3:
  bltu t1, t0, 4f
  .word 0xffffffff
4:
  beq t0, t1, 5f
  addi a0, zero, 42
  jal zero, 6f
5:
  .word 0xffffffff
6:
#elif APE_TEST == 4
  jal ra, 1f
  addi a0, a0, 2
  jal zero, 2f
1:
  addi a0, zero, 40
  jalr zero, 0(ra)
2:
#elif APE_TEST == 5
  lui t0, 0x80000
  addiw t1, t0, -1
  addw t2, t1, t1
  subw t3, zero, t1
  slliw t4, t1, 1
  srliw t5, t0, 31
  sraiw t6, t0, 31
  sllw a1, t1, t5
  srlw a2, t0, t5
  sraw a3, t0, t5
  add a0, a1, a2
  add a0, a0, a3
#elif APE_TEST == 6
  li s0, 0x10000
  li t0, -129
  sd t0, 64(s0)
  lb a1, 64(s0)
  lbu a2, 65(s0)
  lh a3, 64(s0)
  lhu a4, 64(s0)
  lw a5, 64(s0)
  lwu a6, 64(s0)
  ld a7, 64(s0)
  sb a1, 80(s0)
  sh a3, 82(s0)
  sw a5, 84(s0)
  fence rw, rw
  ld a0, 80(s0)
#elif APE_TEST == 7
  li a0, 42
  .word 0xffffffff
  li s0, 0x18000
  sd a0, 0(s0)
#elif APE_TEST == 8
  li s0, 0x10000
  li a0, 42
  ld t0, 1(s0)
  sd a0, 8(s0)
#elif APE_TEST == 9
  li s0, 0x10000
  li a0, 42
  sd a0, 1(s0)
#elif APE_TEST == 10
  li a0, 42
  ld t0, 0(zero)
#elif APE_TEST == 11
  li a0, 42
  sd a0, 0(zero)
#elif APE_TEST == 12
  li s0, 0x10000
  li a0, 42
  sd a0, 0(s0)
#elif APE_TEST == 13
  li s0, 0x10000
  li a0, 42
  ld t0, 0(s0)
  addi a0, zero, 999
  sd a0, 8(s0)
#elif APE_TEST == 14
  li a0, 42
  jal ra, .+2
#elif APE_TEST == 15
  li t0, 0
  li t1, 100
  li a0, 0
1:
  add a0, a0, t0
  addi t0, t0, 1
  blt t0, t1, 1b
#elif APE_TEST == 16
  li s0, 0x10000
  ld t0, 0(s0)
  beq t0, t0, 1f
  jal ra, 2f
  addi t0, zero, 999
2:
  .word 0xffffffff
1:
  addi a0, t0, 35
#elif APE_TEST == 17
  li a0, 42
  .word 0x0200101b /* reserved SLLIW shift amount */
#elif APE_TEST == 18
  li sp, 0x12000
  li a0, 0x10000
  li a1, 8
  call ape_kernel
#elif APE_TEST == 19
  li s0, 0x10000
  ld zero, 0(s0)
  addi zero, zero, 123
  add a0, zero, zero
#elif APE_TEST == 20
  li a0, 42
  fence.i
#elif APE_TEST == 21
  li s0, 0x10000
  li a0, 42
  sd a0, 0(s0)
  addi a0, zero, 999
#elif APE_TEST == 22
  li a0, 42
  li t0, 4096
  jalr ra, 0(t0)
#elif APE_TEST == 23
  li s0, 0x10000
  ld t0, 0(s0)
  beq t0, zero, 1f
  addi a0, t0, 35
  jal zero, 2f
1:
  .word 0xffffffff
2:
#elif APE_TEST == 24
  li s0, 0x18000
  li a0, 42
  sd a0, 0(s0)
#elif APE_TEST == 25
  li a0, 42
  ld zero, 0(zero) /* rd=x0 must not suppress a load exception */
#elif APE_TEST == 26
  auipc t0, 0
  addi t0, t0, 17
  jalr ra, 0(t0) /* bit zero must be cleared, reaching PC 16 */
  .word 0xffffffff
  li a0, 42
#elif APE_TEST == 27
  li t0, 1
  beq t0, zero, .+2 /* non-taken branch must not fault on its unused target */
  li a0, 42
#elif APE_TEST == 28
  li s0, 0x20000
  li a0, 42
  ld t0, 0(s0) /* exclusive upper limit */
#elif APE_TEST == 29
  jal ra, 1f
  li s0, 0x18000
  sd a0, 0(s0)
  .word 0xffffffff
1:
  addi a0, ra, 38 /* link must remain PC+4 when target was predicted */
#elif APE_TEST == 30
  li s0, 0x10000
  li s1, 0x18000
  li t1, 3
  li a0, 0
1:
  ld t0, 0(s0) /* hold retirement while younger branch/body execute */
  addi t1, t1, -1
  bne t1, zero, 2f
  li a0, 42
  ebreak
2:
  addi a0, a0, 1
  sd a0, 0(s1) /* exactly two live writes; no third write on predicted exit */
  /* Occupy the largest tested ROB before fetching the next iteration. Early
     recovery can otherwise fetch all three branches before retirement-only
     predictor training; this fixture must actually predict the final exit taken. */
  .rept 16
  nop
  .endr
  jal zero, 1b
#elif APE_TEST == 31
  li t0, 4
1:
  beq zero, zero, .+4 /* taken outcome even though target equals fall-through */
  addi t0, t0, -1
  bne t0, zero, 1b
  li a0, 42
#else
#error Unknown APE_TEST
#endif
  ebreak
