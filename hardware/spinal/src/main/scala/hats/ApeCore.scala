package hats

import spinal.core._
import spinal.lib._

/** HATS Application Processing Engine: RV64I-subset, not yet a privileged CPU.
  * Single dispatch/issue/retire; ROB-tag renaming; oldest-ready out-of-order issue.
  * Configurable branch prediction, recover at retirement. Memory is head-only.
  */
case class ApeConfig(robEntries: Int = 8, programWords: Int = 1024,
                     prediction: Boolean = true, predictorEntries: Int = 16) {
  require(robEntries >= 4 && isPow2(robEntries))
  require(programWords >= 16 && isPow2(programWords))
  require(predictorEntries >= 2 && isPow2(predictorEntries))
  val tagBits = log2Up(robEntries)
  val codeBits = log2Up(programWords)
}

object ApeOp extends SpinalEnum {
  val ADD, SUB, SLL, SLT, SLTU, XOR, SRL, SRA, OR, AND,
      LUI, AUIPC, BRANCH, JAL, JALR, LOAD, STORE, FENCE, BREAK, ILLEGAL = newElement()
}

/** Public RV64I encodings only. C/M/A/F/D, CSR and privileged instructions trap. */
class ApeDecode(inst: Bits) extends Area {
  val op = ApeOp()
  val valid, writes, use1, use2, immediate, word = Bool()
  val imm = UInt(64 bits)
  val rd = inst(11 downto 7).asUInt
  val rs1 = inst(19 downto 15).asUInt
  val rs2 = inst(24 downto 20).asUInt
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
      op := ApeOp.LUI
      when(opcode === 0x17) { op := ApeOp.AUIPC }
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
      op := ApeOp.JAL; valid := True; writes := True
      imm := (inst(31) ## inst(19 downto 12) ## inst(20) ## inst(30 downto 21) ## False)
        .asSInt.resize(64).asUInt
    }
    is(0x67) { op := ApeOp.JALR; valid := f3 === 0; writes := True; use1 := True }
    is(0x03) { op := ApeOp.LOAD; valid := f3 =/= 7; writes := True; use1 := True }
    is(0x23) {
      op := ApeOp.STORE; valid := f3 <= 3; use1 := True; use2 := True
      imm := (inst(31 downto 25) ## inst(11 downto 7)).asSInt.resize(64).asUInt
    }
    is(0x0f) { op := ApeOp.FENCE; valid := f3 === 0 }
    is(0x73) { when(inst === B(0x00100073L, 32 bits)) { op := ApeOp.BREAK; valid := True } }
  }
  // Unsupported encodings never allocate an architectural destination.
  val destination = writes && valid && rd =/= 0
}

class ApeCore(c: ApeConfig = ApeConfig()) extends Component {
  val io = new Bundle {
    val program = slave Flow(new Bundle {
      val index = UInt(c.codeBits bits)
      val instruction = Bits(32 bits)
    })
    val launch = slave Stream(new Bundle {
      val pc, argument, base, limit = UInt(64 bits)
      val writable = Bool()
    })
    val memory = master Stream(new Bundle {
      val address, data = UInt(64 bits)
      val size = UInt(2 bits) // log2(bytes); data is right-justified
      val write = Bool()
    })
    val response = slave Stream(new Bundle {
      val data = UInt(64 bits) // right-justified, extension is performed by the core
      val error = Bool()
    })
    val halt = master Stream(new Bundle {
      val pc, value = UInt(64 bits)
      val cause = UInt(4 bits) // standard synchronous exception cause numbers
    })
    val retired = master Flow(new Bundle {
      val pc = UInt(64 bits)
      val instruction = Bits(32 bits)
      val rd = UInt(5 bits)
      val writes = Bool()
      val value = UInt(64 bits)
    })
    val issued = master Flow(new Bundle { val pc = UInt(64 bits) })
    val finished = master Flow(new Bundle { val pc = UInt(64 bits) })
    val redirect = master Flow(new Bundle { val from, to = UInt(64 bits) })
    val predicted = master Flow(new Bundle { val pc, next = UInt(64 bits) })
    val controlRetired = master Flow(new Bundle {
      val pc, predictedNext, actualNext = UInt(64 bits)
      val conditional, taken = Bool()
    })
    val busy = out Bool()
    val occupancy = out UInt(log2Up(c.robEntries + 1) bits)
  }

