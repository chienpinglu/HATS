package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import scala.util.Random

/** Port-only semantic execution tests. Alternate policies exercise real shared
  * hardware; they are not an ARM frontend or instruction-set conformance suite.
  */
object ApeSemanticSim extends App {
  val root = Paths.get("build/ape_semantics")
  Files.createDirectories(root)
  Files.writeString(root.resolve("execution.json"), "{\"status\":\"running\"}\n")
  val mask = (BigInt(1) << 64) - 1
  type Op = SpinalEnumElement[ApeOp.type]
  type Condition = SpinalEnumElement[ApeBranchCondition.type]
  type Extension = SpinalEnumElement[ApeResultExtension.type]
  type Fault = SpinalEnumElement[ApeFaultKind.type]
  case class Request(op: Op, a: BigInt = 0, b: BigInt = 0, imm: BigInt = 0,
                     pc: BigInt = 0x80, sequential: BigInt = 0x88,
                     targetMask: BigInt = mask, alignmentMask: BigInt = 3,
                     immediate: Boolean = false, narrow: Boolean = false,
                     extension: Extension = ApeResultExtension.FULL,
                     branch: Condition = ApeBranchCondition.EQ,
                     base: BigInt = 0x10000, limit: BigInt = 0x20000,
                     size: Int = 3, writable: Boolean = true,
                     priorFault: Fault = ApeFaultKind.NONE)
  def signed(x: BigInt, bits: Int): BigInt = {
    val low = x & ((BigInt(1) << bits) - 1)
    if (low.testBit(bits - 1)) low - (BigInt(1) << bits) else low
  }
  var checked, differingExtensions, alternateTargets, faults = 0
  SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("execution").toString).compile(new ApeExecute(ApeConfig())).doSim { dut =>
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      dut.io.clear #= false; dut.io.request.valid #= false; dut.io.result.ready #= false
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      def run(r: Request): BigInt = {
        val rhs = if (r.immediate) r.imm else r.b
        val shift = (rhs & (if (r.narrow) 31 else 63)).toInt
        val raw = (r.op match {
          case ApeOp.ADD => r.a + rhs
          case ApeOp.SUB => r.a - rhs
          case ApeOp.SLL => r.a << shift
          case ApeOp.SRL => (if (r.narrow) r.a & 0xffffffffL else r.a) >> shift
          case ApeOp.SRA => signed(r.a, if (r.narrow) 32 else 64) >> shift
          case ApeOp.SLT => BigInt(if (signed(r.a, 64) < signed(rhs, 64)) 1 else 0)
          case ApeOp.SLTU => BigInt(if (r.a < rhs) 1 else 0)
          case ApeOp.XOR => r.a ^ rhs
          case ApeOp.OR => r.a | rhs
          case ApeOp.AND => r.a & rhs
          case ApeOp.CONSTANT => r.imm
          case ApeOp.PC_ADD => r.pc + r.imm
          case ApeOp.JUMP_RELATIVE | ApeOp.JUMP_REGISTER => r.sequential
          case _ => BigInt(0)
        }) & mask
        val expectedValue = r.extension match {
          case ApeResultExtension.SIGN_32 => signed(raw, 32) & mask
          case ApeResultExtension.ZERO_32 => raw & 0xffffffffL
          case _ => raw
        }
        val take = r.branch match {
          case ApeBranchCondition.EQ => r.a == r.b
          case ApeBranchCondition.NE => r.a != r.b
          case ApeBranchCondition.LT => signed(r.a, 64) < signed(r.b, 64)
          case ApeBranchCondition.GE => signed(r.a, 64) >= signed(r.b, 64)
          case ApeBranchCondition.LTU => r.a < r.b
          case ApeBranchCondition.GEU => r.a >= r.b
        }
        val next = (r.op match {
          case ApeOp.JUMP_REGISTER => (r.a + r.imm) & r.targetMask
          case ApeOp.JUMP_RELATIVE => r.pc + r.imm
          case ApeOp.BRANCH if take => r.pc + r.imm
          case _ => r.sequential
        }) & mask
        val address = (r.a + r.imm) & mask
        val memory = r.op == ApeOp.LOAD || r.op == ApeOp.STORE
        val control = r.op == ApeOp.BRANCH || r.op == ApeOp.JUMP_RELATIVE || r.op == ApeOp.JUMP_REGISTER
        val bytes = BigInt(1) << r.size
        val misaligned = address % bytes != 0
        val denied = address < r.base || address + bytes > r.limit || (r.op == ApeOp.STORE && !r.writable)
        var fault: Fault = ApeFaultKind.NONE
        if (r.op == ApeOp.ILLEGAL) fault = ApeFaultKind.ILLEGAL
        if (r.op == ApeOp.BREAK) fault = ApeFaultKind.BREAKPOINT
        if ((next & r.alignmentMask) != 0) fault = ApeFaultKind.INSTRUCTION_ALIGNMENT
        if (memory && (misaligned || denied)) {
          fault = if (misaligned) {
            if (r.op == ApeOp.LOAD) ApeFaultKind.LOAD_ALIGNMENT else ApeFaultKind.STORE_ALIGNMENT
          } else if (r.op == ApeOp.LOAD) ApeFaultKind.LOAD_ACCESS else ApeFaultKind.STORE_ACCESS
        }
        if (r.priorFault != ApeFaultKind.NONE) fault = r.priorFault
        dut.io.request.valid #= true
        dut.io.request.identity.slot #= checked % 8
        dut.io.request.identity.generation #= checked % 4
        dut.io.request.identity.destination #= 32 + checked % 32
        dut.io.request.op #= r.op; dut.io.request.branch #= r.branch
        dut.io.request.a #= r.a; dut.io.request.b #= r.b; dut.io.request.immediate #= r.imm
        dut.io.request.pc #= r.pc; dut.io.request.sequentialNext #= r.sequential
        dut.io.request.indirectTargetMask #= r.targetMask; dut.io.request.alignmentMask #= r.alignmentMask
        dut.io.request.useImmediate #= r.immediate; dut.io.request.narrow32 #= r.narrow
        dut.io.request.resultExtension #= r.extension
        dut.io.request.base #= r.base; dut.io.request.limit #= r.limit
        dut.io.request.memorySize #= r.size; dut.io.request.writable #= r.writable
        dut.io.request.fault #= (r.priorFault != ApeFaultKind.NONE); dut.io.request.faultKind #= r.priorFault
        sleep(1); assert(dut.io.request.ready.toBoolean); edge(); dut.io.request.valid #= false
        var wait = 0
        while (!dut.io.result.valid.toBoolean && wait < 8) { edge(); wait += 1 }
        assert(dut.io.result.valid.toBoolean, "semantic execution timed out")
        assert(dut.io.result.identity.slot.toInt == checked % 8 && dut.io.result.identity.generation.toInt == checked % 4)
        assert(dut.io.result.identity.destination.toInt == 32 + checked % 32)
        assert(dut.io.result.value.toBigInt == expectedValue, s"semantic value mismatch: $r")
        assert(dut.io.result.next.toBigInt == next && dut.io.result.address.toBigInt == address, s"semantic address mismatch: $r")
        assert(dut.io.result.faultKind.toEnum == fault && dut.io.result.fault.toBoolean == (fault != ApeFaultKind.NONE), s"fault class mismatch: $r")
        assert(dut.io.result.memory.toBoolean == memory && dut.io.result.control.toBoolean == control)
        if (r.op == ApeOp.BRANCH) assert(dut.io.result.taken.toBoolean == take)
        if (fault != ApeFaultKind.NONE) faults += 1
        checked += 1
        dut.io.result.ready #= true; edge(); dut.io.result.ready #= false
        expectedValue
      }
      val rng = new Random(0x53454d)
      val operations = Seq(ApeOp.ADD, ApeOp.SUB, ApeOp.SLL, ApeOp.SRL, ApeOp.SRA,
        ApeOp.SLT, ApeOp.SLTU, ApeOp.XOR, ApeOp.OR, ApeOp.AND, ApeOp.CONSTANT, ApeOp.PC_ADD)
      for (op <- operations; narrow <- Seq(false, true); immediate <- Seq(false, true); i <- 0 until 32) {
        val r = Request(op, BigInt(64, rng), BigInt(64, rng), BigInt(64, rng), immediate = immediate, narrow = narrow)
        run(r)
        val sign = run(r.copy(extension = ApeResultExtension.SIGN_32))
        val zero = run(r.copy(extension = ApeResultExtension.ZERO_32))
        if (sign != zero) differingExtensions += 1
      }
      for (condition <- Seq(ApeBranchCondition.EQ, ApeBranchCondition.NE, ApeBranchCondition.LT, ApeBranchCondition.GE,
                            ApeBranchCondition.LTU, ApeBranchCondition.GEU); a <- Seq(BigInt(0), BigInt(7), mask);
           b <- Seq(BigInt(0), BigInt(7), mask); alignment <- Seq(0, 1, 3)) {
        run(Request(ApeOp.BRANCH, a, b, imm = 6, branch = condition, alignmentMask = alignment))
      }
      for (op <- Seq(ApeOp.JUMP_RELATIVE, ApeOp.JUMP_REGISTER); target <- Seq(0x100, 0x101, 0x102, 0x103);
           clearMask <- Seq(mask, mask - 1, mask - 3); alignment <- Seq(0, 1, 3)) {
        run(Request(op, a = target, imm = 0, targetMask = clearMask, alignmentMask = alignment, sequential = 0x90))
        alternateTargets += 1
      }
      for (op <- Seq(ApeOp.LOAD, ApeOp.STORE); size <- 0 until 4;
           address <- Seq(BigInt(0xffff), BigInt(0x10000), BigInt(0x10001), BigInt(0x1ffff), BigInt(0x20000), mask);
           writable <- Seq(false, true)) run(Request(op, a = address, size = size, writable = writable))
      for (op <- Seq(ApeOp.BREAK, ApeOp.ILLEGAL, ApeOp.LOAD, ApeOp.STORE, ApeOp.JUMP_REGISTER);
           prior <- Seq(ApeFaultKind.NONE, ApeFaultKind.INSTRUCTION_ACCESS, ApeFaultKind.INSTRUCTION_ALIGNMENT)) {
        run(Request(op, a = 1, priorFault = prior))
      }
      assert(differingExtensions > 100 && alternateTargets == 72 && faults > 100)
    }
  Files.writeString(root.resolve("execution.json"), s"""{"status":"passed","semantic_vectors":$checked,"different_sign_zero_results":$differingExtensions,"alternate_target_vectors":$alternateTargets,"fault_vectors":$faults,"claim":"Shared execution RTL with explicit semantics; not another ISA frontend"}
""")
}

