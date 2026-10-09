package hats

import spinal.core._
import spinal.core.sim._
import java.nio.{ByteBuffer, ByteOrder}
import java.nio.file.{Files, Paths, Path}
import java.nio.charset.StandardCharsets
import java.io.PrintWriter
import scala.collection.mutable
import scala.util.Random

/** Large-image APE application profile. The same ELF/input bytes run in Spike.
  * Only the external memory service is modeled; no parser or ISA interpretation.
  */
object ApeToolSim extends App {
  require(args.length == 3, "parser-folder rob-entries prediction-mode")
  val root = Paths.get(args(0)).toAbsolutePath
  val entries = args(1).toInt
  val mode = args(2)
  require(Set("off", "bimodal").contains(mode))
  val out = root.resolve(s"rtl-r$entries-$mode"); Files.createDirectories(out)
  def lines(path: Path): Vector[String] = {
    val src = scala.io.Source.fromFile(path.toFile)
    try src.getLines().toVector finally src.close()
  }
  def save(name: String, text: String): Unit = Files.write(out.resolve(name), text.getBytes(StandardCharsets.UTF_8))
  save("validation.json", "{\"status\":\"running\"}\n")
  val properties = lines(root.resolve("runtime.properties")).map { line =>
    val pair = line.split("=", 2); pair(0) -> pair(1).toInt
  }.toMap
  val code = Files.readAllBytes(root.resolve("code.bin"))
  require(code.length == 0x40000)
  val words = ByteBuffer.wrap(code).order(ByteOrder.LITTLE_ENDIAN)
  val program = Vector.fill(code.length / 4)(words.getInt().toLong & 0xffffffffL)
  val names = lines(root.resolve("rtl-cases.txt"))
  require(names.nonEmpty && names.distinct.size == names.size && names.forall(_.matches("[a-z0-9_-]+")))
  val compiled = SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(out.resolve("sim").toString)
    .compile(new ApeCore(ApeConfig(robEntries = entries, programWords = 65536, prediction = mode == "bimodal")))
  case class Request(address: BigInt, data: BigInt, size: Int, write: Boolean)
  val results = mutable.ArrayBuffer[String]()
  names.zipWithIndex.foreach { case (name, caseIndex) =>
    compiled.doSim(name, seed = caseIndex + 1) { dut =>
      def edge(): Unit = {
        dut.clockDomain.risingEdge(); sleep(5)
        dut.clockDomain.fallingEdge(); sleep(5)
      }
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
      dut.io.launch.valid #= false; dut.io.launch.pc #= 0; dut.io.launch.argument #= 0x180000
      dut.io.launch.base #= 0x100000; dut.io.launch.limit #= 0x1100000; dut.io.launch.writable #= true
      dut.io.memory.ready #= false; dut.io.response.valid #= false; dut.io.response.data #= 0
      dut.io.response.error #= false; dut.io.halt.ready #= false
      for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      for (i <- program.indices) {
        dut.io.program.valid #= true; dut.io.program.index #= i; dut.io.program.instruction #= program(i); edge()
      }
      dut.io.program.valid #= false
      for (invocation <- 0 until 2) {
        val memory = Files.readAllBytes(root.resolve("data.bin")); require(memory.length == 0x1000000)
        def overlay(file: String, address: Int): Unit = {
          val input = Files.readAllBytes(root.resolve(name).resolve(file))
          Array.copy(input, 0, memory, address - 0x100000, input.length)
        }
        overlay("args.bin", 0x180000); overlay("old.bin", 0x181000); overlay("new.bin", 0x1c1000)
        java.util.Arrays.fill(memory, 0x110000, 0x200000, 0xcc.toByte)
        val log = new PrintWriter(out.resolve(s"$name-$invocation.trace.jsonl").toFile)
        val rng = new Random(1000 + caseIndex * 2 + invocation)
        var pending: Option[(Int, BigInt, Boolean)] = None
        var held: Option[Request] = None
        var cycles, retired, requests, stalls = 0
        var minimumSp = BigInt(0x1000000)
        var halted = false
        var result = BigInt(0)
        def span(address: BigInt, bytes: Int, lo: Int, hi: Int): Boolean = address >= lo && address < hi && address + bytes <= hi
        try {
          dut.io.launch.valid #= true; sleep(1); assert(dut.io.launch.ready.toBoolean)
          edge(); dut.io.launch.valid #= false
          while (!halted && cycles < 30000000) {
            dut.io.memory.ready #= (cycles % 5 >= 2 && rng.nextInt(4) != 0)
            val reply = pending.filter(_._1 <= cycles)
            dut.io.response.valid #= reply.nonEmpty; dut.io.response.data #= reply.map(_._2).getOrElse(BigInt(0))
            dut.io.response.error #= reply.exists(_._3)
            sleep(1)
            val request = if (dut.io.memory.valid.toBoolean) Some(Request(dut.io.memory.address.toBigInt,
              dut.io.memory.data.toBigInt, dut.io.memory.size.toInt, dut.io.memory.write.toBoolean)) else None
            held.foreach(previous => assert(request.contains(previous), "held request changed"))
            held = if (!dut.io.memory.ready.toBoolean) request else None
            if (held.nonEmpty) stalls += 1
            if (reply.nonEmpty && dut.io.response.ready.toBoolean) pending = None
            if (request.nonEmpty && dut.io.memory.ready.toBoolean) {
              assert(pending.isEmpty, "multiple outstanding requests")
              val r = request.get; val bytes = 1 << r.size
              assert(r.address % bytes == 0)
              val shared = span(r.address, bytes, 0x210000, 0x300000) || span(r.address, bytes, 0x400000, 0xe00000) ||
                span(r.address, bytes, 0xf00000, 0x1000000)
              val permitted = shared || span(r.address, bytes, if (r.write) properties("writable_start") else 0x100000, properties("bss_end")) ||
                (!r.write && (span(r.address, bytes, 0x180000, 0x180040) || span(r.address, bytes, 0x181000, 0x1c0000) ||
                  span(r.address, bytes, 0x1c1000, 0x200000)))
              var value = BigInt(0)
              if (permitted) {
                val offset = r.address.toInt - 0x100000
                if (r.write) {
                  value = r.data & ((BigInt(1) << (8 * bytes)) - 1)
                  for (i <- 0 until bytes) memory(offset + i) = ((value >> (8 * i)) & 255).toByte
                } else value = (0 until bytes).map(i => BigInt(memory(offset + i) & 255) << (8 * i)).foldLeft(BigInt(0))(_ | _)
              }
              pending = Some((cycles + 2 + rng.nextInt(8), value, !permitted)); requests += 1
              log.println(s"""{"kind":"memory","address":"${r.address}","bytes":$bytes,"write":${r.write},"data":"$value","error":${!permitted}}""")
            }
            if (dut.io.retired.valid.toBoolean) {
              val writes = dut.io.retired.writes.toBoolean
              val rd = if (writes) dut.io.retired.rd.toInt else 0
              val value = if (writes) dut.io.retired.value.toBigInt else BigInt(0)
              val pc = dut.io.retired.pc.toBigInt
              val next = if (dut.io.controlRetired.valid.toBoolean) dut.io.controlRetired.actualNext.toBigInt else pc + 4
              if (writes && rd == 2) { assert(value >= 0xf00000 && value <= 0x1000000 && value % 16 == 0); minimumSp = minimumSp.min(value) }
              log.println(s"""{"kind":"retire","pc":"$pc","instruction":${dut.io.retired.instruction.toLong},"writes":$writes,"rd":$rd,"value":"$value","next":"$next"}""")
              retired += 1
            }
            if (dut.io.halt.valid.toBoolean) {
              assert(dut.io.halt.cause.toInt == 3 && dut.io.halt.pc.toBigInt == properties("exit_pc"),
                s"unexpected trap ${dut.io.halt.cause.toInt} at ${dut.io.halt.pc.toBigInt}")
              assert(pending.isEmpty && held.isEmpty, "halt before drain")
              result = dut.io.halt.value.toBigInt
              log.println(s"""{"kind":"trap","pc":"${dut.io.halt.pc.toBigInt}","cause":3,"value":"$result"}""")
              halted = true
            }
            edge(); cycles += 1
          }
          assert(halted, "tool cycle budget exhausted")
          Files.write(out.resolve(s"$name-$invocation.result.bin"), memory.slice(0x110000, 0x200000))
          for (_ <- 0 until 8) {
            dut.io.response.valid #= false
            assert(dut.io.halt.valid.toBoolean && !dut.io.launch.ready.toBoolean && dut.io.halt.value.toBigInt == result)
            assert(!dut.io.memory.valid.toBoolean && !dut.io.retired.valid.toBoolean); edge()
          }
          dut.io.halt.ready #= true; edge(); dut.io.halt.ready #= false
          results += s"""{"case":"$name","invocation":$invocation,"cycles":$cycles,"retired":$retired,"requests":$requests,"stalls":$stalls,"stack_bytes":${0x1000000-minimumSp.toInt},"result":$result}"""
        } finally log.close()
      }
    }
  }
  save("validation.json", s"""{"status":"passed","rob_entries":$entries,"prediction":"$mode","program_words":65536,"runs":[${results.mkString(",")}]}\n""")
  println(s"APE real-tool RTL: ${results.size} invocations; ROB=$entries, prediction=$mode")
}