  val code = Mem(Bits(32 bits), c.programWords)
  val active = RegInit(False)
  val halted = RegInit(False)
  val haltPc, haltValue = Reg(UInt(64 bits)) init 0
  val haltCause = Reg(UInt(4 bits)) init 0
  val fetchPc, dataBase, dataLimit = Reg(UInt(64 bits)) init 0
  val canWrite = RegInit(False)
  val head, tail = Reg(UInt(c.tagBits bits)) init 0
  val count = Reg(UInt(log2Up(c.robEntries + 1) bits)) init 0
  val arf = Vec.fill(32)(Reg(UInt(64 bits)) init 0)
  val mapped = Vec.fill(32)(RegInit(False))
  val mapping = Vec.fill(32)(Reg(UInt(c.tagBits bits)) init 0)
  val live, issued, done, prepared, sent, fault, writes, src1Ready, src2Ready =
    Vec.fill(c.robEntries)(RegInit(False))
  val cause = Vec.fill(c.robEntries)(Reg(UInt(4 bits)) init 0)
  val pc, value, address, src1, src2, immediate, actualNext, predictedNext =
    Vec.fill(c.robEntries)(Reg(UInt(64 bits)) init 0)
  val taken = Vec.fill(c.robEntries)(RegInit(False))
  val instruction = Vec.fill(c.robEntries)(Reg(Bits(32 bits)) init 0)
  val rd = Vec.fill(c.robEntries)(Reg(UInt(5 bits)) init 0)
  val tag1, tag2 = Vec.fill(c.robEntries)(Reg(UInt(c.tagBits bits)) init 0)
  val op = Vec.fill(c.robEntries)(Reg(ApeOp()) init ApeOp.ILLEGAL)
  val f3 = Vec.fill(c.robEntries)(Reg(UInt(3 bits)) init 0)
  val useImmediate, word = Vec.fill(c.robEntries)(RegInit(False))

  val requestValid, waiting = RegInit(False)
  val requestAddress, requestData = Reg(UInt(64 bits)) init 0
  val requestSize = Reg(UInt(2 bits)) init 0
  val requestWrite = RegInit(False)
  val memoryTag = Reg(UInt(c.tagBits bits)) init 0

  io.busy := active || halted
  io.occupancy := count
  io.launch.ready := !active && !halted && !requestValid && !waiting
  io.halt.valid := halted
  io.halt.pc := haltPc
  io.halt.value := haltValue
  io.halt.cause := haltCause
  io.memory.valid := requestValid
  io.memory.address := requestAddress
  io.memory.data := requestData
  io.memory.size := requestSize
  io.memory.write := requestWrite
  io.response.ready := waiting
  when(io.program.valid && !io.busy) { code.write(io.program.index, io.program.instruction) }
  when(io.halt.fire) { halted := False }

  val retiring = active && count =/= 0 && done(head)
  val redirecting = retiring && !fault(head) && actualNext(head) =/= predictedNext(head)
  val stopping = retiring && fault(head)
  val flushing = redirecting || stopping
  io.retired.valid := retiring && !fault(head)
  io.retired.pc := pc(head)
  io.retired.instruction := instruction(head)
  io.retired.rd := rd(head)
  io.retired.writes := writes(head)
  io.retired.value := value(head)
  io.redirect.valid := redirecting
  io.redirect.from := pc(head)
  io.redirect.to := actualNext(head)
  io.controlRetired.valid := io.retired.valid &&
    (op(head) === ApeOp.BRANCH || op(head) === ApeOp.JAL || op(head) === ApeOp.JALR)
  io.controlRetired.pc := pc(head)
  io.controlRetired.predictedNext := predictedNext(head)
  io.controlRetired.actualNext := actualNext(head)
  io.controlRetired.conditional := op(head) === ApeOp.BRANCH
  io.controlRetired.taken := taken(head)

