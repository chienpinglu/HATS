package hats

import spinal.core._
import spinal.lib._

case class PpeMemoryInstruction() extends Bundle {
  val mask = Bits(8 bits) // scalar accesses use bit zero
  val address, data = Vec(UInt(64 bits), 8)
  val error = Vec(UInt(4 bits), 8) // validated per-lane address/permission fault
  val report = Bits(8 bits) // address-overflow faults have no access observation
  val width = UInt(2 bits)
  val write, scratch, atomicAdd = Bool()
}

/** One wave memory instruction at a time, up to eight independently tagged
  * read groups. Requests are aligned words, not speculative device accesses.
  * Reads coalesce equal words; stores coalesce only consecutive active lanes
  * in the same word and admit one group at a time (precise fault prefix).
  * Logical lane observations remain ordered even when physical replies reorder.
  */
class PpeMemoryEngine(m: MemoryHierarchyConfig) extends Component {
  require(m.clientIdBits >= 3)
  val io = new Bundle {
    val instruction = slave Stream(PpeMemoryInstruction())
    val request = master Stream(CacheWordRequest(m))
    val response = slave Stream(CacheWordResponse(m))
    val scratchRequest = Vec(master Stream(CacheWordRequest(m)), 4)
    val scratchResponse = Vec(slave Stream(CacheWordResponse(m)), 4)
    val cancel = in Bool()
    val access = master Stream(new Bundle {
      val lane = UInt(3 bits)
      val address, data = UInt(64 bits)
      val error = UInt(4 bits)
      val report = Bool()
    })
    val finished = master Stream(new Bundle { val failed, cancelled = Bool() })
    val idle = out Bool()
    val outstanding = out UInt(4 bits)
    val words, lanes, rejectedReplies, bankParallelCycles = out UInt(64 bits)
  }
  val active, cancelled, failed, stopIssue, logicalDone = RegInit(False)
  val desc = Reg(PpeMemoryInstruction())
  val epoch = Reg(UInt(m.epochBits bits)) init 0
  val sent, pending, ready = Vec.fill(8)(RegInit(False))
  val values = Vec.fill(8)(Reg(UInt(64 bits)) init 0)
  val errors = Vec.fill(8)(Reg(UInt(4 bits)) init 0)
  val cursor = Reg(UInt(4 bits)) init 0
  val offer = Vec.fill(5)(RegInit(False)) // global, then four scratch banks
  val selected = Vec.fill(5)(Reg(UInt(3 bits)) init 0)
  val requests = Seq(io.request) ++ (0 until 4).map(io.scratchRequest(_))
  val responses = Seq(io.response) ++ (0 until 4).map(io.scratchResponse(_))
  val outstanding = CountOne(pending.asBits).resize(4)
  io.outstanding := outstanding
  io.idle := !active
  io.instruction.ready := !active
  io.finished.valid := active && logicalDone && !pending.asBits.orR && !offer.asBits.orR
  io.finished.failed := failed; io.finished.cancelled := cancelled
  when(io.finished.fire) { active := False }
  when(io.instruction.fire) {
    active := True; desc := io.instruction.payload; epoch := epoch + 1; cursor := 0
    cancelled := False; failed := False; stopIssue := False; logicalDone := False
    for (n <- 0 until 8) {
      sent(n) := False; pending(n) := False
      ready(n) := io.instruction.error(n) =/= 0
      errors(n) := io.instruction.error(n); values(n) := 0
    }
  }
  when(active && io.cancel) { cancelled := True; stopIssue := True }
  val eligible = Bits(8 bits)
  val group = Vec(UInt(3 bits), 8)
  for (n <- 0 until 8) {
    val earlierFault = (0 until n).map(k => desc.mask(k) && desc.error(k) =/= 0).foldLeft(False)(_ || _)
    eligible(n) := desc.mask(n) && desc.error(n) === 0 && !earlierFault
    group(n) := n
    for (k <- (0 until n).reverse) {
      val same = desc.address(k)(63 downto 3) === desc.address(n)(63 downto 3)
      val contiguous = (k+1 until n).map(j => !desc.mask(j) ||
        desc.address(j)(63 downto 3) === desc.address(n)(63 downto 3)).foldLeft(True)(_ && _)
      when(eligible(k) && same && (!desc.write || contiguous)) { group(n) := k }
    }
  }
  val byteMask = Bits(8 bits)
  byteMask := 255
  switch(desc.width) { is(0) { byteMask := 1 }; is(1) { byteMask := 3 }; is(2) { byteMask := 15 } }
  val valueMask = UInt(64 bits)
  valueMask := U((BigInt(1) << 64) - 1, 64 bits)
  switch(desc.width) {
    is(0) { valueMask := 255 }; is(1) { valueMask := 65535 }
    is(2) { valueMask := U(BigInt("ffffffff", 16), 64 bits) }
  }
  val wordCount, laneCount, rejectCount, parallelCount = Reg(UInt(64 bits)) init 0
  io.words := wordCount; io.lanes := laneCount; io.rejectedReplies := rejectCount; io.bankParallelCycles := parallelCount
  val fires = Bits(5 bits)
  val rejects = Bits(5 bits)
  for (p <- 0 until 5) {
    val req = requests(p); val rsp = responses(p)
    val which = selected(p)
    val candidates = Bits(8 bits)
    for (n <- 0 until 8) {
      val port = if (p == 0) !desc.scratch else desc.scratch && desc.address(n)(4 downto 3) === p-1
      val earlierUnsent = (0 until n).map(k => eligible(k) && group(k) === k && !sent(k)).foldLeft(False)(_ || _)
      candidates(n) := eligible(n) && group(n) === n && !sent(n) && port && (!desc.write || !earlierUnsent)
    }
    when(active && !stopIssue && !io.cancel && !offer(p) && candidates.orR &&
      (!desc.write || (!pending.asBits.orR && !offer.asBits.orR))) {
      offer(p) := True; selected(p) := OHToUInt(OHMasking.first(candidates))
    }
    req.valid := offer(p)
    req.id := which.resize(m.clientIdBits); req.epoch := epoch
    req.address := ((desc.address(which) |>> 3) << 3).resize(64)
    req.write := desc.write; req.atomicAdd := desc.atomicAdd; req.data := 0; req.mask := 0
    // Ordered lane overwrite defines colliding stores, including partial words.
    for (n <- 0 until 8) {
      val mask = byteMask |<< desc.address(n)(2 downto 0)
      val shifted = desc.data(n).asBits |<< (desc.address(n)(2 downto 0) << 3)
      for (b <- 0 until 8) when(eligible(n) && group(n) === which && mask(b)) {
        req.mask(b) := True; req.data(b*8, 8 bits) := shifted(b*8, 8 bits)
      }
    }
    fires(p) := req.fire
    when(req.fire) { offer(p) := False; sent(which) := True; pending(which) := True }
    rsp.ready := True
    val id = rsp.id.resize(3)
    val correctPort = if (p == 0) !desc.scratch else desc.scratch && desc.address(id)(4 downto 3) === p-1
    val matches = active && rsp.id < 8 && rsp.epoch === epoch && pending(id) && correctPort
    rejects(p) := rsp.fire && !matches
    when(rsp.fire && matches) {
      pending(id) := False
      when(rsp.error) { stopIssue := True }
      for (n <- 0 until 8) when(eligible(n) && group(n) === id) {
        ready(n) := True; errors(n) := Mux(rsp.error, U(4, 4 bits), U(0, 4 bits))
        values(n) := (rsp.data.asUInt |>> (desc.address(n)(2 downto 0) << 3)) & valueMask
      }
    }
    when(req.valid) {
      assert(active && eligible(which) && group(which) === which && !sent(which), "PPE request lost its group")
    }
  }
  when(fires.orR) { wordCount := wordCount + CountOne(fires).resize(64) }
  when(rejects.orR) { rejectCount := rejectCount + CountOne(rejects).resize(64) }
  when(CountOne(fires(4 downto 1)) > 1) { parallelCount := parallelCount + 1 }
  val lane = cursor.resize(3)
  io.access.valid := active && !logicalDone && cursor < 8 && desc.mask(lane) && ready(lane)
  io.access.lane := lane; io.access.address := desc.address(lane)
  io.access.data := Mux(desc.atomicAdd, values(lane), Mux(desc.write, desc.data(lane) & valueMask, values(lane)))
  io.access.error := errors(lane); io.access.report := desc.report(lane)
  when(active && !logicalDone) {
    when(cursor === 8) { logicalDone := True }
    .elsewhen(!desc.mask(lane)) { cursor := cursor + 1 }
    .elsewhen(io.access.fire) {
      laneCount := laneCount + 1
      when(errors(lane) =/= 0) { failed := True; logicalDone := True; stopIssue := True }
        .otherwise { cursor := cursor + 1 }
    }.elsewhen(cancelled && !ready(lane) && !offer.asBits.orR && !pending.asBits.orR) { logicalDone := True }
  }
  when(!active) { assert(!pending.asBits.orR && !offer.asBits.orR, "PPE instruction reused before drain") }
  when(desc.write && active) { assert(outstanding <= 1, "multiple irreversible store groups in flight") }
  when(io.instruction.fire && io.instruction.atomicAdd) {
    assert(io.instruction.mask === B(1, 8 bits) && !io.instruction.scratch && io.instruction.width === 3,
      "PPE AMOADD is one scalar global 64-bit operation")
  }
}
