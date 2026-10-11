package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import scala.collection.mutable
import scala.util.Random

/** Runs one real application image through APE+LSQ+D-L1 and compares its
  * architectural trace and post-clean backing memory with the direct APE run.
  * The lower line service is behavioral and is not a DRAM/controller model.
  */
object CachedApplicationSim extends App {
  val root = Paths.get(args.headOption.getOrElse("build/ape_app"))
  val out = Paths.get(args.lift(1).getOrElse("build/s04/cached-application"))
  val sets = args.lift(2).map(_.toInt).getOrElse(8)
  val mshrs = args.lift(3).map(_.toInt).getOrElse(4)
  val instructionCache = args.lift(4).contains("icache")
  val application = args.lift(5).getOrElse("repo_source_edit")
  val invocation = args.lift(6).map(_.toInt).getOrElse(0)
  val caseStem = s"$application-$invocation"
  Files.createDirectories(out)
  val program = Files.readAllLines(root.resolve("code.hex")).toArray.toVector.map(x => java.lang.Long.parseLong(x.toString, 16))
  val initial = Files.readAllBytes(root.resolve(s"$application.bin"))
  val expectedMemory = Files.readAllBytes(root.resolve(s"r8-bimodal/$caseStem.memory.bin"))
  val expectedTrace = Files.readAllLines(root.resolve(s"r8-bimodal/$caseStem.arch.jsonl"))
  val exitPc = Files.readAllLines(root.resolve("runtime.properties")).toArray.toVector
    .map(_.toString.split("=", 2)).map(a => a(0) -> a(1).toLong).toMap.apply("exit_pc")
  require(program.size == 1024 && initial.length == 65536 && expectedMemory.length == initial.length)
  val codeMemory = Array.fill[Byte](4096)(0)
  program.zipWithIndex.foreach { case (word, i) =>
    for (b <- 0 until 4) codeMemory(i * 4 + b) = ((word >> (8 * b)) & 255).toByte
  }
  val m = MemoryHierarchyConfig(sets = sets, lineBytes = 32, mshrs = mshrs, epochBits = 2)
  val compiled = SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(out.resolve("rtl").toString).compile(new ApeCachedDataTile(m, instructionCache = instructionCache))
  compiled.doSim(caseStem) { dut =>
    def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
    case class Request(source: Int, slot: Int, generation: Int, address: BigInt, write: Boolean, data: Vector[BigInt])
    case class Pending(request: Request, due: Int)
    val memory = mutable.Map.empty[BigInt, Int]
    initial.indices.foreach(i => memory(BigInt(0x10000 + i)) = initial(i) & 255)
    val pending = mutable.ArrayBuffer.empty[Pending]
    val architectural = mutable.ArrayBuffer.empty[String]
    val rng = new Random(805)
    var cycle = 0
    var held: Option[Request] = None
    var halted = false
    var flushing = false
    var flushed = false
    var accepted = 0
    var completed = 0
    var reorders = 0
    var maxOutstanding = 0
    var maxFabricOutstanding = 0
    dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
    dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
    dut.io.launch.valid #= false; dut.io.launch.pc #= 0; dut.io.launch.argument #= 0x16000
    dut.io.launch.base #= 0x10000; dut.io.launch.limit #= 0x20000; dut.io.launch.writable #= true
    dut.io.halt.ready #= false; dut.io.lower.ready #= false
    dut.io.reply.valid #= false; dut.io.reply.slot #= 0; dut.io.reply.generation #= 0
    dut.io.reply.write #= false; dut.io.reply.data.foreach(_ #= 0); dut.io.reply.error #= false
    if (instructionCache) dut.io.replySource #= 0
    dut.io.flush.valid #= false; dut.io.flush.payload #= false; dut.io.flushed.ready #= true
    dut.io.deviceResponse.valid #= false; dut.io.deviceResponse.id #= 0; dut.io.deviceResponse.epoch #= 0
    dut.io.deviceResponse.data #= 0; dut.io.deviceResponse.error #= false
    for (_ <- 0 until 4) edge()
    dut.clockDomain.deassertReset(); edge()
    for (i <- program.indices) {
      dut.io.program.valid #= true; dut.io.program.index #= i
      dut.io.program.instruction #= (if (instructionCache) 0L else program(i)); edge()
    }
    dut.io.program.valid #= false; dut.io.launch.valid #= true
    sleep(1); assert(dut.io.launch.ready.toBoolean); edge(); dut.io.launch.valid #= false
    while (!flushed && cycle < 1000000) {
      dut.io.lower.ready #= rng.nextInt(5) != 0
      val due = pending.indices.filter(i => pending(i).due <= cycle).lastOption
      dut.io.reply.valid #= due.nonEmpty
      due.foreach { idx =>
        val r = pending(idx).request
        dut.io.reply.slot #= r.slot; dut.io.reply.generation #= r.generation; dut.io.reply.write #= r.write
        if (instructionCache) dut.io.replySource #= r.source
        for (word <- 0 until m.words) {
          val data = (0 until 8).foldLeft(BigInt(0))((v, b) => {
            val address = r.address + word * 8 + b
            val byte = if (r.source == 0) {
              if (address >= 0 && address < codeMemory.length) codeMemory(address.toInt) & 255 else 0
            } else memory.getOrElse(address, 0)
            v | (BigInt(byte) << (b * 8))
          })
          dut.io.reply.data(word) #= data
        }
        dut.io.reply.error #= false
      }
      dut.io.flush.valid #= halted && !flushing
      dut.io.halt.ready #= halted
      sleep(1)
      maxOutstanding = maxOutstanding.max(dut.io.cacheOutstanding.toInt)
      if (instructionCache) maxFabricOutstanding = maxFabricOutstanding.max(dut.io.fabricOutstanding.toInt)
      if (dut.io.memoryRetired.valid.toBoolean) {
        val bytes = 1 << dut.io.memoryRetired.size.toInt
        val data = dut.io.memoryRetired.data.toBigInt & ((BigInt(1) << (bytes * 8)) - 1)
        architectural += s"""{"kind":"memory","address":"${dut.io.memoryRetired.address.toBigInt}","bytes":$bytes,"write":${dut.io.memoryRetired.write.toBoolean},"data":"$data","error":${dut.io.memoryRetired.error.toBoolean}}"""
      }
      if (dut.io.retired.valid.toBoolean) {
        val w = dut.io.retired.writes.toBoolean
        val rd = if (w) dut.io.retired.rd.toInt else 0
        val value = if (w) dut.io.retired.value.toBigInt else BigInt(0)
        val pc = dut.io.retired.pc.toBigInt
        val next = dut.io.retiredNext.toBigInt
        architectural += s"""{"kind":"retire","pc":"$pc","instruction":${dut.io.retired.instruction.toLong},"writes":$w,"rd":$rd,"value":"$value","next":"$next"}"""
      }
      if (dut.io.halt.valid.toBoolean) {
        assert(dut.io.halt.cause.toInt == 3 && dut.io.halt.pc.toBigInt == exitPc)
        assert(pending.isEmpty && dut.io.outstanding.toInt == 0, "application halted with pending memory work")
        halted = true
        architectural += s"""{"kind":"trap","pc":"${dut.io.halt.pc.toBigInt}","cause":3,"value":"${dut.io.halt.value.toBigInt}"}"""
      }
      if (dut.io.flush.valid.toBoolean && dut.io.flush.ready.toBoolean) flushing = true
      if (dut.io.flushed.valid.toBoolean) {
        assert(!dut.io.flushed.payload.toBoolean && dut.io.clean.toBoolean)
        val actual = Array.tabulate(initial.length)(i => memory.getOrElse(BigInt(0x10000 + i), 0).toByte)
        assert(actual.sameElements(expectedMemory), "cleaned D-L1 backing memory differs from direct APE application")
        flushed = true
      }
      if (due.nonEmpty && dut.io.reply.ready.toBoolean) {
        val idx = due.get; val r = pending.remove(idx).request
        if (idx != 0) reorders += 1
        if (r.write) for (word <- 0 until m.words; b <- 0 until 8)
          memory(r.address + word * 8 + b) = ((r.data(word) >> (b * 8)) & 255).toInt
        completed += 1
      }
      val req = if (dut.io.lower.valid.toBoolean) Some(Request(
        if (instructionCache) dut.io.lowerSource.toInt else 1, dut.io.lower.slot.toInt, dut.io.lower.generation.toInt,
        dut.io.lower.address.toBigInt, dut.io.lower.write.toBoolean, dut.io.lower.data.map(_.toBigInt).toVector)) else None
      held.foreach(previous => assert(req.contains(previous), "line request changed during backpressure"))
      held = if (!dut.io.lower.ready.toBoolean) req else None
      if (req.nonEmpty && dut.io.lower.ready.toBoolean) {
        val r = req.get
        val source = r.source
        if (source == 0) assert(!r.write && r.address >= 0 && r.address + m.lineBytes <= codeMemory.length,
          "instruction line request escaped the executable region")
        else assert(r.address >= 0x10000 && r.address + m.lineBytes <= 0x20000,
          "data line request escaped application memory")
        assert(!pending.exists(p => p.request.slot == r.slot && p.request.source == source), "duplicate outstanding line identity")
        val sourced = r.copy(source = source)
        pending += Pending(sourced, cycle + 7 + rng.nextInt(9)); accepted += 1
      }
      edge(); cycle += 1
    }
    assert(flushed && pending.isEmpty && dut.io.idle.toBoolean, "cached application failed to halt, clean, or drain")
    val expectedRows = expectedTrace.toArray.toVector.map(_.toString)
    val actualRows = architectural.toVector
    val expectedRetire = expectedRows.filter(_.contains("\"kind\":\"retire\""))
    val actualRetire = actualRows.filter(_.contains("\"kind\":\"retire\""))
    val expectedMemoryEvents = expectedRows.filter(_.contains("\"kind\":\"memory\""))
    val actualMemory = actualRows.filter(_.contains("\"kind\":\"memory\""))
    assert(actualRetire == expectedRetire, "cached APE retirement sequence differs from direct APE; " +
      s"actual=${actualRetire.size} expected=${expectedRetire.size} first=" +
      actualRetire.zip(expectedRetire).indexWhere { case (a, e) => a != e })
    assert(actualMemory.size == expectedMemoryEvents.size && actualMemory.sorted == expectedMemoryEvents.sorted,
      s"cached APE architectural memory events differ from direct APE: ${actualMemory.size} vs ${expectedMemoryEvents.size}")
    assert(actualRows.last == expectedRows.last, "application trap differs from direct APE")
    assert(accepted == completed && accepted > 0)
    Files.write(out.resolve(s"$caseStem.memory.bin"), Array.tabulate(initial.length)(i => memory.getOrElse(BigInt(0x10000 + i), 0).toByte))
    Files.writeString(out.resolve(s"$caseStem.arch.jsonl"), architectural.mkString("\n") + "\n")
    Files.writeString(out.resolve("validation.json"),
      s"""{"status":"passed","S04_complete":false,"claim_class":"actual_application_on_APE_LSQ_${if (instructionCache) "I_D_L1_FABRIC" else "D_L1"}_RTL","application":"$application","invocation":$invocation,"mode":"${if (instructionCache) "I_D_L1" else "D_L1"}","sets":$sets,"mshrs":$mshrs,"cycles":$cycle,"line_requests":$accepted,"line_completions":$completed,"max_cache_outstanding":$maxOutstanding,"max_fabric_outstanding":$maxFabricOutstanding,"response_reorders":$reorders,"cache_hits":${dut.io.hits.toBigInt},"cache_misses":${dut.io.misses.toBigInt},"cache_refills":${dut.io.refills.toBigInt},"cache_writebacks":${dut.io.writebacks.toBigInt},"architectural_trace_matches_direct_APE":true,"final_memory_matches_direct_APE":true,"instruction_cache_hits":${if (instructionCache) dut.io.instructionHits.toBigInt else BigInt(0)},"instruction_cache_misses":${if (instructionCache) dut.io.instructionMisses.toBigInt else BigInt(0)},"fetch_requests":${if (instructionCache) dut.io.fetchRequests.toBigInt else BigInt(0)},"lower_service":"behavioral fixed-delay line service with randomized ready and response ordering","limits":["no PPE/ownership integration","not calibrated DRAM timing"]}\n""")
  }
  ApeSimArtifactCleanup.discardVerilatorBuildTree(out.resolve("rtl"), "ApeCachedDataTile")
  println(s"Cached APE application PASS application=$application-$invocation mode=${if (instructionCache) "I/D-L1" else "D-L1"} sets=$sets mshrs=$mshrs; direct architectural trace and final memory match")
}
