package hats

import spinal.core._
import spinal.lib._

/** A completion identity is a lease, not just a reused ROB index. */
case class ApeExecutionIdentity(c: ApeConfig) extends Bundle {
  val slot = UInt(c.tagBits bits)
  val generation = UInt(c.generationBits bits)
  val destination = UInt(c.physicalTagBits bits)
}

case class ApeExecutionRequest(c: ApeConfig) extends Bundle {
  val identity = ApeExecutionIdentity(c)
  val op = ApeOp()
  val branch = ApeBranchCondition()
  val a, b, immediate, pc, sequentialNext, base, limit = UInt(64 bits)
  val indirectTargetMask, alignmentMask = UInt(64 bits)
  val useImmediate, narrow32, writable, fault = Bool()
  val resultExtension = ApeResultExtension()
  val faultKind = ApeFaultKind()
  val memorySize = UInt(2 bits)
}

case class ApeExecutionResult(c: ApeConfig) extends Bundle {
  val identity = ApeExecutionIdentity(c)
  val value, next, address = UInt(64 bits)
  val taken, memory, control, fault = Bool()
  val faultKind = ApeFaultKind()
}

/** Operand register -> integer/branch/AGU logic -> result register.
  * Extra registered result stages are a stress/configuration knob, not extra
  * arithmetic timing cuts. Backpressure holds every payload and ownership lease.
  * Selective recovery leaves tokens in flight for the ROB to reject by identity;
  * global recovery synchronously clears the entire local execution pipeline.
  */
class ApeExecute(c: ApeConfig) extends Component {
  val io = new Bundle {
    val clear = in Bool()
    val request = slave Stream(ApeExecutionRequest(c))
    val result = master Stream(ApeExecutionResult(c))
    val pending = out Vec(Flow(ApeExecutionIdentity(c)), c.executionStages)
  }
  val operands = Reg(ApeExecutionRequest(c))
  val operandValid = RegInit(False)
  val payload = Vec.fill(c.executionStages - 1)(Reg(ApeExecutionResult(c)))
  val valid = Vec.fill(c.executionStages - 1)(RegInit(False))
  val advance = Vec(Bool(), c.executionStages - 1)
  for (i <- (0 until c.executionStages - 1).reverse) {
    advance(i) := !valid(i) || (if (i == c.executionStages - 2) io.result.ready else advance(i + 1))
  }
  io.request.ready := (!operandValid || advance(0)) && !io.clear
  io.result.valid := valid.last && !io.clear
  io.result.payload := payload.last
  io.pending(0).valid := operandValid
  io.pending(0).payload := operands.identity
  for (i <- 0 until c.executionStages - 1) {
    io.pending(i + 1).valid := valid(i)
    io.pending(i + 1).payload := payload(i).identity
  }

