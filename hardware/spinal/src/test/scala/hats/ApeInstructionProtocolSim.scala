package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import scala.collection.mutable

/** Real core -> I/D L1 -> shared fabric. Known-answer publication/fault tests
  * complement (not replace) the separate external Spike instruction matrix.
  * The independent backing byte image is changed only by explicit host edits
  * while quiescent or successful actual RTL writeback transactions.
  */
object ApeInstructionProtocolSim extends App {
  val root = Paths.get(args.headOption.getOrElse("build/s04/instruction-protocol"))
  Files.createDirectories(root)
  Files.writeString(root.resolve("validation.json"), "{\"status\":\"running\"}\n")
  val m = MemoryHierarchyConfig(sets = 8, lineBytes = 32, mshrs = 4, epochBits = 2)
  def addi(rd: Int, rs: Int, imm: Int): Long = ((imm & 4095).toLong << 20) | (rs << 15) | (rd << 7) | 0x13
  def branch(a: Int, b: Int, delta: Int): Long = (((delta >> 12) & 1).toLong << 31) |
    (((delta >> 5) & 63).toLong << 25) | (b << 20) | (a << 15) | (1 << 12) |
    (((delta >> 1) & 15) << 8) | (((delta >> 11) & 1) << 7) | 0x63
  val breakpoint = 0x00100073L
  SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData").workspacePath(root.resolve("rtl").toString)
    .compile(new ApeCachedDataTile(m, instructionCache = true)).doSim("publication_faults", seed = 0x50404) { dut =>
      val memory = Array.fill[Byte](0x20000)(0)
      def read(a: Int, n: Int): BigInt = (0 until n).foldLeft(BigInt(0))((v, b) => v | (BigInt(memory(a+b)&255) << (b*8)))
      def write(a: Int, n: Int, value: BigInt): Unit = for (b <- 0 until n) memory(a+b) = ((value >> (b*8)) & 255).toByte
      def program(pc: Int, words: Long*): Unit = words.zipWithIndex.foreach { case (w, i) => write(pc+i*4, 4, BigInt(w)) }
      program(0, addi(10, 0, 42), breakpoint)
      program(256, addi(10, 0, 11), breakpoint)
      // The actual APE writes a new instruction to address 256 through D-L1.
      val newInstruction = addi(10, 0, 77)
      program(64, addi(1, 0, 256), (newInstruction & 0xfffff000L) | (2 << 7) | 0x37,
        addi(2, 2, (newInstruction & 4095).toInt), 0x0020a023L, breakpoint)
      program(512, 0x000100b7L, 0x0000b103L, addi(0,0,0), addi(0,0,0), addi(0,0,0), addi(0,0,0),
        addi(0,0,0), branch(2, 0, 36))
      program(544, addi(10,0,-1), breakpoint)
      program(576, addi(10,0,99), breakpoint)
      program(1024, addi(10,0,123), breakpoint)
      write(0x10000, 8, 1)
      case class Request(source: Int, slot: Int, generation: Int, address: Int, store: Boolean, data: Vector[BigInt])
      case class Pending(request: Request, due: Int, error: Boolean)
      case class Step(launch: Boolean, halt: Option[(BigInt, BigInt, Int)], maintenance: Boolean, ack: Option[Boolean])
      val pending = mutable.ArrayBuffer[Pending]()
      var held: Option[Request] = None
      var cycle, accepted, completed, stale, lowerStalls, instructionReads, writebacks, failedWrites = 0
      var maxPending, reorders, codeStores, executions, publications, publicationStalls, fetchFailures = 0
      var badCode = Set.empty[Int]
      var slowWrongPath, failWrites, allowCodeStore = false
      val seenCodeLines = mutable.Set[Int]()
      val seenSources = mutable.Set[Int]()
      var nextCorruption = 7
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
      dut.io.launch.valid #= false; dut.io.launch.pc #= 0; dut.io.launch.argument #= 0
      dut.io.launch.base #= 0; dut.io.launch.limit #= 0x20000; dut.io.launch.writable #= true
      dut.io.halt.ready #= false; dut.io.flush.valid #= false; dut.io.flush.payload #= false; dut.io.flushed.ready #= false
      dut.io.lower.ready #= false; dut.io.reply.valid #= false; dut.io.replySource #= 0
      dut.io.reply.slot #= 0; dut.io.reply.generation #= 0; dut.io.reply.write #= false
      dut.io.reply.data.foreach(_ #= 0); dut.io.reply.error #= false
      for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      def tick(launch: Option[Int] = None, takeHalt: Boolean = false, maintain: Boolean = false, takeAck: Boolean = false): Step = {
        require(cycle < 20000, "protocol simulation budget exceeded")
        dut.io.launch.valid #= launch.nonEmpty; dut.io.launch.pc #= launch.getOrElse(0).toLong
        dut.io.halt.ready #= takeHalt; dut.io.flush.valid #= maintain; dut.io.flushed.ready #= takeAck
        dut.io.lower.ready #= (cycle % 5 >= 2)
        val due = pending.indices.filter(i => pending(i).due <= cycle).lastOption
        val corrupt = due.nonEmpty && cycle >= nextCorruption
        dut.io.reply.valid #= due.nonEmpty
        due.foreach { index =>
          val p = pending(index); val r = p.request
          dut.io.replySource #= r.source; dut.io.reply.slot #= r.slot
          dut.io.reply.generation #= (if (corrupt) (r.generation+1)&3 else r.generation)
          dut.io.reply.write #= r.store; dut.io.reply.error #= p.error
          for (w <- 0 until m.words) dut.io.reply.data(w) #= read(r.address+w*8, 8)
        }
        sleep(1)
        val result = Step(dut.io.launch.valid.toBoolean && dut.io.launch.ready.toBoolean,
          if (dut.io.halt.valid.toBoolean) Some((dut.io.halt.pc.toBigInt, dut.io.halt.value.toBigInt, dut.io.halt.cause.toInt)) else None,
          dut.io.flush.valid.toBoolean && dut.io.flush.ready.toBoolean,
          if (dut.io.flushed.valid.toBoolean) Some(dut.io.flushed.payload.toBoolean) else None)
        if (dut.io.wordAccepted.valid.toBoolean && dut.io.wordAccepted.write.toBoolean) {
          assert(allowCodeStore && dut.io.wordAccepted.address.toBigInt == 256 && dut.io.wordAccepted.mask.toInt == 15)
          assert((dut.io.wordAccepted.data.toBigInt & 0xffffffffL) == newInstruction)
          codeStores += 1
        }
        if (due.nonEmpty && dut.io.reply.ready.toBoolean) {
          if (corrupt) { stale += 1; nextCorruption = cycle+37 }
          else {
            val index = due.get; val p = pending.remove(index); val r = p.request
            completed += 1; if (index > 0) reorders += 1
            if (r.source == 0 && p.error) fetchFailures += 1
            if (r.store) {
              if (p.error) failedWrites += 1 else {
                for (w <- 0 until m.words) write(r.address+w*8, 8, r.data(w))
                writebacks += 1
              }
            }
          }
        }
        val offered = if (dut.io.lower.valid.toBoolean) Some(Request(dut.io.lowerSource.toInt, dut.io.lower.slot.toInt,
          dut.io.lower.generation.toInt, dut.io.lower.address.toBigInt.toInt, dut.io.lower.write.toBoolean,
          dut.io.lower.data.map(_.toBigInt).toVector)) else None
        held.foreach(r => assert(offered.contains(r), "fabric request changed under backpressure"))
        held = offered.filter(_ => !dut.io.lower.ready.toBoolean)
        if (held.nonEmpty) lowerStalls += 1
        if (offered.nonEmpty && dut.io.lower.ready.toBoolean) {
          val r = offered.get
          assert(!pending.exists(p => p.request.source == r.source && p.request.slot == r.slot), "live source ID reused")
          assert(r.address >= 0 && r.address + m.lineBytes <= memory.length && r.address % m.lineBytes == 0)
          if (r.source == 0) { assert(!r.store && r.address < 4096); instructionReads += 1; seenCodeLines += r.address }
          else if (r.store) assert(r.address == 256, "unauthorized code/data publication")
          seenSources += r.source
          val delay = if (r.source == 1 && r.address == 0x10000) 140
            else if (r.source == 0 && r.address == 544 && slowWrongPath) 300 else 7 + cycle%7
          val error = if (r.source == 0) badCode(r.address) else r.store && failWrites
          pending += Pending(r, cycle+delay, error); accepted += 1
        }
        maxPending = maxPending.max(pending.size)
        edge(); cycle += 1
        assert(dut.io.fabricOutstanding.toInt == pending.size, "fabric ledger differs from independent port scoreboard")
        result
      }
      def execute(pc: Int, value: Int, haltPc: Int, cause: Int = 3): Unit = {
        assert(dut.io.idle.toBoolean && pending.isEmpty, "launch without quiescence")
        assert(tick(launch = Some(pc)).launch)
        var result = tick().halt
        while (result.isEmpty) result = tick().halt
        assert(result.get == ((BigInt(haltPc), BigInt(value), cause)), s"wrong terminal result $result")
        assert(pending.isEmpty && dut.io.outstanding.toInt == 0, "terminal result before transport drained")
        for (_ <- 0 until 4) assert(tick().halt == result, "halt changed while held")
        assert(tick(takeHalt = true).halt == result)
        assert(dut.io.idle.toBoolean); executions += 1
      }
      def publish(expectError: Boolean): Unit = {
        assert(tick(maintain = true).maintenance)
        var result: Option[Boolean] = None
        // Keep a launch offered while publication runs; it must stay blocked.
        while (result.isEmpty) { val step = tick(launch = Some(0)); assert(!step.launch); result = step.ack }
        assert(result.contains(expectError))
        for (_ <- 0 until 5) {
          val step = tick(launch = Some(0)); assert(!step.launch && step.ack == result)
          publicationStalls += 1
        }
        assert(tick(takeAck = true).ack == result)
        assert(dut.io.idle.toBoolean && pending.isEmpty)
        publications += 1
      }
      execute(0, 42, 4)
      program(0, addi(10,0,43), breakpoint) // explicit external writer while idle
      val beforeStale = instructionReads
      execute(0, 42, 4) // lack of publication must be observable, not silently coherent
      assert(instructionReads == beforeStale)
      publish(expectError = false); execute(0, 43, 4)
      execute(256, 11, 260)
      allowCodeStore = true; execute(64, 0, 80); allowCodeStore = false
      assert(codeStores == 1 && !dut.io.clean.toBoolean && read(256, 4) == addi(10,0,11))
      execute(256, 11, 260) // actual dirty D-L1 store remains invisible to I-L1
      failWrites = true; publish(expectError = true); failWrites = false
      assert(!dut.io.clean.toBoolean && failedWrites == 1 && read(256, 4) == addi(10,0,11))
      val beforeFailedPublication = instructionReads
      execute(256, 11, 260); assert(instructionReads == beforeFailedPublication)
      publish(expectError = false)
      assert(dut.io.clean.toBoolean && writebacks == 1 && read(256, 4) == newInstruction)
      execute(256, 77, 260)
      badCode = Set(1024); execute(1024, 0, 1024, cause = 1)
      publish(expectError = false)
      badCode = Set(544); execute(512, 99, 580)
      val earlyFaults = fetchFailures
      assert(earlyFaults >= 2 && dut.io.fetchFaults.toBigInt >= 2)
      publish(expectError = false)
      slowWrongPath = true; val discardedBefore = dut.io.fetchDiscarded.toBigInt
      execute(512, 99, 580)
      assert(dut.io.fetchDiscarded.toBigInt > discardedBefore, "late wrong-path fetch did not drain/discard")
      assert(dut.io.fabricAccepted.toBigInt == accepted && dut.io.fabricCompleted.toBigInt == completed && accepted == completed)
      assert(dut.io.fabricRejected.toBigInt == stale && stale > 0 && lowerStalls > 0 && maxPending >= 2)
      assert(seenSources == Set(0,1) && seenCodeLines.contains(544) && reorders > 0)
      Files.writeString(root.resolve("validation.json"), s"""{"status":"passed","issue":5,"S04_complete":false,"claim_class":"actual_APE_instruction_publication_fault_RTL","cycles":$cycle,"executions":$executions,"publications":$publications,"publication_stall_cycles":$publicationStalls,"cpu_code_stores":$codeStores,"successful_code_writebacks":$writebacks,"failed_code_writebacks":$failedWrites,"fetch_failures":$fetchFailures,"fetch_discarded":${dut.io.fetchDiscarded.toBigInt},"fabric_accepted":$accepted,"fabric_completed":$completed,"fabric_rejected":$stale,"max_fabric_outstanding":$maxPending,"response_reorders":$reorders,"request_stall_cycles":$lowerStalls,"limits":["Known-answer protocol tests complement the separate Spike matrix","Explicit exclusive physical ownership assumed; inter-engine ownership controller still required","No FENCE.I ISA extension: explicit tile maintenance publishes code","Reset only initially with quiescent fabric; later code updates require no reset"]}\n""")
    }
  ApeSimArtifactCleanup.discardVerilatorBuildTree(root.resolve("rtl"), "ApeCachedDataTile")
}
