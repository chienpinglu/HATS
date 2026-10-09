package hats

import spinal.core._
import spinal.lib._

case class PpeConfig(programWords: Int = 1024) {
  require(programWords >= 16 && programWords <= 65536 && isPow2(programWords))
  val codeBits = log2Up(programWords)
}

/** Independent hardware decoder for the original PPE-ISA-0.1 encoding. */
class PpeDecode(inst: Bits) extends Area {
  val op = inst(7 downto 0).asUInt
  val d = inst(12 downto 8).asUInt
  val a = inst(17 downto 13).asUInt
  val b = inst(22 downto 18).asUInt
  val p = inst(25 downto 23).asUInt
  val width = inst(27 downto 26).asUInt
  val flags = inst(29 downto 28)
  val immediate = inst(63 downto 32).asSInt
  val vector = (op >= 13 && op <= 26) || op === 33 || op === 34
  val memory = op >= 31 && op <= 34
  val store = op === 32 || op === 34
  val compare = op >= 23 && op <= 25
  val scalarWrite = op >= 1 && op <= 12
  val arithmetic = op >= 1 && op <= 26
  val allowed = Bits(64 bits)
  val encoding = Bool()
  allowed := B(255, 64 bits); encoding := False
  def fields(names: String*): BigInt = {
    val masks = Map("d" -> (BigInt(31) << 8), "a" -> (BigInt(31) << 13),
      "b" -> (BigInt(31) << 18), "p" -> (BigInt(7) << 23), "w" -> (BigInt(3) << 26),
      "f" -> (BigInt(3) << 28), "i" -> (BigInt("ffffffff", 16) << 32))
    names.foldLeft(BigInt(255))((v, n) => v | masks(n))
  }
  switch(op) {
    is(1, 13) { allowed := B(fields("d", "w", "f", "i"), 64 bits); encoding := !flags(1) }
    is(2, 14) { allowed := B(fields("d", "a", "w", "f"), 64 bits); encoding := op === 14 || !flags(1) }
    is(3, 4, 5, 6, 7, 8, 9, 10, 11, 12) {
      allowed := B(fields("d", "a", "b", "w", "f"), 64 bits); encoding := !flags(1)
    }
    is(15, 16, 17, 18, 19, 20, 21, 22) {
      allowed := B(fields("d", "a", "b", "w", "f"), 64 bits); encoding := True
    }
    is(23, 24, 25) {
      allowed := B(fields("d", "a", "b", "w", "f"), 64 bits); encoding := d < 8 && !flags(0)
    }
    is(26) { allowed := B(fields("d", "a", "b", "p", "w", "f"), 64 bits); encoding := !flags(1) }
    is(27) { allowed := B(fields("i"), 64 bits); encoding := True }
    is(28) { allowed := B(fields("a", "i"), 64 bits); encoding := True }
    is(29) { allowed := B(fields("p", "i"), 64 bits); encoding := True }
    is(30, 35, 36) { encoding := True }
    is(31, 32) { allowed := B(fields("d", "a", "w", "f", "i"), 64 bits); encoding := True }
    is(33, 34) { allowed := B(fields("d", "a", "b", "w", "f", "i"), 64 bits); encoding := True }
    is(37) { allowed := B(fields("a"), 64 bits); encoding := True }
  }
  val legal = encoding && (inst & ~allowed) === 0 &&
    (!arithmetic || ((width === 2 || width === 3) && (!flags(0) || width === 2))) &&
    (!memory || (!flags(0) || (!store && width =/= 3)))
}

object PpeState extends SpinalEnum {
  val IDLE, CLEAR, FETCH, EXECUTE, LANE, SEND, WAIT, LOAD_COMMIT, RETIRE, HALT = newElement()
}

/** One resident wave, eight logical lanes; original integer PPE implementation.
  * Code registration/structured-region validation is a trusted loader obligation.
  * Global memory is one-outstanding, tagged, uncached; scratch is separate.
  * Architectural inspection ports are verification collateral, not a chip pinout.
  */
