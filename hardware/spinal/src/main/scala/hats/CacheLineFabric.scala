package hats

import spinal.core._
import spinal.lib._

case class FabricLineRequest(m: MemoryHierarchyConfig, ports: Int) extends Bundle {
  val source = UInt(log2Up(ports) bits)
  val transfer = CacheLineRequest(m)
}
case class FabricLineResponse(m: MemoryHierarchyConfig, ports: Int) extends Bundle {
  val source = UInt(log2Up(ports) bits)
  val transfer = CacheLineResponse(m)
}

/** Tagged, locked round-robin merge. No global request/response FIFO ordering
  * is assumed. Ownership lasts through the matching response, including errors.
  * This is a cache-facing line interconnect, not a coherence or DRAM controller.
  */
class CacheLineFabric(m: MemoryHierarchyConfig, ports: Int = 2) extends Component {
  require(ports >= 2 && isPow2(ports))
  val io = new Bundle {
    val requests = Vec(slave Stream(CacheLineRequest(m)), ports)
    val responses = Vec(master Stream(CacheLineResponse(m)), ports)
    val lower = master Stream(FabricLineRequest(m, ports))
    val reply = slave Stream(FabricLineResponse(m, ports))
    val idle = out Bool()
    val outstanding = out UInt(log2Up(ports * m.mshrs + 1) bits)
    val accepted, completed, rejected = out UInt(64 bits)
  }
  val pending = Vec.fill(ports)(Vec.fill(m.mshrs)(RegInit(False)))
  val generation = Vec.fill(ports)(Vec.fill(m.mshrs)(Reg(UInt(m.epochBits bits)) init 0))
  val write = Vec.fill(ports)(Vec.fill(m.mshrs)(RegInit(False)))
  val held = RegInit(False)
  val heldSource, cursor = Reg(UInt(log2Up(ports) bits)) init 0
  val candidates = Bits(ports bits)
  for (p <- 0 until ports) candidates(p) := io.requests((cursor + p).resize(log2Up(ports))).valid
  val selected = Mux(held, heldSource, (cursor + OHToUInt(OHMasking.first(candidates))).resize(log2Up(ports)))
  io.lower.valid := candidates.orR
  io.lower.source := selected; io.lower.transfer := io.requests(selected).payload
  for (p <- 0 until ports) io.requests(p).ready := io.lower.ready && selected === p
  when(io.lower.valid && !io.lower.ready) { held := True; heldSource := selected }
  val rp = io.reply.source; val rs = io.reply.transfer.slot
  val matched = pending(rp)(rs) && generation(rp)(rs) === io.reply.transfer.generation && write(rp)(rs) === io.reply.transfer.write
  for (p <- 0 until ports) {
    io.responses(p).valid := io.reply.valid && rp === p
    io.responses(p).payload := io.reply.transfer
  }
  io.reply.ready := io.responses(rp).ready
  val acceptedCount, completedCount, rejectedCount = Reg(UInt(64 bits)) init 0
  io.accepted := acceptedCount; io.completed := completedCount; io.rejected := rejectedCount
  when(io.reply.fire) {
    when(matched) { pending(rp)(rs) := False; completedCount := completedCount + 1 }
      .otherwise { rejectedCount := rejectedCount + 1 }
  }
  when(io.lower.fire) {
    val slot = io.lower.transfer.slot
    assert(!pending(selected)(slot) || (io.reply.fire && matched && rp === selected && rs === slot),
      "line source reused an outstanding MSHR lease")
    pending(selected)(slot) := True; generation(selected)(slot) := io.lower.transfer.generation
    write(selected)(slot) := io.lower.transfer.write
    cursor := selected + 1; held := False; acceptedCount := acceptedCount + 1
  }
  io.outstanding := CountOne(pending.asBits).resized
  io.idle := !pending.asBits.orR && !io.lower.valid
  when(held) { assert(io.requests(heldSource).valid, "held line source withdrew its request") }
  assert(acceptedCount - completedCount === io.outstanding.resize(64), "line fabric ownership accounting mismatch")
}