  val x = operands
  val a = x.a
  val b = Mux(x.useImmediate, x.immediate, x.b)
  val shift = Mux(x.narrow32, b(4 downto 0).resize(6), b(5 downto 0))
  val rightValue = Mux(x.narrow32, a(31 downto 0).resize(64), a)
  val signedValue = Mux(x.narrow32, a(31 downto 0).asSInt.resize(64), a.asSInt)
  val rawResult = UInt(64 bits)
  rawResult := 0
  switch(x.op) {
    is(ApeOp.ADD) { rawResult := a + b }
    is(ApeOp.SUB) { rawResult := a - b }
    is(ApeOp.SLL) { rawResult := (a |<< shift).resize(64) }
    is(ApeOp.SLT) { rawResult := (a.asSInt < b.asSInt).asUInt.resize(64) }
    is(ApeOp.SLTU) { rawResult := (a < b).asUInt.resize(64) }
    is(ApeOp.XOR) { rawResult := a ^ b }
    is(ApeOp.SRL) { rawResult := rightValue |>> shift }
    is(ApeOp.SRA) { rawResult := (signedValue >> shift).asUInt }
    is(ApeOp.OR) { rawResult := a | b }
    is(ApeOp.AND) { rawResult := a & b }
    is(ApeOp.CONSTANT) { rawResult := x.immediate }
    is(ApeOp.PC_ADD) { rawResult := x.pc + x.immediate }
    is(ApeOp.JUMP_RELATIVE, ApeOp.JUMP_REGISTER) { rawResult := x.sequentialNext }
  }
  val calculated = ApeExecutionResult(c)
  calculated.identity := x.identity
  calculated.value := rawResult
  switch(x.resultExtension) {
    is(ApeResultExtension.SIGN_32) { calculated.value := rawResult(31 downto 0).asSInt.resize(64).asUInt }
    is(ApeResultExtension.ZERO_32) { calculated.value := rawResult(31 downto 0).resize(64) }
  }
  calculated.taken := False
  switch(x.branch) {
    is(ApeBranchCondition.EQ) { calculated.taken := a === x.b }
    is(ApeBranchCondition.NE) { calculated.taken := a =/= x.b }
    is(ApeBranchCondition.LT) { calculated.taken := a.asSInt < x.b.asSInt }
    is(ApeBranchCondition.GE) { calculated.taken := a.asSInt >= x.b.asSInt }
    is(ApeBranchCondition.LTU) { calculated.taken := a < x.b }
    is(ApeBranchCondition.GEU) { calculated.taken := a >= x.b }
  }
  calculated.next := x.sequentialNext
  when(x.op === ApeOp.JUMP_RELATIVE || (x.op === ApeOp.BRANCH && calculated.taken)) {
    calculated.next := x.pc + x.immediate
  }
  when(x.op === ApeOp.JUMP_REGISTER) { calculated.next := (a + x.immediate) & x.indirectTargetMask }
  calculated.control := x.op === ApeOp.BRANCH || x.op === ApeOp.JUMP_RELATIVE || x.op === ApeOp.JUMP_REGISTER
  calculated.memory := x.op === ApeOp.LOAD || x.op === ApeOp.STORE
  calculated.address := a + x.immediate
  val bytes = (U(1, 65 bits) |<< x.memorySize).resize(65)
  val misaligned = (calculated.address.resize(65) & (bytes - 1)) =/= 0
  val illegalAccess = calculated.address < x.base || calculated.address.resize(65) + bytes > x.limit.resize(65) ||
    (x.op === ApeOp.STORE && !x.writable)
  val targetMisaligned = (calculated.next & x.alignmentMask) =/= 0
  calculated.faultKind := x.faultKind
  when(!x.fault) {
    calculated.faultKind := ApeFaultKind.NONE
    when(x.op === ApeOp.ILLEGAL) { calculated.faultKind := ApeFaultKind.ILLEGAL }
    when(x.op === ApeOp.BREAK) { calculated.faultKind := ApeFaultKind.BREAKPOINT }
    when(targetMisaligned) { calculated.faultKind := ApeFaultKind.INSTRUCTION_ALIGNMENT }
    when(calculated.memory && (misaligned || illegalAccess)) {
      calculated.faultKind := Mux(x.op === ApeOp.LOAD, ApeFaultKind.LOAD_ACCESS, ApeFaultKind.STORE_ACCESS)
      when(misaligned) {
        calculated.faultKind := Mux(x.op === ApeOp.LOAD, ApeFaultKind.LOAD_ALIGNMENT, ApeFaultKind.STORE_ALIGNMENT)
      }
    }
  }
  calculated.fault := calculated.faultKind =/= ApeFaultKind.NONE
  when(io.request.fire && io.request.fault) {
    assert(io.request.faultKind =/= ApeFaultKind.NONE, "fault lacks a semantic classification")
  }
  when(io.request.ready) {
    operandValid := io.request.valid
    when(io.request.valid) { operands := io.request.payload }
  }
  when(advance(0)) {
    valid(0) := operandValid
    when(operandValid) { payload(0) := calculated }
  }
  for (i <- 1 until c.executionStages - 1) {
    when(advance(i)) {
      valid(i) := valid(i - 1)
      when(valid(i - 1)) { payload(i) := payload(i - 1) }
    }
  }
  when(io.clear) {
    operandValid := False
    valid.foreach(_ := False)
  }
}
