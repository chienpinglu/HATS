package hats

import spinal.core._
import spinal.core.sim._
import scala.collection.mutable
import scala.util.Random
import java.nio.file.{Files, Paths}

/** Port-only model reconstructs mappings/ownership by replaying surviving
  * instructions, not by copying the DUT's snapshot or allocation-mask algorithm.
  */
object ApeCheckpointSim extends App {
  val out = Paths.get("build/ape_checkpoints"); Files.createDirectories(out)
  Files.writeString(out.resolve("validation.json"), "{\"status\":\"running\"}\n")
  val reports = mutable.ArrayBuffer[String]()
  for ((physical, capacity) <- Seq((36, 1), (36, 4), (64, 2), (64, 4))) {
    val compiled = SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
      .workspacePath(out.resolve(s"p$physical-c$capacity").toString)
      .compile(new ApeRename(ApeRv64Profile.registers, physical, 8, capacity))
    compiled.doSim("surviving_instruction_model", seed = physical + capacity) { dut =>
      val rng = new Random(0x43503034 + physical + capacity)
      case class Entry(id: Long, rd: Int, tag: Option[Int], result: BigInt, checkpoint: Option[Int],
                       var completed: Boolean = false, var resolved: Boolean = false)
      val pending = mutable.ArrayBuffer[Entry]()
      val committed = Array.tabulate(32)(identity)
      val values = Array.fill[BigInt](physical)(0)
      val ready = Array.tabulate(physical)(_ < 32)
      var serial = 0L
      var captures, redirects, nested, concurrent, capacityStalls, registerStalls, retires, squashCount = 0
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      dut.io.clear #= false; dut.io.argument #= 0; dut.io.recover #= false
      dut.io.allocate.valid #= false; dut.io.allocate.payload #= 1
      dut.io.writeback.valid #= false; dut.io.writeback.tag #= 0; dut.io.writeback.value #= 0
      dut.io.commit.valid #= false; dut.io.commit.architectural #= 0; dut.io.commit.physical #= 0
      dut.io.checkpoint.valid #= false; dut.io.checkpoint.payload #= 0
      dut.io.resolve.valid #= false; dut.io.resolve.slot #= 0; dut.io.resolve.redirect #= false; dut.io.squash #= 0
      dut.io.source(0) #= 0; dut.io.source(1) #= 0; dut.io.sourceUsed #= 3
      def edge(): Unit = { dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5) }
      for (_ <- 0 until 4) edge()
      dut.clockDomain.deassertReset(); edge()
      for (cycle <- 0 until 8000) {
        val clear = cycle % 997 == 0
        val argument = BigInt(64, rng)
        val fullRecovery = !clear && cycle % 131 == 0
        val checkpoints = pending.filter(e => e.checkpoint.nonEmpty && !e.resolved)
        val resolve = if (!clear && !fullRecovery && checkpoints.nonEmpty && rng.nextInt(3) == 0)
          Some(checkpoints(rng.nextInt(checkpoints.size))) else None
        val redirect = resolve.nonEmpty && rng.nextBoolean()
        val commit = if (!clear && pending.headOption.exists(_.completed) && (redirect || rng.nextBoolean())) pending.headOption else None
        val writers = pending.filter(e => e.tag.nonEmpty && e.checkpoint.isEmpty && !e.completed)
        val wb = if (clear || fullRecovery) None else resolve.filter(_.tag.nonEmpty).orElse(
          if (resolve.isEmpty && writers.nonEmpty && rng.nextInt(4) != 0) Some(writers(rng.nextInt(writers.size))) else None)
        val spec = committed.clone()
        pending.foreach(e => e.tag.foreach(t => spec(e.rd) = t))
        val owned = committed.toSet ++ pending.flatMap(_.tag)
        val free = (0 until physical).filterNot(owned)
        val canAllocate = free.nonEmpty && !clear && !fullRecovery && !redirect
        val cpAvailable = checkpoints.size < capacity && !clear && !fullRecovery
        val request = !clear && !fullRecovery && !redirect && pending.size < 16 && rng.nextInt(5) != 0
        val branch = rng.nextInt(3) == 0
        val rd = if (branch && rng.nextBoolean()) 0 else 1 + rng.nextInt(31)
        val dispatch = request && (!branch || cpAvailable) && (rd == 0 || canAllocate)
        val tag = if (dispatch && rd != 0) Some(free.min) else None
        val cp = if (dispatch && branch) Some((0 until 8).find(i => !checkpoints.exists(_.checkpoint.contains(i))).get) else None
        val killed = resolve.filter(_ => redirect).map(e => pending.filter(_.id > e.id)).getOrElse(Seq.empty)
        val squash = killed.flatMap(_.checkpoint).foldLeft(BigInt(0))((b, i) => b.setBit(i))
        val sources = Seq(cycle % 32, rng.nextInt(32))
        dut.io.clear #= clear; dut.io.argument #= argument; dut.io.recover #= fullRecovery
        dut.io.allocate.valid #= (request && (!branch || cpAvailable) && rd != 0); dut.io.allocate.payload #= rd
        dut.io.writeback.valid #= wb.nonEmpty
        wb.foreach(e => { dut.io.writeback.tag #= e.tag.get; dut.io.writeback.value #= e.result })
        dut.io.commit.valid #= commit.exists(_.tag.nonEmpty)
        commit.filter(_.tag.nonEmpty).foreach(e => { dut.io.commit.architectural #= e.rd; dut.io.commit.physical #= e.tag.get })
        dut.io.checkpoint.valid #= cp.nonEmpty; dut.io.checkpoint.payload #= cp.getOrElse(0).toLong
        dut.io.resolve.valid #= resolve.nonEmpty; dut.io.resolve.slot #= resolve.flatMap(_.checkpoint).getOrElse(0).toLong
        dut.io.resolve.redirect #= redirect; dut.io.squash #= squash
        for (n <- 0 until 2) dut.io.source(n) #= sources(n)
        sleep(1)
        assert(dut.io.freeCount.toInt == free.size && dut.io.checkpointsUsed.toInt == checkpoints.size)
        assert(dut.io.allocate.ready.toBoolean == canAllocate && dut.io.checkpointAvailable.toBoolean == cpAvailable)
        assert(dut.io.committedArgument.toBigInt == values(committed(10)))
        tag.foreach(t => assert(dut.io.allocatedTag.toInt == t))
        for (n <- 0 until 2) {
          val t = spec(sources(n)); val bypass = wb.filter(_.tag.contains(t))
          assert(dut.io.sourceTag(n).toInt == t)
          assert(((dut.io.sourceReady.toInt >> n) & 1) == (if (sources(n) == 0 || ready(t) || bypass.nonEmpty) 1 else 0))
          assert(dut.io.sourceValue(n).toBigInt == (if (sources(n) == 0) BigInt(0) else bypass.map(_.result).getOrElse(values(t))))
        }
        edge()
        if (clear) {
          for (r <- 0 until 32) committed(r) = r
          for (r <- 0 until physical) { values(r) = if (r == 10) argument else BigInt(0); ready(r) = r < 32 }
          pending.clear()
        } else {
          if (request && branch && !cpAvailable) capacityStalls += 1
          if (request && (!branch || cpAvailable) && rd != 0 && !canAllocate) registerStalls += 1
          wb.foreach(e => { values(e.tag.get) = e.result; ready(e.tag.get) = true; e.completed = true })
          commit.foreach(e => { e.tag.foreach(t => committed(e.rd) = t); pending.remove(0); retires += 1 })
          resolve.foreach(e => { e.resolved = true; e.completed = true })
          if (redirect) {
            redirects += 1; squashCount += killed.size
            if (checkpoints.exists(e => e.id < resolve.get.id)) nested += 1
            if (commit.nonEmpty) concurrent += 1
            pending.filterInPlace(_.id <= resolve.get.id)
          }
          if (fullRecovery) pending.clear()
          if (dispatch) {
            tag.foreach(t => ready(t) = false)
            serial += 1; pending += Entry(serial, rd, tag, BigInt(64, rng), cp)
            if (cp.nonEmpty) captures += 1
          }
        }
      }
      assert(captures > 100 && redirects > 50 && concurrent > 10 && capacityStalls > 0 && retires > 500 && squashCount > 100,
        s"coverage: captures=$captures redirects=$redirects concurrent=$concurrent capacityStalls=$capacityStalls retires=$retires squash=$squashCount")
      if (capacity > 1) assert(nested > 20, s"insufficient nested redirects: $nested")
      if (physical == 36) assert(registerStalls > 0)
      reports += s"""{"physical_registers":$physical,"capacity":$capacity,"cycles":8000,"captures":$captures,"redirects":$redirects,"nested_redirects":$nested,"commit_and_redirect":$concurrent,"checkpoint_stalls":$capacityStalls,"register_stalls":$registerStalls,"retirements":$retires,"squashed_instructions":$squashCount}"""
    }
  }
  Files.writeString(out.resolve("validation.json"), s"""{"status":"passed","claim":"actual checkpoint/rename RTL checked against surviving-instruction replay; not formal proof","runs":[${reports.mkString(",")}]}\n""")
  println("Checkpoint ownership PASS: 32000 RTL cycles, four register/checkpoint configurations")
}
