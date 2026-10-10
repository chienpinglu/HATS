package hats

import spinal.core._

/** Internal operations, not a software-visible ISA. One operation is one
  * architectural instruction in the current backend; expansion is unsupported.
  */
object ApeOp extends SpinalEnum {
  val ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND,
      CONSTANT, PC_ADD, BRANCH, JUMP_RELATIVE, JUMP_REGISTER, LOAD, STORE,
      FENCE, BREAK, ILLEGAL = newElement()
}

object ApeBranchCondition extends SpinalEnum {
  val EQ, NE, LT, GE, LTU, GEU = newElement()
}

object ApeResultExtension extends SpinalEnum {
  val FULL, SIGN_32, ZERO_32 = newElement()
}

/** Semantic fault classes. ISA exception numbers are an adapter responsibility. */
object ApeFaultKind extends SpinalEnum {
  val NONE, ILLEGAL, BREAKPOINT, INSTRUCTION_ALIGNMENT, INSTRUCTION_ACCESS,
      LOAD_ALIGNMENT, STORE_ALIGNMENT, LOAD_ACCESS, STORE_ACCESS = newElement()
}

/** One integer register namespace with one immutable zero slot. Neither encoded
  * instruction register numbers nor the launch/result ABI are assumed by rename.
  * Other register classes, flags and multi-destination groups remain unsupported.
  */
case class ApeRegisterLayout(entries: Int, zero: Int, argument: Int) {
  require(entries >= 4 && isPow2(entries))
  require(zero >= 0 && zero < entries && argument >= 0 && argument < entries && argument != zero)
  val bits = log2Up(entries)
}
