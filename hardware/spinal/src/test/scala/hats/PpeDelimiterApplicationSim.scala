package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Path, Paths}
import scala.collection.mutable

/** One real PPE task across all delimiter groups, with I/D-L1 retained. */
object PpeDelimiterApplicationSim extends App {
  require(args.length == 4 || args.length == 5, "case directory output directory sets mshrs [delimiter|ai_relu]")
  val root = Paths.get(args(0)).toAbsolutePath; val out = Paths.get(args(1)).toAbsolutePath
  Files.createDirectories(out)
  val sets = args(2).toInt; val mshrs = args(3).toInt
  val kernel = if (args.length == 5) args(4) else "delimiter"
  require(Set("delimiter", "ai_relu").contains(kernel), s"unsupported PPE application kernel: $kernel")
  val m = MemoryHierarchyConfig(sets = sets, mshrs = mshrs, wordPoison = true)
  val lineBytes = m.lineBytes; val instructionBase = 0x100000
  val fixtureName = if (kernel == "delimiter") "delimiter_256_g0" else "ai_relu_256_g0"
  val folder = root.resolve(fixtureName)
  val p = scala.io.Source.fromFile(folder.resolve("case.properties").toFile).getLines()
    .map(_.split("=", 2)).map(a => a(0) -> BigInt(a(1))).toMap
  val code = scala.io.Source.fromFile(folder.resolve("code.hex").toFile).getLines().map(BigInt(_, 16)).toVector
  val codeMemory = Array.fill[Byte](8192)(0)
  code.indices.foreach(w => (0 until 8).foreach(b => codeMemory(w*8+b) = ((code(w) >> (8*b)) & 255).toByte))
  val original = Files.readAllBytes(folder.resolve("memory.bin")); val memory = original.clone()
  val inputAddr = 256; val outputAddr = (if (kernel == "delimiter") 1024 else 2304)
  val length = 256
  val expected = original.clone()
  if (kernel == "delimiter") {
    val delimiters = "{}[]:,".getBytes("US-ASCII")
    for (n <- 0 until length) expected(outputAddr+n) = (if (delimiters.contains(original(inputAddr+n))) 1 else 0).toByte
  } else {
    val inputA = 256; val inputB = 1280
    def readI32(address: Int): Int = (0 until 4).foldLeft(0)((v, b) => v | ((original(address+b) & 0xff) << (8*b)))
    def writeI32(address: Int, value: Int): Unit = (0 until 4).foreach(b => expected(address+b) = (value >>> (8*b)).toByte)
    for (n <- 0 until 256) writeI32(outputAddr+n*4, math.max(0, readI32(inputA+n*4) + readI32(inputB+n*4)))
  }

  SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(out.resolve("sim").toString).compile(new PpeCachedDataTile(m, instructionCache = true))
    .doSim("ppe_delimiter_application", seed = 0x5a04) { dut =>
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      dut.clockDomain.clockSim #= false
      dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
      dut.io.launch.valid #= false; dut.io.launch.task #= 0; dut.io.launch.epoch #= 0
      dut.io.launch.argument #= 0; dut.io.launch.argumentBytes #= 0; dut.io.launch.addressSpace #= 0
      dut.io.launch.generation #= 0; dut.io.launch.group #= 0; dut.io.launch.groups #= 0
      dut.io.launch.budget #= 0; dut.io.launch.base #= 0; dut.io.launch.limit #= 0
      dut.io.launch.writable #= false; dut.io.launch.codeWords #= 0; dut.io.launch.scratchBytes #= 0
      dut.io.completion.ready #= false; dut.io.inspectScratch #= 0
      dut.io.deviceRequest.ready #= false; dut.io.deviceResponse.valid #= false
      dut.io.deviceResponse.id #= 0; dut.io.deviceResponse.epoch #= 0; dut.io.deviceResponse.data #= 0
      dut.io.deviceResponse.error #= false; dut.io.lower.ready #= false; dut.io.reply.valid #= false
      dut.io.reply.slot #= 0; dut.io.reply.generation #= 0; dut.io.reply.write #= false
      dut.io.reply.error #= false; dut.io.reply.poison #= 0; dut.io.reply.data.foreach(_ #= 0)
      dut.io.replySource #= 0; dut.io.flush.valid #= false; dut.io.flush.payload #= false
      dut.io.flushed.ready #= false
      dut.clockDomain.assertReset(); for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      code.indices.foreach { i =>
        dut.io.program.valid #= true; dut.io.program.index #= i; dut.io.program.instruction #= 0
        sleep(1); assert(dut.io.program.ready.toBoolean); edge()
      }
      dut.io.program.valid #= false

      case class Request(source: Int, slot: Int, generation: Int, address: Int, write: Boolean,
                         data: Vector[BigInt], poison: Int, due: Int)
      val pending = mutable.ArrayBuffer[Request]()
      var cycle = 0; var accepted = 0; var completed = 0; var stalls = 0; var reordered = 0
      var fetches = 0; var loads = 0; var stores = 0; var retired = 0; var maxPending = 0
      var held: Option[(Int, Int, Int, Int, Boolean, Vector[BigInt], Int)] = None
      val rnd = new scala.util.Random(0x5a04)
      def tick(): Unit = {
        val due = pending.indices.filter(i => pending(i).due <= cycle).lastOption
        dut.io.reply.valid #= due.nonEmpty
        due.foreach { i => val r = pending(i); dut.io.replySource #= r.source; dut.io.reply.slot #= r.slot
          dut.io.reply.generation #= r.generation; dut.io.reply.write #= r.write; dut.io.reply.error #= false
          dut.io.reply.poison #= r.poison
          val backing = if (r.source == 0) codeMemory else memory
          val offset = r.address - (if (r.source == 0) instructionBase else 0)
          for (w <- 0 until m.words) dut.io.reply.data(w) #= (0 until 8).foldLeft(BigInt(0))((v,b) => v | (BigInt(backing(offset+w*8+b) & 255) << (8*b)))
        }
        dut.io.lower.ready #= (cycle % 6 >= 2 && rnd.nextInt(5) != 0)
        sleep(1)
        val bus = if (dut.io.lower.valid.toBoolean) Some((dut.io.lowerSource.toInt, dut.io.lower.slot.toInt,
          dut.io.lower.generation.toInt, dut.io.lower.address.toBigInt.toInt, dut.io.lower.write.toBoolean,
          dut.io.lower.data.map(_.toBigInt).toVector, dut.io.lower.poison.toInt)) else None
        held.foreach(r => assert(bus.contains(r), "lower request changed under backpressure"))
        held = if (!dut.io.lower.ready.toBoolean) bus else None
        if (held.nonEmpty) stalls += 1
        due.foreach { i =>
          assert(dut.io.reply.ready.toBoolean)
          val r = pending.remove(i); if (i < pending.size) reordered += 1
          if (r.write) for (w <- 0 until m.words; b <- 0 until 8) memory(r.address+w*8+b) = ((r.data(w) >> (8*b)) & 255).toByte
          completed += 1
        }
        bus.filter(_ => dut.io.lower.ready.toBoolean).foreach { r =>
          val (source, slot, gen, addr, write, data, poison) = r
          val backing = if (source == 0) codeMemory else memory; val offset = addr - (if (source == 0) instructionBase else 0)
          assert(addr % lineBytes == 0 && offset >= 0 && offset+lineBytes <= backing.length)
          assert(!pending.exists(x => x.source == source && x.slot == slot))
          if (source == 0) { assert(!write); fetches += 1 }
          val delay = if (source == 0) 2 else 9 + rnd.nextInt(23)
          pending += Request(source, slot, gen, addr, write, data, poison, cycle+delay); accepted += 1
        }
        if (dut.io.access.valid.toBoolean && !dut.io.access.scratch.toBoolean) {
          assert(dut.io.access.error.toInt == 0)
          if (dut.io.access.write.toBoolean) stores += 1 else loads += 1
        }
        if (dut.io.retired.valid.toBoolean) { assert(pending.isEmpty && held.isEmpty && dut.io.outstanding.toInt == 0); retired += 1 }
        maxPending = maxPending.max(pending.size)
        edge(); cycle += 1; assert(cycle < 300000, "PPE delimiter task timed out")
      }
      var groups = 0
      for (group <- 0 until 32) {
        dut.io.launch.task #= p("task"); dut.io.launch.epoch #= 100+group
        dut.io.launch.argument #= 0; dut.io.launch.argumentBytes #= 24; dut.io.launch.addressSpace #= 2
        dut.io.launch.generation #= 3; dut.io.launch.group #= group; dut.io.launch.groups #= 32
        dut.io.launch.budget #= 1000000; dut.io.launch.base #= 0; dut.io.launch.limit #= original.length
        dut.io.launch.writable #= true; dut.io.launch.codeWords #= code.size; dut.io.launch.scratchBytes #= 0
        dut.io.launch.valid #= true; sleep(1); assert(dut.io.launch.ready.toBoolean); edge(); dut.io.launch.valid #= false
        while (!dut.io.completion.valid.toBoolean) tick()
        assert(dut.io.completion.status.toInt == 1, s"group $group failed cause=${dut.io.completion.cause.toInt}")
        assert(pending.isEmpty && held.isEmpty && dut.io.outstanding.toInt == 0)
        dut.io.completion.ready #= true; tick(); dut.io.completion.ready #= false; groups += 1
      }
      var flushed = false; var sent = false
      while (!flushed) {
        dut.io.flush.valid #= !sent; dut.io.flushed.ready #= (cycle % 4 == 0)
        sleep(1)
        val take = dut.io.flush.valid.toBoolean && dut.io.flush.ready.toBoolean
        val ack = dut.io.flushed.valid.toBoolean && dut.io.flushed.ready.toBoolean
        if (ack) assert(!dut.io.flushed.payload.toBoolean)
        tick(); sent ||= take; flushed ||= ack
      }
      dut.io.flush.valid #= false; dut.io.flushed.ready #= false
      assert(dut.io.clean.toBoolean && dut.io.idle.toBoolean && accepted == completed && pending.isEmpty)
      assert(memory.sameElements(expected), s"final backing memory differs from independent $kernel oracle")
      Files.write(out.resolve("output-memory.bin"), memory)
      val digest = java.security.MessageDigest.getInstance("SHA-256").digest(expected).map(b => f"${b & 0xff}%02x").mkString
      val report = s"""{"status":"passed","claim_class":"actual_PPE_I_D_L1_32_group_task","kernel":"$kernel","groups_completed":$groups,"input_bytes":$length,"loads":$loads,"stores":$stores,"retired":$retired,"instruction_fetches":$fetches,"accepted_lines":$accepted,"completed_lines":$completed,"reorders":$reordered,"request_stalls":$stalls,"max_outstanding":$maxPending,"i_hits":${dut.io.instructionHits.toBigInt},"i_misses":${dut.io.instructionMisses.toBigInt},"d_hits":${dut.io.hits.toBigInt},"d_misses":${dut.io.misses.toBigInt},"sets":$sets,"mshrs":$mshrs,"output_sha256":"$digest"}"""
      Files.writeString(out.resolve("validation.json"), report + "\n")
    }
}
