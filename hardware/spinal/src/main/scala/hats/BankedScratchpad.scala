package hats

import spinal.core._
import spinal.lib._

/** Four independently accessed 64-bit banks, interleaved by word address.
  * Clear owns every bank; callers must first drain all accepted requests.
  * Inspection is a verification-only asynchronous port.
  */
class BankedScratchpad(m: MemoryHierarchyConfig) extends Component {
  val io = new Bundle {
    val request = Vec(slave Stream(CacheWordRequest(m)), 4)
    val response = Vec(master Stream(CacheWordResponse(m)), 4)
    val clear = in Bool()
    val clearRow = in UInt(7 bits)
    val inspect = in UInt(9 bits)
    val data = out Bits(64 bits)
    val idle = out Bool()
  }
  val busy = Bits(4 bits)
  val inspected = Vec(Bits(64 bits), 4)
  for (b <- 0 until 4) {
    val memory = Mem(Bits(64 bits), 128)
    val valid = RegInit(False)
    val result = Reg(CacheWordResponse(m))
    val req = io.request(b)
    val rsp = io.response(b)
    val legal = req.address < 4096 && req.address(2 downto 0) === 0 && req.address(4 downto 3) === b
    req.ready := !io.clear && (!valid || rsp.ready)
    rsp.valid := valid; rsp.payload := result; busy(b) := valid
    when(rsp.fire) { valid := False }
    when(req.fire) {
      valid := True; result.id := req.id; result.epoch := req.epoch
      result.error := !legal
      result.data := Mux(legal && !req.write, memory.readAsync(req.address(11 downto 5)), B(0, 64 bits))
    }
    val writing = io.clear || (req.fire && req.write && legal)
    memory.write(Mux(io.clear, io.clearRow, req.address(11 downto 5)),
      Mux(io.clear, B(0, 64 bits), req.data), writing, Mux(io.clear, B(255, 8 bits), req.mask))
    inspected(b) := memory.readAsync(io.inspect(8 downto 2))
    when(io.clear) { assert(!valid, "scratch clear discarded an accepted request") }
  }
  io.data := inspected(io.inspect(1 downto 0))
  io.idle := !busy.orR
}
