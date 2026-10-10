package hats

import spinal.core._

/** The only implemented architectural personality: the documented RV64I subset.
  * Common execution carries explicit semantics; this adapter owns RV presentation.
  */
object ApeRv64Profile {
  val registers = ApeRegisterLayout(entries = 32, zero = 0, argument = 10)
  val instructionBytes = 4
  val operationsPerInstruction = 1
  val instructionShift = log2Up(instructionBytes)
  val alignmentMask = BigInt(instructionBytes - 1)
  val indirectTargetMask = (BigInt(1) << 64) - 2 // JALR clears bit zero.

  def encodeFault(kind: SpinalEnumCraft[ApeFaultKind.type]): UInt = {
    val encoded = UInt(4 bits)
    encoded := 0
    switch(kind) {
      is(ApeFaultKind.INSTRUCTION_ALIGNMENT) { encoded := 0 }
      is(ApeFaultKind.INSTRUCTION_ACCESS) { encoded := 1 }
      is(ApeFaultKind.ILLEGAL) { encoded := 2 }
      is(ApeFaultKind.BREAKPOINT) { encoded := 3 }
      is(ApeFaultKind.LOAD_ALIGNMENT) { encoded := 4 }
      is(ApeFaultKind.LOAD_ACCESS) { encoded := 5 }
      is(ApeFaultKind.STORE_ALIGNMENT) { encoded := 6 }
      is(ApeFaultKind.STORE_ACCESS) { encoded := 7 }
    }
    encoded
  }
}

/** Fetch/decode/lowering boundary for one supported instruction per ROB owner. */
class ApeRv64Frontend(inst: Bits, pc: UInt, programWords: Int) extends Area {
  val decoded = new ApeDecode(inst).decoded
  val sequentialNext = pc + ApeRv64Profile.instructionBytes
  val misaligned = (pc & U(ApeRv64Profile.alignmentMask, 64 bits)) =/= 0
  val fetchFault = misaligned || pc >= BigInt(programWords) * ApeRv64Profile.instructionBytes
  val fetchFaultKind = Mux(misaligned, ApeFaultKind.INSTRUCTION_ALIGNMENT, ApeFaultKind.INSTRUCTION_ACCESS)
  val resultExtension = ApeResultExtension()
  resultExtension := ApeResultExtension.FULL
  when(decoded.narrow32) { resultExtension := ApeResultExtension.SIGN_32 }
}
