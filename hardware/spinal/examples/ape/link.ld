/* APE bare-metal test image; no allocated data sections. */
ENTRY(_start)
SECTIONS {
  . = 0;
  .text : { *(.text.start) *(.text*) }
  /DISCARD/ : { *(.comment) *(.riscv.attributes) *(.eh_frame*) }
}
