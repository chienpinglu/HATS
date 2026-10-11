package hats

import spinal.core._
import spinal.core.sim._
import scala.collection.mutable
import java.nio.file.{Files, Paths}

/** S04 scalar AMOADD extension through PPE, coalescer, D-L1 and modeled service. */
object PpeAtomicAddSim extends App {
  val root = Paths.get(args.headOption.getOrElse("build/s04/ppe-atomic"))
  Files.createDirectories(root)
  val m = MemoryHierarchyConfig(sets = 8, lineBytes = 32, mshrs = 4, epochBits = 8, wordPoison = true)
  def enc(op: Int, d: Int = 0, a: Int = 0, b: Int = 0, width: Int = 0, imm: Int = 0): BigInt =
    BigInt(op) | (BigInt(d) << 8) | (BigInt(a) << 13) | (BigInt(b) << 18) |
      (BigInt(width) << 26) | ((BigInt(imm) & 0xffffffffL) << 32)
  val program = Vector(enc(1, d=8, width=3, imm=0x10000), enc(1, d=9, width=3, imm=1), enc(38, d=10, a=8, b=9, width=3),
    enc(1, d=9, width=3, imm=2), enc(38, d=11, a=8, b=9, width=3), enc(1, d=9, width=3, imm=3), enc(38, d=12, a=8, b=9, width=3),
    enc(31, d=13, a=8, width=3), enc(35), enc(37, a=13))
  val compiled = SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(root.resolve("rtl").toString).compile(new PpeCachedDataTile(m))
  compiled.doSim("ppe_amoadd_path") { dut =>
    case class Lower(slot: Int, generation: Int, address: BigInt, write: Boolean, data: Vector[BigInt], due: Int)
    val backing = mutable.Map.empty[BigInt, Int].withDefaultValue(0)
    for (b <- 0 until 8) backing(BigInt(0x10000+b)) = ((BigInt(10) >> (8*b)) & 255).toInt
    val pending = mutable.ArrayBuffer[Lower]()
    val operands = mutable.ArrayBuffer[BigInt]()
    var cycle = 0; var retired = 0; var completed = false; var sentFlush = false; var flushed = false
    def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
    dut.clockDomain.clockSim #= false
    dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
    dut.io.launch.valid #= false; dut.io.launch.task #= 1; dut.io.launch.epoch #= 1
    dut.io.launch.argument #= 0; dut.io.launch.argumentBytes #= 0; dut.io.launch.addressSpace #= 0
    dut.io.launch.generation #= 0; dut.io.launch.group #= 0; dut.io.launch.groups #= 1
    dut.io.launch.budget #= 1000; dut.io.launch.base #= 0x10000; dut.io.launch.limit #= 0x10020
    dut.io.launch.writable #= true; dut.io.launch.codeWords #= program.size; dut.io.launch.scratchBytes #= 0
    dut.io.completion.ready #= false; dut.io.inspectScratch #= 0
    dut.io.deviceRequest.ready #= false; dut.io.deviceResponse.valid #= false
    dut.io.deviceResponse.id #= 0; dut.io.deviceResponse.epoch #= 0; dut.io.deviceResponse.data #= 0; dut.io.deviceResponse.error #= false
    dut.io.lower.ready #= false; dut.io.reply.valid #= false; dut.io.reply.slot #= 0
    dut.io.reply.generation #= 0; dut.io.reply.write #= false; dut.io.reply.error #= false
    dut.io.reply.poison #= 0; dut.io.reply.data.foreach(_ #= 0)
    dut.io.flush.valid #= false; dut.io.flush.payload #= true; dut.io.flushed.ready #= false
    dut.clockDomain.assertReset(); for (_ <- 0 until 4) edge(); dut.clockDomain.deassertReset(); edge()
    for (i <- program.indices) {
      dut.io.program.valid #= true; dut.io.program.index #= i; dut.io.program.instruction #= program(i)
      sleep(1); assert(dut.io.program.ready.toBoolean); edge()
    }
    dut.io.program.valid #= false; dut.io.launch.valid #= true; sleep(1)
    assert(dut.io.launch.ready.toBoolean); edge(); dut.io.launch.valid #= false
    while (!flushed && cycle < 20000) {
      dut.io.lower.ready #= true
      val due = pending.indices.find(i => pending(i).due <= cycle)
      dut.io.reply.valid #= due.nonEmpty
      due.foreach { i =>
        val r = pending(i); dut.io.reply.slot #= r.slot; dut.io.reply.generation #= r.generation
        dut.io.reply.write #= r.write; dut.io.reply.error #= false; dut.io.reply.poison #= 0
        for (w <- 0 until m.words) dut.io.reply.data(w) #= (0 until 8).foldLeft(BigInt(0))((v,b) =>
          v | (BigInt(backing(r.address + w*8 + b)) << (8*b)))
      }
      dut.io.flush.valid #= (completed && !sentFlush); dut.io.flushed.ready #= true
      if (dut.io.wordAccepted.valid.toBoolean && dut.io.wordAccepted.atomicAdd.toBoolean) {
        assert(dut.io.wordAccepted.write.toBoolean && dut.io.wordAccepted.mask.toInt == 255)
        operands += dut.io.wordAccepted.data.toBigInt
      }
      if (dut.io.access.valid.toBoolean && dut.io.access.atomicAdd.toBoolean)
        assert(dut.io.access.write.toBoolean && dut.io.access.size.toInt == 3)
      if (dut.io.retired.valid.toBoolean) retired += 1
      if (dut.io.completion.valid.toBoolean) {
        assert(dut.io.completion.status.toInt == 1 && dut.io.completion.cause.toInt == 0,
          s"completion status=${dut.io.completion.status.toInt} cause=${dut.io.completion.cause.toInt} pc=${dut.io.completion.pc.toBigInt} addr=${dut.io.completion.address.toBigInt} operands=$operands")
        assert(dut.io.completion.value.toBigInt == 16,
          s"return=${dut.io.completion.value.toBigInt}, old=${dut.io.scalar(10).toBigInt}/${dut.io.scalar(11).toBigInt}/${dut.io.scalar(12).toBigInt}, load=${dut.io.scalar(13).toBigInt}, operands=$operands")
        assert(dut.io.scalar(10).toBigInt == 10 && dut.io.scalar(11).toBigInt == 11 && dut.io.scalar(12).toBigInt == 13)
        assert(dut.io.scalar(13).toBigInt == 16)
        assert((0 until 8).foldLeft(BigInt(0))((v,b) => v | (BigInt(backing(BigInt(0x10000+b))) << (8*b))) == 16)
        completed = true; dut.io.completion.ready #= true
      }
      if (dut.io.flush.valid.toBoolean && dut.io.flush.ready.toBoolean) sentFlush = true
      if (dut.io.flushed.valid.toBoolean && dut.io.flushed.ready.toBoolean) {
        assert(!dut.io.flushed.payload.toBoolean); flushed = true
      }
      if (due.nonEmpty && dut.io.reply.ready.toBoolean) {
        val r = pending.remove(due.get)
        if (r.write) for (w <- 0 until m.words; b <- 0 until 8)
          backing(r.address+w*8+b) = ((r.data(w) >> (8*b)) & 255).toInt
      }
      if (dut.io.lower.valid.toBoolean && dut.io.lower.ready.toBoolean)
        pending += Lower(dut.io.lower.slot.toInt, dut.io.lower.generation.toInt, dut.io.lower.address.toBigInt,
          dut.io.lower.write.toBoolean, dut.io.lower.data.map(_.toBigInt).toVector, cycle+3)
      edge(); cycle += 1
    }
    assert(completed && flushed && pending.isEmpty && dut.io.idle.toBoolean)
    assert(operands.toVector == Vector(BigInt(1), BigInt(2), BigInt(3)), s"atomic operands: $operands")
    assert(retired == program.size && dut.io.clean.toBoolean)
    val backingWord = (0 until 8).foldLeft(BigInt(0))((v,b) => v | (BigInt(backing(BigInt(0x10000+b))) << (8*b)))
    Files.writeString(root.resolve("validation.json"),
      s"""{"status":"passed","S04_complete":false,"claim_class":"PPE_scalar_AMOADD_D_LS_engine_D_L1_modeled_line_service","atomic_requests":${operands.size},"operands":[${operands.mkString(",")}],"prior_values":[10,11,13],"load_after_atomic":"16","backing_after_fence":"$backingWord","retired":$retired,"limits":["single PPE owner and D-L1","exclusive ownership handoff serialization not exercised by this test","behavioral backing line service, not DRAM RTL"]}\n""")
  }
  val deviceRoot = root.resolve("device-negative")
  val deviceCompiled = SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(deviceRoot.resolve("rtl").toString)
    .compile(new PpeCachedDataTile(m, deviceRegions = Seq((BigInt(0x10000), BigInt(0x10020)))))
  deviceCompiled.doSim("atomic_device_rejected") { dut =>
    val badProgram = Vector(enc(1, d=8, width=3, imm=0x10000), enc(1, d=9, width=3, imm=1),
      enc(38, d=10, a=8, b=9, width=3), enc(37, a=10))
    var cycle = 0; var deviceRequests = 0; var cacheAtomicRequests = 0; var lowerRequests = 0; var observedFault = false
    def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
    dut.clockDomain.clockSim #= false
    dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
    dut.io.launch.valid #= false; dut.io.launch.task #= 2; dut.io.launch.epoch #= 1
    dut.io.launch.argument #= 0; dut.io.launch.argumentBytes #= 0; dut.io.launch.addressSpace #= 0
    dut.io.launch.generation #= 0; dut.io.launch.group #= 0; dut.io.launch.groups #= 1
    dut.io.launch.budget #= 1000; dut.io.launch.base #= 0x10000; dut.io.launch.limit #= 0x10020
    dut.io.launch.writable #= true; dut.io.launch.codeWords #= badProgram.size; dut.io.launch.scratchBytes #= 0
    dut.io.completion.ready #= false; dut.io.inspectScratch #= 0
    dut.io.deviceRequest.ready #= true; dut.io.deviceResponse.valid #= false
    dut.io.deviceResponse.id #= 0; dut.io.deviceResponse.epoch #= 0; dut.io.deviceResponse.data #= 0; dut.io.deviceResponse.error #= false
    dut.io.lower.ready #= true; dut.io.reply.valid #= false; dut.io.reply.slot #= 0
    dut.io.reply.generation #= 0; dut.io.reply.write #= false; dut.io.reply.error #= false
    dut.io.reply.poison #= 0; dut.io.reply.data.foreach(_ #= 0)
    dut.io.flush.valid #= false; dut.io.flush.payload #= false; dut.io.flushed.ready #= true
    dut.clockDomain.assertReset(); for (_ <- 0 until 4) edge(); dut.clockDomain.deassertReset(); edge()
    for (i <- badProgram.indices) {
      dut.io.program.valid #= true; dut.io.program.index #= i; dut.io.program.instruction #= badProgram(i)
      sleep(1); assert(dut.io.program.ready.toBoolean); edge()
    }
    dut.io.program.valid #= false; dut.io.launch.valid #= true; sleep(1)
    assert(dut.io.launch.ready.toBoolean); edge(); dut.io.launch.valid #= false
    while (!observedFault && cycle < 5000) {
      if (dut.io.deviceRequest.valid.toBoolean) deviceRequests += 1
      if (dut.io.wordAccepted.valid.toBoolean && dut.io.wordAccepted.atomicAdd.toBoolean) cacheAtomicRequests += 1
      if (dut.io.lower.valid.toBoolean) lowerRequests += 1
      if (dut.io.completion.valid.toBoolean) {
        assert(dut.io.completion.status.toInt == 2 && dut.io.completion.cause.toInt == 4)
        observedFault = true; dut.io.completion.ready #= true
      }
      edge(); cycle += 1
    }
    assert(observedFault && deviceRequests == 0 && cacheAtomicRequests == 0 && lowerRequests == 0,
      s"atomic device negative control leaked: fault=$observedFault device=$deviceRequests cache=$cacheAtomicRequests lower=$lowerRequests")
    Files.writeString(deviceRoot.resolve("validation.json"),
      s"""{"status":"passed","device_atomic_rejected_before_io":true,"fault_cause":4,"device_requests":$deviceRequests,"cache_atomic_requests":$cacheAtomicRequests,"lower_requests":$lowerRequests,"cycles":$cycle}\n""")
  }
  ApeSimArtifactCleanup.discardVerilatorBuildTree(root.resolve("rtl"), "PpeCachedDataTile")
  ApeSimArtifactCleanup.discardVerilatorBuildTree(deviceRoot.resolve("rtl"), "PpeCachedDataTile")
  println("PPE scalar AMOADD through memory engine and D-L1 passed")
}
