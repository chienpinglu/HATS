package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths, Path}
import java.nio.charset.StandardCharsets
import java.io.PrintWriter
import scala.collection.mutable
import scala.util.Random

/** Transports original binary fixtures to actual RTL. No ISA/model is executed
  * here; Python checks independently generated state and memory traces later.
  */
object PpeCoreSim extends App {
  require(args.length == 1, "PPE case directory")
  val root = Paths.get(args(0)).toAbsolutePath
  def lines(path: Path): Vector[String] = {
    val src = scala.io.Source.fromFile(path.toFile)
    try src.getLines().toVector finally src.close()
  }
  def save(path: Path, value: String): Unit = Files.write(path, value.getBytes(StandardCharsets.UTF_8))
  val names = lines(root.resolve("cases.txt"))
  require(names.nonEmpty && names.distinct.size == names.size && names.forall(_.matches("[a-z0-9_]+")))
  val compiled = SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("sim").toString).compile(new PpeCore())
  val summaries = mutable.ArrayBuffer[String]()
  compiled.doSim("ppe_suite", seed = 0x4841) { dut =>
    def edge(): Unit = {
      dut.clockDomain.risingEdge(); sleep(5)
      dut.clockDomain.fallingEdge(); sleep(5)
    }
    dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
    dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
    dut.io.launch.valid #= false
    dut.io.launch.task #= 0; dut.io.launch.epoch #= 0; dut.io.launch.argument #= 0; dut.io.launch.argumentBytes #= 0
    dut.io.launch.addressSpace #= 0; dut.io.launch.generation #= 0; dut.io.launch.group #= 0; dut.io.launch.groups #= 0
    dut.io.launch.budget #= 0; dut.io.launch.base #= 0; dut.io.launch.limit #= 0
    dut.io.launch.writable #= false; dut.io.launch.codeWords #= 0; dut.io.launch.scratchBytes #= 0
    dut.io.memory.ready #= false; dut.io.response.valid #= false; dut.io.response.data #= 0; dut.io.response.error #= false
    dut.io.response.task #= 0; dut.io.response.epoch #= 0; dut.io.response.addressSpace #= 0
    dut.io.response.generation #= 0; dut.io.response.transaction #= 0
    dut.io.completion.ready #= false; dut.io.inspectScratch #= 0
    for (_ <- 0 until 4) edge()
    dut.clockDomain.deassertReset(); edge()
    def scalar = (0 until 32).map(r => "\"" + dut.io.scalar(r).toBigInt + "\"").mkString("[", ",", "]")
    def vector = (0 until 32).map(r => (0 until 8).map(n => "\"" + dut.io.vector(r)(n).toBigInt + "\"").mkString("[", ",", "]")).mkString("[", ",", "]")
    def predicates = (0 until 8).map(r => dut.io.predicate(r).toInt).mkString("[", ",", "]")
    def architecture = s""""scalar":$scalar,"vector":$vector,"predicate":$predicates,"active":${dut.io.activeMask.toInt},"depth":${dut.io.depth.toInt}"""
    case class Request(task: BigInt, epoch: BigInt, space: BigInt, generation: BigInt, id: BigInt,
                       address: BigInt, data: BigInt, size: Int, write: Boolean, lane: Int, mask: Int)
    case class Reply(due: Int, request: Request, value: BigInt, error: Boolean, stale: Int)
    def currentRequest = Request(dut.io.memory.task.toBigInt, dut.io.memory.epoch.toBigInt,
      dut.io.memory.addressSpace.toBigInt, dut.io.memory.generation.toBigInt, dut.io.memory.transaction.toBigInt,
      dut.io.memory.address.toBigInt, dut.io.memory.data.toBigInt, dut.io.memory.size.toInt,
      dut.io.memory.write.toBoolean, dut.io.memory.lane.toInt, dut.io.memory.laneMask.toInt)
    names.zipWithIndex.foreach { case (name, caseIndex) =>
      val folder = root.resolve(name)
      val prop = lines(folder.resolve("case.properties")).map { line =>
        val parts = line.split("=", 2); parts(0) -> BigInt(parts(1))
      }.toMap
      val program = lines(folder.resolve("code.hex")).map(BigInt(_, 16))
      dut.io.launch.valid #= false
      for (index <- program.indices) {
        dut.io.program.valid #= true; dut.io.program.index #= index; dut.io.program.instruction #= program(index)
        sleep(1); assert(dut.io.program.ready.toBoolean); edge()
      }
      dut.io.program.valid #= false
      for (invocation <- 0 until 2) {
        val memory = Files.readAllBytes(folder.resolve("memory.bin"))
        val epoch = prop("epoch") + invocation
        val output = folder.resolve(s"rtl-$invocation"); Files.createDirectories(output)
        val trace = new PrintWriter(output.resolve("trace.jsonl").toFile)
        val accesses = new PrintWriter(output.resolve("access.jsonl").toFile)
        val rng = new Random(caseIndex * 3 + invocation + 7)
        var pending: Option[Reply] = None
        var held: Option[Request] = None
        var cycles, retired, requests, stalls, staleReplies = 0
        var done = false
        dut.io.launch.task #= prop("task"); dut.io.launch.epoch #= epoch
        dut.io.launch.argument #= prop("argument"); dut.io.launch.argumentBytes #= prop("argumentBytes")
        dut.io.launch.addressSpace #= prop("addressSpace"); dut.io.launch.generation #= prop("generation")
        dut.io.launch.group #= prop("group"); dut.io.launch.groups #= prop("groups")
        dut.io.launch.budget #= prop("budget"); dut.io.launch.base #= prop("base"); dut.io.launch.limit #= prop("limit")
        dut.io.launch.writable #= (prop("writable") != 0)
        dut.io.launch.codeWords #= prop("codeWords"); dut.io.launch.scratchBytes #= prop("scratchBytes")
        dut.io.launch.valid #= true; sleep(1); assert(dut.io.launch.ready.toBoolean)
        edge(); dut.io.launch.valid #= false
        try {
          while (!done && cycles < 200000) {
            dut.io.memory.ready #= (cycles >= prop("readyAfter") && cycles % 5 >= 2 && rng.nextInt(4) != 0)
            val reply = pending.filter(r => r.due <= cycles && prop("kind") != 4)
            dut.io.response.valid #= reply.nonEmpty
            reply.foreach { response =>
              val r = response.request
              dut.io.response.task #= (r.task + (if (response.stale == 1) 1 else 0))
              dut.io.response.epoch #= (r.epoch + (if (response.stale == 2) 1 else 0))
              dut.io.response.addressSpace #= (r.space + (if (response.stale == 3) 1 else 0))
              dut.io.response.generation #= (r.generation + (if (response.stale == 4) 1 else 0))
              dut.io.response.transaction #= (r.id + (if (response.stale == 5) 1 else 0))
              dut.io.response.data #= response.value; dut.io.response.error #= response.error
            }
            // Offer the second launch while occupied; hold until it can start.
            if (invocation == 0 && cycles == 20) { dut.io.launch.epoch #= (epoch + 1); dut.io.launch.valid #= true }
            // An occupied core must also reject program writes.
            dut.io.program.valid #= true; dut.io.program.index #= 0; dut.io.program.instruction #= 0
            sleep(1)
            assert(!dut.io.launch.ready.toBoolean && !dut.io.program.ready.toBoolean, "occupied resource accepted new work")
            val request = if (dut.io.memory.valid.toBoolean) Some(currentRequest) else None
            held.foreach(previous => assert(request.contains(previous), "held request changed"))
            held = if (!dut.io.memory.ready.toBoolean) request else None
            if (held.nonEmpty) stalls += 1
            if (request.nonEmpty && dut.io.memory.ready.toBoolean) {
              assert(pending.isEmpty, "more than one outstanding transaction")
              val r = request.get; val size = 1 << r.size
              assert(r.task == prop("task") && r.epoch == epoch && r.space == prop("addressSpace") && r.generation == prop("generation"))
              assert(r.id == requests && r.address >= prop("base") && r.address + size <= prop("limit") && r.address % size == 0)
              assert(!r.write || prop("writable") != 0)
              assert(r.mask == 0 || r.mask == (1 << r.lane))
              val offset = (r.address - prop("base")).toInt
              val value = if (r.write) r.data else (0 until size).map(i => BigInt(memory(offset+i) & 255) << (8*i)).foldLeft(BigInt(0))(_ | _)
              val delay = if (prop("delay") > 0) prop("delay").toInt else 2 + rng.nextInt(9)
              pending = Some(Reply(cycles + delay, r, value, r.address == prop("fail"), if (prop("stale") != 0) 1 else 0))
              requests += 1
            }
            if (reply.nonEmpty && dut.io.response.ready.toBoolean) {
              val response = reply.get
              if (response.stale != 0) {
                staleReplies += 1
                pending = Some(response.copy(due = cycles + 2, stale = if (response.stale == 5) 0 else response.stale + 1))
                assert(!dut.io.access.valid.toBoolean && !dut.io.completion.valid.toBoolean, "stale response published an effect")
              } else {
                if (response.request.write && !response.error) {
                  val offset = (response.request.address - prop("base")).toInt
                  for (i <- 0 until (1 << response.request.size)) memory(offset+i) = ((response.value >> (i*8)) & 255).toByte
                }
                pending = None
              }
            }
            if (dut.io.access.valid.toBoolean) {
              val error = dut.io.access.error.toInt
              val value = if (error == 0) s""", "value":${dut.io.access.data.toBigInt}""" else ""
              accesses.println(s"""{"retirement_index":$retired,"scratch":${dut.io.access.scratch.toBoolean},"address":${dut.io.access.address.toBigInt},"size":${1 << dut.io.access.size.toInt},"store":${dut.io.access.write.toBoolean},"lane":${dut.io.access.lane.toInt},"error":$error$value}""")
            }
            if (dut.io.retired.valid.toBoolean) {
              assert(pending.isEmpty && held.isEmpty, "retirement/fence/barrier before memory drain")
              trace.println(s"""{"pc":${dut.io.retired.pc.toBigInt},"next_pc":${dut.io.retired.nextPc.toBigInt},"mask":${dut.io.retired.mask.toInt},"instruction":"${dut.io.retired.instruction.toBigInt}",$architecture}""")
              retired += 1
            }
            if (prop("kind") == 4 && cycles >= 800) {
              assert(!dut.io.completion.valid.toBoolean && dut.io.waiting.toBoolean && dut.io.busy.toBoolean)
              assert(pending.nonEmpty && requests == 1 && retired == 0, "timed-out unresponsive service was reused")
              done = true
            } else if (dut.io.completion.valid.toBoolean) {
              assert(pending.isEmpty && held.isEmpty, "completion before drain")
              assert(dut.io.completion.task.toBigInt == prop("task") && dut.io.completion.epoch.toBigInt == epoch)
              done = true
            } else edge()
            cycles += 1
          }
          assert(done, s"PPE timed out: $name/$invocation")
          def completion = {
            val pc = dut.io.completion.pc.toBigInt
            val status = if (dut.io.completion.status.toInt == 4) "rejected" else "fault"
            if (prop("kind") == 4) "{\"status\":\"quiescence_required\"}"
            else if (dut.io.completion.status.toInt == 1) s"""{"status":"success","value":"${dut.io.completion.value.toBigInt}","pc":$pc}"""
            else s"""{"status":"$status","cause":${dut.io.completion.cause.toInt},"pc":$pc,"address":${dut.io.completion.address.toBigInt},"lane_mask":${dut.io.completion.laneMask.toInt}}"""
          }
          val completed = completion
          save(output.resolve("completion.json"), completed + "\n")
          save(output.resolve("state.json"), "{" + architecture + "}\n")
          Files.write(output.resolve("memory.bin"), memory)
          val scratch = new Array[Byte](4096)
          for (index <- 0 until 512) {
            dut.io.inspectScratch #= index; sleep(1)
            val value = dut.io.scratchData.toBigInt
            for (i <- 0 until 8) scratch(index*8+i) = ((value >> (i*8)) & 255).toByte
          }
          Files.write(output.resolve("scratch.bin"), scratch)
          dut.io.response.valid #= false
          for (_ <- 0 until 8) {
            edge(); assert(dut.io.completion.valid.toBoolean == (prop("kind") != 4) && completion == completed)
            assert(!dut.io.memory.valid.toBoolean)
          }
          dut.io.program.valid #= false
          if (prop("kind") == 4) {
            // Testbench explicitly quiesces the fabric, then resets. The core
            // never invents a safe completion or discards a live transaction.
            pending = None; dut.io.launch.valid #= false; dut.clockDomain.assertReset()
            for (_ <- 0 until 4) edge()
            dut.clockDomain.deassertReset(); edge()
          } else { dut.io.completion.ready #= true; edge(); dut.io.completion.ready #= false }
          assert(!dut.io.busy.toBoolean && !dut.io.completion.valid.toBoolean)
          summaries += s"""{"case":"$name","invocation":$invocation,"cycles":$cycles,"retired":$retired,"requests":$requests,"stalls":$stalls,"stale_replies":$staleReplies}"""
        } finally { trace.close(); accesses.close() }
      }
      println(s"PPE executed $name twice")
    }
  }
  save(root.resolve("rtl-validation.json"), s"""{"status":"executed","runs":[${summaries.mkString(",")}]}\n""")
}
