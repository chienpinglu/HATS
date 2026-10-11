package hats

import spinal.core._
import spinal.core.sim._
import scala.collection.mutable
import scala.util.Random
import java.nio.file.{Files, Paths}

/** Executes the actual selected APE + LSQ + D-L1. The sequential byte/register
  * oracle observes retirement; it never assumes speculative reads are ordered.
  * A second memory image services real cache-line transfers and is compared
  * after maintenance. Fetch still uses program RAM, not an instruction cache.
  */
object ApeCachedDataSim extends App {
  import ApeReference._
  val root = Paths.get(args.headOption.getOrElse("build/s04/ape-data"))
  val programRoot = Paths.get(args.lift(1).getOrElse("."))
  val instructionCache = args.lift(2).contains("instructions")
  val deviceGuard = args.lift(2).contains("device-guard")
  val stressOnly = args.lift(3).contains("stress")
  require(args.lift(2).forall(Set("data", "instructions", "device-guard").contains))
  Files.createDirectories(root)
  Files.writeString(root.resolve("validation.json"), "{\"status\":\"running\"}\n")
  case class Test(name: String, program: Vector[Long], entry: BigInt = 0, writable: Boolean = true,
                  busError: Boolean = false, failedReadLines: Set[BigInt] = Set.empty)
  def image(name: String): Vector[Long] = {
    val source = scala.io.Source.fromFile(programRoot.resolve(s"build/ape/programs/$name.hex").toFile)
    try source.getLines().map(java.lang.Long.parseLong(_, 16)).toVector finally source.close()
  }
  def addi(rd: Int, rs: Int, imm: Int): Long = ((imm & 4095).toLong << 20) | (rs << 15) | (rd << 7) | 0x13
  def load(rd: Int, rs: Int, off: Int, size: Int = 3): Long = ((off & 4095).toLong << 20) | (rs << 15) | (size << 12) | (rd << 7) | 3
  def store(rs: Int, base: Int, off: Int, size: Int = 3): Long =
    (((off >> 5) & 127).toLong << 25) | (rs << 20) | (base << 15) | (size << 12) | ((off & 31) << 7) | 0x23
  val lui = 0x000100b7L // x1 = 0x10000
  val br = 0x00100073L
  val directed = Vector(
    Test("parallel_loads", Vector(lui) ++ (0 until 6).map(i => load(i+2, 1, i*32)) ++ Vector(addi(10, 7, 0), br)),
    Test("queue_full", Vector(lui) ++ (0 until 9).map(i => load(i+2, 1, i*32)) ++ Vector(br)),
    Test("forward_bytes", Vector(lui, addi(3, 1, 64), addi(4, 0, 85), store(4, 3, 0, 0),
      load(5, 3, 0, 2), load(6, 3, 0), addi(10, 6, 0), br)),
    Test("youngest_store_bytes", Vector(lui, load(2, 1, 0), addi(3, 0, 85), addi(4, 0, 0x345), store(3, 1, 96, 0),
      store(4, 1, 96, 1), load(10, 1, 96, 1), br)),
    Test("unknown_store_address", Vector(lui, load(2, 1, 0), addi(2, 2, -7), 0x00110133L,
      store(1, 2, 128), load(10, 1, 128), br)),
    Test("fence", Vector(lui, load(2, 1, 0), store(2, 1, 160), 0x0ff0000fL, load(10, 1, 160), br)),
    Test("wrong_path_read_drain", Vector(lui, load(2, 1, 0), 0x00011863L, load(3, 1, 32),
      load(4, 1, 64), store(1, 1, 256), addi(10, 0, 42), br), failedReadLines = Set(BigInt(0x10040))),
    Test("older_fault_after_younger_read", Vector(lui, load(2, 1, 0), load(3, 1, 32),
      store(1, 1, 256), addi(10, 0, 42), br), busError = true))
  val replayPressure = Test("replay_under_queue_pressure", Vector(lui, load(2, 1, 0), addi(2, 2, -7), 0x00110133L,
    store(1, 2, 128)) ++ (0 until 7).map(i => load(10 + i, 1, 128 + i * 32)) ++ Vector(br))
  val tests = if (stressOnly) Vector(replayPressure) else (0 until 32).map(i => Test(s"p$i", image(s"p$i"), writable = i != 12, busError = i == 13 || i == 21)) ++
    (0 until 8).map(i => Test(s"random$i", image(s"random$i"))) ++
    (0 until 8).map(i => Test(s"control$i", image(s"control$i"))) ++
    Seq(Test("entry_alignment", image("p0"), entry = 2), Test("entry_bounds", image("p0"), entry = 4096)) ++ directed
  val m = MemoryHierarchyConfig(sets = 8, lineBytes = 32, mshrs = 4, epochBits = 2)
  val coreConfiguration = if (stressOnly) ApeConfig(robEntries = 16, physicalRegisters = 48,
    memoryQueueEntries = 8, memoryHierarchy = Some(m)) else ApeConfig(physicalRegisters = 48)
  if (deviceGuard) {
    val deviceLoad = Vector(0x0001f0b7L, load(10, 1, 0), br)
    val compiledGuard = SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("device-guard-rtl").toString).compile(new ApeCachedDataTile(m, configuration = coreConfiguration,
        forbiddenRegions = Seq((BigInt(0x1f000), BigInt(0x20000)))))
    var rejected = false
    try {
      compiledGuard.doSim("device_region_must_not_enter_cache") { dut =>
        def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
        dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
        dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
        dut.io.launch.valid #= false; dut.io.launch.pc #= 0; dut.io.launch.argument #= 0
        dut.io.launch.base #= 0x1f000; dut.io.launch.limit #= 0x20000; dut.io.launch.writable #= false
        dut.io.halt.ready #= false; dut.io.lower.ready #= false; dut.io.reply.valid #= false
        dut.io.reply.slot #= 0; dut.io.reply.generation #= 0; dut.io.reply.write #= false
        dut.io.reply.data.foreach(_ #= 0); dut.io.reply.error #= false
        dut.io.flush.valid #= false; dut.io.flush.payload #= false; dut.io.flushed.ready #= true
        for (_ <- 0 until 4) edge(); dut.clockDomain.deassertReset(); edge()
        for ((word, index) <- deviceLoad.zipWithIndex) {
          dut.io.program.valid #= true; dut.io.program.index #= index; dut.io.program.instruction #= word; edge()
        }
        dut.io.program.valid #= false; dut.io.launch.valid #= true; edge(); dut.io.launch.valid #= false
        var cycles = 0
        while (cycles < 2000) { edge(); cycles += 1 }
      }
    } catch { case _: Throwable => rejected = true }
    require(rejected, "device-region negative control did not trip the RTL assertion")
    ApeSimArtifactCleanup.discardVerilatorBuildTree(root.resolve("device-guard-rtl"), "ApeCachedDataTile")
    Files.writeString(root.resolve("device-region-negative-control.json"),
      "{\"status\":\"passed\",\"claim_class\":\"forbidden_aperture_rejected_by_RTL_assertion\",\"S04_complete\":false}\n")
    println("Device-region negative control passed: forbidden aperture reached no valid completion")
  }
  val compiled = SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("rtl").toString).compile(new ApeCachedDataTile(m, configuration = coreConfiguration,
      instructionCache = instructionCache,
      forbiddenRegions = if (deviceGuard) Seq((BigInt(0x1f000), BigInt(0x20000))) else Seq.empty))
  val reports = mutable.ArrayBuffer[String]()
  tests.zipWithIndex.foreach { case (test, index) =>
    Files.writeString(root.resolve(test.name + ".hex"), test.program.map(w => f"$w%08x\n").mkString)
    Files.writeString(root.resolve(test.name + ".case.json"),
      s"""{"name":"${test.name}","entry":"${test.entry}","writable":${test.writable},"bus_error":${test.busError}}\n""")
    compiled.doSim(test.name, seed = index+400) { dut =>
      val rng = new Random(index+400)
      val reference = new Machine(test.program, initialMemory(), entry = test.entry, writable = test.writable, busError = test.busError)
      val external = initialMemory()
      case class Lower(source: Int, slot: Int, generation: Int, address: BigInt, write: Boolean, data: Vector[BigInt])
      case class Pending(request: Lower, due: Int)
      val pending = mutable.ArrayBuffer[Pending]()
      val architectural = mutable.ArrayBuffer[String]()
      var held: Option[Lower] = None
      var cycle, retired, reads, writes, lowerReorders, maxOutstanding, maxCacheOutstanding, lowerStalls, wordCount = 0
      var instructionReads, maxFabricOutstanding = 0
      var halted, flushing, flushed = false
      var heldHalt: Option[(BigInt, BigInt, Int)] = None
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
      dut.io.launch.valid #= false; dut.io.launch.pc #= test.entry; dut.io.launch.argument #= 0
      dut.io.launch.base #= 0x10000; dut.io.launch.limit #= 0x20000; dut.io.launch.writable #= test.writable
      dut.io.halt.ready #= false
      dut.io.lower.ready #= false; dut.io.reply.valid #= false; dut.io.reply.slot #= 0
      dut.io.reply.generation #= 0; dut.io.reply.write #= false; dut.io.reply.data.foreach(_ #= 0); dut.io.reply.error #= false
      if (instructionCache) dut.io.replySource #= 0
      dut.io.flush.valid #= false; dut.io.flush.payload #= true; dut.io.flushed.ready #= true
      for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      for (i <- 0 until 1024) {
        dut.io.program.valid #= true; dut.io.program.index #= i
        // Poison the obsolete programming port in I-cache mode: it must not be
        // an alternative instruction source or bypass the actual line service.
        dut.io.program.instruction #= (if (instructionCache) 0L else test.program.lift(i).getOrElse(0L)); sleep(1); edge()
      }
      dut.io.program.valid #= false; dut.io.launch.valid #= true; sleep(1)
      assert(dut.io.launch.ready.toBoolean); edge(); dut.io.launch.valid #= false
      while (!flushed && cycle < 100000) {
        dut.io.lower.ready #= (rng.nextInt(5) != 0)
        val due = pending.indices.filter(i => pending(i).due <= cycle).lastOption
        dut.io.reply.valid #= due.nonEmpty
        due.foreach { i =>
          val r = pending(i).request
          dut.io.reply.slot #= r.slot; dut.io.reply.generation #= r.generation; dut.io.reply.write #= r.write
          if (instructionCache) dut.io.replySource #= r.source
          dut.io.reply.error #= (r.source == 1 && (test.busError || (!r.write && test.failedReadLines(r.address))))
          for (w <- 0 until m.words) {
            val data = if (r.source == 0) {
              val index = (r.address / 4).toInt + w*2
              BigInt(test.program.lift(index).getOrElse(0L)) | (BigInt(test.program.lift(index+1).getOrElse(0L)) << 32)
            } else (0 until 8).foldLeft(BigInt(0))((v, b) => v | (BigInt(external.getOrElse(r.address+w*8+b, 0)) << (b*8)))
            dut.io.reply.data(w) #= data
          }
        }
        dut.io.flush.valid #= (halted && !flushing)
        dut.io.halt.ready #= heldHalt.nonEmpty
        sleep(1)
        maxOutstanding = maxOutstanding.max(dut.io.outstanding.toInt)
        maxCacheOutstanding = maxCacheOutstanding.max(dut.io.cacheOutstanding.toInt)
        maxFabricOutstanding = maxFabricOutstanding.max(dut.io.fabricOutstanding.toInt)
        // All external comparison values below come from public RTL observation
        // ports. Nothing from the sequential reference is copied into this trace.
        if (dut.io.memoryRetired.valid.toBoolean) {
          val bytes = 1 << dut.io.memoryRetired.size.toInt
          val data = dut.io.memoryRetired.data.toBigInt & ((BigInt(1) << (bytes*8))-1)
          architectural += s"""{"kind":"memory","address":"${dut.io.memoryRetired.address.toBigInt}","bytes":$bytes,"write":${dut.io.memoryRetired.write.toBoolean},"data":"$data","error":${dut.io.memoryRetired.error.toBoolean}}"""
        }
        if (dut.io.retired.valid.toBoolean) {
          val write = dut.io.retired.writes.toBoolean
          val rd = if (write) dut.io.retired.rd.toInt else 0
          val value = if (write) dut.io.retired.value.toBigInt else BigInt(0)
          architectural += s"""{"kind":"retire","pc":"${dut.io.retired.pc.toBigInt}","instruction":${dut.io.retired.instruction.toLong},"writes":$write,"rd":$rd,"value":"$value","next":"${dut.io.retiredNext.toBigInt}"}"""
          val expected = reference.step()
          assert(dut.io.retired.pc.toBigInt == expected.pc && dut.io.retired.instruction.toLong == expected.instruction,
            s"${test.name} retirement PC/instruction mismatch at $cycle")
          if (test.name == "fence" && expected.instruction == 0x0ff0000fL) {
            assert((0 until 8).forall(b => external.getOrElse(BigInt(0x100a0 + b), 0) == reference.memory.getOrElse(BigInt(0x100a0 + b), 0)),
              "APE FENCE retired before its dirty D-L1 line became visible below the cache")
          }
          assert(dut.io.retired.writes.toBoolean == expected.writes)
          if (expected.writes) assert(dut.io.retired.rd.toInt == expected.rd && dut.io.retired.value.toBigInt == expected.value,
            s"${test.name} register mismatch PC=${expected.pc} x${expected.rd}: ${dut.io.retired.value.toBigInt} != ${expected.value}; replay=${dut.io.memoryReplays.toBigInt}, speculative=${dut.io.speculativeLoads.toBigInt}, outstanding=${dut.io.outstanding.toBigInt}, hits=${dut.io.hits.toBigInt}, misses=${dut.io.misses.toBigInt}")
          retired += 1
        }
        // Check irreversible authorization at actual cache acceptance. Loads are
        // allowed to precede reference PC; every store must be the current head.
        if (dut.io.wordAccepted.valid.toBoolean) wordCount += 1
        if (dut.io.wordAccepted.valid.toBoolean && dut.io.wordAccepted.write.toBoolean) {
          val ins = test.program((reference.pc / 4).toInt)
          assert((ins & 127) == 0x23, s"store escaped architectural head at PC ${reference.pc}")
          val offset = sx(BigInt(((ins >>> 25) << 5) | ((ins >>> 7) & 31)), 12)
          val address = u(reference.registers(((ins >>> 15) & 31).toInt) + offset)
          val bytes = 1 << ((ins >>> 12).toInt & 3)
          val shift = (address & 7).toInt
          val data = reference.registers(((ins >>> 20) & 31).toInt) << (shift*8)
          assert(dut.io.wordAccepted.address.toBigInt == (address & ~BigInt(7)))
          assert(dut.io.wordAccepted.mask.toInt == ((1 << bytes)-1) << shift)
          for (b <- shift until shift+bytes) assert(((dut.io.wordAccepted.data.toBigInt >> (b*8)) & 255) == ((data >> (b*8)) & 255))
        }
        if (dut.io.halt.valid.toBoolean) {
          val actual = (dut.io.halt.pc.toBigInt, dut.io.halt.value.toBigInt, dut.io.halt.cause.toInt)
          heldHalt match {
            case Some(previous) => assert(actual == previous); halted = true
            case None =>
              architectural += s"""{"kind":"trap","pc":"${actual._1}","cause":${actual._3},"value":"${actual._2}"}"""
              val trap = try { reference.step(); throw new AssertionError("unexpected RTL halt") } catch { case t: Trap => t }
              assert(actual == ((trap.pc, reference.registers(10), trap.cause)), s"halt mismatch $actual vs $trap")
              assert(pending.isEmpty && dut.io.outstanding.toInt == 0, "halt exposed before speculative reads drained")
              heldHalt = Some(actual)
          }
        }
        if (dut.io.flush.valid.toBoolean && dut.io.flush.ready.toBoolean) flushing = true
        if (dut.io.flushed.valid.toBoolean) {
          assert(!dut.io.flushed.payload.toBoolean && dut.io.clean.toBoolean)
          assert((external.keySet ++ reference.memory.keySet).forall(a => external.getOrElse(a, 0) == reference.memory.getOrElse(a, 0)),
            s"${test.name} final backing bytes differ after clean")
          flushed = true
        }
        if (due.nonEmpty && dut.io.reply.ready.toBoolean) {
          val i = due.get; val r = pending.remove(i).request
          if (i != 0) lowerReorders += 1
          if (r.write && !test.busError) for (w <- 0 until m.words; b <- 0 until 8)
            external(r.address+w*8+b) = ((r.data(w) >> (b*8)) & 255).toInt
        }
        val request = if (dut.io.lower.valid.toBoolean) Some(Lower(if (instructionCache) dut.io.lowerSource.toInt else 1, dut.io.lower.slot.toInt,
          dut.io.lower.generation.toInt, dut.io.lower.address.toBigInt, dut.io.lower.write.toBoolean,
          dut.io.lower.data.map(_.toBigInt).toVector)) else None
        held.foreach(r => assert(request.contains(r), "cache lower request changed under backpressure"))
        held = request.filter(_ => !dut.io.lower.ready.toBoolean)
        if (held.nonEmpty) lowerStalls += 1
        if (request.nonEmpty && dut.io.lower.ready.toBoolean) {
          val r = request.get
          if (r.source == 0) assert(!r.write && r.address + m.lineBytes <= 4096, "instruction read escaped code region")
          else assert(r.address >= 0x10000 && r.address + m.lineBytes <= 0x20000, "line read escaped owned RAM")
          assert(!pending.exists(p => p.request.slot == r.slot && p.request.source == r.source), "duplicate live lower identity")
          val delay = if (r.source == 0) 3 + rng.nextInt(4)
            else if (test.name == "replay_under_queue_pressure") {
              val lane = ((r.address / m.lineBytes) % 4).toInt
              250 + ((3 - lane + 4) % 4) * 40
            }
            else if (test.name == "queue_full" ||
              (test.name == "wrong_path_read_drain" && r.address != 0x10000)) 250
            else if (r.address == 0x10000) 100 else 8 + rng.nextInt(16)
          pending += Pending(r, cycle + delay)
          if (r.source == 0) instructionReads += 1 else if (r.write) writes += 1 else reads += 1
        }
        edge(); cycle += 1
      }
      assert(flushed && pending.isEmpty && dut.io.idle.toBoolean,
        s"${test.name} timed out or did not drain: flushed=$flushed pending=${pending.size} idle=${dut.io.idle.toBoolean} outstanding=${dut.io.outstanding.toBigInt} leases=${dut.io.memoryLeasedRows.toBigInt} rob=${dut.io.robOccupancy.toBigInt} head=${dut.io.memoryHead.toBigInt} replayPending=${dut.io.memoryReplayPending.toBoolean} replayStore=${dut.io.memoryReplayStoreSlot.toBigInt} storeRetired=${dut.io.memoryReplayStoreRetired.toBoolean} busy=${dut.io.coreBusy.toBoolean} cache=${dut.io.cacheOutstanding.toBigInt} halt=${dut.io.halt.valid.toBoolean} discarded=${dut.io.discarded.toBigInt}")
      val counts = Map("allocated" -> dut.io.allocated.toBigInt, "forwarded" -> dut.io.forwarded.toBigInt,
        "partial_forwarded" -> dut.io.partialForwarded.toBigInt, "unknown_store_stalls" -> dut.io.unknownStoreStalls.toBigInt,
        "speculative_loads" -> dut.io.speculativeLoads.toBigInt, "memory_replays" -> dut.io.memoryReplays.toBigInt,
        "fence_stalls" -> dut.io.fenceStalls.toBigInt, "discarded" -> dut.io.discarded.toBigInt,
        "hits" -> dut.io.hits.toBigInt, "misses" -> dut.io.misses.toBigInt,
        "refills" -> dut.io.refills.toBigInt, "writebacks" -> dut.io.writebacks.toBigInt)
      assert(counts("refills") == reads && counts("writebacks") == writes)
      assert(dut.io.instructionMisses.toBigInt == instructionReads)
      if (instructionCache && test.entry == 0) assert(instructionReads > 0 && dut.io.fetchRequests.toBigInt > 0)
      assert(counts("hits") + counts("misses") == wordCount && counts("allocated") == wordCount + counts("forwarded"),
        "accepted LSU operations differ from actual cache traffic and local forwarding")
      test.name match {
        case "parallel_loads" => assert(maxOutstanding >= 6 && maxCacheOutstanding == 4 && lowerReorders > 0)
        case "queue_full" => assert(maxOutstanding == 8 && maxCacheOutstanding == 4 && counts("allocated") == 9)
        case "forward_bytes" => assert(counts("partial_forwarded") > 0,
          s"byte forwarding witness disappeared: $counts")
        case "youngest_store_bytes" => assert(counts("forwarded") > 0 && reference.registers(10) == 0x345)
        case "unknown_store_address" => assert(counts("speculative_loads") > 0 && counts("memory_replays") > 0,
          s"unknown-store overlap did not speculatively execute and replay: $counts")
        case "replay_under_queue_pressure" =>
          assert(maxOutstanding == 8 && maxCacheOutstanding == 4 && counts("memory_replays") > 0 &&
            counts("speculative_loads") > 0 && lowerReorders > 0 && counts("refills") >= 4,
            s"combined LSQ/MSHR/conflict/replay stress did not reach all witnesses: maxLSQ=$maxOutstanding " +
              s"maxMSHR=$maxCacheOutstanding reorders=$lowerReorders counters=$counts")
        case "fence" => assert(counts("fence_stalls") > 0)
        case "wrong_path_read_drain" => assert(counts("discarded") >= 2 && writes == 0 && retired == 4)
        case "older_fault_after_younger_read" => assert(writes == 0 && retired == 1 && maxOutstanding >= 2)
        case _ =>
      }
      val counters = counts.toSeq.sortBy(_._1).map { case (k, v) => s"\"$k\":$v" }.mkString(",")
      Files.writeString(root.resolve(test.name + ".arch.jsonl"), architectural.mkString("\n") + "\n")
      reports += s"""{"name":"${test.name}","cycles":$cycle,"retired":$retired,"word_requests":$wordCount,"instruction_reads":$instructionReads,"instruction_hits":${dut.io.instructionHits.toBigInt},"fetch_requests":${dut.io.fetchRequests.toBigInt},"max_fabric_outstanding":$maxFabricOutstanding,"max_outstanding":$maxOutstanding,"max_cache_outstanding":$maxCacheOutstanding,"lower_reorders":$lowerReorders,"lower_stalls":$lowerStalls,"counters":{$counters}}"""
    }
  }
  ApeSimArtifactCleanup.discardVerilatorBuildTree(root.resolve("rtl"), "ApeCachedDataTile")
  val claim = if (instructionCache) "actual_APE_LSQ_instruction_data_L1_fabric_RTL" else "actual_APE_LSQ_data_L1_RTL"
  val fetchLimit = if (instructionCache) "One outstanding frontend fetch word; no claim of wide fetch bandwidth" else "Instruction fetch still uses program RAM"
  val profile = s"ROB${coreConfiguration.robEntries}/P${coreConfiguration.physicalRegisters}/W${coreConfiguration.issueWidth}/C${coreConfiguration.branchCheckpoints}/D${coreConfiguration.executionStages}/G${coreConfiguration.generationBits}"
  Files.writeString(root.resolve("validation.json"), s"""{"status":"passed","issue":5,"S04_complete":false,"claim_class":"$claim","profile":"$profile","tests":[${reports.mkString(",")}],"limits":["$fetchLimit","No PPE/ownership-controller/device/atomic integration yet","Dependence replay stress is bounded to the emitted program and behavioral line service","Independent local ISA oracle; external Spike comparison is a separate driver gate","Modeled external line service, not measured DRAM timing"]}\n""")
  println(s"APE LSQ/D-L1: ${tests.size} actual RTL executions passed; S04 remains open")
}
