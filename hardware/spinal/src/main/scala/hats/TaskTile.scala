package hats

import spinal.core._
import spinal.lib._

case class TileConfig(contexts: Int = 4, programWords: Int = 256) {
  require(contexts >= 2 && (contexts & (contexts - 1)) == 0)
  require(programWords >= 32 && (programWords & (programWords - 1)) == 0)
  val contextBits = log2Up(contexts)
  val programBits = log2Up(programWords)
}

object TaskState extends SpinalEnum {
  val FREE, RUN, ISSUE, MEMORY, JOIN, DONE = newElement()
}

object Fault {
  val None = 0
  val Instruction = 1
  val Pc = 2
  val Alignment = 3
  val Capability = 4
  val Unmapped = 5
  val Bus = 6
  val Resources = 7
  val TaskProtocol = 8
  val Cancelled = 9
  val MemoryProtocol = 10
}

case class Launch() extends Bundle {
  val pc = UInt(64 bits)
  val argument = UInt(64 bits)
  val base = UInt(64 bits)
  val limit = UInt(64 bits) // exclusive, inherited by every child
  val writable = Bool()
}
case class MemoryRequest(c: TileConfig) extends Bundle {
  val context = UInt(c.contextBits bits)
  val address = UInt(64 bits)
  val data = Bits(64 bits)
  val write = Bool()
  val target = UInt(4 bits)
}
case class MemoryResponse(c: TileConfig) extends Bundle {
  val context = UInt(c.contextBits bits)
  val data = Bits(64 bits)
  val error = Bool()
}
case class Completion() extends Bundle {
  val result = Bits(64 bits)
  val fault = UInt(8 bits)
}

/** One shared scalar pipeline, independent A64 contexts, hardware fork/join.
  * Physical memory, no caches/MMU/tensors. Not a conformant Arm processor.
  */
class TaskTile(c: TileConfig = TileConfig()) extends Component {
  val io = new Bundle {
    val program = slave Flow(new Bundle {
      val index = UInt(c.programBits bits)
      val instruction = Bits(32 bits)
    })
    val launch = slave Stream(Launch())
    val cancel = in Bool()
    val request = master Stream(MemoryRequest(c))
    val response = slave Stream(MemoryResponse(c))
    val completion = master Stream(Completion())
    val busy = out Bool()
    val cycles = out UInt(64 bits)
    val issuedInstructions = out UInt(64 bits)
    val spawned = out UInt(32 bits)
    val memoryResumes = out UInt(32 bits)
    val joinResumes = out UInt(32 bits)
    val state = out Vec(TaskState(), c.contexts)
    val pc = out Vec(UInt(64 bits), c.contexts)
  }

  val code = Mem(Bits(32 bits), c.programWords)
  val busy = RegInit(False)
  val aborting = RegInit(False)
  val fault = Reg(UInt(8 bits)) init 0
  val state = Vec.fill(c.contexts)(Reg(TaskState()) init TaskState.FREE)
  val pc = Vec.fill(c.contexts)(Reg(UInt(64 bits)) init 0)
  // Register 31 is physically present but reads as XZR; SP forms are rejected.
  val registers = Vec.fill(c.contexts)(Vec.fill(32)(Reg(UInt(64 bits)) init 0))
  val hasChild = Vec.fill(c.contexts)(RegInit(False))
  val child = Vec.fill(c.contexts)(Reg(UInt(c.contextBits bits)) init 0)
  val destination = Vec.fill(c.contexts)(Reg(UInt(5 bits)) init 0)
  val isLoad = Vec.fill(c.contexts)(RegInit(False))
  val issued = Vec.fill(c.contexts)(RegInit(False))
  val base = Reg(UInt(64 bits)) init 0
  val limit = Reg(UInt(64 bits)) init 0
  val writable = RegInit(False)
  val cursor = Reg(UInt(c.contextBits bits)) init 0
  val requestValid = RegInit(False)
  val request = Reg(MemoryRequest(c))
  val cycles = Reg(UInt(64 bits)) init 0
  val issuedInstructions = Reg(UInt(64 bits)) init 0
  val spawned = Reg(UInt(32 bits)) init 0
  val memoryResumes = Reg(UInt(32 bits)) init 0
  val joinResumes = Reg(UInt(32 bits)) init 0

  io.busy := busy
  io.cycles := cycles
  io.issuedInstructions := issuedInstructions
  io.spawned := spawned
  io.memoryResumes := memoryResumes
  io.joinResumes := joinResumes
  io.state := state
  io.pc := pc
  io.request.valid := requestValid
  io.request.payload := request
  io.response.ready := True
  val drained = !requestValid && !issued.asBits.orR
  io.completion.valid := busy && drained && (aborting || state(0) === TaskState.DONE)
  io.completion.result := registers(0)(0).asBits
  io.completion.fault := fault
  io.launch.ready := !busy && !io.response.valid && !io.cancel

