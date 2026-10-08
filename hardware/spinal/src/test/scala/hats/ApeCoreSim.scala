package hats

import spinal.core._
import spinal.core.sim._
import scala.collection.mutable
import scala.util.Random
import java.nio.file.{Files, Paths}
import java.nio.charset.StandardCharsets

object ApeCoreSim extends App {
  import ApeReference._
  val entries = args.headOption.map(_.toInt).getOrElse(8)
  val mode = args.lift(1).getOrElse("bimodal")
  require(Set("off", "bimodal").contains(mode))
  val prediction = mode == "bimodal"
  case class Test(name: String, image: String, cause: Int = 3, writable: Boolean = true,
                  busError: Boolean = false, entry: BigInt = 0, expected: Option[BigInt] = None)
  val names = Seq("integer_alu", "rename_raw_waw_war", "wrong_path_effects", "branches",
    "call_return", "word_alu", "memory_sizes", "illegal_precise", "load_alignment",
    "store_alignment", "load_bounds", "store_bounds", "store_readonly", "load_bus_fault",
    "jump_alignment", "loop_rob_wrap", "nested_redirect", "reserved_encoding", "compiled_c",
    "zero_register", "unsupported_fence_i", "store_bus_fault", "fetch_bounds", "not_taken", "command_store",
    "zero_load_fault", "jalr_clear_bit0", "untaken_misaligned_target", "load_upper_bound",
    "direct_jump_prediction", "predicted_taken_exit", "taken_fallthrough_target")
  val traps = Map(7 -> 2, 8 -> 4, 9 -> 6, 10 -> 5, 11 -> 7, 12 -> 7, 13 -> 5, 14 -> 0,
    17 -> 2, 20 -> 2, 21 -> 7, 22 -> 1, 25 -> 5, 28 -> 5)
  val known = Map(1 -> BigInt(40), 2 -> BigInt(42), 3 -> BigInt(42), 4 -> BigInt(42),
    15 -> BigInt(4950), 16 -> BigInt(42), 18 -> BigInt(274), 19 -> BigInt(0), 23 -> BigInt(42), 24 -> BigInt(42),
    25 -> BigInt(42), 26 -> BigInt(42), 27 -> BigInt(42), 28 -> BigInt(42),
    29 -> BigInt(42), 30 -> BigInt(42), 31 -> BigInt(42))
  val tests = names.zipWithIndex.map { case (name, i) =>
    Test(name, s"p$i", traps.getOrElse(i, 3), writable = i != 12,
      busError = i == 13 || i == 21, expected = known.get(i))
  } ++ (0 until 8).map(i => Test(s"random_$i", s"random$i")) ++
    (0 until 8).map(i => Test(s"control_$i", s"control$i")) ++ Seq(
    Test("entry_alignment", "p0", cause = 0, entry = 2),
    Test("entry_bounds", "p0", cause = 1, entry = 4096))
  val out = Paths.get(s"build/ape/r$entries-$mode")
  Files.createDirectories(out)
  def writeFile(name: String, content: String): Unit =
    Files.write(out.resolve(name), content.getBytes(StandardCharsets.UTF_8))
  writeFile("validation.json", "{\"status\":\"running\"}\n")
  val compiled = SimConfig.withVerilator.withWave.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(s"build/ape/sim/r$entries-$mode")
    .compile(new ApeCore(ApeConfig(robEntries = entries, prediction = prediction)))
  val reports = mutable.ArrayBuffer[String]()
  case class Request(address: BigInt, data: BigInt, size: Int, write: Boolean)
  tests.zipWithIndex.foreach { case (test, testIndex) =>
    compiled.doSim(test.name, seed = testIndex + 1) { dut =>
      val rng = new Random(testIndex + 1)
      val source = scala.io.Source.fromFile(s"build/ape/programs/${test.image}.hex")
      val program = try source.getLines().map(java.lang.Long.parseLong(_, 16)).toVector finally source.close()
      dut.clockDomain.clockSim #= false
      dut.clockDomain.assertReset()
      dut.io.program.valid #= false
      dut.io.program.index #= 0
      dut.io.program.instruction #= 0
      dut.io.launch.valid #= false
      dut.io.launch.pc #= test.entry
      dut.io.launch.argument #= 0
      dut.io.launch.base #= 0x10000
      dut.io.launch.limit #= 0x20000
      dut.io.launch.writable #= test.writable
      dut.io.memory.ready #= false
      dut.io.response.valid #= false
      dut.io.response.data #= 0
      dut.io.response.error #= false
      dut.io.halt.ready #= false
      def edge(): Unit = {
        dut.clockDomain.risingEdge(); sleep(5)
        dut.clockDomain.fallingEdge(); sleep(5)
      }
      for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      for (i <- 0 until 1024) {
        dut.io.program.valid #= true
        dut.io.program.index #= i
        dut.io.program.instruction #= (if (i < program.size) program(i) else 0L)
        sleep(1); edge()
      }
      dut.io.program.valid #= false

      // Exercise fresh launch after a held/consumed halt, without resetting RTL.
      for (invocation <- 0 until 2) {
        val memory = initialMemory()
        val reference = new Machine(program, mutable.Map.from(memory), entry = test.entry,
          writable = test.writable, busError = test.busError)
        val issuedPcs, finishedPcs, retiredPcs = mutable.ArrayBuffer[BigInt]()
        val trace = mutable.ArrayBuffer[String]()
        // External-oracle interchange: values below come from DUT signals and
        // the supplied memory service, never from ApeReference retirement values.
        val architectural = mutable.ArrayBuffer[String]()
        val memoryRequests = mutable.ArrayBuffer[Request]()
        var pending: Option[(Int, BigInt)] = None
        var held: Option[Request] = None
        var cycle = 0
        var stalls = 0
        var commandWrites = 0
        var branches = 0
        var branchMisses = 0
        var controls = 0
        var redirects = 0
        var predictedTakenBranches = 0
        var predictedTakenExit = false
        var halted = false
        dut.io.launch.valid #= true
        sleep(1)
        assert(dut.io.launch.ready.toBoolean, "restart was not accepted")
        edge()
        dut.io.launch.valid #= false
        while (!halted && cycle < 12000) {
          dut.io.memory.ready #= (cycle % 5 >= 2 && rng.nextInt(4) != 0)
          val reply = pending.filter(_._1 <= cycle)
          dut.io.response.valid #= reply.nonEmpty
          dut.io.response.data #= reply.map(_._2).getOrElse(BigInt(0))
          dut.io.response.error #= test.busError
          sleep(1)
          val req = if (dut.io.memory.valid.toBoolean) Some(Request(dut.io.memory.address.toBigInt,
            dut.io.memory.data.toBigInt, dut.io.memory.size.toInt, dut.io.memory.write.toBoolean)) else None
          held.foreach(x => assert(req.contains(x), s"memory request changed while stalled at $cycle"))
          held = if (!dut.io.memory.ready.toBoolean) req else None
          if (held.nonEmpty) stalls += 1
          if (reply.nonEmpty && dut.io.response.ready.toBoolean) pending = None
          if (req.nonEmpty && dut.io.memory.ready.toBoolean) {
            assert(pending.isEmpty, "more than one external transaction outstanding")
            val r = req.get
            // Check at acceptance, not only final memory: temporary or duplicate
            // wrong-path effects must not be hidden by later stores.
            val nextWord = if (reference.pc >= 0 && reference.pc / 4 < program.size)
              program((reference.pc / 4).toInt) else 0L
            val memOpcode = (nextWord & 127).toInt
            assert(memOpcode == 0x03 || memOpcode == 0x23, "memory issued ahead of architectural head")
            val isStore = memOpcode == 0x23
            val memF3 = ((nextWord >>> 12) & 7).toInt
            val baseReg = ((nextWord >>> 15) & 31).toInt
            val dataReg = ((nextWord >>> 20) & 31).toInt
            val offset = if (isStore) sx(BigInt(((nextWord >>> 25) << 5) | ((nextWord >>> 7) & 31)), 12)
              else sx(BigInt(nextWord >>> 20), 12)
            assert(r.address == u(reference.registers(baseReg) + offset) && r.write == isStore &&
              r.size == (memF3 & 3), "memory request does not match next architectural instruction")
            if (isStore) assert(r.data == reference.registers(dataReg), "store data mismatch at acceptance")
            memoryRequests += r
            val bytes = 1 << r.size
            val data = (0 until bytes).map(i => BigInt(memory.getOrElse(r.address + i, 0)) << (8 * i))
              .foldLeft(BigInt(0))(_ | _)
            if (r.write && !test.busError) {
              for (i <- 0 until bytes) memory(r.address + i) = ((r.data >> (8 * i)) & 255).toInt
              if (r.address == 0x18000) commandWrites += 1
            }
            pending = Some((cycle + 15 + rng.nextInt(8), data))
            trace += s"$cycle memory ${r.address} ${r.write} ${r.size} ${r.data}"
            val publishedData = if (r.write) r.data & ((BigInt(1) << (8 * bytes)) - 1)
              else if (test.busError) BigInt(0) else data
            architectural += s"""{"kind":"memory","address":"${r.address}","bytes":$bytes,"write":${r.write},"data":"$publishedData","error":${test.busError}}"""
          }
          if (dut.io.issued.valid.toBoolean) {
            issuedPcs += dut.io.issued.pc.toBigInt
            trace += s"$cycle issue ${issuedPcs.last}"
          }
          if (dut.io.predicted.valid.toBoolean) {
            trace += s"$cycle predict ${dut.io.predicted.pc.toBigInt} ${dut.io.predicted.next.toBigInt}"
          }
          if (dut.io.finished.valid.toBoolean) {
            finishedPcs += dut.io.finished.pc.toBigInt
            trace += s"$cycle finish ${finishedPcs.last}"
          }
          if (dut.io.retired.valid.toBoolean) {
            val expected = reference.step()
            assert(dut.io.retired.pc.toBigInt == expected.pc, s"retirement PC mismatch at $cycle: $expected")
            assert(dut.io.retired.instruction.toLong == expected.instruction, "instruction mismatch")
            assert(dut.io.retired.writes.toBoolean == expected.writes, s"destination enable mismatch: $expected")
            if (expected.writes) {
              assert(dut.io.retired.rd.toInt == expected.rd, "destination register mismatch")
              assert(dut.io.retired.value.toBigInt == expected.value,
                s"value mismatch at PC ${expected.pc}: RTL ${dut.io.retired.value.toBigInt}, expected $expected")
            }
            retiredPcs += expected.pc
            trace += s"$cycle retire ${expected.pc} ${expected.rd} ${expected.writes} ${expected.value}"
            val writes = dut.io.retired.writes.toBoolean
            val rd = if (writes) dut.io.retired.rd.toInt else 0
            val value = if (writes) dut.io.retired.value.toBigInt else BigInt(0)
            val pc = dut.io.retired.pc.toBigInt
            val next = if (dut.io.controlRetired.valid.toBoolean) dut.io.controlRetired.actualNext.toBigInt
              else (pc + 4) & ((BigInt(1) << 64) - 1)
            architectural += s"""{"kind":"retire","pc":"$pc","instruction":${dut.io.retired.instruction.toLong},"writes":$writes,"rd":$rd,"value":"$value","next":"$next"}"""
          }
          if (dut.io.redirect.valid.toBoolean) {
            redirects += 1
            trace += s"$cycle redirect ${dut.io.redirect.from.toBigInt} ${dut.io.redirect.to.toBigInt}"
          }
          if (dut.io.controlRetired.valid.toBoolean) {
            controls += 1
            val branchPc = dut.io.controlRetired.pc.toBigInt
            val predicted = dut.io.controlRetired.predictedNext.toBigInt
            val actual = dut.io.controlRetired.actualNext.toBigInt
            assert(actual == reference.pc, "control-flow result differs from ISA model")
            assert(dut.io.redirect.valid.toBoolean == (predicted != actual), "incorrect recovery decision")
            if (dut.io.controlRetired.conditional.toBoolean) {
              branches += 1
              if (predicted != actual) branchMisses += 1
              if (predicted != branchPc + 4) predictedTakenBranches += 1
              if (predicted != branchPc + 4 && actual == branchPc + 4) predictedTakenExit = true
            }
            trace += s"$cycle control $branchPc $predicted $actual"
          }
          if (dut.io.halt.valid.toBoolean) {
            val trap = try { reference.step(); sys.error("RTL trapped but sequential model did not") }
              catch { case t: Trap => t }
            assert(trap.cause == test.cause, s"unexpected model trap $trap")
            assert(dut.io.halt.cause.toInt == trap.cause && dut.io.halt.pc.toBigInt == trap.pc,
              s"precise trap mismatch: RTL ${dut.io.halt.cause.toInt}/${dut.io.halt.pc.toBigInt}, model $trap")
            assert(dut.io.halt.value.toBigInt == reference.registers(10), "architectural result lost at trap")
            test.expected.foreach(v => assert(dut.io.halt.value.toBigInt == v, s"known-answer mismatch: $v"))
            assert(memory == reference.memory, "memory differs from sequential execution")
            assert(pending.isEmpty && held.isEmpty, "halt published before external memory drained")
            architectural += s"""{"kind":"trap","pc":"${dut.io.halt.pc.toBigInt}","cause":${dut.io.halt.cause.toInt},"value":"${dut.io.halt.value.toBigInt}"}"""
            halted = true
          }
          edge()
          cycle += 1
        }
        writeFile(s"${test.name}-$invocation.trace", trace.mkString("\n") + "\n")
        writeFile(s"${test.name}-$invocation.arch.jsonl", architectural.mkString("\n") + "\n")
        writeFile(s"${test.name}-$invocation.case.json",
          s"""{"schema":1,"name":"${test.name}","image":"${test.image}","entry":"${test.entry}","writable":${test.writable},"bus_error":${test.busError},"invocation":$invocation}
""")
        assert(halted, s"timeout in ${test.name}")
        if (test.image == "p1") {
          assert(Seq(4, 8, 12).forall(p => issuedPcs.contains(BigInt(p)) && finishedPcs.contains(BigInt(p))),
            "missing events in out-of-order evidence")
          assert(issuedPcs.indexOf(BigInt(12)) < issuedPcs.indexOf(BigInt(8)), "no out-of-order issue observed")
          assert(finishedPcs.indexOf(BigInt(12)) < finishedPcs.indexOf(BigInt(4)), "no out-of-order completion observed")
        }
        if (test.image == "p2") {
          assert(issuedPcs.contains(BigInt(16)), "wrong-path arithmetic was never speculated")
          assert(!retiredPcs.contains(BigInt(16)), "wrong-path result retired")
          assert(!memoryRequests.exists(_.address >= 0x18000), "wrong-path MMIO escaped")
        }
        assert(commandWrites == (if (test.image == "p24") 1 else if (test.image == "p30") 2 else 0),
          "task-command side effect count")
        if (test.image == "p15") {
          assert(branches == 100)
          if (prediction) assert(predictedTakenBranches > 0 && branchMisses < 10 && predictedTakenExit,
            "predictor did not learn loop / recover on exit")
          else assert(branchMisses == 99 && predictedTakenBranches == 0)
        }
        if (test.image == "p29") assert(redirects == (if (prediction) 0 else 1), "JAL prediction missing")
        if (test.image == "p30" && prediction) assert(predictedTakenExit,
          "wrong-path command test did not exercise a predicted-taken exit")
        val stopPc = dut.io.halt.pc.toBigInt
        val stopValue = dut.io.halt.value.toBigInt
        for (_ <- 0 until 8) {
          dut.io.response.valid #= false
          assert(dut.io.halt.valid.toBoolean && !dut.io.launch.ready.toBoolean)
          assert(dut.io.halt.pc.toBigInt == stopPc && dut.io.halt.value.toBigInt == stopValue)
          assert(!dut.io.memory.valid.toBoolean && !dut.io.retired.valid.toBoolean)
          edge()
        }
        dut.io.halt.ready #= true; edge(); dut.io.halt.ready #= false
        reports += s"""{"name":"${test.name}","invocation":$invocation,"passed":true,"cycles":$cycle,"retired":${retiredPcs.size},"result":"$stopValue","memory_requests":${memoryRequests.size},"request_stall_cycles":$stalls,"command_writes":$commandWrites,"controls":$controls,"branches":$branches,"branch_misses":$branchMisses,"redirects":$redirects,"predicted_taken_branches":$predictedTakenBranches}"""
      }
    }
  }
  writeFile("validation.json", s"""{"status":"passed","rob_entries":$entries,"prediction":"$mode","claim":"Generated RTL compared at retirement with a local sequential RV64I model; not full ISA conformance or big-core performance","scenarios":${tests.size},"runs":${reports.size},"results":[${reports.mkString(",")}]}
""")
  println(s"APE PASS: ${tests.size} scenarios, ${reports.size} invocations, ROB=$entries, prediction=$mode")
}
