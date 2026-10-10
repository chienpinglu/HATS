package hats

import spinal.core._
import spinal.lib._

/** Untagged bimodal predictor. The owner must train only retired branches.
  * Lookup sees pre-edge state; clear wins over training. Fallthrough is provided
  * by the architectural frontend rather than derived from an assumed length.
  */
class ApeBranchPredictor(enabled: Boolean, entries: Int, indexShift: Int = 2) extends Component {
  require(entries >= 2 && isPow2(entries))
  require(indexShift >= 0 && indexShift + log2Up(entries) <= 64)
  val io = new Bundle {
    val clear = in Bool()
    val pc, target, sequentialNext = in UInt(64 bits)
    val conditional, directJump = in Bool()
    val update = slave Flow(new Bundle {
      val pc = UInt(64 bits)
      val taken = Bool()
    })
    val next = out UInt(64 bits)
  }
  io.next := io.sequentialNext
  if (enabled) {
    val width = log2Up(entries)
    val counters = Vec.fill(entries)(Reg(UInt(2 bits)) init 1)
    val query = io.pc(width + indexShift - 1 downto indexShift)
    val train = io.update.pc(width + indexShift - 1 downto indexShift)
    when(io.directJump || (io.conditional && counters(query)(1))) {
      io.next := io.target
    }
    when(io.update.valid) {
      when(io.update.taken) {
        when(counters(train) =/= 3) { counters(train) := counters(train) + 1 }
      }.otherwise {
        when(counters(train) =/= 0) { counters(train) := counters(train) - 1 }
      }
    }
    when(io.clear) { for (counter <- counters) counter := 1 }
  }
}