class ApeRv64ProfileProbe extends Component {
  val io = new Bundle {
    val instruction = in Bits(32 bits)
    val pc = in UInt(64 bits)
    val faultKind = in(ApeFaultKind())
    val encodedCause = out UInt(4 bits)
    val valid, fetchFault = out Bool()
    val fetchFaultKind = out(ApeFaultKind())
    val sequential = out UInt(64 bits)
    val extension = out(ApeResultExtension())
  }
  val front = new ApeRv64Frontend(io.instruction, io.pc, 1024)
  io.valid := front.decoded.valid; io.fetchFault := front.fetchFault
  io.fetchFaultKind := front.fetchFaultKind; io.sequential := front.sequentialNext
  io.extension := front.resultExtension; io.encodedCause := ApeRv64Profile.encodeFault(io.faultKind)
}

object ApeRv64ProfileSim extends App {
  val root = Paths.get("build/ape_semantics"); Files.createDirectories(root)
  Files.writeString(root.resolve("profile.json"), "{\"status\":\"running\"}\n")
  var checks = 0
  SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("profile").toString).compile(new ApeRv64ProfileProbe).doSim { dut =>
      val faults = Seq(ApeFaultKind.NONE -> 0, ApeFaultKind.INSTRUCTION_ALIGNMENT -> 0, ApeFaultKind.INSTRUCTION_ACCESS -> 1,
        ApeFaultKind.ILLEGAL -> 2, ApeFaultKind.BREAKPOINT -> 3, ApeFaultKind.LOAD_ALIGNMENT -> 4,
        ApeFaultKind.LOAD_ACCESS -> 5, ApeFaultKind.STORE_ALIGNMENT -> 6, ApeFaultKind.STORE_ACCESS -> 7)
      for ((kind, cause) <- faults; pc <- Seq(0, 2, 4092, 4096, 4098);
           (instruction, valid, word) <- Seq((0x00150513L, true, false), (0x0015051bL, true, true), (0xffffffffL, false, false))) {
        dut.io.instruction #= instruction; dut.io.pc #= pc; dut.io.faultKind #= kind; sleep(1)
        assert(dut.io.encodedCause.toInt == cause && dut.io.valid.toBoolean == valid)
        assert(dut.io.sequential.toBigInt == pc + 4 && dut.io.fetchFault.toBoolean == (pc % 4 != 0 || pc >= 4096))
        if (dut.io.fetchFault.toBoolean) assert(dut.io.fetchFaultKind.toEnum ==
          (if (pc % 4 != 0) ApeFaultKind.INSTRUCTION_ALIGNMENT else ApeFaultKind.INSTRUCTION_ACCESS))
        if (valid) assert(dut.io.extension.toEnum == (if (word) ApeResultExtension.SIGN_32 else ApeResultExtension.FULL))
        checks += 1
      }
    }
  Files.writeString(root.resolve("profile.json"), s"""{"status":"passed","checks":$checks,"claim":"RV64 frontend policy and public exception presentation RTL; not full ISA conformance"}
""")
}

