package hats

import spinal.core._
import spinal.core.sim._
import scala.collection.mutable
import scala.util.Random
import java.nio.file.{Files, Paths}
import java.nio.charset.StandardCharsets

/** The testbench supplies only initial code/input, memory responses and cancellation.
  * It never chooses a runnable context, creates a child or completes a join.
  */
object TaskTileSim extends App {
  val contextCount = args.headOption.map(_.toInt).getOrElse(4)
  val configuration = TileConfig(contexts = contextCount)
  case class Test(name: String, program: String, argument: BigInt = 0,
    expected: BigInt = 0, fault: Int = 0, base: BigInt = 0x10000,
    limit: BigInt = 0x200000, writable: Boolean = true, entry: BigInt = 0,
    cancelAt: Int = -1, cancelOnRequest: Boolean = false, busError: Boolean = false,
    spawns: Int = -1, joins: Int = -1, seed: Int = 1, reorder: Boolean = false,
    injectBadResponse: Boolean = false, cancelOnPresented: Boolean = false)
  case class Request(ctx: Int, address: BigInt, data: BigInt, write: Boolean, target: Int)
  case class Pending(req: Request, due: Int)
  case class Snapshot(launch: Boolean, request: Option[Request], response: Boolean,
    done: Boolean, result: BigInt, fault: Int)

