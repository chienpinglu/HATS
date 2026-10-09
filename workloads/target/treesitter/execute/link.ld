ENTRY(_start)
PHDRS { code PT_LOAD FLAGS(5); constant PT_LOAD FLAGS(4); data PT_LOAD FLAGS(6); }
SECTIONS {
  . = 0;
  .text : { *(.text.start) *(.text*) } :code
  ASSERT(. <= 0x40000, "text exceeds 256 KiB test profile")
  . = 0x100000;
  .rodata : { *(.rodata*) *(.srodata*) } :constant
  . = ALIGN(16);
  .data : { *(.data*) *(.sdata*) } :data
  . = ALIGN(16);
  __bss_start = .;
  .bss (NOLOAD) : { *(.bss*) *(.sbss*) *(COMMON) . = ALIGN(16); } :data
  __bss_end = .;
  ASSERT(. <= 0x180000, "static state overlaps input")
  __stack_top = 0x1000000;
  /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.eh_frame*) }
}