/** The predictor owns history indexing, not instruction length/fallthrough. */
object ApePredictorPolicySim extends App {
  val root = Paths.get("build/ape_semantics")
  Files.createDirectories(root)
  Files.writeString(root.resolve("predictor.json"), "{\"status\":\"running\"}\n")
  var checks = 0
  for (shift <- Seq(1, 3); enabled <- Seq(false, true)) {
    SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
      .workspacePath(root.resolve(s"predictor-s$shift-$enabled").toString)
      .compile(new ApeBranchPredictor(enabled, 16, shift)).doSim { dut =>
        val history = Array.fill(16)(1)
        val rng = new Random(0x5052 + shift)
        dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
        dut.io.clear #= false; dut.io.pc #= 0; dut.io.target #= 0; dut.io.sequentialNext #= 8
        dut.io.conditional #= false; dut.io.directJump #= false
        dut.io.update.valid #= false; dut.io.update.pc #= 0; dut.io.update.taken #= false
        def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
        for (_ <- 0 until 4) edge()
        dut.clockDomain.deassertReset(); edge()
        for (cycle <- 0 until 128) {
          val pc = rng.nextInt(128) << shift
          val train = rng.nextInt(128) << shift
          val sequential = pc + 2 * (1 + cycle % 4)
          val cond = rng.nextBoolean(); val jump = cycle % 7 == 0
          val take = rng.nextBoolean(); val clear = cycle % 17 == 0
          dut.io.pc #= pc; dut.io.target #= pc + 128; dut.io.sequentialNext #= sequential
          dut.io.conditional #= cond; dut.io.directJump #= jump; dut.io.clear #= clear
          dut.io.update.valid #= true; dut.io.update.pc #= train; dut.io.update.taken #= take
          def check(): Unit = {
            sleep(1)
            val target = if (enabled && (jump || cond && history((pc >> shift) % 16) >= 2)) pc + 128 else sequential
            assert(dut.io.next.toBigInt == target); checks += 1
          }
          check(); edge()
          if (clear) java.util.Arrays.fill(history, 1)
          else {
            val i = (train >> shift) % 16
            history(i) = math.max(0, math.min(3, history(i) + (if (take) 1 else -1)))
          }
          check()
        }
      }
  }
  Files.writeString(root.resolve("predictor.json"), s"""{"status":"passed","checks":$checks,"index_shifts":[1,3],"claim":"Actual predictor with independently supplied fallthrough and indexing policy"}
""")
}