  // Oldest-ready selection. Unready older instructions do not block ready ALUs.
  val ready = Bits(c.robEntries bits)
  for (offset <- 0 until c.robEntries) {
    val slot = (head + offset).resize(c.tagBits)
    ready(offset) := live(slot) && !issued(slot) && src1Ready(slot) && src2Ready(slot)
  }
  val selectedOffset = OHToUInt(OHMasking.first(ready))
  val selected = (head + selectedOffset).resize(c.tagBits)
  val issue = active && ready.orR && !flushing && !io.response.fire
  val a = src1(selected)
  val b = Mux(useImmediate(selected), immediate(selected), src2(selected))
  val shift = Mux(word(selected), b(4 downto 0).resize(6), b(5 downto 0))
  val rightValue = Mux(word(selected), a(31 downto 0).resize(64), a)
  val signedValue = Mux(word(selected), a(31 downto 0).asSInt.resize(64), a.asSInt)
  val rawResult = UInt(64 bits)
  rawResult := 0
  switch(op(selected)) {
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
    is(ApeOp.LUI) { rawResult := immediate(selected) }
    is(ApeOp.AUIPC) { rawResult := pc(selected) + immediate(selected) }
    is(ApeOp.JAL, ApeOp.JALR) { rawResult := pc(selected) + 4 }
  }
  val result = Mux(word(selected), rawResult(31 downto 0).asSInt.resize(64).asUInt, rawResult)
  val branchTaken = Bool()
  branchTaken := False
  switch(f3(selected)) {
    is(0) { branchTaken := a === src2(selected) }
    is(1) { branchTaken := a =/= src2(selected) }
    is(4) { branchTaken := a.asSInt < src2(selected).asSInt }
    is(5) { branchTaken := a.asSInt >= src2(selected).asSInt }
    is(6) { branchTaken := a < src2(selected) }
    is(7) { branchTaken := a >= src2(selected) }
  }
  val next = UInt(64 bits)
  next := pc(selected) + 4
  when(op(selected) === ApeOp.JAL || (op(selected) === ApeOp.BRANCH && branchTaken)) {
    next := pc(selected) + immediate(selected)
  }
  when(op(selected) === ApeOp.JALR) { next := (a + immediate(selected)) & U(BigInt("fffffffffffffffe", 16), 64 bits) }
  val isMemory = op(selected) === ApeOp.LOAD || op(selected) === ApeOp.STORE
  val effectiveAddress = a + immediate(selected)
  val bytes = (U(1, 65 bits) |<< f3(selected)(1 downto 0)).resize(65)
  val misaligned = (effectiveAddress.resize(65) & (bytes - 1)) =/= 0
  val illegalAccess = effectiveAddress < dataBase || effectiveAddress.resize(65) + bytes > dataLimit.resize(65) ||
    (op(selected) === ApeOp.STORE && !canWrite)
  val issueFault = fault(selected) || op(selected) === ApeOp.ILLEGAL || op(selected) === ApeOp.BREAK ||
    next(1 downto 0) =/= 0 || (isMemory && (misaligned || illegalAccess))
  val issueCause = UInt(4 bits)
  issueCause := cause(selected)
  when(!fault(selected)) {
    issueCause := 2
    when(op(selected) === ApeOp.BREAK) { issueCause := 3 }
    when(next(1 downto 0) =/= 0) { issueCause := 0 }
    when(isMemory) {
      issueCause := Mux(op(selected) === ApeOp.LOAD, U(5, 4 bits), U(7, 4 bits))
      when(misaligned) { issueCause := Mux(op(selected) === ApeOp.LOAD, U(4, 4 bits), U(6, 4 bits)) }
    }
  }

