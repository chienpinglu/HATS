package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import scala.collection.mutable

/** Actual PPE writes its own code through D-L1; execution changes only after
  * successful publication. Independent known-answer protocol/retirement checks.
  */
object PpeInstructionProtocolSim extends App {
  val root = Paths.get(args(0)); Files.createDirectories(root)
  val m = MemoryHierarchyConfig(wordPoison = true)
  val base = 0x100000
  def instruction(op: Int, d: Int = 0, a: Int = 0, b: Int = 0, width: Int = 0, imm: Long = 0): BigInt =
    BigInt(op) | (BigInt(d) << 8) | (BigInt(a) << 13) | (BigInt(b) << 18) |
      (BigInt(width) << 26) | ((BigInt(imm) & BigInt("ffffffff", 16)) << 32)
  def mov(value: Int): BigInt = instruction(1, d=8, width=3, imm=value)
  var runs, publications, acknowledgements, codeStores, failedWrites, successfulWrites, instructionFailures = 0
  var accepted, completed, stale, requestStalls, discarded = 0
  val results = mutable.ArrayBuffer[String]()
  SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("sim").toString).compile(new PpeCachedDataTile(m, instructionCache = true))
    .doSim("ppe_instruction_protocol") { dut =>
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      val external = Array.fill[BigInt](1024)(0)
      // argument=0: execute/read the modifiable instruction; argument=1: writer.
      val writer = Vector(instruction(28, a=0, imm=3), mov(11), instruction(37, a=8),
        instruction(1, d=8, width=3, imm=base+8), instruction(1, d=9, width=3, imm=77),
        instruction(1, d=10, width=3, imm=32), instruction(8, d=9, a=9, b=10, width=3),
        instruction(1, d=10, width=3, imm=mov(0).toLong), instruction(6, d=9, a=9, b=10, width=3),
        instruction(32, d=9, a=8, width=3), instruction(37, a=9))
      writer.zipWithIndex.foreach { case(word,i) => external(i)=word }
      case class Transfer(source: Int, slot: Int, generation: Int, address: Int, write: Boolean, data: Vector[BigInt], poison: Int)
      case class Pending(r: Transfer, due: Int, sequence: Int, badSent: Boolean = false)
      val pending = mutable.ArrayBuffer[Pending]()
      var held: Option[Transfer] = None
      var cycle, origin = 0
      var readyAfter, replyAfter = 0
      var failWrite, failRead = false
      var poison = 0
      var observedRetired = Vector.empty[Int]
      var observedAccesses = Vector.empty[(BigInt, BigInt, Boolean, Int)]
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
      dut.io.launch.valid #= false; dut.io.launch.task #= 7; dut.io.launch.epoch #= 1
      dut.io.launch.argument #= 0; dut.io.launch.argumentBytes #= 0
      dut.io.launch.addressSpace #= 2; dut.io.launch.generation #= 3
      dut.io.launch.group #= 0; dut.io.launch.groups #= 1; dut.io.launch.budget #= 10000
      dut.io.launch.base #= base; dut.io.launch.limit #= base+8192
      dut.io.launch.writable #= true; dut.io.launch.codeWords #= writer.length; dut.io.launch.scratchBytes #= 0
      dut.io.completion.ready #= false; dut.io.inspectScratch #= 0
      dut.io.deviceRequest.ready #= false; dut.io.deviceResponse.valid #= false
      dut.io.deviceResponse.id #= 0; dut.io.deviceResponse.epoch #= 0
      dut.io.deviceResponse.data #= 0; dut.io.deviceResponse.error #= false
      dut.io.lower.ready #= false; dut.io.reply.valid #= false; dut.io.replySource #= 0
      dut.io.reply.slot #= 0; dut.io.reply.generation #= 0; dut.io.reply.write #= false
      dut.io.reply.data.foreach(_ #= 0); dut.io.reply.error #= false; dut.io.reply.poison #= 0
      dut.io.flush.valid #= false; dut.io.flush.payload #= true; dut.io.flushed.ready #= false
      for (_ <- 0 until 4) edge(); dut.clockDomain.deassertReset(); edge()
      // Deliberately load illegal zeros into the obsolete programming interface.
      for (i <- writer.indices) {
        dut.io.program.valid #= true; dut.io.program.index #= i; sleep(1)
        assert(dut.io.program.ready.toBoolean); edge()
      }
      dut.io.program.valid #= false
      def completion = (dut.io.completion.status.toInt, dut.io.completion.cause.toInt,
        dut.io.completion.pc.toBigInt, dut.io.completion.address.toBigInt,
        dut.io.completion.laneMask.toInt, dut.io.completion.value.toBigInt)
      def tick(): Unit = {
        dut.io.lower.ready #= (cycle-origin >= readyAfter && cycle % 5 >= 2)
        val index = pending.indices.find(i => pending(i).due <= cycle && cycle-origin >= replyAfter)
        dut.io.reply.valid #= index.nonEmpty
        index.foreach { i =>
          val p = pending(i); val r = p.r
          dut.io.replySource #= r.source; dut.io.reply.slot #= r.slot
          dut.io.reply.generation #= ((r.generation + (if (p.badSent) 0 else 1)) & 255)
          dut.io.reply.write #= r.write
          dut.io.reply.error #= (if (r.write) failWrite else r.source == 0 && failRead)
          dut.io.reply.poison #= (if (r.address == base) poison else 0)
          for (w <- 0 until m.words) dut.io.reply.data(w) #= external((r.address-base)/8+w)
        }
        sleep(1)
        val bus = if (dut.io.lower.valid.toBoolean) Some(Transfer(dut.io.lowerSource.toInt, dut.io.lower.slot.toInt,
          dut.io.lower.generation.toInt, dut.io.lower.address.toBigInt.toInt, dut.io.lower.write.toBoolean,
          dut.io.lower.data.map(_.toBigInt).toVector, dut.io.lower.poison.toInt)) else None
        held.foreach(r => assert(bus.contains(r), "offered instruction/publication request changed before acceptance"))
        held = if (!dut.io.lower.ready.toBoolean) bus else None
        if (held.nonEmpty) requestStalls += 1
        index.foreach { i =>
          assert(dut.io.reply.ready.toBoolean)
          val p = pending(i); val r = p.r
          if (!p.badSent) { stale += 1; pending(i) = p.copy(badSent=true, due=cycle+1) }
          else {
            pending.remove(i); completed += 1
            if (r.write) {
              if (failWrite) failedWrites += 1
              else {
                successfulWrites += 1
                for (w <- 0 until m.words) external((r.address-base)/8+w)=r.data(w)
              }
            } else if (r.source == 0 && (failRead || (r.address == base && poison != 0))) instructionFailures += 1
          }
        }
        bus.filter(_ => dut.io.lower.ready.toBoolean).foreach { r =>
          assert(r.address >= base && r.address + m.lineBytes <= base+8192 && r.address % m.lineBytes == 0)
          assert(!pending.exists(p => p.r.source == r.source && p.r.slot == r.slot))
          assert(r.source != 0 || !r.write)
          pending += Pending(r, cycle+8, accepted); accepted += 1
        }
        if (dut.io.wordAccepted.valid.toBoolean && dut.io.wordAccepted.write.toBoolean) {
          assert(dut.io.wordAccepted.address.toBigInt == base+8 && dut.io.wordAccepted.data.toBigInt == mov(77)
            && dut.io.wordAccepted.mask.toInt == 255, "unexpected PPE code modification")
          codeStores += 1
        }
        if (dut.io.access.valid.toBoolean) observedAccesses :+= ((dut.io.access.address.toBigInt,
          dut.io.access.data.toBigInt, dut.io.access.write.toBoolean, dut.io.access.error.toInt))
        if (dut.io.retired.valid.toBoolean) observedRetired :+= dut.io.retired.pc.toBigInt.toInt
        if (dut.io.completion.valid.toBoolean) assert(pending.isEmpty && held.isEmpty && dut.io.fabricOutstanding.toInt == 0,
          "PPE published completion before instruction/data transport drained")
        edge(); cycle += 1; assert(cycle < 20000, "PPE instruction protocol deadlock")
      }
      def execute(name: String, value: BigInt = 0, argument: Int = 0, budget: Int = 10000,
                  cause: Int = 0, pc: Int = 16, address: BigInt = 0, retired: Vector[Int] = Vector(0,8,16)): Unit = {
        observedRetired = Vector.empty; observedAccesses = Vector.empty; origin = cycle
        dut.io.launch.argument #= argument; dut.io.launch.budget #= budget; dut.io.launch.epoch #= (runs+1)
        dut.io.launch.valid #= true; sleep(1); assert(dut.io.launch.ready.toBoolean)
        tick(); dut.io.launch.valid #= false
        while (!dut.io.completion.valid.toBoolean) {
          assert(!dut.io.launch.ready.toBoolean)
          if (budget == 140 && cycle-origin >= 145 && cycle-origin < 195) assert(dut.io.busy.toBoolean && dut.io.waiting.toBoolean)
          tick()
        }
        val expected = (if (cause == 0) 1 else 2, cause, BigInt(pc), address, 0, value)
        assert(completion == expected, s"$name completion: ${completion} != $expected")
        assert(observedRetired == retired, s"$name retirement prefix $observedRetired != $retired")
        if (argument == 1) assert(observedAccesses == Vector((BigInt(base+8), mov(77), true, 0)))
        else assert(observedAccesses.isEmpty, "fetch operation appeared as an architectural data access")
        for (_ <- 0 until 5) { tick(); assert(dut.io.completion.valid.toBoolean && completion == expected) }
        dut.io.completion.ready #= true; tick(); dut.io.completion.ready #= false
        assert(dut.io.idle.toBoolean && pending.isEmpty)
        runs += 1
        results += s"""{"name":"$name","cause":$cause,"retired":${retired.size},"value":"$value"}"""
      }
      def publish(error: Boolean = false): Unit = {
        origin = cycle; readyAfter=0; replyAfter=0
        dut.io.flush.valid #= true; dut.io.flush.payload #= true
        sleep(1); assert(dut.io.flush.ready.toBoolean); tick(); dut.io.flush.valid #= false
        dut.io.launch.valid #= true
        while (!dut.io.flushed.valid.toBoolean) { assert(!dut.io.launch.ready.toBoolean); tick() }
        for (_ <- 0 until 5) {
          assert(!dut.io.launch.ready.toBoolean && dut.io.flushed.valid.toBoolean && dut.io.flushed.payload.toBoolean == error)
          tick(); acknowledgements += 1
        }
        dut.io.launch.valid #= false; dut.io.flushed.ready #= true; tick(); dut.io.flushed.ready #= false
        assert(dut.io.idle.toBoolean && dut.io.clean.toBoolean == !error); publications += 1
      }
      execute("original", value=11)
      execute("actual_PPE_code_store", value=mov(77), argument=1, pc=80,
        retired=Vector(0,24,32,40,48,56,64,72,80))
      assert(!dut.io.clean.toBoolean && external(1) == mov(11))
      execute("stale_before_publication", value=11)
      failWrite=true; publish(error=true)
      assert(external(1) == mov(11)); execute("failed_clean_preserves_old_code", value=11)
      failWrite=false; publish()
      assert(external(1) == mov(77)); execute("published_PPE_code", value=77)
      external(1)=mov(43); execute("host_edit_stays_stale", value=77)
      publish(); execute("published_host_code", value=43)
      publish(); poison=2
      execute("word_local_fetch_poison", cause=4, pc=8, address=base+8, retired=Vector(0))
      publish(); poison=0; failRead=true
      execute("whole_line_fetch_fault", cause=4, pc=0, address=base, retired=Vector.empty)
      publish(); failRead=false
      external(0)=instruction(27, imm=2); poison=2
      execute("branch_skips_poisoned_word", value=0, retired=Vector(0,16))
      publish(); poison=0; failRead=true; readyAfter=200
      execute("offered_fetch_timeout_drain", budget=140, cause=5, pc=0, retired=Vector.empty)
      publish(); readyAfter=0; replyAfter=200
      execute("accepted_fetch_timeout_drain", budget=140, cause=5, pc=0, retired=Vector.empty)
      publish(); failRead=false; replyAfter=0
      execute("recovery_after_late_fault", value=0, retired=Vector(0,16))
      assert(codeStores == 1 && failedWrites == 1 && successfulWrites == 1)
      assert(accepted == completed && dut.io.fabricAccepted.toBigInt == accepted && dut.io.fabricCompleted.toBigInt == completed)
      assert(dut.io.fabricRejected.toBigInt == stale)
      discarded = dut.io.fetchDiscarded.toBigInt.toInt
      assert(discarded == 2 && dut.io.fetchFaults.toBigInt == 4)
    }
  Files.writeString(root.resolve("validation.json"), s"""{"status":"passed","claim_class":"PPE_instruction_publication_and_drain_RTL","runs":$runs,"publications":$publications,"held_ack_cycles":$acknowledgements,"code_stores":$codeStores,"failed_writebacks":$failedWrites,"successful_writebacks":$successfulWrites,"faulting_instruction_line_replies":$instructionFailures,"accepted":$accepted,"completed":$completed,"rejected":$stale,"request_stalls":$requestStalls,"discarded_fetches":$discarded,"tests":[${results.mkString(",")}]}\n""")
}
