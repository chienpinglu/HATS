package hats

import spinal.core._
import spinal.lib._

/** ISA-independent oldest-ready selection over the ROB reservation rows.
  * A grant is an accepted issue, never a request held across backpressure.
  * This contract requires execution input readiness independent of request valid.
  * Lower numbered available lanes take older work; blocked lanes reserve none.
  */
class ApeIssueScheduler(entries: Int, width: Int) extends Component {
  require(entries >= 4 && isPow2(entries) && width >= 1 && width <= 2)
  val bits = log2Up(entries)
  val io = new Bundle {
    val enable = in Bool()
    val head = in UInt(bits bits)
    val ready = in Bits(entries bits)
    val laneReady = in Bits(width bits)
    val grant = out Vec(Flow(UInt(bits bits)), width)
    val readyCount = out UInt(log2Up(entries + 1) bits)
    val issueCount = out UInt(log2Up(width + 1) bits)
  }
  val candidates = Vec(Bits(entries bits), width + 1)
  for (offset <- 0 until entries) {
    candidates(0)(offset) := io.ready((io.head + offset).resize(bits))
  }
  for (lane <- 0 until width) {
    val chosen = OHMasking.first(candidates(lane))
    io.grant(lane).valid := io.enable && io.laneReady(lane) && candidates(lane).orR
    io.grant(lane).payload := (io.head + OHToUInt(chosen)).resize(bits)
    candidates(lane + 1) := candidates(lane)
    when(io.grant(lane).valid) { candidates(lane + 1) := candidates(lane) & ~chosen }
  }
  io.readyCount := CountOne(io.ready).resize(io.readyCount.getWidth)
  io.issueCount := CountOne(io.grant.map(_.valid)).resize(io.issueCount.getWidth)
  if (width == 2) {
    when(io.grant(0).valid && io.grant(1).valid) {
      assert(io.grant(0).payload =/= io.grant(1).payload, "one ROB owner issued to two lanes")
    }
  }
}
