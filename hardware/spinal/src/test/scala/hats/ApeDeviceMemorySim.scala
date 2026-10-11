package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import scala.collection.mutable

/** Executes real APE cacheable RAM and uncached device operations through RTL.
  * The testbench is only the external line/device service; it checks that D-L1
  * clean completes before the first device request and that device traffic never
  * enters the cacheable line interface.
  */
object ApeDeviceMemorySim extends App {
  val out = Paths.get(args.headOption.getOrElse("build/s04/ape-device")); Files.createDirectories(out)
  val m = MemoryHierarchyConfig(sets = 8, lineBytes = 32, mshrs = 4)
  val deviceRegion = Seq((BigInt(0x20000), BigInt(0x20010)))
  val code = Vector(BigInt("000100b7",16), BigInt("05a00113",16), BigInt("0020b023",16),
    BigInt("000201b7",16), BigInt("0001b203",16), BigInt("0021b423",16),
    BigInt("0081b283",16), BigInt("0ff0000f",16), BigInt("00100073",16))
  val bytes = Array.fill[Byte](0x110000)(0)
  for ((inst, i) <- code.zipWithIndex; b <- 0 until 4) bytes(i*4+b) = ((inst >> (8*b)) & 255).toByte
  def readWord(address: Int): BigInt = (0 until 8).foldLeft(BigInt(0))((v,b) => v | (BigInt(bytes(address+b) & 255) << (8*b)))
  def writeWord(address: Int, value: BigInt): Unit = for (b <- 0 until 8) bytes(address+b) = ((value >> (8*b)) & 255).toByte
  case class Line(slot: Int, generation: Int, write: Boolean, address: Int, words: Vector[BigInt], source: Int, due: Int)
  case class Device(id: Int, epoch: Int, address: BigInt, write: Boolean, data: BigInt, mask: Int, due: Int)
  val linePending = mutable.ArrayBuffer[Line]()
  val devicePending = mutable.Queue[Device]()
  var cycles = 0; var lowerAccepted = 0; var lowerCompleted = 0; var deviceAccepted = 0
  var deviceReads = 0; var deviceWrites = 0; var deviceStalls = 0; var retired = 0
  var sawCleanBeforeDevice = false
  var injectedBadId = false; var rejectedBadId = false
  var injectedBadEpoch = false; var rejectedBadEpoch = false

