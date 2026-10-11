package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import scala.collection.mutable

/** Executes a PPE store/load program through I/D-L1 and a serialized uncached device aperture. */
object PpeDeviceMemorySim extends App {
  val out = Paths.get(args.headOption.getOrElse("build/s04/ppe-device")); Files.createDirectories(out)
  val m = MemoryHierarchyConfig(sets = 8, lineBytes = 32, mshrs = 4, wordPoison = true)
  val aperture = Seq((BigInt(0x20000), BigInt(0x20008)))
  def instruction(op: Int, d: Int = 0, a: Int = 0, width: Int = 0, imm: Long = 0): BigInt =
    BigInt(op) | (BigInt(d) << 8) | (BigInt(a) << 13) | (BigInt(width) << 26) |
      ((BigInt(imm) & BigInt("ffffffff", 16)) << 32)
  val program = Vector(
    instruction(1, d = 8, width = 3, imm = 0x10000),
    instruction(1, d = 9, width = 3, imm = 0x5a),
    instruction(32, d = 9, a = 8, width = 3),
    instruction(1, d = 8, width = 3, imm = 0x20000),
    instruction(1, d = 9, width = 3, imm = 0x12345678),
    instruction(32, d = 9, a = 8, width = 3),
    instruction(31, d = 10, a = 8, width = 3),
    instruction(37, a = 10))
  val instructionBase = 0x100000
  val memory = Array.fill[Byte](0x110000)(0)
  for ((inst, i) <- program.zipWithIndex; b <- 0 until 8)
    memory(instructionBase + i*8 + b) = ((inst >> (8*b)) & 255).toByte
  case class Line(source: Int, slot: Int, generation: Int, write: Boolean, address: Int, words: Vector[BigInt], due: Int)
  case class Device(id: Int, epoch: Int, address: BigInt, write: Boolean, data: BigInt, mask: Int,
                    due: Int)
  val linePending = mutable.ArrayBuffer[Line]()
  val devicePending = mutable.Queue[Device]()
  var cycle = 0
  var lowerAccepted = 0; var lowerCompleted = 0
  var deviceAccepted = 0; var deviceReads = 0; var deviceWrites = 0; var deviceStalls = 0
  var cleanBeforeDevice = true; var rejectedBadId = false; var rejectedBadEpoch = false
  var injectedBadId = false; var injectedBadEpoch = false
  var deviceValue = BigInt(0)
  var completion: Option[(Int, Int, BigInt)] = None
  val dut = SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(out.resolve("sim").toString)
    .compile(new PpeCachedDataTile(m, instructionCache = true, instructionBase = instructionBase,
      deviceRegions = aperture))
  dut.doSim("ppe_uncached_device") { d =>
    def edge(): Unit = { d.clockDomain.risingEdge(); sleep(5); d.clockDomain.fallingEdge(); sleep(5); cycle += 1 }
    d.clockDomain.clockSim #= false; d.clockDomain.assertReset()
    d.io.program.valid #= false; d.io.program.index #= 0; d.io.program.instruction #= 0
    d.io.launch.valid #= false; d.io.launch.task #= 1; d.io.launch.epoch #= 1
    d.io.launch.argument #= 0; d.io.launch.argumentBytes #= 0; d.io.launch.addressSpace #= 2
    d.io.launch.generation #= 1; d.io.launch.group #= 0; d.io.launch.groups #= 1
    d.io.launch.budget #= 10000; d.io.launch.base #= 0x10000; d.io.launch.limit #= 0x20008
    d.io.launch.writable #= true; d.io.launch.codeWords #= program.length; d.io.launch.scratchBytes #= 0
    d.io.completion.ready #= true; d.io.inspectScratch #= 0
    d.io.lower.ready #= false; d.io.reply.valid #= false; d.io.reply.slot #= 0
    d.io.reply.generation #= 0; d.io.reply.write #= false; d.io.reply.error #= false
    d.io.reply.poison #= 0; d.io.reply.data.foreach(_ #= 0)
    d.io.deviceRequest.ready #= false; d.io.deviceResponse.valid #= false
    d.io.deviceResponse.id #= 0; d.io.deviceResponse.epoch #= 0
    d.io.deviceResponse.data #= 0; d.io.deviceResponse.error #= false
    d.io.replySource #= 0
    d.io.flush.valid #= false; d.io.flush.payload #= true; d.io.flushed.ready #= true
    for (_ <- 0 until 4) edge(); d.clockDomain.deassertReset(); edge()
    program.zipWithIndex.foreach { case (word, i) =>
      d.io.program.valid #= true; d.io.program.index #= i; d.io.program.instruction #= 0
      sleep(1); assert(d.io.program.ready.toBoolean); edge()
    }
    d.io.program.valid #= false
    d.io.launch.valid #= true
    var launchWait = 0
    while (!d.io.launch.ready.toBoolean && launchWait < 50) { edge(); launchWait += 1 }
    assert(d.io.launch.ready.toBoolean, "PPE device launch timed out")
    edge(); d.io.launch.valid #= false
    var done = false
    var heldLine: Option[Line] = None
    var heldDevice: Option[Device] = None
    while (!done && cycle < 20000) {
      d.io.lower.ready #= cycle % 5 >= 2
      d.io.deviceRequest.ready #= cycle % 4 != 1
      if (d.io.deviceRequest.valid.toBoolean && !d.io.deviceRequest.ready.toBoolean) deviceStalls += 1
      val readyLine = linePending.indices.find(i => linePending(i).due <= cycle)
      d.io.reply.valid #= readyLine.nonEmpty
      readyLine.foreach { i =>
        val r = linePending(i)
        d.io.replySource #= r.source
        d.io.reply.slot #= r.slot; d.io.reply.generation #= r.generation; d.io.reply.write #= r.write
        d.io.reply.error #= false; d.io.reply.poison #= 0
        for (w <- 0 until m.words) {
          val value = (0 until 8).foldLeft(BigInt(0))((v, b) => v | (BigInt(memory(r.address + w*8 + b) & 255) << (8*b)))
          d.io.reply.data(w) #= value
        }
      }
      val dueDevice = devicePending.headOption.filter(_.due <= cycle)
      d.io.deviceResponse.valid #= dueDevice.nonEmpty
      dueDevice.foreach { req =>
        val wrongId = !injectedBadId
        val wrongEpoch = !wrongId && !injectedBadEpoch
        d.io.deviceResponse.id #= (if (wrongId) req.id ^ 1 else req.id)
        d.io.deviceResponse.epoch #= (if (wrongEpoch) req.epoch ^ 1 else req.epoch)
        d.io.deviceResponse.data #= deviceValue; d.io.deviceResponse.error #= false
        if (wrongId) injectedBadId = true
        else if (wrongEpoch) injectedBadEpoch = true
      }
      sleep(1)
      val line = if (d.io.lower.valid.toBoolean) Some(Line(d.io.lowerSource.toInt, d.io.lower.slot.toInt,
        d.io.lower.generation.toInt, d.io.lower.write.toBoolean, d.io.lower.address.toBigInt.toInt,
        d.io.lower.data.map(_.toBigInt).toVector, cycle+6)) else None
      heldLine.foreach(r => assert(line.map(_.copy(due = r.due)).contains(r), "PPE lower request changed under backpressure"))
      heldLine = if (line.nonEmpty && !d.io.lower.ready.toBoolean) line else None
      heldDevice.foreach(r => assert(d.io.deviceRequest.valid.toBoolean &&
        d.io.deviceRequest.id.toInt == r.id && d.io.deviceRequest.epoch.toInt == r.epoch &&
        d.io.deviceRequest.address.toBigInt == r.address && d.io.deviceRequest.write.toBoolean == r.write &&
        d.io.deviceRequest.data.toBigInt == r.data && d.io.deviceRequest.mask.toInt == r.mask,
        "PPE device request changed under backpressure"))
      heldDevice = if (d.io.deviceRequest.valid.toBoolean && !d.io.deviceRequest.ready.toBoolean)
        Some(Device(d.io.deviceRequest.id.toInt, d.io.deviceRequest.epoch.toInt, d.io.deviceRequest.address.toBigInt,
          d.io.deviceRequest.write.toBoolean, d.io.deviceRequest.data.toBigInt, d.io.deviceRequest.mask.toInt, cycle)) else None
      readyLine.foreach { i => if (d.io.reply.ready.toBoolean) { linePending.remove(i); lowerCompleted += 1 } }
      line.filter(_ => d.io.lower.ready.toBoolean).foreach { req =>
        assert(req.address >= 0 && req.address + m.lineBytes <= memory.length)
        assert(req.address < 0x20000 || req.address >= 0x20008, "PPE device address entered D-L1 lower interface")
        if (req.write) for (w <- 0 until m.words; b <- 0 until 8)
          memory(req.address+w*8+b) = ((req.words(w) >> (b*8)) & 255).toByte
        linePending += req; lowerAccepted += 1
      }
      if (d.io.deviceRequest.valid.toBoolean && d.io.deviceRequest.ready.toBoolean) {
        val req = Device(d.io.deviceRequest.id.toInt, d.io.deviceRequest.epoch.toInt, d.io.deviceRequest.address.toBigInt,
          d.io.deviceRequest.write.toBoolean, d.io.deviceRequest.data.toBigInt, d.io.deviceRequest.mask.toInt, cycle+5)
        assert(req.address == 0x20000 && req.mask == 255, s"unexpected PPE device request $req")
        cleanBeforeDevice &&= memory.slice(0x10000, 0x10008).map(_ & 255).toVector == Vector(0x5a,0,0,0,0,0,0,0)
        if (req.write) {
          for (b <- 0 until 8 if (req.mask & (1 << b)) != 0)
            deviceValue = (deviceValue & ~(BigInt(255) << (8*b))) | (((req.data >> (8*b)) & 255) << (8*b))
          deviceWrites += 1
        } else deviceReads += 1
        devicePending.enqueue(req); deviceAccepted += 1
      }
      dueDevice.foreach { req =>
        if (!d.io.deviceResponse.ready.toBoolean) {
          if (req.id != d.io.deviceResponse.id.toInt) rejectedBadId = true
          if (req.epoch != d.io.deviceResponse.epoch.toInt) rejectedBadEpoch = true
        } else devicePending.dequeue()
      }
      if (d.io.completion.valid.toBoolean) {
        completion = Some((d.io.completion.status.toInt, d.io.completion.cause.toInt, d.io.completion.value.toBigInt))
        done = true
      }
      edge()
    }
    assert(done, "PPE device program timed out")
  }
  assert(completion.contains((1, 0, BigInt("12345678", 16))), s"wrong PPE architectural result: $completion")
  assert(deviceAccepted == 2 && deviceWrites == 1 && deviceReads == 1 && deviceStalls > 0,
    s"PPE device counts mismatch: accepted=$deviceAccepted writes=$deviceWrites reads=$deviceReads stalls=$deviceStalls")
  assert(cleanBeforeDevice && rejectedBadId && rejectedBadEpoch, "PPE clean-before-device or malformed-response checks failed")
  assert(linePending.isEmpty && devicePending.isEmpty && lowerAccepted == lowerCompleted,
    s"PPE device drain mismatch: lines=$linePending devices=$devicePending lower=$lowerAccepted/$lowerCompleted")
  assert(memory.slice(0x10000, 0x10008).map(_ & 255).toVector == Vector(0x5a,0,0,0,0,0,0,0))
  Files.writeString(out.resolve("validation.json"),
    s"""{"status":"passed","issue":5,"S04_complete":false,"claim_class":"actual_PPE_I_D_L1_clean_then_uncached_device_RTL","instruction_cache":true,"device_requests":$deviceAccepted,"device_reads":$deviceReads,"device_writes":$deviceWrites,"device_backpressure_cycles":$deviceStalls,"clean_before_every_device_request":$cleanBeforeDevice,"malformed_response_id_rejected":$rejectedBadId,"malformed_response_epoch_rejected":$rejectedBadEpoch,"lower_accepted":$lowerAccepted,"lower_completed":$lowerCompleted,"architectural_completion":{"status":${completion.get._1},"cause":${completion.get._2},"value":"${completion.get._3}"},"limits":["Device behavior is a deterministic external testbench service","PPE scalar AMOADD is covered separately; cross-engine atomic serialization and atomic-device interaction are not established"]}\n""")
  println(s"PPE uncached device RTL passed: $deviceAccepted requests, $deviceReads reads, $deviceWrites writes")
}