  val loadValue = UInt(64 bits)
  loadValue := io.response.data
  switch(f3(memoryTag)) {
    is(0) { loadValue := io.response.data(7 downto 0).asSInt.resize(64).asUInt }
    is(1) { loadValue := io.response.data(15 downto 0).asSInt.resize(64).asUInt }
    is(2) { loadValue := io.response.data(31 downto 0).asSInt.resize(64).asUInt }
    is(4) { loadValue := io.response.data(7 downto 0).resize(64) }
    is(5) { loadValue := io.response.data(15 downto 0).resize(64) }
    is(6) { loadValue := io.response.data(31 downto 0).resize(64) }
  }
  // One broadcast port. Memory responses take priority over new ALU issue.
  val cdbValid = (issue && !isMemory && !issueFault && writes(selected)) ||
    (io.response.fire && !io.response.error && !requestWrite && writes(memoryTag))
  val cdbTag = Mux(io.response.fire, memoryTag, selected)
  val cdbValue = Mux(io.response.fire, loadValue, result)
  io.issued.valid := issue
  io.issued.pc := pc(selected)
  io.finished.valid := (issue && (!isMemory || issueFault)) || io.response.fire
  io.finished.pc := Mux(io.response.fire, pc(memoryTag), pc(selected))

  when(issue) {
    issued(selected) := True
    actualNext(selected) := next
    taken(selected) := branchTaken
    address(selected) := effectiveAddress
    value(selected) := result
    fault(selected) := issueFault
    cause(selected) := issueCause
    when(isMemory && !issueFault) { prepared(selected) := True }
      .otherwise { done(selected) := True }
  }
  for (i <- 0 until c.robEntries) {
    when(cdbValid && live(i)) {
      when(!src1Ready(i) && tag1(i) === cdbTag) { src1Ready(i) := True; src1(i) := cdbValue }
      when(!src2Ready(i) && tag2(i) === cdbTag) { src2Ready(i) := True; src2(i) := cdbValue }
    }
  }
  // No external load, store, or MMIO can pass an older unretired instruction.
  when(active && count =/= 0 && prepared(head) && !sent(head) && !requestValid && !waiting && !flushing) {
    requestValid := True
    requestAddress := address(head)
    requestData := src2(head)
    requestSize := f3(head)(1 downto 0)
    requestWrite := op(head) === ApeOp.STORE
    memoryTag := head
    sent(head) := True
  }
  when(io.memory.fire) { requestValid := False; waiting := True }
  when(io.response.fire) {
    waiting := False
    done(memoryTag) := True
    value(memoryTag) := loadValue
    fault(memoryTag) := io.response.error
    cause(memoryTag) := Mux(requestWrite, U(7, 4 bits), U(5, 4 bits))
  }

  val fetched = code.readAsync(fetchPc(c.codeBits + 1 downto 2))
  val decode = new ApeDecode(fetched)
  val fetchFault = fetchPc(1 downto 0) =/= 0 || fetchPc >= c.programWords * 4
  val dispatch = active && count < c.robEntries && !flushing
  val predictor = new ApeBranchPredictor(c.prediction, c.predictorEntries)
  predictor.io.clear := io.launch.fire
  predictor.io.pc := fetchPc
  predictor.io.target := fetchPc + decode.imm
  predictor.io.conditional := decode.valid && !fetchFault && decode.op === ApeOp.BRANCH
  predictor.io.directJump := decode.valid && !fetchFault && decode.op === ApeOp.JAL
  predictor.io.update.valid := io.controlRetired.valid && io.controlRetired.conditional
  predictor.io.update.pc := pc(head)
  predictor.io.update.taken := taken(head)
  io.predicted.valid := dispatch
  io.predicted.pc := fetchPc
  io.predicted.next := predictor.io.next
  def operand(reg: UInt, used: Bool): (Bool, UInt) = {
    val rdy = Bool()
    val data = UInt(64 bits)
    rdy := True
    data := 0
    when(used && reg =/= 0) {
      data := arf(reg)
      when(mapped(reg)) {
        rdy := done(mapping(reg)) && !fault(mapping(reg))
        data := value(mapping(reg))
        when(cdbValid && mapping(reg) === cdbTag) { rdy := True; data := cdbValue }
      }
    }
    (rdy, data)
  }
  val operand1 = operand(decode.rs1, decode.use1 && decode.valid && !fetchFault)
  val operand2 = operand(decode.rs2, decode.use2 && decode.valid && !fetchFault)

