package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths, Path}
import java.io.PrintWriter
import scala.collection.mutable
import scala.util.Random

/** Actual PPE + coalescer + banked scratch + D-L1. The host services only
  * physical lines; it neither decodes instructions nor manufactures lane state.
  * Python compares public observations against the independent ISA model.
  */
object PpeCachedDataSim extends App {
  require(args.length >= 1 && args.length <= 4, "fresh PPE case directory [instructions] [sets] [mshrs]")
  val instructionCache = args.lift(1).contains("instructions")
  val sets = args.lift(2).map(_.toInt).getOrElse(16)
  val mshrs = args.lift(3).map(_.toInt).getOrElse(4)
  val instructionBase = 0x100000
  val root = Paths.get(args(0)).toAbsolutePath
  def lines(path: Path): Vector[String] = {
    val f = scala.io.Source.fromFile(path.toFile); try f.getLines().toVector finally f.close()
  }
  def save(path: Path, text: String): Unit = Files.writeString(path, text + "\n")
  val names = lines(root.resolve("cases.txt"))
  val m = MemoryHierarchyConfig(sets = sets, mshrs = mshrs, wordPoison = true)
  val summaries = mutable.ArrayBuffer[String]()
  SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("cached-sim").toString).compile(new PpeCachedDataTile(m, instructionCache))
    .doSim("ppe_cached_suite", seed = 0x5304) { dut =>
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      dut.clockDomain.clockSim #= false
      dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
      dut.io.launch.valid #= false
      dut.io.launch.task #= 0; dut.io.launch.epoch #= 0; dut.io.launch.argument #= 0; dut.io.launch.argumentBytes #= 0
      dut.io.launch.addressSpace #= 0; dut.io.launch.generation #= 0; dut.io.launch.group #= 0; dut.io.launch.groups #= 0
      dut.io.launch.budget #= 0; dut.io.launch.base #= 0; dut.io.launch.limit #= 0
      dut.io.launch.writable #= false; dut.io.launch.codeWords #= 0; dut.io.launch.scratchBytes #= 0
      dut.io.completion.ready #= false; dut.io.inspectScratch #= 0
      dut.io.deviceRequest.ready #= false; dut.io.deviceResponse.valid #= false
      dut.io.deviceResponse.id #= 0; dut.io.deviceResponse.epoch #= 0
      dut.io.deviceResponse.data #= 0; dut.io.deviceResponse.error #= false
      dut.io.lower.ready #= false; dut.io.reply.valid #= false; dut.io.reply.slot #= 0
      dut.io.reply.generation #= 0; dut.io.reply.write #= false; dut.io.reply.error #= false
      dut.io.reply.poison #= 0; dut.io.reply.data.foreach(_ #= 0)
      if (instructionCache) dut.io.replySource #= 0
      dut.io.flush.valid #= false; dut.io.flush.payload #= true; dut.io.flushed.ready #= false
      dut.clockDomain.assertReset(); for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      def scalar = (0 until 32).map(r => "\"" + dut.io.scalar(r).toBigInt + "\"").mkString("[", ",", "]")
      def vector = (0 until 32).map(r => (0 until 8).map(n => "\"" + dut.io.vector(r)(n).toBigInt + "\"").mkString("[", ",", "]")).mkString("[", ",", "]")
      def predicates = (0 until 8).map(r => dut.io.predicate(r).toInt).mkString("[", ",", "]")
      def architecture = s""""scalar":$scalar,"vector":$vector,"predicate":$predicates,"active":${dut.io.activeMask.toInt},"depth":${dut.io.depth.toInt}"""
      case class Lower(source: Int, slot: Int, generation: Int, address: Int, write: Boolean, data: Vector[BigInt], poison: Int)
      case class Pending(request: Lower, due: Int, sequence: Int)
      def counters = Vector(dut.io.words.toBigInt, dut.io.lanes.toBigInt, dut.io.scratchParallel.toBigInt,
        dut.io.hits.toBigInt, dut.io.misses.toBigInt, dut.io.refills.toBigInt, dut.io.writebacks.toBigInt,
        dut.io.instructionHits.toBigInt, dut.io.instructionMisses.toBigInt, dut.io.fetchRequests.toBigInt,
        dut.io.fabricAccepted.toBigInt, dut.io.fabricCompleted.toBigInt, dut.io.fabricRejected.toBigInt)
      names.zipWithIndex.foreach { case (name, caseIndex) =>
        val folder = root.resolve(name)
        val prop = lines(folder.resolve("case.properties")).map { line =>
          val p = line.split("=", 2); p(0) -> BigInt(p(1))
        }.toMap
        require(prop("kind") <= 4)
        val program = lines(folder.resolve("code.hex")).map(BigInt(_, 16))
        val codeMemory = Array.fill[Byte](8192)(0)
        for (w <- program.indices; b <- 0 until 8) codeMemory(w*8+b) = ((program(w) >> (8*b)) & 255).toByte
        for (index <- program.indices) {
          dut.io.program.valid #= true; dut.io.program.index #= index
          dut.io.program.instruction #= (if (instructionCache) BigInt(0) else program(index))
          sleep(1); assert(dut.io.program.ready.toBoolean); edge()
        }
        dut.io.program.valid #= false
        for (invocation <- 0 until 2) {
          val input = Files.readAllBytes(folder.resolve("memory.bin"))
          // Byte objects may occupy a fraction of the explicitly owned line.
          val memory = Array.fill[Byte](((input.length + m.lineBytes-1) / m.lineBytes)*m.lineBytes)(0)
          Array.copy(input, 0, memory, 0, input.length)
          val initial = counters
          val output = folder.resolve(s"rtl-$invocation"); Files.createDirectories(output)
          val trace = new PrintWriter(output.resolve("trace.jsonl").toFile)
          val accesses = new PrintWriter(output.resolve("access.jsonl").toFile)
          val rng = new Random(caseIndex * 3 + invocation + 41)
          val pending = mutable.ArrayBuffer[Pending]()
          var held: Option[Lower] = None
          var cycles, retired, accepted, completed, words, reorders, stalls, stale, maxPending, maxWords, maxMshrs = 0
          var instructionReads, maxFabric = 0
          val expectedBacking = mutable.Map[Int, Byte]()
          var done = false
          var releaseReplies = prop("kind") != 4
          val epoch = prop("epoch") + invocation
          dut.io.launch.task #= prop("task"); dut.io.launch.epoch #= epoch
          dut.io.launch.argument #= prop("argument"); dut.io.launch.argumentBytes #= prop("argumentBytes")
          dut.io.launch.addressSpace #= prop("addressSpace"); dut.io.launch.generation #= prop("generation")
          dut.io.launch.group #= prop("group"); dut.io.launch.groups #= prop("groups")
          dut.io.launch.budget #= prop("budget"); dut.io.launch.base #= prop("base"); dut.io.launch.limit #= prop("limit")
          dut.io.launch.writable #= (prop("writable") != 0)
          dut.io.launch.codeWords #= prop("codeWords"); dut.io.launch.scratchBytes #= prop("scratchBytes")
          dut.io.launch.valid #= true; sleep(1); assert(dut.io.launch.ready.toBoolean)
          edge(); dut.io.launch.valid #= false
          def tick(observe: Boolean = true): Unit = {
            val offeringCode = instructionCache && dut.io.lowerSource.toInt == 0
            dut.io.lower.ready #= ((offeringCode || cycles >= prop("readyAfter")) && cycles % 7 >= 2 && rng.nextInt(4) != 0)
            val due = pending.indices.filter(i => pending(i).due <= cycles &&
              (releaseReplies || (instructionCache && pending(i).request.source == 0))).lastOption
            val corrupt = due.nonEmpty && cycles % 11 == 0
            dut.io.reply.valid #= due.nonEmpty
            due.foreach { i =>
              val r = pending(i).request
              if (instructionCache) dut.io.replySource #= r.source
              dut.io.reply.slot #= r.slot; dut.io.reply.generation #= ((r.generation + (if (corrupt) 1 else 0)) & 255)
              dut.io.reply.write #= r.write; dut.io.reply.error #= false
              val code = instructionCache && r.source == 0
              val backing = if (code) codeMemory else memory
              val offset = r.address - (if (code) instructionBase else 0)
              val fail = if (code) BigInt(-1) else prop("fail")
              val poison = if (fail >= r.address && fail < r.address + m.lineBytes) 1 << ((fail.toInt-r.address)/8) else 0
              dut.io.reply.poison #= poison
              for (w <- 0 until m.words) dut.io.reply.data(w) #= (0 until 8).foldLeft(BigInt(0))((v,b) =>
                v | (BigInt(backing(offset+w*8+b) & 255) << (8*b)))
            }
            sleep(1)
            val bus = if (dut.io.lower.valid.toBoolean) Some(Lower(if (instructionCache) dut.io.lowerSource.toInt else 1, dut.io.lower.slot.toInt,
              dut.io.lower.generation.toInt, dut.io.lower.address.toBigInt.toInt, dut.io.lower.write.toBoolean,
              dut.io.lower.data.map(_.toBigInt).toVector, dut.io.lower.poison.toInt)) else None
            held.foreach(r => assert(bus.contains(r), "held cache-line request changed"))
            held = if (!dut.io.lower.ready.toBoolean) bus else None
            if (held.nonEmpty) stalls += 1
            due.foreach { i =>
              assert(dut.io.reply.ready.toBoolean)
              if (corrupt) stale += 1
              else {
                val p = pending.remove(i); if (i > 0) reorders += 1
                if (p.request.write) for (w <- 0 until m.words; b <- 0 until 8)
                  memory(p.request.address+w*8+b) = ((p.request.data(w) >> (8*b)) & 255).toByte
                completed += 1
              }
            }
            bus.filter(_ => dut.io.lower.ready.toBoolean).foreach { r =>
              val code = instructionCache && r.source == 0
              val offset = r.address - (if (code) instructionBase else 0)
              assert(offset >= 0 && offset + m.lineBytes <= (if (code) codeMemory.length else memory.length) && r.address % m.lineBytes == 0)
              assert(!pending.exists(p => p.request.source == r.source && p.request.slot == r.slot), "overlapping cache-line lease")
              if (code) { assert(!r.write); instructionReads += 1 }
              // Word poison must survive healthy writes/eviction in its line.
              if (r.write) {
                val f = prop("fail")
                val expected = if (f >= r.address && f < r.address + m.lineBytes) 1 << ((f.toInt-r.address)/8) else 0
                assert(r.poison == expected, "writeback lost word poison")
              }
              // The two-line strided D-L1 case is the bounded explicit
              // response-reordering witness, including the 2-MSHR endpoint:
              // hold its first data line, then return the younger line first.
              val reorderProbe = instructionCache && name == "s04_stride_s0_5" && r.source == 1
              val earlierProbe = pending.exists(p => p.request.source == 1 && name == "s04_stride_s0_5")
              val delay = if (reorderProbe) { if (earlierProbe) 2 else 80 }
                else if (code) 2 else if (prop("delay") > 0) prop("delay").toInt else 12 + rng.nextInt(45)
              pending += Pending(r, cycles + delay, accepted); accepted += 1
            }
            if (dut.io.wordAccepted.valid.toBoolean) {
              assert(observe && dut.io.busy.toBoolean, "word request outside owned invocation")
              val a = dut.io.wordAccepted.address.toBigInt
              assert(a >= 0 && a + 8 <= memory.length && a % 8 == 0)
              if (dut.io.wordAccepted.write.toBoolean) {
                assert(prop("writable") != 0)
                val mask = dut.io.wordAccepted.mask.toInt
                for (b <- 0 until 8 if (mask & (1 << b)) != 0)
                  assert(a+b >= prop("base") && a+b < prop("limit"), "store byte escaped object permission")
                for (b <- 0 until 8 if (mask & (1 << b)) != 0)
                  expectedBacking((a+b).toInt) = ((dut.io.wordAccepted.data.toBigInt >> (8*b)) & 255).toByte
              }
              words += 1
            }
            maxPending = maxPending.max(pending.size)
            maxWords = maxWords.max(dut.io.outstanding.toInt); maxMshrs = maxMshrs.max(dut.io.cacheOutstanding.toInt)
            maxFabric = maxFabric.max(dut.io.fabricOutstanding.toInt)
            if (observe && dut.io.access.valid.toBoolean) {
              val error = dut.io.access.error.toInt
              val value = if (error == 0) s""", "value":${dut.io.access.data.toBigInt}""" else ""
              accesses.println(s"""{"retirement_index":$retired,"scratch":${dut.io.access.scratch.toBoolean},"address":${dut.io.access.address.toBigInt},"size":${1 << dut.io.access.size.toInt},"store":${dut.io.access.write.toBoolean},"lane":${dut.io.access.lane.toInt},"error":$error$value}""")
            }
            if (observe && dut.io.retired.valid.toBoolean) {
              assert(pending.isEmpty && held.isEmpty && dut.io.outstanding.toInt == 0, "retired before drain")
              val retiredOp = (dut.io.retired.instruction.toBigInt & 255).toInt
              if (retiredOp == 35 || retiredOp == 36) {
                assert(expectedBacking.forall { case (address, value) => memory(address) == value },
                  "PPE FENCE/BARRIER retired before dirty D-L1 bytes became visible below the cache")
              }
              trace.println(s"""{"pc":${dut.io.retired.pc.toBigInt},"next_pc":${dut.io.retired.nextPc.toBigInt},"mask":${dut.io.retired.mask.toInt},"instruction":"${dut.io.retired.instruction.toBigInt}",$architecture}""")
              retired += 1
            }
            if (observe && prop("kind") == 4 && cycles >= prop("budget").toInt+640) {
              assert(!dut.io.completion.valid.toBoolean && dut.io.waiting.toBoolean && dut.io.busy.toBoolean)
              assert(pending.size == 1 && accepted - instructionReads == 1 && words == 1 && retired == 0,
                "unresponsive timed-out group was discarded or reused")
              done = true
            } else if (observe && dut.io.completion.valid.toBoolean) done = true
            edge(); cycles += 1; assert(cycles < 300000, s"cached PPE deadlock $name/$invocation")
          }
          try {
            while (!done) tick()
            if (prop("kind") != 4)
              assert(pending.isEmpty && held.isEmpty && dut.io.outstanding.toInt == 0, "completion before drain")
            val completion = if (prop("kind") == 4) "{\"status\":\"quiescence_required\"}"
            else if (dut.io.completion.status.toInt == 1)
              s"""{"status":"success","value":"${dut.io.completion.value.toBigInt}","pc":${dut.io.completion.pc.toBigInt}}"""
            else s"""{"status":"${if (dut.io.completion.status.toInt == 4) "rejected" else "fault"}","cause":${dut.io.completion.cause.toInt},"pc":${dut.io.completion.pc.toBigInt},"address":${dut.io.completion.address.toBigInt},"lane_mask":${dut.io.completion.laneMask.toInt}}"""
            save(output.resolve("completion.json"), completion); save(output.resolve("state.json"), "{" + architecture + "}")
            val scratch = new Array[Byte](4096)
            for (index <- 0 until 512) {
              dut.io.inspectScratch #= index; sleep(1); val value = dut.io.scratchData.toBigInt
              for (b <- 0 until 8) scratch(index*8+b) = ((value >> (8*b)) & 255).toByte
            }
            Files.write(output.resolve("scratch.bin"), scratch)
            if (prop("kind") == 4) {
              // The missing service eventually recovers; drain it rather than
              // resetting/discarding an accepted transaction to get a pass.
              val beforeDrain = architecture
              releaseReplies = true
              while (!dut.io.completion.valid.toBoolean) tick(false)
              assert(dut.io.completion.status.toInt == 2 && dut.io.completion.cause.toInt == 5)
              assert(architecture == beforeDrain && pending.isEmpty && dut.io.outstanding.toInt == 0)
            }
            if (prop("kind") >= 3) assert(words == 1 && accepted - instructionReads == 1 && completed == accepted,
              "timeout admitted a second group or failed to drain the first")
            for (_ <- 0 until 8) { tick(false); assert(dut.io.completion.valid.toBoolean && !dut.io.lower.valid.toBoolean) }
            dut.io.completion.ready #= true; tick(false); dut.io.completion.ready #= false
            var sent, flushed = false
            while (!flushed) {
              dut.io.flush.valid #= !sent; dut.io.flushed.ready #= (cycles % 5 == 0)
              sleep(1)
              val take = dut.io.flush.valid.toBoolean && dut.io.flush.ready.toBoolean
              val ack = dut.io.flushed.valid.toBoolean && dut.io.flushed.ready.toBoolean
              if (ack) assert(!dut.io.flushed.payload.toBoolean)
              tick(false); sent ||= take; flushed ||= ack
            }
            dut.io.flush.valid #= false; dut.io.flushed.ready #= false
            assert(dut.io.clean.toBoolean && dut.io.idle.toBoolean && accepted == completed && pending.isEmpty)
            assert(memory.drop(input.length).forall(_ == 0), "store altered owned padding outside the object")
            Files.write(output.resolve("memory.bin"), memory.take(input.length))
            val delta = counters.zip(initial).map { case(a,b) => a-b }
            assert(delta(3)+delta(4) == words, "cache counters differ from accepted word traffic")
            if (instructionCache) {
              assert(delta(10) == accepted && delta(11) == completed && delta(12) == stale, "fabric counter mismatch")
              assert(delta(7)+delta(8) == delta(9) && delta(8) == instructionReads, "fetch/I-cache counter mismatch")
              assert((prop("kind") == 2) == (instructionReads == 0), "instruction path absent or invalid launch fetched")
            }
            summaries += s"""{"case":"$name","invocation":$invocation,"cycles":$cycles,"retired":$retired,"global_words":$words,"all_words":${delta(0)},"lanes":${delta(1)},"scratch_parallel":${delta(2)},"hits":${delta(3)},"misses":${delta(4)},"refills":${delta(5)},"writebacks":${delta(6)},"accepted_lines":$accepted,"completed_lines":$completed,"max_lines":$maxPending,"max_words":$maxWords,"max_mshrs":$maxMshrs,"reorders":$reorders,"stale":$stale,"stalls":$stalls,"timeout_protocol":${prop("kind") >= 3},"late_service_drain":${prop("kind") == 4},"instruction_reads":$instructionReads,"instruction_hits":${delta(7)},"instruction_misses":${delta(8)},"fetch_requests":${delta(9)},"fabric_accepted":${delta(10)},"fabric_completed":${delta(11)},"fabric_rejected":${delta(12)},"max_fabric":$maxFabric}"""
          } finally { trace.close(); accesses.close() }
      }
      println(s"Cached PPE executed $name twice")
      }
    }
  ApeSimArtifactCleanup.discardVerilatorBuildTree(root.resolve("cached-sim"), "PpeCachedDataTile")
  save(root.resolve("cached-validation.json"), s"""{"status":"executed","instruction_cache":$instructionCache,"runs":[${summaries.mkString(",")}]}""")
}
