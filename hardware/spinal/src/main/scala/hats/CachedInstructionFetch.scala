package hats

import spinal.core._
import spinal.lib._

/** One outstanding fetch word, separate from the nonblocking instruction L1.
  * PC changes do not cancel offered requests. Identity/address checks prevent
  * wrong-path data or faults from entering the current frontend. Both 32-bit
  * APE and 64-bit PPE instructions can consume this aligned 64-bit word port.
  */
class CachedInstructionFetch(m: MemoryHierarchyConfig) extends Component {
  val io = new Bundle {
    val pc = in UInt(64 bits)
    val enable, accessible, clear = in Bool()
    val available, error, idle = out Bool()
    val word = out Bits(64 bits)
    val request = master Stream(CacheWordRequest(m))
    val response = slave Stream(CacheWordResponse(m))
    val requests, discarded, faults, rejected = out UInt(64 bits)
  }
  val offered, waiting, buffered, failed = RegInit(False)
  val requestAddress, bufferAddress = Reg(UInt(64 bits)) init 0
  val data = Reg(Bits(64 bits)) init 0
  val epoch = Reg(UInt(m.epochBits bits)) init 0
  val wanted = io.pc & U(BigInt("fffffffffffffff8", 16), 64 bits)
  val hit = buffered && bufferAddress === wanted
  io.available := !io.accessible || hit
  io.word := data; io.error := io.accessible && hit && failed
  io.idle := !offered && !waiting
  val requestCount, discardCount, faultCount, rejectCount = Reg(UInt(64 bits)) init 0
  io.requests := requestCount; io.discarded := discardCount
  io.faults := faultCount; io.rejected := rejectCount
  when(io.enable && io.accessible && !hit && io.idle && !io.clear) {
    offered := True; requestAddress := wanted; epoch := epoch + 1
  }
  io.request.valid := offered
  io.request.address := requestAddress; io.request.id := 0; io.request.epoch := epoch
  io.request.write := False; io.request.atomicAdd := False; io.request.mask := 0; io.request.data := 0
  when(io.request.fire) { offered := False; waiting := True; requestCount := requestCount + 1 }
  io.response.ready := True
  when(io.response.fire) {
    when(waiting && io.response.id === 0 && io.response.epoch === epoch) {
      waiting := False
      when(io.response.error) { faultCount := faultCount + 1 }
      when(io.enable && requestAddress === wanted) {
        data := io.response.data; failed := io.response.error
        bufferAddress := requestAddress; buffered := True
      }.otherwise { discardCount := discardCount + 1 }
    }.otherwise { rejectCount := rejectCount + 1 }
  }
  when(io.clear) {
    assert(io.idle, "fetch buffer invalidation requires drained transport")
    buffered := False; failed := False
  }
  assert(!(offered && waiting), "fetch lease has overlapping request/response phases")
}
