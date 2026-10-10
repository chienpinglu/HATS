package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import scala.collection.mutable
import scala.util.Random

/** Exhaustive small masks and randomized large masks; no ISA semantics in oracle. */
object ApeIssueSchedulerSim extends App {
  val root = Paths.get("build/ape_issue")
  Files.createDirectories(root)
  Files.writeString(root.resolve("validation.json"), "{\"status\":\"running\"}\n")
  val reports = mutable.ArrayBuffer[String]()
  for (entries <- Seq(4, 8, 16); width <- Seq(1, 2)) {
    var checks, dual, bypass = 0
    SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
      .workspacePath(root.resolve(s"r$entries-w$width").toString)
      .compile(new ApeIssueScheduler(entries, width)).doSim { dut =>
        val rng = new Random(0x495353 + entries * 4 + width)
        val masks = if (entries <= 8) 0 until (1 << entries) else 0 until 2048
        for (head <- 0 until entries; k <- masks; lanes <- 0 until (1 << width); enabled <- Seq(false, true)) {
          val mask = if (entries <= 8) k else rng.nextInt(1 << entries)
          dut.io.head #= head; dut.io.ready #= mask; dut.io.laneReady #= lanes; dut.io.enable #= enabled
          sleep(1)
          val remaining = mutable.Queue.from((0 until entries).map(i => (head + i) % entries).filter(s => (mask & (1 << s)) != 0))
          var expectedCount = 0
          for (lane <- 0 until width) {
            val valid = enabled && (lanes & (1 << lane)) != 0 && remaining.nonEmpty
            assert(dut.io.grant(lane).valid.toBoolean == valid)
            if (valid) { assert(dut.io.grant(lane).payload.toInt == remaining.dequeue()); expectedCount += 1 }
          }
          assert(dut.io.readyCount.toInt == Integer.bitCount(mask) && dut.io.issueCount.toInt == expectedCount)
          if (expectedCount == 2) dual += 1
          if (width == 2 && lanes == 2 && expectedCount == 1) bypass += 1
          checks += 1
        }
      }
    if (width == 2) assert(dual > 0 && bypass > 0)
    reports += s"""{"rob_entries":$entries,"issue_width":$width,"checks":$checks,"dual_grants":$dual,"blocked_lane_bypasses":$bypass}"""
  }
  Files.writeString(root.resolve("validation.json"), s"""{"status":"passed","claim":"Scheduler selection RTL, not integrated dual-issue execution","configurations":[${reports.mkString(",")}]}
""")
}
