package hats

import spinal.core._
import spinal.lib._

case class OwnedLineRequest(m: MemoryHierarchyConfig) extends Bundle {
  val source = UInt(2 bits) // {engine: APE=0/PPE=1, local I/D fabric source}
  val ownerGeneration = UInt(32 bits)
  val transfer = CacheLineRequest(m)
}
case class OwnershipLineRequest(m: MemoryHierarchyConfig) extends Bundle {
  val source = UInt(1 bits)
  val ownerGeneration = UInt(32 bits)
  val transfer = CacheLineRequest(m)
}
case class OwnedLineResponse(m: MemoryHierarchyConfig) extends Bundle {
  val source = UInt(2 bits)
  val ownerGeneration = UInt(32 bits)
  val transfer = CacheLineResponse(m)
}
case class OwnershipResult() extends Bundle {
  val owner = Bool()
  val failed = Bool()
  val generation = UInt(32 bits)
}

object OwnershipPhase extends SpinalEnum {
  val RUN, DRAIN, FLUSH, RESULT = newElement()
}

/** Exclusive whole-cacheable-RAM ownership transfer between the APE and PPE.
  * Ownership changes only after the current engine drains every accepted line,
  * completes D-clean/invalidate then I-invalidate, and returns a successful
  * acknowledgement. Failed clean keeps the old owner. Static address
  * protection, virtual memory, devices and atomics are separate contracts.
  */