  when(retiring) {
    live(head) := False
    head := head + 1
    when(!fault(head) && writes(head)) {
      arf(rd(head)) := value(head)
      when(mapped(rd(head)) && mapping(rd(head)) === head) { mapped(rd(head)) := False }
    }
  }
  when(dispatch) {
    live(tail) := True; issued(tail) := False; done(tail) := False
    prepared(tail) := False; sent(tail) := False
    pc(tail) := fetchPc; instruction(tail) := fetched
    rd(tail) := decode.rd; writes(tail) := decode.destination && !fetchFault
    op(tail) := decode.op
    when(!decode.valid) { op(tail) := ApeOp.ILLEGAL }
    immediate(tail) := decode.imm; useImmediate(tail) := decode.immediate
    word(tail) := decode.word; f3(tail) := decode.f3
    src1Ready(tail) := operand1._1; src1(tail) := operand1._2; tag1(tail) := mapping(decode.rs1)
    src2Ready(tail) := operand2._1; src2(tail) := operand2._2; tag2(tail) := mapping(decode.rs2)
    fault(tail) := fetchFault
    cause(tail) := Mux(fetchPc(1 downto 0) =/= 0, U(0, 4 bits), U(1, 4 bits))
    when(decode.destination && !fetchFault) { mapped(decode.rd) := True; mapping(decode.rd) := tail }
    tail := tail + 1
    predictedNext(tail) := predictor.io.next
    fetchPc := predictor.io.next
  }
  when(dispatch =/= retiring) {
    when(dispatch) { count := count + 1 }.otherwise { count := count - 1 }
  }
  // All older instructions have retired here, so the ARF is the recovery map.
  when(flushing) {
    for (i <- 0 until c.robEntries) { live(i) := False; done(i) := False }
    for (i <- 0 until 32) { mapped(i) := False }
    head := 0; tail := 0; count := 0
    fetchPc := actualNext(head)
    when(stopping) {
      active := False; halted := True
      haltPc := pc(head); haltCause := cause(head); haltValue := arf(10)
    }
  }
  when(io.launch.fire) {
    active := True
    fetchPc := io.launch.pc; dataBase := io.launch.base; dataLimit := io.launch.limit
    canWrite := io.launch.writable
    head := 0; tail := 0; count := 0
    for (i <- 0 until c.robEntries) {
      live(i) := False; done(i) := False; issued(i) := False
      prepared(i) := False; sent(i) := False
    }
    for (i <- 0 until 32) {
      if (i == 10) arf(i) := io.launch.argument else arf(i) := 0
      mapped(i) := False
    }
  }

  // Structural invariants are checked by the RTL simulator, not just the oracle.
  assert(arf(0) === 0 && !mapped(0), "x0 must never be renamed or modified")
  assert(CountOne(live.asBits).resize(count.getWidth) === count, "ROB occupancy mismatch")
  assert(!(requestValid && waiting), "request and response phases overlap")
  for (i <- 1 until 32) {
    when(mapped(i)) {
      assert(live(mapping(i)) && writes(mapping(i)) && rd(mapping(i)) === i,
        "rename map points outside its live producer")
    }
  }
  when(requestValid || waiting) {
    assert(active && live(head) && memoryTag === head && !fault(head),
      "external effect escaped the non-speculative head")
  }
}

object GenerateApe extends App {
  for (n <- Seq(4, 8, 16); prediction <- Seq(false, true)) {
    val mode = if (prediction) "bimodal" else "off"
    SpinalConfig(targetDirectory = s"build/ape/rtl/r$n-$mode")
      .generateVerilog(new ApeCore(ApeConfig(robEntries = n, prediction = prediction)))
  }
}