  when(io.program.valid && !busy) { code.write(io.program.index, io.program.instruction) }
  when(busy) {
    cursor := cursor + 1
    // Freeze published completion and telemetry while the consumer stalls.
    when(!io.completion.valid) { cycles := cycles + 1 }
  }

  def fail(code: Int): Unit = {
    when(!aborting) {
      fault := U(code, 8 bits)
      aborting := True
    }
  }
  def put(ctx: UInt, rd: UInt, value: UInt): Unit = {
    when(rd =/= 31) { registers(ctx)(rd) := value.resized }
  }
  def get(ctx: UInt, rs: UInt): UInt = Mux(rs === 31, U(0, 64 bits), registers(ctx)(rs))

  val instruction = code.readAsync(pc(cursor)(c.programBits + 1 downto 2))
  val rd = instruction(4 downto 0).asUInt
  val rn = instruction(9 downto 5).asUInt
  val rm = instruction(20 downto 16).asUInt
  val nextPc = pc(cursor) + 4
  val source = get(cursor, rn)
  val value = get(cursor, rd)
  val address = (source + (instruction(21 downto 10).asUInt.resize(64) << 3)).resize(64)
  val target = UInt(4 bits)
  target := 15
  for (i <- 0 until 8) {
    when(address >= (0x10000L + i * 0x10000L) && address < (0x20000L + i * 0x10000L)) {
      target := i // 0..3 HBM; 4..7 domain LPDDR
    }
  }
  when(address >= 0x100000L && address < 0x200000L) { target := 8 } // CPU LPDDR

  val freeFound = Bool()
  val freeSlot = UInt(c.contextBits bits)
  freeFound := False
  freeSlot := 0
  for (i <- (1 until c.contexts).reverse) {
    when(state(i) === TaskState.FREE) { freeFound := True; freeSlot := i }
  }

  // Instruction issue yields to responses and request acceptance. A response
  // and acceptance for different contexts may proceed together.
  when(io.response.fire) {
    val r = io.response.context
    when(busy && issued(r) && state(r) === TaskState.MEMORY) {
      issued(r) := False
      when(!aborting) {
        when(io.response.error) { fail(Fault.Bus) }
          .otherwise {
            when(isLoad(r)) { put(r, destination(r), io.response.data.asUInt) }
            state(r) := TaskState.RUN
            memoryResumes := memoryResumes + 1
          }
      }
    }.elsewhen(busy && !io.completion.valid) { fail(Fault.MemoryProtocol) }
  }
  // Request acceptance is independent of responses; both may fire together.
  when(io.request.fire) {
    requestValid := False
    issued(request.context) := True
    state(request.context) := TaskState.MEMORY
  }

  when(io.launch.fire) {
    busy := True
    aborting := False
    fault := 0
    base := io.launch.base
    limit := io.launch.limit
    writable := io.launch.writable
    cursor := 0
    cycles := 0; issuedInstructions := 0; spawned := 0; memoryResumes := 0; joinResumes := 0
    for (i <- 0 until c.contexts) {
      state(i) := (if (i == 0) TaskState.RUN else TaskState.FREE)
      issued(i) := False; hasChild(i) := False
      if (i == 0) pc(i) := io.launch.pc else pc(i) := 0
      for (r <- 0 until 32) {
        if (i == 0 && r == 0) registers(i)(r) := io.launch.argument
        else registers(i)(r) := 0
      }
    }
  }