  val tests = (0 until 12).map(i => Test(s"fork_join_$i", "fork_join", i,
    expected = 42 + i, spawns = 1, joins = 1, seed = 31 + i)) ++ Seq(
    Test("recursive_full", "recursive", contextCount - 1, expected = contextCount,
      spawns = contextCount - 1, joins = contextCount - 1),
    Test("resource_exhaustion", "recursive", contextCount, fault = Fault.Resources),
    Test("slot_reuse", "reuse", 40, expected = 42, spawns = 2, joins = 2),
    Test("arithmetic", "arithmetic", expected = 4095),
    Test("alignment", "load", 0x10001, fault = Fault.Alignment),
    Test("capability_low", "load", 0x10000, base = 0x10008, fault = Fault.Capability),
    Test("capability_cross_end", "load", 0x10000, limit = 0x10004, fault = Fault.Capability),
    Test("read_only", "store", 0x10000, writable = false, fault = Fault.Capability),
    Test("unmapped", "load", 0x90000, fault = Fault.Unmapped),
    Test("bus_error", "load", 0x10000, fault = Fault.Bus, busError = true),
    Test("bad_instruction", "bad_instruction", fault = Fault.Instruction),
    Test("bad_pc", "load", entry = 1024, fault = Fault.Pc),
    Test("unaligned_pc", "load", entry = 2, fault = Fault.Pc),
    Test("join_without_child", "join_without_child", fault = Fault.TaskProtocol),
    Test("unjoined_child", "unjoined_child", fault = Fault.TaskProtocol),
    Test("cancel_compute", "loop", fault = Fault.Cancelled, cancelAt = 30),
    Test("cancel_memory_drain", "load", 0x10000, fault = Fault.Cancelled, cancelOnRequest = true),
    Test("cancel_stalled_request", "load", 0x10000, fault = Fault.Cancelled, cancelOnPresented = true),
    Test("out_of_order", "multi_memory", expected = 20, spawns = 1, joins = 1, reorder = true),
    Test("bad_response", "loop", fault = Fault.MemoryProtocol, injectBadResponse = true)
  ) ++ (0 until 9).map { i =>
    val address = if (i == 8) 0x100000 else 0x10000 * (i + 1)
    val expected = if (i == 0) 7 else if (i == 1) 13 else if (i == 8) 35 else 100 + i
    Test(s"memory_target_$i", "load", address, expected = expected)
  }
  Files.createDirectories(Paths.get("build"))
  // An interrupted/failed run must not leave an old report looking current.
  Files.write(Paths.get(s"build/validation-c$contextCount.json"),
    "{\"status\":\"running\",\"claim\":\"SpinalSim RTL mechanism tests only\"}\n".getBytes(StandardCharsets.UTF_8))
  // SpinalSim 1.12.3 uses the former WData typedef. Verilator 5.052 names
  // the same uint32_t wide-vector element EData. This is a C++ bridge alias,
  // not an RTL transformation or a replacement simulation path.
  val compiled = SimConfig.withVerilator.withWave
    .addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(s"build/sim/c$contextCount").compile(new TaskTile(configuration))
  val reports = mutable.ArrayBuffer[String]()
  tests.foreach { test =>
    compiled.doSim(test.name, seed = test.seed) { dut =>
      val random = new Random(test.seed)
      val memory = mutable.Map[BigInt, BigInt](BigInt(0x10000) -> BigInt(7),
        BigInt(0x20000) -> BigInt(13), BigInt(0x100000) -> BigInt(35))
      (2 until 8).foreach(i => memory(BigInt(0x10000 * (i + 1))) = BigInt(100 + i))
      val pending = mutable.ArrayBuffer[Pending]()
      val requests = mutable.ArrayBuffer[Request]()
      var acceptedLaunches = 0
      var memoryReplies = 0
      var outOfOrderReplies = 0
      var stalled: Option[Request] = None
      dut.clockDomain.clockSim #= false
      dut.clockDomain.assertReset()
      dut.io.program.valid #= false
      dut.io.program.index #= 0
      dut.io.program.instruction #= 0
      dut.io.launch.valid #= false
      dut.io.launch.pc #= 0
      dut.io.launch.argument #= 0
      dut.io.launch.base #= 0
      dut.io.launch.limit #= 0
      dut.io.launch.writable #= false
      dut.io.cancel #= false
      dut.io.request.ready #= false
      dut.io.response.valid #= false
      dut.io.response.context #= 0
      dut.io.response.data #= 0
      dut.io.response.error #= false
      dut.io.completion.ready #= false

      def step(): Snapshot = {
        sleep(5)
        val request = if (dut.io.request.valid.toBoolean) Some(Request(
          dut.io.request.context.toInt, dut.io.request.address.toBigInt,
          dut.io.request.data.toBigInt, dut.io.request.write.toBoolean, dut.io.request.target.toInt)) else None
        stalled.foreach(old => assert(request.contains(old), "request changed under backpressure"))
        val accepted = if (dut.io.request.ready.toBoolean) request else None
        stalled = if (!dut.io.request.ready.toBoolean) request else None
        val snap = Snapshot(dut.io.launch.valid.toBoolean && dut.io.launch.ready.toBoolean,
          accepted, dut.io.response.valid.toBoolean && dut.io.response.ready.toBoolean,
          dut.io.completion.valid.toBoolean, dut.io.completion.result.toBigInt,
          dut.io.completion.fault.toInt)
        dut.clockDomain.risingEdge()
        sleep(5)
        dut.clockDomain.fallingEdge()
        sleep(1)
        snap
      }
      for (_ <- 0 until 4) step()
      dut.clockDomain.deassertReset()
      step()
      val src = scala.io.Source.fromFile(s"build/programs/${test.program}.hex")
      val program = try src.getLines().map(s => BigInt(s, 16)).toVector finally src.close()
      // Clear every word so out-of-image control flow traps deterministically.
      for (i <- 0 until 256) {
        dut.io.program.valid #= true
        dut.io.program.index #= i
        dut.io.program.instruction #= (if (i < program.size) program(i) else BigInt("ffffffff", 16))
        step()
      }
      dut.io.program.valid #= false
      dut.io.launch.valid #= true
      dut.io.launch.pc #= test.entry
      dut.io.launch.argument #= test.argument
      dut.io.launch.base #= test.base
      dut.io.launch.limit #= test.limit
      dut.io.launch.writable #= test.writable
      assert(step().launch)
      acceptedLaunches += 1
      dut.io.launch.valid #= false
      var completed: Option[Snapshot] = None
      var cycle = 0
      var cancellationSent = false
      while (completed.isEmpty && cycle < 4000) {
        dut.io.request.ready #= (if (test.cancelOnPresented) cycle >= 20 else random.nextInt(4) != 0)
        val due = pending.indices.filter(i => pending(i).due <= cycle)
        val responseIndex = if (due.nonEmpty) Some(due(random.nextInt(due.size))) else None
        val response = responseIndex.map(pending(_))
        dut.io.response.valid #= response.isDefined
        response.foreach { p =>
          dut.io.response.context #= p.req.ctx
          dut.io.response.data #= memory.getOrElse(p.req.address, BigInt(0))
          dut.io.response.error #= test.busError
        }
        if (test.injectBadResponse && cycle == 10) {
          dut.io.response.valid #= true
          dut.io.response.context #= contextCount - 1
          dut.io.response.data #= 0
          dut.io.response.error #= false
        }
        val cancel = !cancellationSent && ((test.cancelAt >= 0 && cycle >= test.cancelAt) ||
          (test.cancelOnRequest && requests.nonEmpty) ||
          (test.cancelOnPresented && dut.io.request.valid.toBoolean))
        dut.io.cancel #= cancel
        if (cancel) cancellationSent = true
        val snap = step()
        assert(!snap.launch, "host scheduling appeared after initial submission")
        if (snap.response && responseIndex.isDefined) {
          val index = responseIndex.get
          if (index != 0) outOfOrderReplies += 1
          pending.remove(index)
          memoryReplies += 1
        }
        snap.request.foreach { req =>
          val expectedTarget = if (req.address >= 0x100000 && req.address < 0x200000) 8
            else (req.address / 0x10000).toInt - 1
          assert(req.target == expectedTarget, s"bad target for $req")
          assert(req.address >= test.base && req.address + 8 <= test.limit)
          assert(!req.write || test.writable)
          assert(!pending.exists(_.req.ctx == req.ctx), "two outstanding requests from one context")
          requests += req
          if (req.write && !test.busError) memory(req.address) = req.data
          val latency = if (test.reorder && requests.size == 1) 100
            else if (test.cancelOnRequest) 40 else 2 + random.nextInt(18)
          pending += Pending(req, cycle + latency)
        }
        if (snap.done) completed = Some(snap)
        cycle += 1
      }
      assert(completed.isDefined, s"timeout: ${test.name}")
      val result = completed.get
      assert(result.fault == test.fault, s"${test.name}: fault ${result.fault}, expected ${test.fault}")
      if (test.fault == 0) assert(result.result == test.expected,
        s"${test.name}: result ${result.result}, expected ${test.expected}")
      assert(pending.isEmpty, "completion preceded memory drain")
      assert(acceptedLaunches == 1)
      if (test.spawns >= 0) assert(dut.io.spawned.toBigInt == test.spawns)
      if (test.joins >= 0) assert(dut.io.joinResumes.toBigInt == test.joins)
      if (test.program == "fork_join") {
        assert(memory(BigInt(0x50000)) == 35 + test.argument)
        assert(requests.map(_.ctx).distinct.size == 2)
      }
      if (test.reorder) assert(outOfOrderReplies > 0, "did not exercise response reordering")
      if (test.cancelOnRequest || test.cancelOnPresented) assert(requests.size == 1 && memoryReplies == 1)
      if (Set(Fault.Alignment, Fault.Capability, Fault.Unmapped).contains(test.fault))
        assert(requests.isEmpty, "invalid access escaped tile")
      dut.io.response.valid #= false
      dut.io.cancel #= false
      dut.io.request.ready #= true
      val issuedInstructions = dut.io.issuedInstructions.toBigInt
      val spawns = dut.io.spawned.toBigInt
      val joins = dut.io.joinResumes.toBigInt
      for (_ <- 0 until 8) {
        val held = step()
        assert(held.done && held.result == result.result && held.fault == result.fault,
          "completion not stable under backpressure")
      }
      dut.io.completion.ready #= true
      assert(step().done)
      assert(!dut.io.busy.toBoolean)
      // Restart without reset: no state or outstanding requests may leak.
      dut.io.completion.ready #= false
      dut.io.launch.pc #= test.entry
      dut.io.launch.valid #= true
      assert(step().launch, "tile did not accept restart")
      dut.io.launch.valid #= false
      dut.io.cancel #= true
      step()
      dut.io.cancel #= false
      assert(step().done, "restarted tile did not cancel cleanly")
      val report = s"""{"name":"${test.name}","passed":true,"seed":${test.seed},"cycles":$cycle,"instructions_issued":$issuedInstructions,"spawns":$spawns,"join_resumes":$joins,"memory_requests":${requests.size},"out_of_order_replies":$outOfOrderReplies,"host_submissions":1,"host_scheduling_after_submission":0,"fault":${result.fault}}"""
      reports += report
      println("HATS_RESULT " + report)
    }
  }
  val report = s"""{"status":"passed","contexts":$contextCount,"claim":"SpinalHDL generated RTL exercised by SpinalSim with Verilator; task-mechanism evidence, not agent performance or Arm conformance","tests":${tests.size},"results":[${reports.mkString(",")}]}
"""
  Files.write(Paths.get(s"build/validation-c$contextCount.json"), report.getBytes(StandardCharsets.UTF_8))
}