class MemoryOwnershipController(m: MemoryHierarchyConfig) extends Component {
  val io = new Bundle {
    val requests = Vec(slave Stream(OwnershipLineRequest(m)), 2)
    val responses = Vec(master Stream(FabricLineResponse(m, 2)), 2)
    val clientIdle = in Bits(2 bits)
    val flush = Vec(master Stream(Bool()), 2)
    val flushed = Vec(slave Stream(Bool()), 2)
    val handoff = slave Stream(Bool()) // false APE, true PPE
    val result = master Stream(OwnershipResult())
    val lower = master Stream(OwnedLineRequest(m))
    val reply = slave Stream(OwnedLineResponse(m))
    val owner = out Bool()
    val generation = out UInt(32 bits)
    val idle = out Bool()
    val run = out Bool()
    val outstanding = out UInt(log2Up(2*2*m.mshrs+1) bits)
    val accepted, completed, rejected, denied, handoffs, handoffFailures = out UInt(64 bits)
  }
  val owner = RegInit(False)
  val ownerIndex = owner.asUInt
  val generation = Reg(UInt(32 bits)) init 0
  val phase = Reg(OwnershipPhase()) init OwnershipPhase.RUN
  val desired = Reg(Bool()) init False
  val flushTarget = Reg(Bool()) init False
  val outcomeOwner, outcomeFailed = RegInit(False)
  val replyValid = RegInit(False)
  val replyPayload = Reg(OwnershipResult())
  io.owner := owner; io.generation := generation
  io.run := phase === OwnershipPhase.RUN && !replyValid
  io.result.valid := replyValid; io.result.payload := replyPayload
  when(io.result.fire) { replyValid := False; phase := OwnershipPhase.RUN }
  io.handoff.ready := phase === OwnershipPhase.RUN && !replyValid
  when(io.handoff.fire) {
    desired := io.handoff.payload
    when(io.handoff.payload === owner) {
      replyPayload.owner := owner; replyPayload.failed := False; replyPayload.generation := generation
      replyValid := True; phase := OwnershipPhase.RESULT
    }.otherwise { phase := OwnershipPhase.DRAIN }
  }
  io.idle := phase === OwnershipPhase.RUN && !replyValid && !io.lower.valid && io.outstanding === 0
  val held = RegInit(False)
  // APE/PPE line requests are admitted only from the current owner. The
  // selected source must hold its payload under backpressure.
  val ownerRequest = io.requests(ownerIndex).valid && io.requests(ownerIndex).ownerGeneration === generation &&
    (phase === OwnershipPhase.RUN || phase === OwnershipPhase.DRAIN || phase === OwnershipPhase.FLUSH)
  io.lower.valid := ownerRequest
  io.lower.source := (owner ## io.requests(ownerIndex).source).asUInt
  io.lower.ownerGeneration := generation
  io.lower.transfer := io.requests(ownerIndex).transfer
  when(io.lower.valid && !io.lower.ready) { held := True }
  when(io.lower.fire) { held := False }
  val pending = Vec.fill(2)(Vec.fill(2)(Vec.fill(m.mshrs)(RegInit(False))))
  val tagGeneration = Vec.fill(2)(Vec.fill(2)(Vec.fill(m.mshrs)(Reg(UInt(m.epochBits bits)) init 0)))
  val tagWrite = Vec.fill(2)(Vec.fill(2)(Vec.fill(m.mshrs)(RegInit(False))))
  val tagOwnerGeneration = Vec.fill(2)(Vec.fill(2)(Vec.fill(m.mshrs)(Reg(UInt(32 bits)) init 0)))
  val source = io.reply.source
  val engine = source(1 downto 1); val local = source(0 downto 0); val slot = io.reply.transfer.slot
  val matches = pending(engine)(local)(slot) && tagGeneration(engine)(local)(slot) === io.reply.transfer.generation &&
    tagWrite(engine)(local)(slot) === io.reply.transfer.write &&
    tagOwnerGeneration(engine)(local)(slot) === io.reply.ownerGeneration && io.reply.ownerGeneration === generation
  // Stale/malformed replies are consumed so they cannot block progress. A
  // matching response remains owned by the controller until the target cache
  // accepts it; never retire the lower ledger on downstream backpressure.
  io.reply.ready := !matches || io.responses(engine).ready
  for (e <- 0 until 2) {
    val isOwner = if (e == 0) !owner else owner
    io.flush(e).valid := phase === OwnershipPhase.FLUSH && (if (e == 0) !flushTarget else flushTarget)
    io.flush(e).payload := True
    io.flushed(e).ready := phase === OwnershipPhase.FLUSH && (if (e == 0) !flushTarget else flushTarget)
    io.requests(e).ready := io.lower.ready && io.lower.valid && isOwner
    io.responses(e).valid := io.reply.valid && matches && io.reply.source(1 downto 1) === U(e, 1 bits) && isOwner
    io.responses(e).source := io.reply.source(0).asUInt; io.responses(e).transfer := io.reply.transfer
  }
  val pendingBits = Bits(4*m.mshrs bits)
  for (e <- 0 until 2; l <- 0 until 2; s <- 0 until m.mshrs) {
    pendingBits((e*2+l)*m.mshrs+s) := pending(e)(l)(s)
  }
  val outstandingCount = CountOne(pendingBits).resize(io.outstanding.getWidth)
  io.outstanding := outstandingCount
  val acceptedCount, completedCount, rejectedCount, deniedCount, handoffCount, failureCount = Reg(UInt(64 bits)) init 0
  io.accepted := acceptedCount; io.completed := completedCount; io.rejected := rejectedCount; io.denied := deniedCount
  io.handoffs := handoffCount; io.handoffFailures := failureCount
  when(io.lower.fire) {
    val e = io.lower.source(1 downto 1); val l = io.lower.source(0 downto 0); val s = io.lower.transfer.slot
    assert(!pending(e)(l)(s), "ownership fabric source reused a live lower request")
    pending(e)(l)(s) := True; tagGeneration(e)(l)(s) := io.lower.transfer.generation
    tagWrite(e)(l)(s) := io.lower.transfer.write; tagOwnerGeneration(e)(l)(s) := io.lower.ownerGeneration
    acceptedCount := acceptedCount+1
  }
  when(io.reply.fire) {
    when(matches) { pending(engine)(local)(slot) := False; completedCount := completedCount+1 }
      .otherwise { rejectedCount := rejectedCount+1 }
  }
  assert(acceptedCount-completedCount === outstandingCount.resize(64), "ownership request ledger lost a transaction")
  for (e <- 0 until 2) when(io.requests(e).valid && ((if (e == 0) owner else !owner) || io.requests(e).ownerGeneration =/= generation)) {
    deniedCount := deniedCount+1
  }
  when(held) { assert(ownerRequest, "held owner request changed or lost its ownership generation") }
  when(phase === OwnershipPhase.DRAIN && io.clientIdle(ownerIndex) && outstandingCount === 0) {
    phase := OwnershipPhase.FLUSH; flushTarget := owner
  }
  val targetIndex = flushTarget.asUInt
  when(phase === OwnershipPhase.FLUSH && io.flushed(targetIndex).fire) {
    when(io.flushed(targetIndex).payload) {
      replyValid := True; outcomeFailed := True; outcomeOwner := owner
      replyPayload.owner := owner; replyPayload.failed := True; replyPayload.generation := generation
      failureCount := failureCount+1; phase := OwnershipPhase.RESULT
    }.otherwise {
      when(flushTarget =/= desired) { flushTarget := desired }
        .otherwise {
          replyValid := True; outcomeFailed := False; outcomeOwner := owner
          replyPayload.owner := desired; replyPayload.failed := False; replyPayload.generation := generation+1
          owner := desired; generation := generation+1; handoffCount := handoffCount+1; phase := OwnershipPhase.RESULT
        }
    }
  }
}