  when(busy && !aborting && !io.cancel && !io.response.valid && !io.request.fire && !io.completion.valid) {
    when(state(cursor) === TaskState.JOIN) {
      when(state(child(cursor)) === TaskState.DONE) {
        put(cursor, destination(cursor), registers(child(cursor))(0))
        state(child(cursor)) := TaskState.FREE
        hasChild(cursor) := False
        state(cursor) := TaskState.RUN
        joinResumes := joinResumes + 1
      }
    }.elsewhen(state(cursor) === TaskState.RUN) {
      when(pc(cursor)(1 downto 0) =/= 0 || pc(cursor) >= c.programWords * 4) {
        fail(Fault.Pc)
      }.otherwise {
        val wide = instruction & B(0xff800000L, 32 bits)
        val mem = instruction & B(0xffc00000L, 32 bits)
        // Successful instructions advance PC unless explicitly redirected.
        pc(cursor) := nextPc
        issuedInstructions := issuedInstructions + 1
        when(wide === B(0xd2800000L, 32 bits) || wide === B(0xf2800000L, 32 bits)) {
          val shift = (instruction(22 downto 21).asUInt.resize(6) << 4).resize(6)
          val imm = (instruction(20 downto 5).asUInt.resize(64) |<< shift)
          val mask = U(0xffff, 64 bits) |<< shift
          put(cursor, rd, Mux(wide === B(0xf2800000L, 32 bits), (value & ~mask) | imm, imm))
        }.elsewhen(wide === B(0x91000000L, 32 bits) || wide === B(0xd1000000L, 32 bits)) {
          val imm = Mux(instruction(22), (instruction(21 downto 10).asUInt.resize(64) << 12).resize(64),
            instruction(21 downto 10).asUInt.resize(64))
          when(rn === 31 || rd === 31) { fail(Fault.Instruction) }
            .otherwise { put(cursor, rd, Mux(instruction(30), source - imm, source + imm)) }
        }.elsewhen((instruction & B(0xffe0fc00L, 32 bits)) === B(0x8b000000L, 32 bits)) {
          put(cursor, rd, source + get(cursor, rm))
        }.elsewhen(mem === B(0xf9400000L, 32 bits) || mem === B(0xf9000000L, 32 bits)) {
          val load = instruction(22)
          when(rn === 31) { fail(Fault.Instruction) }
            .elsewhen(address(2 downto 0) =/= 0) { fail(Fault.Alignment) }
            .elsewhen(address === 0xff00L) {
              when(load || hasChild(cursor)) { fail(Fault.TaskProtocol) }
                .elsewhen(!freeFound) { fail(Fault.Resources) }
                .elsewhen(value(1 downto 0) =/= 0 || value >= c.programWords * 4) { fail(Fault.Pc) }
                .otherwise {
                  state(freeSlot) := TaskState.RUN
                  pc(freeSlot) := value
                  hasChild(freeSlot) := False
                  for (r <- 0 until 32) registers(freeSlot)(r) := U(0, 64 bits)
                  registers(freeSlot)(0) := registers(cursor)(0)
                  hasChild(cursor) := True
                  child(cursor) := freeSlot
                  registers(cursor)(0) := freeSlot.resize(64)
                  spawned := spawned + 1
                }
            }.elsewhen(address === 0xff08L) {
              when(!load || !hasChild(cursor)) { fail(Fault.TaskProtocol) }
                .otherwise { destination(cursor) := rd; state(cursor) := TaskState.JOIN }
            }.elsewhen(address < base || address.resize(65) + 8 > limit.resize(65) || (!load && !writable)) {
              fail(Fault.Capability)
            }.elsewhen(target === 15) { fail(Fault.Unmapped) }
            .elsewhen(requestValid) {
              // Retry locally; do not retire an instruction that did not issue.
              pc(cursor) := pc(cursor)
              issuedInstructions := issuedInstructions
            }.otherwise {
              requestValid := True
              request.context := cursor
              request.address := address
              request.data := value.asBits
              request.write := !load
              request.target := target
              destination(cursor) := rd
              isLoad(cursor) := load
              state(cursor) := TaskState.ISSUE
            }
        }.elsewhen((instruction & B(0xfc000000L, 32 bits)) === B(0x14000000L, 32 bits)) {
          val offset = (instruction(25 downto 0).asSInt.resize(64) << 2).asUInt.resize(64)
          pc(cursor) := pc(cursor) + offset
        }.elsewhen((instruction & B(0xfe000000L, 32 bits)) === B(0xb4000000L, 32 bits)) {
          val offset = (instruction(23 downto 5).asSInt.resize(64) << 2).asUInt.resize(64)
          when((value =/= 0) === instruction(24)) { pc(cursor) := pc(cursor) + offset }
        }.elsewhen(instruction === B(0xd503201fL, 32 bits)) {
          // NOP
        }.elsewhen(instruction === B(0xd4200000L, 32 bits)) {
          when(hasChild(cursor)) { fail(Fault.TaskProtocol) }
            .otherwise { state(cursor) := TaskState.DONE }
        }.otherwise { fail(Fault.Instruction) }
      }
    }
  }

  when(io.cancel && busy && !io.completion.valid) { fail(Fault.Cancelled) }
  when(io.completion.fire) {
    busy := False
    aborting := False
    for (i <- 0 until c.contexts) { state(i) := TaskState.FREE; hasChild(i) := False }
  }
}

object Generate extends App {
  for (n <- Seq(2, 4, 8)) {
    SpinalConfig(targetDirectory = s"build/rtl/c$n").generateVerilog(new TaskTile(TileConfig(contexts = n)))
  }
}
