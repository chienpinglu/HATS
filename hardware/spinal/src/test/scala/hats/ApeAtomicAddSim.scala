package hats

import spinal.core.sim._
import spinal.core._
import scala.collection.mutable
import java.nio.file.{Files, Paths}

/** Focused end-to-end RV64A AMOADD.D -> APE LSQ -> data L1 simulation.
  * The backing line service is behavioral and is not an external-memory RTL model.
  */
object ApeAtomicAddSim extends App {
  val root = Paths.get(args.headOption.getOrElse("build/s04/ape-atomic"))
  Files.createDirectories(root)
  val m = MemoryHierarchyConfig(sets = 8, lineBytes = 32, mshrs = 4, epochBits = 2)
  def addi(rd: Int, rs: Int, imm: Int): Long = ((imm & 4095).toLong << 20) | (rs << 15) | (rd << 7) | 0x13
  def amoadd(rd: Int, rs1: Int, rs2: Int, aq: Int = 0, rl: Int = 0, funct5: Int = 0, width: Int = 3): Long =
    (funct5.toLong << 27) | (aq.toLong << 26) | (rl.toLong << 25) | (rs2.toLong << 20) |
      (rs1.toLong << 15) | (width.toLong << 12) | (rd.toLong << 7) | 0x2f
  val luiX1 = 0x000100b7L // x1 = 0x10000
  val fence = 0x0ff0000fL
  val ebreak = 0x00100073L
  val program = Vector(luiX1, addi(2, 0, 1), amoadd(3, 1, 2, aq = 1, rl = 1), addi(2, 0, 2),
    amoadd(4, 1, 2), addi(2, 0, 3), amoadd(5, 1, 2),
    ((0L << 20) | (1L << 15) | (3L << 12) | (6L << 7) | 0x03L),
    addi(10, 6, 0), fence, ebreak)
  val badProgram = Vector(luiX1, addi(2, 0, 1), amoadd(3, 1, 2, width = 2), ebreak)
  val compiled = SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("rtl").toString).compile(new ApeCachedDataTile(m))
  val reports = mutable.ArrayBuffer[String]()
  Seq(("amoadd_d", program, true), ("unsupported_amoadd_w", badProgram, false)).foreach { case (name, words, shouldComplete) =>
    compiled.doSim(name) { dut =>
      val external = mutable.Map.empty[BigInt, Int].withDefaultValue(0)
      for (b <- 0 until 8) external(BigInt(0x10000 + b)) = (BigInt(10) >> (8*b) & 255).toInt
      case class Pending(slot: Int, generation: Int, address: BigInt, write: Boolean, data: Vector[BigInt], due: Int)
      val pending = mutable.ArrayBuffer[Pending]()
      val writes = mutable.ArrayBuffer[BigInt]()
      var cycle = 0; var retiredAmo = 0; var atomicRequests = 0; var loadValue = BigInt(-1)
      val oldValues = mutable.Map.empty[Int, BigInt]
      var halted = false; var flushing = false; var flushed = false
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
      dut.io.launch.valid #= false; dut.io.launch.pc #= 0; dut.io.launch.argument #= 0
      dut.io.launch.base #= 0x10000; dut.io.launch.limit #= 0x20000; dut.io.launch.writable #= true
      dut.io.halt.ready #= false; dut.io.lower.ready #= false
      dut.io.reply.valid #= false; dut.io.reply.slot #= 0; dut.io.reply.generation #= 0; dut.io.reply.write #= false
      dut.io.reply.data.foreach(_ #= 0); dut.io.reply.error #= false
      dut.io.deviceResponse.valid #= false; dut.io.deviceResponse.id #= 0; dut.io.deviceResponse.epoch #= 0
      dut.io.deviceResponse.data #= 0; dut.io.deviceResponse.error #= false
      dut.io.flush.valid #= false; dut.io.flush.payload #= false; dut.io.flushed.ready #= true
      for (_ <- 0 until 4) edge(); dut.clockDomain.deassertReset(); edge()
      for (i <- 0 until 1024) {
        dut.io.program.valid #= true; dut.io.program.index #= i; dut.io.program.instruction #= words.lift(i).getOrElse(0L); edge()
      }
      dut.io.program.valid #= false; dut.io.launch.valid #= true; edge(); dut.io.launch.valid #= false
      while (!flushed && cycle < 20000) {
        dut.io.lower.ready #= true
        val due = pending.indices.find(i => pending(i).due <= cycle)
        dut.io.reply.valid #= due.nonEmpty
        due.foreach { i =>
          val p = pending(i); dut.io.reply.slot #= p.slot; dut.io.reply.generation #= p.generation; dut.io.reply.write #= p.write
          for (w <- 0 until m.words) {
            val value = (0 until 8).foldLeft(BigInt(0))((v,b) => v | (BigInt(external(p.address + w*8 + b)) << (8*b)))
            dut.io.reply.data(w) #= value
          }
          dut.io.reply.error #= false
        }
        dut.io.flush.valid #= (halted && !flushing)
        if (dut.io.memoryRetired.valid.toBoolean && dut.io.memoryRetired.write.toBoolean &&
          words.lift((dut.io.retired.pc.toBigInt / 4).toInt).exists(w => (w & 127) == 0x2f)) retiredAmo += 1
        if (dut.io.retired.valid.toBoolean && dut.io.retired.writes.toBoolean && Set(3, 4, 5)(dut.io.retired.rd.toInt))
          oldValues(dut.io.retired.rd.toInt) = dut.io.retired.value.toBigInt
        if (dut.io.retired.valid.toBoolean && dut.io.retired.writes.toBoolean && dut.io.retired.rd.toInt == 6)
          loadValue = dut.io.retired.value.toBigInt
        if (dut.io.wordAccepted.valid.toBoolean && dut.io.wordAccepted.atomicAdd.toBoolean) atomicRequests += 1
        if (dut.io.halt.valid.toBoolean) { halted = true; dut.io.halt.ready #= true }
        if (dut.io.flush.valid.toBoolean && dut.io.flush.ready.toBoolean) flushing = true
        if (dut.io.flushed.valid.toBoolean) flushed = true
        if (due.nonEmpty && dut.io.reply.ready.toBoolean) {
          val p = pending.remove(due.get)
          if (p.write) { writes += p.data.head; for (w <- 0 until m.words; b <- 0 until 8)
            external(p.address+w*8+b) = ((p.data(w) >> (8*b)) & 255).toInt }
        }
        if (dut.io.lower.valid.toBoolean && dut.io.lower.ready.toBoolean) {
          val address = dut.io.lower.address.toBigInt; val data = dut.io.lower.data.map(_.toBigInt).toVector
          pending += Pending(dut.io.lower.slot.toInt, dut.io.lower.generation.toInt, address, dut.io.lower.write.toBoolean,
            data, cycle + 3)
        }
        edge(); cycle += 1
      }
      if (shouldComplete) {
        assert(flushed && pending.isEmpty && dut.io.idle.toBoolean, "AMO test did not drain and clean")
        assert(retiredAmo == 3 && atomicRequests == 3, s"atomic retirement/request mismatch $retiredAmo/$atomicRequests")
        assert(oldValues.toMap == Map(3 -> BigInt(10), 4 -> BigInt(11), 5 -> BigInt(13)), s"wrong prior values $oldValues")
        assert(loadValue == 16, s"load after three AMOs saw $loadValue, expected 16")
        assert(external(0x10000) == 16, "final backing memory is not 16")
      } else assert(halted && atomicRequests == 0, "unsupported AMO.W was not rejected before cache access")
      val prior = oldValues.toSeq.sortBy(_._1).map { case (rd, value) => s"\"$rd\":\"$value\"" }.mkString(",")
      reports += s"""{"name":"$name","cycles":$cycle,"atomic_requests":$atomicRequests,"retired_atomic":$retiredAmo,"prior_values":{$prior},"load_value":"$loadValue","backing_word":"${(0 until 8).foldLeft(BigInt(0))((v,b) => v | (BigInt(external(BigInt(0x10000+b))) << (8*b)))}","halted":$halted,"passed":${if (shouldComplete) flushed && loadValue == 16 && atomicRequests == 3 else halted && atomicRequests == 0}}"""
    }
  }
  ApeSimArtifactCleanup.discardVerilatorBuildTree(root.resolve("rtl"), "ApeCachedDataTile")
  Files.writeString(root.resolve("validation.json"), s"""{"status":"passed","S04_complete":false,"claim_class":"APE_LSQ_D_L1_RV64A_AMOADD_D_modeled_line_service","tests":[${reports.mkString(",") }],"limits":["single APE owner only","behavioral backing line service, not DRAM RTL","cross-engine atomic serialization not covered","PPE instruction-level atomic support not covered"]}\n""")
  println("APE RV64A AMOADD.D RTL path passed; S04 remains open")
}
