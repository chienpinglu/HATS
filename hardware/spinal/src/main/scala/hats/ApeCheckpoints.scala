package hats

import spinal.core._
import spinal.lib._

/** ROB-slot-owned rename snapshots. The core qualifies delayed completion before
  * driving resolve; this storage component does not interpret an instruction set.
  */
class ApeCheckpoints(physicalRegisters: Int, slots: Int, capacity: Int, architecturalRegisters: Int = 32) extends Component {
  require(slots >= 4 && isPow2(slots) && capacity >= 1 && capacity <= slots)
  require(architecturalRegisters >= 4 && isPow2(architecturalRegisters) && architecturalRegisters < physicalRegisters)
  val tagBits = log2Up(physicalRegisters)
  val io = new Bundle {
    val clear = in Bool()
    val snapshot = in Vec(UInt(tagBits bits), architecturalRegisters)
    val allocation = slave Flow(UInt(tagBits bits))
    val capture = slave Flow(UInt(log2Up(slots) bits))
    val resolve = slave Flow(new Bundle { val slot = UInt(log2Up(slots) bits); val redirect = Bool() })
    val squash = in Bits(slots bits)
    val available = out Bool()
    val occupied = out UInt(log2Up(slots + 1) bits)
    val restored = out Vec(UInt(tagBits bits), architecturalRegisters)
    val reclaimed = out Bits(physicalRegisters bits)
  }
  val valid = Reg(Bits(slots bits)) init 0
  val maps = Vec.fill(slots)(Vec.fill(architecturalRegisters)(Reg(UInt(tagBits bits)) init 0))
  val younger = Vec.fill(slots)(Reg(Bits(physicalRegisters bits)) init 0)
  io.occupied := CountOne(valid).resize(io.occupied.getWidth)
  io.available := io.occupied < capacity && !io.clear
  io.restored := maps(io.resolve.slot)
  io.reclaimed := younger(io.resolve.slot)
  for (s <- 0 until slots) {
    when(valid(s) && io.allocation.valid) { younger(s)(io.allocation.payload) := True }
  }
  when(io.resolve.valid) {
    assert(valid(io.resolve.slot), "resolution does not own a live checkpoint")
    valid(io.resolve.slot) := False
    when(io.resolve.redirect) {
      valid := valid & ~io.squash & ~UIntToOh(io.resolve.slot, slots)
      assert(!io.capture.valid && !io.allocation.valid, "dispatch during checkpoint restoration")
    }
  }
  when(io.capture.valid) {
    assert(io.available && !valid(io.capture.payload), "checkpoint overflow or reuse")
    maps(io.capture.payload) := io.snapshot
    younger(io.capture.payload) := B(0, physicalRegisters bits) // Own link destination is already in the snapshot.
    valid(io.capture.payload) := True
  }
  when(io.clear) { valid := 0 }
  assert(io.occupied <= capacity, "checkpoint capacity exceeded")
}
