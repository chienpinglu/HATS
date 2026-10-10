package hats

import spinal.core._
import spinal.core.sim._
import scala.collection.mutable
import scala.util.Random
import java.nio.file.{Files, Paths}
import java.nio.charset.StandardCharsets

/** Port-only elastic-pipeline oracle. Architectural instruction coverage is
  * separately supplied by core/Spike comparisons, not inferred from this test.
  */
object ApeExecuteSim extends App {
  case class Token(slot: Int, generation: Int, destination: Int, a: BigInt, b: BigInt, pc: BigInt, subtract: Boolean)
  val mask = (BigInt(1) << 64) - 1
  val root = Paths.get("build/ape_execution")
  Files.createDirectories(root)
  def save(name: String, text: String): Unit = Files.write(root.resolve(name), text.getBytes(StandardCharsets.UTF_8))
  save("validation.json", "{\"status\":\"running\"}\n")
  val reports = mutable.ArrayBuffer[String]()
  for ((depth, bits) <- Seq((2, 1), (2, 2), (8, 1), (16, 2))) {
    val c = ApeConfig(executionStages = depth, generationBits = bits)
    var accepted, completed, canceled, stalled, full, resets = 0
    SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
      .workspacePath(root.resolve(s"depth$depth-g$bits").toString)
      .compile(new ApeExecute(c)).doSim { dut =>
        val rng = new Random(0x415045 + depth * 10 + bits)
        val queue = mutable.Queue[(Token, Int)]()
        dut.clockDomain.clockSim #= false
        dut.clockDomain.assertReset()
        dut.io.clear #= false
        dut.io.request.valid #= false
        dut.io.result.ready #= false
        def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
        for (_ <- 0 until 4) edge()
        dut.clockDomain.deassertReset()
        var offered: Option[Token] = None
        def snapshot(): Seq[Any] = Seq(dut.io.result.identity.slot.toBigInt,
          dut.io.result.identity.generation.toBigInt, dut.io.result.identity.destination.toBigInt,
          dut.io.result.value.toBigInt, dut.io.result.next.toBigInt, dut.io.result.address.toBigInt,
          dut.io.result.faultKind.toEnum) ++ Seq(dut.io.result.taken, dut.io.result.memory,
          dut.io.result.control, dut.io.result.fault).map(x => if (x.toBoolean) BigInt(1) else BigInt(0))
        var held: Option[Seq[Any]] = None
        for (cycle <- 0 until 4200) {
          val clear = cycle < 4000 && cycle > 0 && cycle % 251 == 0
          if (offered.isEmpty && cycle < 4000 && rng.nextInt(5) != 0) {
            offered = Some(Token(rng.nextInt(8), rng.nextInt(1 << bits), rng.nextInt(64),
              BigInt(64, rng), BigInt(64, rng), BigInt(cycle * 4), rng.nextBoolean()))
          }
          val t = offered.getOrElse(Token(0, 0, 0, 0, 0, 0, false))
          dut.io.clear #= clear
          // Periodic long stalls force full occupancy independent of random luck.
          dut.io.result.ready #= (cycle >= 4000 || (cycle % 173 >= 37 && rng.nextBoolean()))
          dut.io.request.valid #= offered.nonEmpty
          dut.io.request.identity.slot #= t.slot
          dut.io.request.identity.generation #= t.generation
          dut.io.request.identity.destination #= t.destination
          dut.io.request.op #= (if (t.subtract) ApeOp.SUB else ApeOp.ADD)
          dut.io.request.branch #= ApeBranchCondition.EQ
          dut.io.request.a #= t.a; dut.io.request.b #= t.b
          dut.io.request.immediate #= 0; dut.io.request.pc #= t.pc
          dut.io.request.sequentialNext #= t.pc + 4
          dut.io.request.indirectTargetMask #= mask - 1; dut.io.request.alignmentMask #= 3
          dut.io.request.base #= 0; dut.io.request.limit #= mask
          dut.io.request.useImmediate #= false; dut.io.request.narrow32 #= false
          dut.io.request.resultExtension #= ApeResultExtension.FULL
          dut.io.request.writable #= true; dut.io.request.fault #= false
          dut.io.request.faultKind #= ApeFaultKind.NONE; dut.io.request.memorySize #= 3
          sleep(1)
          val pending = dut.io.pending.filter(_.valid.toBoolean).map(p =>
            (p.slot.toInt, p.generation.toInt, p.destination.toInt)).toSeq.sorted
          assert(pending == queue.map { case (x, _) => (x.slot, x.generation, x.destination) }.toSeq.sorted,
            "pending lease inventory lost or invented a token")
          if (pending.size == depth) full += 1
          if (clear) {
            assert(!dut.io.request.ready.toBoolean && !dut.io.result.valid.toBoolean)
            canceled += queue.size; queue.clear(); offered = None; held = None; resets += 1
          } else {
            held.foreach(v => assert(dut.io.result.valid.toBoolean && snapshot() == v,
              "completion changed while backpressured"))
            held = if (dut.io.result.valid.toBoolean && !dut.io.result.ready.toBoolean)
              Some(snapshot()) else None
            if (dut.io.result.valid.toBoolean) {
              assert(queue.nonEmpty, "completion without an accepted request")
              val (x, started) = queue.front
              assert(cycle - started >= depth, "result bypassed a required register boundary")
              assert(dut.io.result.identity.slot.toInt == x.slot && dut.io.result.identity.generation.toInt == x.generation &&
                dut.io.result.identity.destination.toInt == x.destination, "completion identity changed")
              val expected = (if (x.subtract) x.a - x.b else x.a + x.b) & mask
              assert(dut.io.result.value.toBigInt == expected && dut.io.result.next.toBigInt == x.pc + 4)
              assert(!dut.io.result.memory.toBoolean && !dut.io.result.control.toBoolean && !dut.io.result.fault.toBoolean)
              if (dut.io.result.ready.toBoolean) { queue.dequeue(); completed += 1 }
            }
            if (offered.nonEmpty && dut.io.request.ready.toBoolean) {
              queue.enqueue((t, cycle)); accepted += 1; offered = None
            } else if (offered.nonEmpty) stalled += 1
          }
          edge()
        }
        assert(queue.isEmpty && offered.isEmpty)
        assert(accepted == completed + canceled && completed > 500 && canceled > 0 && stalled > 500 && full > 100 && resets == 15)
      }
    reports += s"""{"depth":$depth,"generation_bits":$bits,"cycles":4200,"accepted":$accepted,"completed":$completed,"canceled":$canceled,"input_stalls":$stalled,"full_cycles":$full,"clear_events":$resets}"""
  }
  save("validation.json", s"""{"status":"passed","cycles":16800,"claim":"Actual elastic execution RTL transport, register latency, backpressure and clear; add/sub datapath only","configurations":[${reports.mkString(",")}]}
""")
}

