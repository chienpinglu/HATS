package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}

/** Word-granular poison is reported metadata, not a modeled ECC circuit.
  * A faulting word must not corrupt healthy neighbours or disappear on eviction.
  */
object MemoryPoisonSim extends App {
  val root = Paths.get(args(0)); Files.createDirectories(root)
  val c = MemoryHierarchyConfig(sets = 4, lineBytes = 32, mshrs = 4, wordPoison = true)
  var requests, faults, busReads, busWrites, failedWrites, flushes = 0
  SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("sim").toString).compile(new NonBlockingL1(c)).doSim("word_poison") { dut =>
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      val external = Array.tabulate[BigInt](128)(i => BigInt(0x1000 + i))
      var poison = 2
      var failWrite, failRead = false
      var cycle = 0
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      dut.io.request.valid #= false; dut.io.request.id #= 0; dut.io.request.epoch #= 1
      dut.io.request.address #= 0; dut.io.request.data #= 0; dut.io.request.mask #= 255
      dut.io.request.write #= false; dut.io.request.atomicAdd #= false
      dut.io.response.ready #= true; dut.io.lower.ready #= true
      dut.io.reply.valid #= false; dut.io.reply.slot #= 0; dut.io.reply.generation #= 0
      dut.io.reply.write #= false; dut.io.reply.error #= false; dut.io.reply.poison #= 0
      dut.io.reply.data.foreach(_ #= 0)
      dut.io.drain #= false; dut.io.flush.valid #= false; dut.io.flush.payload #= true; dut.io.flushed.ready #= true
      for (_ <- 0 until 4) edge(); dut.clockDomain.deassertReset(); edge()
      case class Transfer(slot: Int, generation: Int, address: Int, write: Boolean, data: Vector[BigInt], poison: Int, due: Int)
      var pending: Option[Transfer] = None
      def tick(): Unit = {
        val reply = pending.filter(_.due <= cycle)
        dut.io.reply.valid #= reply.nonEmpty
        reply.foreach { r =>
          dut.io.reply.slot #= r.slot; dut.io.reply.generation #= r.generation; dut.io.reply.write #= r.write
          dut.io.reply.error #= (if (r.write) failWrite else failRead)
          dut.io.reply.poison #= (if (r.address == 0) poison else 0)
          for (w <- 0 until c.words) dut.io.reply.data(w) #= external(r.address/8+w)
        }
        sleep(1)
        if (reply.nonEmpty) {
          assert(dut.io.reply.ready.toBoolean)
          val r = reply.get
          if (r.write) {
            assert(r.poison == (if (r.address == 0) poison else 0), "lost poison metadata")
            if (!failWrite) for (w <- 0 until c.words) external(r.address/8+w) = r.data(w)
            else failedWrites += 1
          }
          pending = None
        }
        if (dut.io.lower.valid.toBoolean && dut.io.lower.ready.toBoolean) {
          assert(pending.isEmpty)
          val r = Transfer(dut.io.lower.slot.toInt, dut.io.lower.generation.toInt,
            dut.io.lower.address.toBigInt.toInt, dut.io.lower.write.toBoolean,
            dut.io.lower.data.map(_.toBigInt).toVector, dut.io.lower.poison.toInt, cycle+4)
          pending = Some(r)
          if (r.write) busWrites += 1 else busReads += 1
        }
        edge(); cycle += 1; assert(cycle < 10000)
      }
      def access(address: Int, store: Boolean = false, value: BigInt = 0, mask: Int = 255, error: Boolean = false, expected: BigInt = 0): Unit = {
        dut.io.request.valid #= true; dut.io.request.id #= requests; dut.io.request.address #= address
        dut.io.request.write #= store; dut.io.request.atomicAdd #= false
        dut.io.request.data #= value; dut.io.request.mask #= mask
        sleep(1); while (!dut.io.request.ready.toBoolean) { tick(); sleep(1) }
        tick(); dut.io.request.valid #= false; sleep(1)
        while (!dut.io.response.valid.toBoolean) { tick(); sleep(1) }
        assert(dut.io.response.id.toInt == requests && dut.io.response.epoch.toInt == 1)
        assert(dut.io.response.error.toBoolean == error)
        assert(dut.io.response.data.toBigInt == (if (store || error) BigInt(0) else expected))
        tick(); requests += 1; if (error) faults += 1
      }
      def flush(invalidate: Boolean, error: Boolean = false): Unit = {
        dut.io.flush.valid #= true; dut.io.flush.payload #= invalidate
        sleep(1); while (!dut.io.flush.ready.toBoolean) { tick(); sleep(1) }
        tick(); dut.io.flush.valid #= false; sleep(1)
        while (!dut.io.flushed.valid.toBoolean) { tick(); sleep(1) }
        assert(dut.io.flushed.payload.toBoolean == error)
        tick(); assert(dut.io.clean.toBoolean == !error); flushes += 1
      }
      access(8, store = true, value = 0xdead, error = true)
      assert(dut.io.clean.toBoolean, "faulting refill store made line dirty")
      access(0, expected = 0x1000); access(8, error = true)
      access(0, store = true, value = 0xaa, mask = 1)
      access(8, store = true, value = 0xbeef, error = true)
      assert(!dut.io.clean.toBoolean)
      failWrite = true; flush(invalidate = true, error = true)
      assert(external(0) == 0x1000 && external(1) == 0x1001)
      access(0, expected = 0x10aa); access(8, error = true)
      failWrite = false; flush(invalidate = true)
      assert(external(0) == 0x10aa && external(1) == 0x1001)
      access(0, expected = 0x10aa); access(8, error = true)
      // Repair at the owner occurs only after explicit invalidation.
      flush(invalidate = true); poison = 0
      access(8, expected = 0x1001)
      failRead = true; access(32, error = true); failRead = false
      access(32, expected = 0x1004)
      flush(invalidate = true)
      assert(pending.isEmpty && dut.io.idle.toBoolean && dut.io.clean.toBoolean)
    }
  assert(requests == 12 && faults == 6 && busWrites == 2 && failedWrites == 1 && flushes == 4)
  Files.writeString(root.resolve("validation.json"), s"""{"status":"passed","claim_class":"word_poison_L1_component_RTL","requests":$requests,"faults":$faults,"reads":$busReads,"writes":$busWrites,"failed_writes":$failedWrites,"flushes":$flushes}\n""")
}
