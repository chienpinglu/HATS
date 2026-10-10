package hats

import spinal.core._

/** Typed single-instruction boundary. No raw funct3/funct7 crosses into the
  * scheduler or memory execution path. The current register/fault policy is RV64.
  */
case class ApeDecodedOp() extends Bundle {
  val op = ApeOp()
  val valid, destination, use1, use2, immediate, narrow32 = Bool()
  val imm = UInt(64 bits)
  val rd, rs1, rs2 = UInt(5 bits)
  val branch = ApeBranchCondition()
  val memorySize = UInt(2 bits)
  val loadSigned = Bool()
}

/** Public RV64I encodings only. C/M/A/F/D, CSR and privileged instructions trap. */
class ApeDecode(inst: Bits) extends Area {
  val decoded = ApeDecodedOp()
  val op = decoded.op
  val valid = decoded.valid
  val writes = Bool()
  val use1 = decoded.use1; val use2 = decoded.use2
  val immediate = decoded.immediate; val word = decoded.narrow32
  val imm = decoded.imm
  val rd = decoded.rd; rd := inst(11 downto 7).asUInt
  decoded.rs1 := inst(19 downto 15).asUInt
  decoded.rs2 := inst(24 downto 20).asUInt
  val f3 = inst(14 downto 12).asUInt
  val f7 = inst(31 downto 25).asUInt
  val opcode = inst(6 downto 0).asUInt
  op := ApeOp.ILLEGAL
  valid := False
  writes := False
  use1 := False
  use2 := False
  immediate := False
  word := False
  imm := inst(31 downto 20).asSInt.resize(64).asUInt
  switch(opcode) {
    is(0x37, 0x17) {
      valid := True; writes := True
      imm := (inst(31 downto 12) ## B(0, 12 bits)).asSInt.resize(64).asUInt
      op := ApeOp.CONSTANT
      when(opcode === 0x17) { op := ApeOp.PC_ADD }
    }
    is(0x13, 0x1b, 0x33, 0x3b) {
      writes := True; use1 := True
      immediate := !opcode(5)
      use2 := opcode(5)
      word := opcode(3)
      switch(f3) {
        is(0) {
          when(!opcode(5) || f7 === 0) { valid := True; op := ApeOp.ADD }
          when(opcode(5) && f7 === 0x20) { valid := True; op := ApeOp.SUB }
        }
        is(1) {
          op := ApeOp.SLL
          when(opcode(5)) { valid := f7 === 0 }
            .otherwise { valid := inst(31 downto 26) === 0 && (!opcode(3) || !inst(25)) }
        }
        is(5) {
          op := ApeOp.SRL
          when(inst(30)) { op := ApeOp.SRA }
          when(opcode(5)) { valid := f7 === 0 || f7 === 0x20 }
            .otherwise {
              valid := (inst(31 downto 26) === 0 || inst(31 downto 26) === 0x10) &&
                (!opcode(3) || !inst(25))
            }
        }
        is(2, 3, 4, 6, 7) {
          valid := !opcode(3) && (!opcode(5) || f7 === 0)
          switch(f3) {
            is(2) { op := ApeOp.SLT }
            is(3) { op := ApeOp.SLTU }
            is(4) { op := ApeOp.XOR }
            is(6) { op := ApeOp.OR }
            is(7) { op := ApeOp.AND }
          }
        }
      }
    }
    is(0x63) {
      op := ApeOp.BRANCH; use1 := True; use2 := True
      valid := f3 === 0 || f3 === 1 || f3 >= 4
      imm := (inst(31) ## inst(7) ## inst(30 downto 25) ## inst(11 downto 8) ## False)
        .asSInt.resize(64).asUInt
    }
    is(0x6f) {
      op := ApeOp.JUMP_RELATIVE; valid := True; writes := True
      imm := (inst(31) ## inst(19 downto 12) ## inst(20) ## inst(30 downto 21) ## False)
        .asSInt.resize(64).asUInt
    }
    is(0x67) { op := ApeOp.JUMP_REGISTER; valid := f3 === 0; writes := True; use1 := True }
    is(0x03) { op := ApeOp.LOAD; valid := f3 =/= 7; writes := True; use1 := True }
    is(0x23) {
      op := ApeOp.STORE; valid := f3 <= 3; use1 := True; use2 := True
      imm := (inst(31 downto 25) ## inst(11 downto 7)).asSInt.resize(64).asUInt
    }
    is(0x0f) { op := ApeOp.FENCE; valid := f3 === 0 }
    is(0x73) { when(inst === B(0x00100073L, 32 bits)) { op := ApeOp.BREAK; valid := True } }
  }
  // Unsupported encodings never allocate an architectural destination.
  decoded.destination := writes && valid && rd =/= 0
  decoded.memorySize := f3(1 downto 0)
  decoded.loadSigned := !f3(2)
  decoded.branch := ApeBranchCondition.EQ
  switch(f3) {
    is(1) { decoded.branch := ApeBranchCondition.NE }
    is(4) { decoded.branch := ApeBranchCondition.LT }
    is(5) { decoded.branch := ApeBranchCondition.GE }
    is(6) { decoded.branch := ApeBranchCondition.LTU }
    is(7) { decoded.branch := ApeBranchCondition.GEU }
  }
}
