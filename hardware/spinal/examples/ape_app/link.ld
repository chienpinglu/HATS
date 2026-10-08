/* Fixed-address, static LP64 application profile; no dynamic linker or OS. */
ENTRY(_start)
PHDRS {
  code PT_LOAD FLAGS(5);
  constant PT_LOAD FLAGS(4);
  data PT_LOAD FLAGS(6);
}
SECTIONS {
  . = 0;
  .text : { *(.text.start) *(.text*) } :code
  ASSERT(. <= 0x1000, "application exceeds instruction storage")
  . = 0x10000;
  .rodata : { *(.rodata*) *(.srodata*) } :constant
  . = ALIGN(16);
  .data : { *(.data*) *(.sdata*) } :data
  . = ALIGN(16);
  __bss_start = .;
  .bss (NOLOAD) : { *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(16); } :data
  __bss_end = .;
  ASSERT(. <= 0x14000, "static data overlaps reserved application regions")
  __stack_top = 0x20000;
  /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.eh_frame*) }
}