class PpeCore(c: PpeConfig = PpeConfig()) extends Component {
  val io = new Bundle {
    val program = slave Stream(new Bundle {
      val index = UInt(c.codeBits bits)
      val instruction = Bits(64 bits)
    })
    val launch = slave Stream(new Bundle {
      val task, epoch, argument, argumentBytes, budget, base, limit = UInt(64 bits)
      val addressSpace, generation, group, groups, codeWords, scratchBytes = UInt(32 bits)
      val writable = Bool()
    })
    val memory = master Stream(new Bundle {
      val task, epoch, address, data = UInt(64 bits)
      val addressSpace, generation, transaction = UInt(32 bits)
      val size = UInt(2 bits)
      val lane = UInt(3 bits)
      val laneMask = Bits(8 bits)
      val write = Bool()
    })
    val response = slave Stream(new Bundle {
      val task, epoch, data = UInt(64 bits)
      val addressSpace, generation, transaction = UInt(32 bits)
      val error = Bool()
    })
    val completion = master Stream(new Bundle {
      val task, epoch, value, pc, address = UInt(64 bits)
      val status, cause = UInt(4 bits)
      val laneMask = Bits(8 bits)
    })
    val retired = master Flow(new Bundle {
      val pc, nextPc = UInt(64 bits)
      val instruction = Bits(64 bits)
      val mask = Bits(8 bits)
    })
    val access = master Flow(new Bundle {
      val address, data = UInt(64 bits)
      val size = UInt(2 bits)
      val lane = UInt(3 bits)
      val write, scratch = Bool()
      val error = UInt(4 bits)
    })
    val scalar = out Vec(UInt(64 bits), 32)
    val vector = out Vec(Vec(UInt(64 bits), 8), 32)
    val predicate = out Vec(Bits(8 bits), 8)
    val activeMask = out Bits(8 bits)
    val depth = out UInt(4 bits)
    val inspectScratch = in UInt(9 bits)
    val scratchData = out Bits(64 bits)
    val busy, waiting = out Bool()
  }
  val state = Reg(PpeState()) init PpeState.IDLE
  val code = Mem(Bits(64 bits), c.programWords)
  io.program.ready := state === PpeState.IDLE && !io.launch.valid
  when(io.program.fire) { code.write(io.program.index, io.program.instruction) }
  io.launch.ready := state === PpeState.IDLE
  val s = Vec.fill(32)(Reg(UInt(64 bits)) init 0)
  val v = Vec.fill(32)(Vec.fill(8)(Reg(UInt(64 bits)) init 0))
  val predicate = Vec.fill(8)(Reg(Bits(8 bits)) init 0)
  val active = Reg(Bits(8 bits)) init 0
  val depth = Reg(UInt(4 bits)) init 0
  val frameMask, frameFalse = Vec.fill(8)(Reg(Bits(8 bits)) init 0)
  val frameElse, frameJoin = Vec.fill(8)(Reg(UInt(32 bits)) init 0)
  val frameThen = Vec.fill(8)(RegInit(False))
  val top = (depth - 1).resize(3)
  val scratch = Mem(Bits(64 bits), 512)
  val clearIndex = Reg(UInt(9 bits)) init 0
  val scratchAddress = UInt(9 bits)
  val scratchWrite = Bool()
  val scratchWriteData = Bits(64 bits)
  val scratchMask = Bits(8 bits)
  scratchAddress := 0; scratchWrite := False; scratchWriteData := 0; scratchMask := 0
  scratch.write(scratchAddress, scratchWriteData, scratchWrite, scratchMask)
  io.scratchData := scratch.readAsync(io.inspectScratch)
  val task, epoch, base, limit, ticks = Reg(UInt(64 bits)) init 0
  val addressSpace, generation, count, reservation, transaction = Reg(UInt(32 bits)) init 0
  val writable, expired = RegInit(False)
  val pc, nextPc = Reg(UInt(32 bits)) init 0
  val inst = Reg(Bits(64 bits)) init 0
  val instMask = Reg(Bits(8 bits)) init 0
  val returning = RegInit(False)
  val resultValue, faultPc, faultAddress = Reg(UInt(64 bits)) init 0
  val status, cause = Reg(UInt(4 bits)) init 0
  val faultMask = Reg(Bits(8 bits)) init 0
  val lane = Reg(UInt(4 bits)) init 0
  val buffered = Vec.fill(8)(Reg(UInt(64 bits)) init 0)
  val requestAddress, requestData = Reg(UInt(64 bits)) init 0
  val requestLane = Reg(UInt(3 bits)) init 0
  val dec = new PpeDecode(inst)
  val uniform = active === B(255, 8 bits) && depth === 0
  def bytePc(value: UInt): UInt = (value.resize(64) << 3).resize(64)
  def fault(reason: Int, address: UInt = U(0, 64 bits), mask: Bits = B(0, 8 bits)): Unit = {
    status := 2; cause := reason; faultPc := bytePc(pc); faultAddress := address; faultMask := mask
    resultValue := 0; state := PpeState.HALT
  }
  def retire(): Unit = { state := PpeState.RETIRE }
  def finishLane(): Unit = { lane := Mux(dec.vector, lane + 1, U(8, 4 bits)); state := PpeState.LANE }
  val laneId = lane.resize(3)
  val laneFault = Mux(dec.vector, (B(1, 8 bits) |<< laneId), B(0, 8 bits))
  val fullAddress = s(dec.a).resize(66).asSInt +
    Mux(dec.vector, v(dec.b)(laneId), U(0, 64 bits)).resize(66).asSInt + dec.immediate.resize(66)
  val address = fullAddress.asUInt.resize(64)
  val bytes = (U(1, 5 bits) |<< dec.width)
  val endAddress = address.resize(65) + bytes.resize(65)
  val aligned = (address & (bytes.resize(64) - 1)) === 0
  val inRange = Mux(dec.flags(1), endAddress <= reservation.resize(65),
    address >= base && endAddress <= limit.resize(65) && (!dec.store || writable))
  val dataMask = UInt(64 bits)
  dataMask := U(BigInt("ffffffffffffffff", 16), 64 bits)
  switch(dec.width) {
    is(0) { dataMask := 0xff }
    is(1) { dataMask := 0xffff }
    is(2) { dataMask := U(BigInt("ffffffff", 16), 64 bits) }
  }
  val storeValue = Mux(dec.vector, v(dec.d)(laneId), s(dec.d)) & dataMask
  val scratchWord = scratch.readAsync(address(11 downto 3))
  val shift = (address(2 downto 0) << 3).resize(6)
  val scratchValue = (scratchWord.asUInt |>> shift) & dataMask
  def extend(value: UInt): UInt = {
    val result = UInt(64 bits); result := value & dataMask
    when(dec.flags(0)) {
      switch(dec.width) {
        is(0) { result := value(7 downto 0).asSInt.resize(64).asUInt }
        is(1) { result := value(15 downto 0).asSInt.resize(64).asUInt }
        is(2) { result := value(31 downto 0).asSInt.resize(64).asUInt }
      }
    }
    result
  }
  def event(a: UInt, value: UInt, which: UInt, error: UInt): Unit = {
    io.access.valid := True; io.access.address := a; io.access.data := value
    io.access.lane := which; io.access.error := error
  }
  io.scalar := s; io.vector := v; io.predicate := predicate
  io.activeMask := active; io.depth := depth
  io.busy := state =/= PpeState.IDLE
  io.waiting := state === PpeState.WAIT
  io.completion.valid := state === PpeState.HALT
  io.completion.task := task; io.completion.epoch := epoch; io.completion.value := resultValue
  io.completion.pc := faultPc; io.completion.address := faultAddress
  io.completion.status := status; io.completion.cause := cause; io.completion.laneMask := faultMask
  io.retired.valid := state === PpeState.RETIRE
  io.retired.pc := bytePc(pc); io.retired.nextPc := bytePc(nextPc)
  io.retired.instruction := inst; io.retired.mask := instMask
  io.access.valid := False; io.access.address := 0; io.access.data := 0
  io.access.size := dec.width; io.access.lane := 0; io.access.write := dec.store
  io.access.scratch := dec.flags(1); io.access.error := 0
  io.memory.valid := state === PpeState.SEND
  io.memory.task := task; io.memory.epoch := epoch
  io.memory.addressSpace := addressSpace; io.memory.generation := generation
  io.memory.transaction := transaction; io.memory.address := requestAddress; io.memory.data := requestData
  io.memory.size := dec.width; io.memory.write := dec.store; io.memory.lane := requestLane
  io.memory.laneMask := Mux(dec.vector, B(1, 8 bits) |<< requestLane, B(0, 8 bits))
  io.response.ready := True // Consume stale replies without publishing effects.
  val matching = io.response.task === task && io.response.epoch === epoch &&
    io.response.addressSpace === addressSpace && io.response.generation === generation && io.response.transaction === transaction
  val fetched = code.readAsync(pc.resize(c.codeBits))
  val timedOut = expired || ticks === 0
  when(state =/= PpeState.IDLE && state =/= PpeState.HALT) {
    when(ticks =/= 0) { ticks := ticks - 1 }
    when(ticks <= 1) { expired := True }
  }

