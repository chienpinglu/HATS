package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import java.nio.charset.StandardCharsets
import java.io.PrintWriter
import scala.collection.mutable
import scala.util.Random

/** Actual APE execution of a loaded application. No local ISA interpreter. */
object ApeApplicationSim extends App {
  val entries = args.headOption.map(_.toInt).getOrElse(8)
  val mode = args.lift(1).getOrElse("bimodal")
  require(Set("off", "bimodal").contains(mode))
  val root = Paths.get("build/ape_app")
  val out = root.resolve(s"r$entries-$mode")
  Files.createDirectories(out)
  def text(path: java.nio.file.Path): Vector[String] = {
    val source = scala.io.Source.fromFile(path.toFile)
    try source.getLines().toVector finally source.close()
  }
  def save(name: String, value: String): Unit =
    Files.write(out.resolve(name), value.getBytes(StandardCharsets.UTF_8))
  save("validation.json", "{\"status\":\"running\"}\n")
  val properties = text(root.resolve("runtime.properties")).map { line =>
    val pair = line.split("=", 2); pair(0) -> pair(1).toInt
  }.toMap
  val program = text(root.resolve("code.hex")).map(java.lang.Long.parseLong(_, 16))
  require(program.size == 1024)
  val names = text(root.resolve("cases.txt"))
  require(names.distinct.size == names.size && names.forall(_.matches("[a-z0-9_]+")))
  val compiled = SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(s"build/ape_app/sim/r$entries-$mode")
    .compile(new ApeCore(ApeConfig(robEntries = entries, prediction = mode == "bimodal")))
  case class Request(address: BigInt, data: BigInt, size: Int, write: Boolean)
  val results = mutable.ArrayBuffer[String]()
  names.zipWithIndex.foreach { case (name, caseIndex) =>
    compiled.doSim(name, seed = caseIndex + 1) { dut =>
      def edge(): Unit = {
        dut.clockDomain.risingEdge(); sleep(5)
        dut.clockDomain.fallingEdge(); sleep(5)
      }
      dut.clockDomain.clockSim #= false
      dut.clockDomain.assertReset()
      dut.io.program.valid #= false; dut.io.program.index #= 0; dut.io.program.instruction #= 0
      dut.io.launch.valid #= false; dut.io.launch.pc #= 0; dut.io.launch.argument #= 0x16000
      dut.io.launch.base #= 0x10000; dut.io.launch.limit #= 0x20000; dut.io.launch.writable #= true
      dut.io.memory.ready #= false
      dut.io.response.valid #= false; dut.io.response.data #= 0; dut.io.response.error #= false
      dut.io.halt.ready #= false
      for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      for (i <- program.indices) {
        dut.io.program.valid #= true; dut.io.program.index #= i; dut.io.program.instruction #= program(i)
        sleep(1); edge()
      }
      dut.io.program.valid #= false
      for (invocation <- 0 until 2) {
        val memory = Files.readAllBytes(root.resolve(s"$name.bin"))
        require(memory.length == 65536)
        val rng = new Random(1000 + caseIndex * 2 + invocation)
        val log = new PrintWriter(out.resolve(s"$name-$invocation.arch.jsonl").toFile)
        var pending: Option[(Int, BigInt)] = None
        var held: Option[Request] = None
        var cycles, retired, requests, stackWrites, inputReads, stalls = 0
        var minimumSp = BigInt(0x20000)
        var halted = false
        var result = BigInt(0)
        try {
          dut.io.launch.valid #= true
          sleep(1); assert(dut.io.launch.ready.toBoolean); edge(); dut.io.launch.valid #= false
          while (!halted && cycles < 2000000) {
            dut.io.memory.ready #= (cycles % 5 >= 2 && rng.nextInt(4) != 0)
            val reply = pending.filter(_._1 <= cycles)
            dut.io.response.valid #= reply.nonEmpty
            dut.io.response.data #= reply.map(_._2).getOrElse(BigInt(0))
            sleep(1)
            val req = if (dut.io.memory.valid.toBoolean) Some(Request(dut.io.memory.address.toBigInt,
              dut.io.memory.data.toBigInt, dut.io.memory.size.toInt, dut.io.memory.write.toBoolean)) else None
            held.foreach(previous => assert(req.contains(previous), "held request changed"))
            held = if (!dut.io.memory.ready.toBoolean) req else None
            if (held.nonEmpty) stalls += 1
            if (reply.nonEmpty && dut.io.response.ready.toBoolean) pending = None
            if (req.nonEmpty && dut.io.memory.ready.toBoolean) {
              assert(pending.isEmpty, "multiple outstanding transactions")
              val r = req.get
              val bytes = 1 << r.size
              assert(r.address >= 0x10000 && r.address + bytes <= 0x20000 && r.address % bytes == 0)
              val address = r.address.toInt
              val offset = address - 0x10000
              val loaded = (0 until bytes).map(i => BigInt(memory(offset+i) & 255) << (8*i)).foldLeft(BigInt(0))(_ | _)
              if (r.write) {
                assert((address >= properties("writable_start") && address + bytes <= properties("bss_end")) ||
                  (address >= 0x18000 && address + bytes <= 0x19000) ||
                  (address >= 0x1c000 && address + bytes <= 0x20000), "write outside application-owned regions")
                for (i <- 0 until bytes) memory(offset+i) = ((r.data >> (8*i)) & 255).toByte
                if (address >= 0x1c000) stackWrites += 1
              } else if (address >= 0x16000 && address < 0x16410) inputReads += 1
              pending = Some((cycles + 4 + rng.nextInt(12), loaded))
              val value = if (r.write) r.data & ((BigInt(1) << (8*bytes))-1) else loaded
              log.println(s"""{"kind":"memory","address":"$address","bytes":$bytes,"write":${r.write},"data":"$value","error":false}""")
              requests += 1
            }
            if (dut.io.retired.valid.toBoolean) {
              val writes = dut.io.retired.writes.toBoolean
              val rd = if (writes) dut.io.retired.rd.toInt else 0
              val value = if (writes) dut.io.retired.value.toBigInt else BigInt(0)
              val pc = dut.io.retired.pc.toBigInt
              val next = if (dut.io.controlRetired.valid.toBoolean) dut.io.controlRetired.actualNext.toBigInt
                else (pc + 4) & ((BigInt(1) << 64)-1)
              if (writes && rd == 2) {
                assert(value >= 0x1c000 && value <= 0x20000 && value % 16 == 0, "LP64 stack contract")
                minimumSp = minimumSp.min(value)
              }
              log.println(s"""{"kind":"retire","pc":"$pc","instruction":${dut.io.retired.instruction.toLong},"writes":$writes,"rd":$rd,"value":"$value","next":"$next"}""")
              retired += 1
            }
            if (dut.io.halt.valid.toBoolean) {
              assert(dut.io.halt.cause.toInt == 3 && dut.io.halt.pc.toBigInt == properties("exit_pc"),
                "application fault or ABI sentinel failure")
              assert(pending.isEmpty && held.isEmpty, "halt with undrained memory")
              result = dut.io.halt.value.toBigInt
              log.println(s"""{"kind":"trap","pc":"${dut.io.halt.pc.toBigInt}","cause":3,"value":"$result"}""")
              halted = true
            }
            edge(); cycles += 1
          }
          assert(halted, "application timed out")
          assert(stackWrites > 0 && inputReads > 0 && retired > 0)
          Files.write(out.resolve(s"$name-$invocation.memory.bin"), memory)
          for (_ <- 0 until 8) {
            dut.io.response.valid #= false
            assert(dut.io.halt.valid.toBoolean && !dut.io.launch.ready.toBoolean)
            assert(dut.io.halt.value.toBigInt == result && dut.io.halt.pc.toBigInt == properties("exit_pc"))
            assert(!dut.io.memory.valid.toBoolean && !dut.io.retired.valid.toBoolean)
            edge()
          }
          dut.io.halt.ready #= true; edge(); dut.io.halt.ready #= false
          results += s"""{"name":"$name","invocation":$invocation,"cycles":$cycles,"retired":$retired,"memory_requests":$requests,"stack_writes":$stackWrites,"input_reads":$inputReads,"stack_bytes":${0x20000-minimumSp.toInt},"request_stall_cycles":$stalls,"result":$result}"""
        } finally log.close()
      }
    }
  }
  save("validation.json", s"""{"status":"passed","rob_entries":$entries,"prediction":"$mode","results":[${results.mkString(",")}]}
""")
  println(s"APE application PASS: ${results.size} invocations ROB=$entries mode=$mode")
}