  for (instructionCache <- Seq(false, true)) {
    val deviceBefore = deviceAccepted; val readBefore = deviceReads; val writeBefore = deviceWrites
    val dut = SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
      .workspacePath(out.resolve(if (instructionCache) "id" else "d").toString)
      .compile(new ApeCachedDataTile(m, instructionCache = instructionCache, deviceRegions = deviceRegion))
    dut.doSim(if (instructionCache) "ape_device_id" else "ape_device_d") { d =>
      def edge(): Unit = { d.clockDomain.risingEdge(); sleep(5); d.clockDomain.fallingEdge(); sleep(5); cycles += 1 }
      d.clockDomain.clockSim #= false; d.clockDomain.assertReset()
      d.io.program.valid #= false; d.io.program.index #= 0; d.io.program.instruction #= 0
      d.io.launch.valid #= false; d.io.launch.pc #= 0; d.io.launch.argument #= 0
      d.io.launch.base #= 0; d.io.launch.limit #= 0x30000; d.io.launch.writable #= true
      d.io.halt.ready #= true; d.io.lower.ready #= false; d.io.reply.valid #= false
      d.io.reply.slot #= 0; d.io.reply.generation #= 0; d.io.reply.write #= false
      d.io.reply.error #= false; d.io.reply.data.foreach(_ #= 0)
      if (instructionCache) d.io.replySource #= 0
      d.io.deviceRequest.ready #= false; d.io.deviceResponse.valid #= false
      d.io.deviceResponse.id #= 0; d.io.deviceResponse.epoch #= 0; d.io.deviceResponse.data #= 0; d.io.deviceResponse.error #= false
      d.io.flush.valid #= false; d.io.flush.payload #= true; d.io.flushed.ready #= true
      for (_ <- 0 until 4) edge(); d.clockDomain.deassertReset(); edge()
      for ((inst, index) <- code.zipWithIndex) {
        d.io.program.valid #= true; d.io.program.index #= index; d.io.program.instruction #= inst
        edge()
      }
      d.io.program.valid #= false
      d.io.launch.valid #= true
      var waitLaunch = 0
      while (!d.io.launch.ready.toBoolean && waitLaunch < 50) { edge(); waitLaunch += 1 }
      assert(d.io.launch.ready.toBoolean); edge(); d.io.launch.valid #= false
      var heldDevice: Option[Device] = None
      var heldLine: Option[Line] = None
      var done = false
      while (!done && cycles < 20000) {
        d.io.lower.ready #= cycles % 4 != 1
        d.io.deviceRequest.ready #= cycles % 5 >= 2
        if (d.io.deviceRequest.valid.toBoolean && !d.io.deviceRequest.ready.toBoolean) deviceStalls += 1
        val dueLine = linePending.indices.filter(i => linePending(i).due <= cycles).lastOption
        d.io.reply.valid #= dueLine.nonEmpty
        dueLine.foreach { index =>
          val r = linePending(index)
          if (instructionCache) d.io.replySource #= r.source
          d.io.reply.slot #= r.slot; d.io.reply.generation #= r.generation; d.io.reply.write #= r.write
          d.io.reply.error #= false
          for (w <- 0 until m.words) d.io.reply.data(w) #= (0 until 8).foldLeft(BigInt(0))((v,b) => v | (BigInt(bytes(r.address+w*8+b) & 255) << (8*b)))
        }
        val dueDevice = devicePending.headOption.filter(_.due <= cycles)
        d.io.deviceResponse.valid #= dueDevice.nonEmpty
        dueDevice.foreach { req =>
          val wrongId = !instructionCache && !injectedBadId
          val wrongEpoch = instructionCache && !injectedBadEpoch
          d.io.deviceResponse.id #= (if (wrongId) req.id ^ 1 else req.id)
          d.io.deviceResponse.epoch #= (if (wrongEpoch) req.epoch ^ 1 else req.epoch)
          d.io.deviceResponse.data #= (if (req.address == 0x20000) BigInt("12345678",16) else readWord(req.address.toInt))
          d.io.deviceResponse.error #= false
          if (wrongId) injectedBadId = true
          if (wrongEpoch) injectedBadEpoch = true
        }
        sleep(1)
        val line = if (d.io.lower.valid.toBoolean) Some(Line(d.io.lower.slot.toInt, d.io.lower.generation.toInt,
          d.io.lower.write.toBoolean, d.io.lower.address.toBigInt.toInt, d.io.lower.data.map(_.toBigInt).toVector,
          if (instructionCache) d.io.lowerSource.toInt else 0, cycles+7)) else None
        heldLine.foreach(r => assert(line.map(_.copy(due = r.due)).contains(r), "lower line changed under backpressure"))
        heldLine = if (line.nonEmpty && !d.io.lower.ready.toBoolean) line else None
        heldDevice.foreach(r => assert(d.io.deviceRequest.valid.toBoolean &&
          d.io.deviceRequest.id.toInt == r.id && d.io.deviceRequest.epoch.toInt == r.epoch &&
          d.io.deviceRequest.address.toBigInt == r.address && d.io.deviceRequest.write.toBoolean == r.write &&
          d.io.deviceRequest.data.toBigInt == r.data && d.io.deviceRequest.mask.toInt == r.mask,
          "device request changed under backpressure"))
        heldDevice = if (d.io.deviceRequest.valid.toBoolean && !d.io.deviceRequest.ready.toBoolean)
          Some(Device(d.io.deviceRequest.id.toInt, d.io.deviceRequest.epoch.toInt, d.io.deviceRequest.address.toBigInt,
            d.io.deviceRequest.write.toBoolean, d.io.deviceRequest.data.toBigInt, d.io.deviceRequest.mask.toInt, cycles)) else None
        dueLine.foreach { i => if (d.io.reply.ready.toBoolean) { linePending.remove(i); lowerCompleted += 1 } }
        line.filter(_ => d.io.lower.ready.toBoolean).foreach { req =>
          if (req.write) for (w <- 0 until m.words; b <- 0 until 8) bytes(req.address+w*8+b) = ((req.words(w) >> (8*b)) & 255).toByte
          linePending += req.copy(due = cycles+7); lowerAccepted += 1
        }
        if (d.io.deviceRequest.valid.toBoolean && d.io.deviceRequest.ready.toBoolean) {
          val req = Device(d.io.deviceRequest.id.toInt, d.io.deviceRequest.epoch.toInt, d.io.deviceRequest.address.toBigInt,
            d.io.deviceRequest.write.toBoolean, d.io.deviceRequest.data.toBigInt, d.io.deviceRequest.mask.toInt, cycles+6)
          assert(req.address >= 0x20000 && req.address < 0x20010, s"device escaped aperture: ${req.address}")
          assert(readWord(0x10000) == 0x5a, "device request observed before dirty RAM store was cleaned")
          sawCleanBeforeDevice = true
          if (req.write) {
            for (b <- 0 until 8 if (req.mask & (1 << b)) != 0) {
              val old = readWord(req.address.toInt)
              writeWord(req.address.toInt, (old & ~(BigInt(255) << (8*b))) | (((req.data >> (8*b)) & 255) << (8*b)))
            }
            deviceWrites += 1
          } else deviceReads += 1
          devicePending.enqueue(req.copy(due = cycles+6)); deviceAccepted += 1
        }
        if (dueDevice.nonEmpty && !d.io.deviceResponse.ready.toBoolean && injectedBadId) rejectedBadId = true
        if (dueDevice.nonEmpty && !d.io.deviceResponse.ready.toBoolean && injectedBadEpoch) rejectedBadEpoch = true
        if (dueDevice.nonEmpty && d.io.deviceResponse.ready.toBoolean) devicePending.dequeue()
        if (d.io.retired.valid.toBoolean) retired += 1
        if (d.io.halt.valid.toBoolean) done = true
        edge()
      }
      assert(done, "APE device program timed out")
      assert(d.io.halt.cause.toInt == 3, s"unexpected APE halt cause ${d.io.halt.cause.toInt}")
      assert(deviceAccepted-deviceBefore == 3 && deviceReads-readBefore == 2 && deviceWrites-writeBefore == 1,
        s"device traffic count mismatch: accepted=${deviceAccepted-deviceBefore} reads=${deviceReads-readBefore} writes=${deviceWrites-writeBefore}")
      val expectedMalformedResponseRejected = if (instructionCache) rejectedBadEpoch else rejectedBadId
      assert(sawCleanBeforeDevice && expectedMalformedResponseRejected && deviceStalls > 0 &&
        linePending.isEmpty && devicePending.isEmpty,
        s"device drain mismatch: lines=${linePending.toVector} devices=${devicePending.toVector} clean=$sawCleanBeforeDevice idRejected=$rejectedBadId epochRejected=$rejectedBadEpoch stalls=$deviceStalls")
      assert(readWord(0x10000) == 0x5a && readWord(0x20008) == 0x5a)
      assert(!linePending.exists(_.address >= 0x20000), "device region used cacheable line interface")
      if (instructionCache) assert(d.io.fetchRequests.toBigInt > 0 && d.io.instructionMisses.toBigInt > 0)
    }
    ApeSimArtifactCleanup.discardVerilatorBuildTree(out.resolve(if (instructionCache) "id" else "d"), "ApeCachedDataTile")
  }
  assert(rejectedBadId && rejectedBadEpoch, "malformed device response ID and epoch were not both rejected")
  Files.writeString(out.resolve("validation.json"),
    s"""{"status":"passed","issue":5,"S04_complete":false,"claim_class":"actual_APE_D_L1_clean_then_uncached_device_RTL","instruction_cache_profiles":2,"device_requests":$deviceAccepted,"device_reads":$deviceReads,"device_writes":$deviceWrites,"lower_requests":$lowerAccepted,"lower_completions":$lowerCompleted,"device_backpressure_cycles":$deviceStalls,"clean_before_every_device_request":$sawCleanBeforeDevice,"malformed_response_id_rejected":$rejectedBadId,"malformed_response_epoch_rejected":$rejectedBadEpoch,"limits":["Device service is a behavioral testbench model","No concurrent PPE device service or shared atomics claimed"]}\n""")
  println(s"APE uncached device RTL passed: $deviceAccepted requests, $deviceReads reads, $deviceWrites writes")
}