  // One physical scalar ALU and eight logical-lane ALUs; memory remains serial.
  def alu(left: UInt, right: UInt, operation: UInt): UInt = {
    val x, y, raw, result = UInt(64 bits)
    x := left; y := right
    when(dec.width === 2) { x := left(31 downto 0).resize(64); y := right(31 downto 0).resize(64) }
    val signedX, signedY = SInt(64 bits)
    signedX := x.asSInt; signedY := y.asSInt
    when(dec.width === 2) { signedX := x(31 downto 0).asSInt.resize(64); signedY := y(31 downto 0).asSInt.resize(64) }
    val amount = Mux(dec.width === 2, y(4 downto 0).resize(6), y(5 downto 0))
    raw := x
    switch(operation) {
      is(1) { raw := dec.immediate.resize(64).asUInt }
      is(3) { raw := x + y }
      is(4) { raw := x - y }
      is(5) { raw := x & y }
      is(6) { raw := x | y }
      is(7) { raw := x ^ y }
      is(8) { raw := x |<< amount }
      is(9) { raw := x |>> amount }
      is(10) { raw := (signedX >> amount).asUInt }
      is(11) { raw := (signedX < signedY).asUInt.resize(64) }
      is(12) { raw := (x < y).asUInt.resize(64) }
    }
    result := raw
    when(dec.width === 2) {
      result := raw(31 downto 0).resize(64)
      when(dec.flags(0)) { result := raw(31 downto 0).asSInt.resize(64).asUInt }
    }
    result
  }
  val scalarResult = alu(s(dec.a), s(dec.b), dec.op)
  val vectorResults = Vec(UInt(64 bits), 8)
  val comparisons = Bits(8 bits)
  for (n <- 0 until 8) {
    val left = Mux(dec.op === 14 && dec.flags(1), s(dec.a), v(dec.a)(n))
    val right = Mux(dec.flags(1), s(dec.b), v(dec.b)(n))
    val selected = Mux(predicate(dec.p)(n), v(dec.a)(n), v(dec.b)(n))
    val operation = Mux(dec.op === 26, U(2, 8 bits), (dec.op - 12).resize(8))
    vectorResults(n) := alu(Mux(dec.op === 26, selected, left), right, operation)
    val x = Mux(dec.width === 2, left(31 downto 0).resize(64), left)
    val y = Mux(dec.width === 2, right(31 downto 0).resize(64), right)
    val sx = Mux(dec.width === 2, left(31 downto 0).asSInt.resize(64), left.asSInt)
    val sy = Mux(dec.width === 2, right(31 downto 0).asSInt.resize(64), right.asSInt)
    comparisons(n) := Mux(dec.op === 23, x === y, Mux(dec.op === 24, sx < sy, x < y))
  }