/** Adversarial finite-generation wrap tests use the same guard as ApeCore. */
object ApeCompletionGuardSim extends App {
  val root = Paths.get("build/ape_execution")
  Files.createDirectories(root)
  val reports = mutable.ArrayBuffer[String]()
  Files.writeString(root.resolve("ownership.json"), "{\"status\":\"running\"}\n")
  for (bits <- Seq(1, 2)) {
    val c = ApeConfig(executionStages = 8, generationBits = bits)
    var rejected, qualified, conflicts = 0
    SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
      .workspacePath(root.resolve(s"ownership-g$bits").toString)
      .compile(new ApeCompletionGuard(c)).doSim { dut =>
        val rng = new Random(0x5150 + bits)
        for (iteration <- 0 until 8000) {
          val ownerGen = rng.nextInt(1 << bits)
          val ownerDest = 1 + rng.nextInt(63)
          val candidateGen = if (iteration % 3 == 0) (ownerGen + 1) % (1 << bits) else ownerGen
          val candidateDest = if (iteration % 5 == 0) ownerDest % 63 + 1 else ownerDest
          val live = iteration % 7 != 0
          val issued = iteration % 11 != 0
          val complete = iteration % 13 == 0
          dut.io.candidate.slot #= iteration % 8
          dut.io.candidate.generation #= candidateGen
          dut.io.candidate.destination #= candidateDest
          dut.io.ownerGeneration #= ownerGen; dut.io.ownerDestination #= ownerDest
          dut.io.ownerLive #= live; dut.io.ownerIssued #= issued; dut.io.ownerComplete #= complete
          val leases = (0 until 8).map(i => (rng.nextBoolean(), rng.nextInt(8), rng.nextInt(1 << bits), 1 + rng.nextInt(63)))
          leases.zipWithIndex.foreach { case ((valid, slot, gen, dest), i) =>
            dut.io.pending(i).valid #= valid; dut.io.pending(i).slot #= slot
            dut.io.pending(i).generation #= gen; dut.io.pending(i).destination #= dest
          }
          val slot = iteration % 8
          val gen = (iteration / 8) % (1 << bits) // repeatedly wraps, never assumes a large counter
          dut.io.allocationSlot #= slot; dut.io.allocationGeneration #= gen
          sleep(1)
          val expected = live && issued && !complete && candidateGen == ownerGen && candidateDest == ownerDest
          assert(dut.io.qualified.toBoolean == expected, "stale/duplicate/non-owner completion accepted")
          val conflict = leases.exists { case (v, s, g, _) => v && s == slot && g == gen }
          assert(dut.io.allocationSafe.toBoolean == !conflict, "generation wrap aliased an outstanding lease")
          if (expected) qualified += 1 else rejected += 1
          if (conflict) conflicts += 1
        }
      }
    assert(qualified > 2000 && rejected > 2000 && conflicts > 500)
    reports += s"""{"generation_bits":$bits,"checks":8000,"qualified":$qualified,"rejected":$rejected,"wrap_conflicts":$conflicts}"""
  }
  Files.writeString(root.resolve("ownership.json"), s"""{"status":"passed","checks":16000,"claim":"Combinational completion guard and outstanding-token wrap exclusion; not a whole-core ownership proof","configurations":[${reports.mkString(",")}]}
""")
}
