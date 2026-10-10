package hats

import spinal.core._
import spinal.core.sim._
import scala.collection.mutable
import scala.util.Random
import java.nio.file.{Files, Paths}

/** Port-level independent ownership/value scoreboard; never peeks into the DUT. */
object ApeRenameSim extends App {
  val out = Paths.get("build/ape_rename"); Files.createDirectories(out)
  val reports = mutable.ArrayBuffer[String]()
  for (physical <- Seq(33, 36, 64)) {
    val compiled = SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
      .workspacePath(out.resolve(s"p$physical").toString).compile(new ApeRename(ApeRv64Profile.registers, physical))
    compiled.doSim("rename_ownership", seed = physical) { dut =>
      val rng = new Random(0x534f33 + physical)
      val free = mutable.Set((32 until physical): _*)
      val spec = Array.tabulate(32)(identity); val committed = Array.tabulate(32)(identity)
      val values = Array.fill[BigInt](physical)(0); val ready = Array.tabulate(physical)(_ < 32)
      case class Entry(rd: Int, tag: Int, value: BigInt, var complete: Boolean = false)
      val pending = mutable.ArrayBuffer[Entry]()
      var allocations, blocked, recoveries, retires, relaunches, reordered, commitRecovery = 0
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      dut.io.clear #= false; dut.io.argument #= 0; dut.io.recover #= false
      dut.io.checkpoint.valid #= false; dut.io.checkpoint.payload #= 0
      dut.io.resolve.valid #= false; dut.io.resolve.slot #= 0; dut.io.resolve.redirect #= false
      dut.io.squash #= 0
      dut.io.allocate.valid #= false; dut.io.allocate.payload #= 1
      dut.io.writeback.valid #= false; dut.io.writeback.tag #= 0; dut.io.writeback.value #= 0
      dut.io.commit.valid #= false; dut.io.commit.architectural #= 0; dut.io.commit.physical #= 0
      dut.io.source(0) #= 0; dut.io.source(1) #= 0; dut.io.sourceUsed #= 3
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      for (cycle <- 0 until 6000) {
        val clear = cycle % 997 == 0
        val phase = cycle % 997
        val exhaust = phase > 0 && phase <= physical - 30
        val argument = BigInt(64, rng)
        val recover = !clear && !exhaust && (cycle % 29 == 0 || phase == physical - 29)
        val commit = if (!clear && !exhaust && pending.headOption.exists(_.complete) && (recover || rng.nextBoolean())) pending.headOption else None
        val candidates = pending.filter(!_.complete)
        val wb = if (!clear && !recover && !exhaust && candidates.nonEmpty && rng.nextInt(4) != 0) Some(candidates(rng.nextInt(candidates.size))) else None
        val allocate = !clear && !recover && (exhaust || rng.nextInt(5) != 0)
        val rd = 1 + rng.nextInt(31)
        val canAllocate = free.nonEmpty && !clear && !recover
        val chosen = if (canAllocate && allocate) Some(free.min) else None
        val sources = Seq(cycle % 32, rng.nextInt(32))
        val used = rng.nextInt(4)
        dut.io.clear #= clear; dut.io.argument #= argument; dut.io.recover #= recover
        dut.io.allocate.valid #= allocate; dut.io.allocate.payload #= rd
        dut.io.writeback.valid #= wb.nonEmpty
        wb.foreach(e => { dut.io.writeback.tag #= e.tag; dut.io.writeback.value #= e.value })
        dut.io.commit.valid #= commit.nonEmpty
        commit.foreach(e => { dut.io.commit.architectural #= e.rd; dut.io.commit.physical #= e.tag })
        for (n <- 0 until 2) dut.io.source(n) #= sources(n)
        dut.io.sourceUsed #= used
        sleep(1)
        assert(dut.io.allocate.ready.toBoolean == canAllocate)
        assert(dut.io.freeCount.toInt == free.size)
        assert(dut.io.committedArgument.toBigInt == values(committed(10)))
        chosen.foreach(t => assert(dut.io.allocatedTag.toInt == t))
        for (n <- 0 until 2) {
          val tag = spec(sources(n)); val bypass = wb.filter(_.tag == tag)
          val needsValue = (used & (1 << n)) != 0 && sources(n) != 0
          assert(dut.io.sourceTag(n).toInt == tag)
          assert(((dut.io.sourceReady.toInt & (1 << n)) != 0) == (!needsValue || ready(tag) || bypass.nonEmpty))
          val expected = if (!needsValue) BigInt(0) else bypass.map(_.value).getOrElse(values(tag))
          assert(dut.io.sourceValue(n).toBigInt == expected)
        }
        edge()
        if (clear) {
          for (r <- 0 until 32) { spec(r) = r; committed(r) = r }
          for (r <- 0 until physical) { values(r) = if (r == 10) argument else BigInt(0); ready(r) = r < 32 }
          free.clear(); free ++= (32 until physical); pending.clear(); relaunches += 1
        } else {
          if (allocate && !canAllocate) blocked += 1
          wb.foreach { e =>
            if (pending.indexOf(e) > 0 && pending.take(pending.indexOf(e)).exists(!_.complete)) reordered += 1
            values(e.tag) = e.value; ready(e.tag) = true; e.complete = true
          }
          commit.foreach { e =>
            assert(pending.head == e && e.complete)
            free += committed(e.rd); committed(e.rd) = e.tag; pending.remove(0); retires += 1
          }
          chosen.foreach { tag =>
            free -= tag; spec(rd) = tag; ready(tag) = false
            pending += Entry(rd, tag, BigInt(64, rng)); allocations += 1
          }
          if (recover) {
            for (r <- 0 until 32) spec(r) = committed(r)
            free.clear(); free ++= (0 until physical).filterNot(committed.contains)
            pending.clear(); recoveries += 1
            if (commit.nonEmpty) commitRecovery += 1
          }
        }
      }
      assert(allocations > 1000 && blocked > 0 && recoveries > 100 && retires > 500 && relaunches == 7 && commitRecovery > 0,
        s"Insufficient coverage: allocations=$allocations blocked=$blocked recoveries=$recoveries retires=$retires relaunches=$relaunches commitRecovery=$commitRecovery")
      if (physical > 33) assert(reordered > 100, "No out-of-order writeback exercised")
      reports += s"""{"physical_registers":$physical,"cycles":6000,"allocations":$allocations,"resource_stalls":$blocked,"recoveries":$recoveries,"retirements":$retires,"relaunches":$relaunches,"out_of_order_writebacks":$reordered,"commit_and_recovery":$commitRecovery}"""
    }
  }
  Files.writeString(out.resolve("validation.json"), s"""{"status":"passed","claim":"actual rename RTL port scoreboard, not formal proof","runs":[${reports.mkString(",") }]}\n""")
  println("Physical rename PASS: 18000 randomized RTL cycles across 33/36/64 physical registers")
}