  switch(state) {
    is(PpeState.IDLE) {
      when(io.launch.fire) {
        task := io.launch.task; epoch := io.launch.epoch
        addressSpace := io.launch.addressSpace; generation := io.launch.generation
        base := io.launch.base; limit := io.launch.limit; writable := io.launch.writable
        count := io.launch.codeWords; reservation := io.launch.scratchBytes; ticks := io.launch.budget
        pc := 0; nextPc := 0; depth := 0; active := 255; transaction := 0
        returning := False; expired := False; clearIndex := 0
        status := 0; cause := 0; faultPc := 0; faultAddress := 0; faultMask := 0; resultValue := 0
        for (r <- 0 until 32) {
          r match {
            case 0 => s(r) := io.launch.argument
            case 1 => s(r) := io.launch.argumentBytes
            case 2 => s(r) := io.launch.group.resize(64)
            case 3 => s(r) := io.launch.groups.resize(64)
            case 4 => s(r) := 8
            case 6 => s(r) := io.launch.task
            case _ => s(r) := 0
          }
          for (n <- 0 until 8) v(r)(n) := (if (r < 2) U(n, 64 bits) else U(0, 64 bits))
        }
        for (r <- 0 until 8) { predicate(r) := 0; buffered(r) := 0 }
        val argsEnd = io.launch.argument.resize(65) + io.launch.argumentBytes.resize(65)
        when(io.launch.codeWords === 0 || io.launch.codeWords > c.programWords ||
          io.launch.scratchBytes > 4096 || io.launch.scratchBytes(3 downto 0) =/= 0) {
          status := 4; cause := 7; state := PpeState.HALT
        }.elsewhen(io.launch.task === 0 || io.launch.groups === 0 || io.launch.group >= io.launch.groups ||
          io.launch.budget === 0 || io.launch.base >= io.launch.limit || argsEnd > U(BigInt(1) << 64, 65 bits)) {
          status := 4; cause := 8; state := PpeState.HALT
        }.otherwise { state := PpeState.CLEAR }
      }
    }
    is(PpeState.CLEAR) {
      when(timedOut) { fault(5) }.otherwise {
        scratchAddress := clearIndex; scratchWrite := True; scratchWriteData := 0; scratchMask := 255
        clearIndex := clearIndex + 1
        when(clearIndex === 511) { state := PpeState.FETCH }
      }
    }
    is(PpeState.FETCH) {
      when(timedOut) { fault(5) }.elsewhen(pc >= count || active === 0) { fault(1) }
        .otherwise { inst := fetched; instMask := active; nextPc := pc + 1; state := PpeState.EXECUTE }
    }
    is(PpeState.EXECUTE) {
      when(timedOut) { fault(5) }.elsewhen(!dec.legal) { fault(1) }
        .elsewhen((dec.scalarWrite || (dec.memory && !dec.vector) || dec.op >= 35) && !uniform) { fault(6) }
        .otherwise {
          when(dec.scalarWrite) { s(dec.d) := scalarResult; retire() }
          .elsewhen(dec.op >= 13 && dec.op <= 26) {
            when(dec.compare) {
              predicate(dec.d.resize(3)) := (predicate(dec.d.resize(3)) & ~active) | (comparisons & active)
            }.otherwise { for (n <- 0 until 8) when(active(n)) { v(dec.d)(n) := vectorResults(n) } }
            retire()
          }.elsewhen(dec.op === 27 || dec.op === 28) {
            val destination = pc.resize(34).asSInt + dec.immediate.resize(34)
            when(dec.op === 27 || s(dec.a) =/= 0) {
              when(destination < 0 || destination.asUInt >= count.resize(34)) { fault(1) }
                .otherwise { nextPc := destination.asUInt.resize(32); retire() }
            }.otherwise { retire() }
          }.elsewhen(dec.op === 29) {
            val other = inst(47 downto 32).asUInt.resize(32)
            val join = inst(63 downto 48).asUInt.resize(32)
            val yes = active & predicate(dec.p)
            val no = active & ~predicate(dec.p)
            when(depth === 8) { fault(7) }
            .elsewhen(other <= pc + 1 || other > join || join >= count) { fault(6) }
            .otherwise {
              frameMask(depth.resize(3)) := active; frameFalse(depth.resize(3)) := no
              frameElse(depth.resize(3)) := other; frameJoin(depth.resize(3)) := join
              frameThen(depth.resize(3)) := yes.orR; depth := depth + 1
              active := Mux(yes.orR, yes, no)
              when(!yes.orR) { nextPc := other }
              retire()
            }
          }.elsewhen(dec.op === 30) {
            when(depth === 0 || frameJoin(top) =/= pc) { fault(6) }
            .otherwise {
              when(frameThen(top) && frameFalse(top).orR) {
                frameThen(top) := False; active := frameFalse(top); nextPc := frameElse(top)
              }.otherwise { active := frameMask(top); depth := depth - 1 }
              retire()
            }
          }.elsewhen(dec.memory) { lane := 0; state := PpeState.LANE }
          .elsewhen(dec.op === 35 || dec.op === 36) { retire() }
          .elsewhen(dec.op === 37) {
            status := 1; cause := 0; resultValue := s(dec.a); faultPc := bytePc(pc)
            returning := True; retire()
          }.otherwise { fault(1) }
        }
    }
    is(PpeState.LANE) {
      when(timedOut) { fault(5) }
      .elsewhen(lane === 8) { when(dec.store) { retire() }.otherwise { state := PpeState.LOAD_COMMIT } }
      .elsewhen(dec.vector && !active(laneId)) { lane := lane + 1 }
      .elsewhen(fullAddress < 0 || fullAddress.asUInt > U((BigInt(1) << 64) - 1, 66 bits)) { fault(3, address, laneFault) }
      .elsewhen(!aligned || !inRange) {
        event(address, U(0, 64 bits), laneId, Mux(!aligned, U(2, 4 bits), U(3, 4 bits)))
        when(!aligned) { fault(2, address, laneFault) }.otherwise { fault(3, address, laneFault) }
      }.elsewhen(dec.flags(1)) {
        event(address, Mux(dec.store, storeValue, scratchValue), laneId, U(0, 4 bits))
        when(dec.store) {
          scratchAddress := address(11 downto 3); scratchWrite := True
          scratchWriteData := (storeValue |<< shift).asBits
          val mask = Bits(8 bits); mask := 255
          switch(dec.width) { is(0) { mask := 1 }; is(1) { mask := 3 }; is(2) { mask := 15 } }
          scratchMask := mask |<< address(2 downto 0)
        }.otherwise { buffered(laneId) := extend(scratchValue) }
        finishLane()
      }.elsewhen(transaction === U(BigInt("ffffffff", 16), 32 bits)) { fault(7) }
      .otherwise {
        requestAddress := address; requestData := storeValue; requestLane := laneId; state := PpeState.SEND
      }
    }
    // An offered request cannot be withdrawn on timeout. Drain it before reuse.
    is(PpeState.SEND) { when(io.memory.fire) { state := PpeState.WAIT } }
    is(PpeState.WAIT) {
      when(io.response.fire && matching) {
        event(requestAddress, Mux(dec.store, requestData, io.response.data & dataMask), requestLane,
          Mux(io.response.error, U(4, 4 bits), U(0, 4 bits)))
        transaction := transaction + 1
        when(io.response.error) { fault(4, requestAddress, Mux(dec.vector, B(1, 8 bits) |<< requestLane, B(0, 8 bits))) }
        .elsewhen(timedOut) { fault(5) }
        .otherwise { when(!dec.store) { buffered(requestLane) := extend(io.response.data) }; finishLane() }
      }
    }
    is(PpeState.LOAD_COMMIT) {
      when(timedOut) { fault(5) }.otherwise {
        when(dec.vector) { for (n <- 0 until 8) when(active(n)) { v(dec.d)(n) := buffered(n) } }
          .otherwise { s(dec.d) := buffered(0) }
        retire()
      }
    }
    is(PpeState.RETIRE) {
      pc := nextPc
      when(returning) { state := PpeState.HALT }.otherwise { state := PpeState.FETCH }
    }
    is(PpeState.HALT) { when(io.completion.fire) { state := PpeState.IDLE } }
  }
}

object GeneratePpe extends App {
  SpinalConfig(targetDirectory = "build/ppe/rtl").generateVerilog(new PpeCore())
}
