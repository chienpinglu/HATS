package hats

import spinal.core._
import spinal.lib._

/** Single-dispatch physical integer register file and rename/commit maps.
  * Recovery restores committed state, including a same-edge retiring link write.
  * Selective branch recovery restores a checkpoint and reclaims younger tags.
  */
class ApeRename(layout: ApeRegisterLayout, physicalRegisters: Int = 64, checkpointSlots: Int = 8, checkpointCapacity: Int = 4) extends Component {
  require(physicalRegisters > layout.entries && physicalRegisters <= 256)
  val tagBits = log2Up(physicalRegisters)
  val io = new Bundle {
    val clear = in Bool()
    val argument = in UInt(64 bits)
    val source = in Vec(UInt(layout.bits bits), 2)
    val sourceUsed = in Bits(2 bits)
    val sourceTag = out Vec(UInt(tagBits bits), 2)
    val sourceReady = out Bits(2 bits)
    val sourceValue = out Vec(UInt(64 bits), 2)
    val allocate = slave Stream(UInt(layout.bits bits))
    val allocatedTag = out UInt(tagBits bits)
    val writeback = slave Flow(new Bundle { val tag = UInt(tagBits bits); val value = UInt(64 bits) })
    val commit = slave Flow(new Bundle { val architectural = UInt(layout.bits bits); val physical = UInt(tagBits bits) })
    val recover = in Bool()
    val checkpoint = slave Flow(UInt(log2Up(checkpointSlots) bits))
    val resolve = slave Flow(new Bundle { val slot = UInt(log2Up(checkpointSlots) bits); val redirect = Bool() })
    val squash = in Bits(checkpointSlots bits)
    val checkpointAvailable = out Bool()
    val checkpointsUsed = out UInt(log2Up(checkpointSlots + 1) bits)
    val committedArgument = out UInt(64 bits)
    val freeCount = out UInt(log2Up(physicalRegisters + 1) bits)
  }
  val initialCommitted = (BigInt(1) << layout.entries) - 1
  val allRegisters = (BigInt(1) << physicalRegisters) - 1
  val free = Reg(Bits(physicalRegisters bits)) init (allRegisters ^ initialCommitted)
  val committedLive = Reg(Bits(physicalRegisters bits)) init initialCommitted
  val ready = Reg(Bits(physicalRegisters bits)) init initialCommitted
  val data = Vec.fill(physicalRegisters)(Reg(UInt(64 bits)) init 0)
  val speculativeMap = Vec((0 until layout.entries).map(i => Reg(UInt(tagBits bits)) init i))
  val committedMap = Vec((0 until layout.entries).map(i => Reg(UInt(tagBits bits)) init i))
  val chosen = OHToUInt(OHMasking.first(free)).resize(tagBits)
  io.allocatedTag := chosen
  val restoring = io.resolve.valid && io.resolve.redirect
  io.allocate.ready := free.orR && !io.recover && !io.clear && !restoring
  io.freeCount := CountOne(free).resize(io.freeCount.getWidth)
  io.committedArgument := data(committedMap(layout.argument))
  for (n <- 0 until 2) {
    val tag = speculativeMap(io.source(n))
    io.sourceTag(n) := tag
    io.sourceReady(n) := True
    io.sourceValue(n) := 0
    when(io.sourceUsed(n) && io.source(n) =/= layout.zero) {
      io.sourceReady(n) := ready(tag)
      io.sourceValue(n) := data(tag)
      when(io.writeback.valid && io.writeback.tag === tag) {
        io.sourceReady(n) := True; io.sourceValue(n) := io.writeback.value
      }
    }
  }
  val committedAfter = Bits(physicalRegisters bits)
  val freeAfterCommit = Bits(physicalRegisters bits)
  freeAfterCommit := free
  committedAfter := committedLive
  val released = committedMap(io.commit.architectural)
  when(io.commit.valid) {
    committedAfter(released) := False
    committedAfter(io.commit.physical) := True
    committedMap(io.commit.architectural) := io.commit.physical
    freeAfterCommit(released) := True
  }
  committedLive := committedAfter
  when(io.commit.valid) { free(released) := True }
  when(io.allocate.fire) {
    speculativeMap(io.allocate.payload) := chosen
    free(chosen) := False; ready(chosen) := False
  }
  when(io.writeback.valid) { data(io.writeback.tag) := io.writeback.value; ready(io.writeback.tag) := True }
  val checkpoints = new ApeCheckpoints(physicalRegisters, checkpointSlots, checkpointCapacity, layout.entries)
  checkpoints.io.clear := io.clear || io.recover
  checkpoints.io.allocation.valid := io.allocate.fire
  checkpoints.io.allocation.payload := chosen
  checkpoints.io.capture := io.checkpoint
  checkpoints.io.resolve.valid := io.resolve.valid
  checkpoints.io.resolve.slot := io.resolve.slot
  checkpoints.io.resolve.redirect := io.resolve.redirect
  checkpoints.io.squash := io.squash
  io.checkpointAvailable := checkpoints.io.available
  io.checkpointsUsed := checkpoints.io.occupied
  for (r <- 0 until layout.entries) {
    checkpoints.io.snapshot(r) := speculativeMap(r)
    when(io.allocate.fire && io.allocate.payload === r) { checkpoints.io.snapshot(r) := chosen }
  }
  when(restoring) {
    assert(!io.recover, "precise and selective recovery overlap")
    assert((checkpoints.io.reclaimed & committedAfter) === 0, "squash would reclaim committed state")
    free := freeAfterCommit | checkpoints.io.reclaimed
    speculativeMap := checkpoints.io.restored
  }
  when(io.recover) {
    free := ~committedAfter
    for (r <- 0 until layout.entries) {
      speculativeMap(r) := committedMap(r)
      when(io.commit.valid && io.commit.architectural === r) { speculativeMap(r) := io.commit.physical }
    }
  }
  when(io.clear) {
    free := B(allRegisters ^ initialCommitted, physicalRegisters bits)
    committedLive := B(initialCommitted, physicalRegisters bits)
    ready := B(initialCommitted, physicalRegisters bits)
    for (r <- 0 until physicalRegisters) {
      if (r == layout.argument) data(r) := io.argument else data(r) := 0
    }
    for (r <- 0 until layout.entries) { speculativeMap(r) := r; committedMap(r) := r }
  }

  assert(!free(layout.zero) && ready(layout.zero) && data(layout.zero) === 0 &&
    speculativeMap(layout.zero) === layout.zero && committedMap(layout.zero) === layout.zero,
    "zero register was allocated or modified")
  assert((free & committedLive) === 0, "committed physical register is free")
  when(io.allocate.fire) { assert(io.allocate.payload =/= layout.zero && free(chosen), "invalid physical allocation") }
  when(io.writeback.valid) {
    assert(io.writeback.tag =/= layout.zero && io.writeback.tag.resize(tagBits + 1) < physicalRegisters && !free(io.writeback.tag), "writeback to unowned register")
  }
  when(io.commit.valid) {
    assert(io.commit.architectural =/= layout.zero && io.commit.physical.resize(tagBits + 1) < physicalRegisters &&
      !free(io.commit.physical) && ready(io.commit.physical) && !committedLive(io.commit.physical),
      "invalid retirement mapping")
  }
}
