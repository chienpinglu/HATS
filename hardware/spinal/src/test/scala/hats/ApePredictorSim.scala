package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import java.nio.charset.StandardCharsets
import scala.util.Random

/** Cycle-exact independent counter model, including lookup/train aliases. */
object ApePredictorSim extends App {
  val root = Paths.get("build/ape/predictor")
  Files.createDirectories(root)
  def report(s: String): Unit = Files.write(root.resolve("validation.json"), s.getBytes(StandardCharsets.UTF_8))
  report("{\"status\":\"running\"}\n")
  var checked = 0
  for (enabled <- Seq(false, true); entries <- Seq(2, 16)) {
    SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
      .workspacePath(s"build/ape/sim/predictor-$enabled-$entries")
      .compile(new ApeBranchPredictor(enabled, entries)).doSim { dut =>
        val counters = Array.fill(entries)(1)
        val rng = new Random(713)
        dut.clockDomain.clockSim #= false
        dut.clockDomain.assertReset()
        dut.io.clear #= false; dut.io.pc #= 0; dut.io.target #= 256
        dut.io.conditional #= true; dut.io.directJump #= false
        dut.io.update.valid #= false; dut.io.update.pc #= 0; dut.io.update.taken #= false
        def edge(): Unit = {
          dut.clockDomain.risingEdge(); sleep(5)
          dut.clockDomain.fallingEdge(); sleep(5)
        }
        for (_ <- 0 until 4) edge()
        dut.clockDomain.deassertReset(); edge()
        for (cycle <- 0 until 512) {
          val pc = if (cycle < 32) 0 else rng.nextInt(128) * 4
          val trainPc = if (cycle < 32) entries * 4 else rng.nextInt(128) * 4
          val target = pc + 128
          val cond = cycle < 32 || rng.nextBoolean()
          val jump = cycle >= 32 && rng.nextInt(5) == 0
          val update = cycle < 32 || rng.nextBoolean()
          val take = if (cycle < 32) cycle % 16 < 8 else rng.nextBoolean()
          val clear = cycle == 16 || (cycle >= 32 && cycle % 31 == 0)
          dut.io.pc #= pc; dut.io.target #= target
          dut.io.conditional #= cond; dut.io.directJump #= jump
          dut.io.update.valid #= update; dut.io.update.pc #= trainPc; dut.io.update.taken #= take
          dut.io.clear #= clear
          def check(): Unit = {
            sleep(1)
            val expected = if (enabled && (jump || (cond && counters((pc / 4) % entries) >= 2))) target else pc + 4
            assert(dut.io.next.toBigInt == expected, s"prediction mismatch: $cycle/$enabled/$entries")
            checked += 1
          }
          check() // same-cycle training must not be forwarded into lookup
          edge()
          if (clear) java.util.Arrays.fill(counters, 1)
          else if (update) {
            val i = (trainPc / 4) % entries
            counters(i) = math.max(0, math.min(3, counters(i) + (if (take) 1 else -1)))
          }
          check()
        }
      }
  }
  report(s"""{"status":"passed","configurations":4,"lookup_checks":$checked}
""")
  println(s"APE predictor PASS: $checked lookup checks")
}
