package hats

import spinal.core._
import spinal.lib._

/** ROB-backed address/data queue, with independent transport leases. The ROB
  * holds stores until non-speculative authorization at its head. Known older
  * stores forward bytewise; loads may pass unknown older RAM stores and trigger
  * a precise replay if a later-resolved store overlaps. Transport leases survive
  * recovery and cannot alias a reused ROB slot.
  */
case class ApeMemoryRow(c: ApeConfig) extends Bundle {
  val live, prepared, sent, store, fence, device, atomicAdd = Bool()
  val identity = ApeExecutionIdentity(c)
  val address, data = UInt(64 bits)
  val size = UInt(2 bits)
}

case class ApeMemoryResult(c: ApeConfig) extends Bundle {
  val identity = ApeExecutionIdentity(c)
  val data = UInt(64 bits) // right-justified, not sign extended
  val store, atomicAdd, error = Bool()
}

object ApeMemoryLeaseState extends SpinalEnum {
  val FREE, SEND, WAIT, DONE = newElement()
}

class ApeLoadStoreQueue(c: ApeConfig, m: MemoryHierarchyConfig, entries: Int = 8) extends Component {
  require(entries >= 2 && isPow2(entries) && m.clientIdBits >= log2Up(entries))
  val io = new Bundle {
    val rows = in Vec(ApeMemoryRow(c), c.robEntries)
    val head = in UInt(c.tagBits bits)
    val enable = in Bool()
    val replayPending = in Bool()
    val replayStore = in UInt(c.tagBits bits)
    val replayStoreRetired = in Bool()
    val replay = out Bool()
    val replayStoreSlot = out UInt(c.tagBits bits)
    val accepted = master Flow(UInt(c.tagBits bits))
    val result = master Stream(ApeMemoryResult(c))
    val request = master Stream(CacheWordRequest(m))
    val response = slave Stream(CacheWordResponse(m))
    val reusable = out Bits(c.robEntries bits)
    val leasedRows = out Bits(c.robEntries bits)
    val idle = out Bool()
    val outstanding = out UInt(log2Up(entries + 1) bits)
    val allocated, forwarded, partialForwarded, unknownStoreStalls, fenceStalls, rejected,
      speculativeLoads, replays = out UInt(64 bits)
  }
  val states = Vec.fill(entries)(Reg(ApeMemoryLeaseState()) init ApeMemoryLeaseState.FREE)
  val owners = Vec.fill(entries)(Reg(ApeExecutionIdentity(c)))
  val epochs = Vec.fill(entries)(Reg(UInt(m.epochBits bits)) init 0)
  val addresses, storeData, values = Vec.fill(entries)(Reg(UInt(64 bits)) init 0)
  val masks, forwarding = Vec.fill(entries)(Reg(Bits(8 bits)) init 0)
  val forwardData = Vec.fill(entries)(Reg(Bits(64 bits)) init 0)
  val isStore, isAtomicAdd, errors, reported = Vec.fill(entries)(RegInit(False))
  val requestHeld, resultHeld = RegInit(False)
  val heldRequest, heldResult = Reg(UInt(log2Up(entries) bits)) init 0
  val free = Bits(entries bits)
  for (i <- 0 until entries) free(i) := states(i) === ApeMemoryLeaseState.FREE
  val slot = OHToUInt(OHMasking.first(free))
  io.outstanding := CountOne(~free).resized
  io.idle := free.andR
  for (r <- 0 until c.robEntries) {
    io.reusable(r) := !(0 until entries).map(i => !free(i) && owners(i).slot === r).reduce(_ || _)
    io.leasedRows(r) := !io.reusable(r)
  }
  for (i <- 0 until entries) {
    val ownerRow = io.rows(owners(i).slot)
    // Once the triggering store retires, every remaining lease is younger:
    // all older ROB entries (including the store) have left the head.
    val squashedByReplay = io.replayPending && io.replayStoreRetired
    val ownerAlive = ownerRow.live && !squashedByReplay && ownerRow.identity.generation === owners(i).generation &&
      ownerRow.identity.destination === owners(i).destination
    when(states(i) === ApeMemoryLeaseState.DONE && reported(i) && !ownerAlive) {
      states(i) := ApeMemoryLeaseState.FREE
      reported(i) := False
    }
  }
  def byteMask(size: UInt, address: UInt): Bits = {
    val base = Bits(8 bits)
    base := B(1, 8 bits)
    switch(size) { is(1) { base := B(3, 8 bits) }; is(2) { base := B(15, 8 bits) }; is(3) { base := B(255, 8 bits) } }
    (base |<< address(2 downto 0)).resize(8)
  }
  val eligibility = Bits(c.robEntries bits)
  val unknown, barriers = Bits(c.robEntries bits)
  for (r <- 0 until c.robEntries) {
    val row = io.rows(r)
    val age = (U(r, c.tagBits bits) - io.head).resize(c.tagBits)
    unknown(r) := (0 until c.robEntries).map(o => {
      val older = (U(o, c.tagBits bits) - io.head).resize(c.tagBits) < age
      io.rows(o).live && older && io.rows(o).store && !io.rows(o).prepared
    }).reduce(_ || _)
    barriers(r) := (0 until c.robEntries).map(o => io.rows(o).live &&
      (io.rows(o).fence || io.rows(o).device || io.rows(o).atomicAdd) &&
      (U(o, c.tagBits bits) - io.head).resize(c.tagBits) < age).reduce(_ || _)
    val replayAge = (io.replayStore - io.head).resize(c.tagBits)
    val rowReplayAge = (U(r, c.tagBits bits) - io.head).resize(c.tagBits)
    val beforeReplayCut = !io.replayPending || (!io.replayStoreRetired && rowReplayAge <= replayAge)
    eligibility(r) := row.live && row.prepared && !row.sent && io.reusable(r) && beforeReplayCut &&
      Mux(row.device, U(r, c.tagBits bits) === io.head && free.andR,
        Mux(row.atomicAdd, U(r, c.tagBits bits) === io.head && free.andR,
          Mux(row.store, U(r, c.tagBits bits) === io.head, !barriers(r))))
  }
  // Select oldest ready memory operation, not oldest ROB operation.
  val ordered = Bits(c.robEntries bits)
  for (age <- 0 until c.robEntries) ordered(age) := eligibility((io.head + age).resize(c.tagBits))
  val selected = (io.head + OHToUInt(OHMasking.first(ordered))).resize(c.tagBits)
  val row = io.rows(selected)
  val needed = byteMask(row.size, row.address)
  val selectedAge = (selected - io.head).resize(c.tagBits)
  // Walk oldest to youngest; each byte is taken from the youngest covering store.
  val fmask = Vec(Bits(8 bits), c.robEntries + 1)
  val fdata = Vec(Bits(64 bits), c.robEntries + 1)
  fmask(0) := B(0, 8 bits); fdata(0) := B(0, 64 bits)
  for (age <- 0 until c.robEntries) {
    val older = io.rows((io.head + age).resize(c.tagBits))
    val covers = older.live && older.store && older.prepared && U(age, c.tagBits bits) < selectedAge &&
      older.address(63 downto 3) === row.address(63 downto 3)
    val mask = byteMask(older.size, older.address)
    val data = (older.data |<< (older.address(2 downto 0) << 3)).resize(64).asBits
    fmask(age + 1) := fmask(age); fdata(age + 1) := fdata(age)
    when(covers) {
      fmask(age + 1) := fmask(age) | mask
      for (b <- 0 until 8) when(mask(b)) { fdata(age + 1)(b*8, 8 bits) := data(b*8, 8 bits) }
    }
  }
  val fullForward = (fmask.last & needed) === needed && !row.store
  val allocate = io.enable && ordered.orR && free.orR && !io.replay
  io.accepted.valid := allocate; io.accepted.payload := selected
  val allocateCount, forwardCount, partialCount, fenceCount, rejectCount,
    speculativeCount, replayCount = Reg(UInt(64 bits)) init 0
  val replaySeen = RegInit(False)
  io.allocated := allocateCount; io.forwarded := forwardCount; io.partialForwarded := partialCount
  io.unknownStoreStalls := 0; io.fenceStalls := fenceCount; io.rejected := rejectCount
  io.speculativeLoads := speculativeCount; io.replays := replayCount
  val pendingLoads = Bits(c.robEntries bits)
  for (r <- 0 until c.robEntries) pendingLoads(r) := io.rows(r).live && io.rows(r).prepared && !io.rows(r).sent && !io.rows(r).store
  when(io.enable && (pendingLoads & barriers).orR) { fenceCount := fenceCount + 1 }
  val violatingStores = Bits(c.robEntries bits)
  for (s <- 0 until c.robEntries) {
    val store = io.rows(s)
    val storeAge = (U(s, c.tagBits bits) - io.head).resize(c.tagBits)
    val overlappingLease = (0 until entries).map(i => {
      val loadSlot = owners(i).slot
      val load = io.rows(loadSlot)
      val loadAge = (loadSlot - io.head).resize(c.tagBits)
      val ownerMatches = load.live && load.identity.generation === owners(i).generation &&
        load.identity.destination === owners(i).destination
      val byteOverlap = (addresses(i)(63 downto 3) === store.address(63 downto 3)) &&
        (masks(i) & byteMask(store.size, store.address)).orR
      !free(i) && !isStore(i) && ownerMatches && loadAge > storeAge && byteOverlap
    }).reduce(_ || _)
    violatingStores(s) := store.live && store.prepared && store.store && !store.device &&
      !store.atomicAdd && !store.fence && overlappingLease
  }
  val orderedViolations = Bits(c.robEntries bits)
  for (age <- 0 until c.robEntries)
    orderedViolations(age) := violatingStores((io.head + age).resize(c.tagBits))
  // Latch one recovery request in the core. Keep the violating store issuable
  // while that recovery is draining; otherwise the level-sensitive hazard
  // would suppress the very store needed to retire the replay checkpoint.
  io.replay := orderedViolations.orR && !io.replayPending
  io.replayStoreSlot := (io.head + OHToUInt(OHMasking.first(orderedViolations))).resize(c.tagBits)
  when(io.replay && !replaySeen) { replayCount := replayCount + 1 }
  replaySeen := io.replay
  when(allocate) {
    owners(slot) := row.identity; epochs(slot) := epochs(slot) + 1
    addresses(slot) := row.address; storeData(slot) := (row.data |<< (row.address(2 downto 0) << 3)).resized
    masks(slot) := needed; forwarding(slot) := fmask.last; forwardData(slot) := fdata.last
    isStore(slot) := row.store; isAtomicAdd(slot) := row.atomicAdd; errors(slot) := False
    reported(slot) := False
    values(slot) := (fdata.last.asUInt |>> (row.address(2 downto 0) << 3)).resize(64)
    states(slot) := Mux(fullForward, ApeMemoryLeaseState.DONE, ApeMemoryLeaseState.SEND)
    allocateCount := allocateCount + 1
    when(fullForward) { forwardCount := forwardCount + 1 }
    when(!row.store && unknown(selected)) { speculativeCount := speculativeCount + 1 }
    when(!row.store && !fullForward && (fmask.last & needed).orR) { partialCount := partialCount + 1 }
    when(row.store) { assert(selected === io.head, "store escaped non-speculative head") }
  }
  // An offered request is irrevocable even if its load is subsequently squashed.
  // Its ROB slot remains leased until its response has drained.
  val sends, dones = Bits(entries bits)
  for (i <- 0 until entries) {
    sends(i) := states(i) === ApeMemoryLeaseState.SEND
    dones(i) := states(i) === ApeMemoryLeaseState.DONE && !reported(i)
  }
  val send = Mux(requestHeld, heldRequest, OHToUInt(OHMasking.first(sends)))
  io.request.valid := sends.orR
  io.request.id := send.resized; io.request.epoch := epochs(send)
  io.request.address := addresses(send) & U(BigInt("fffffffffffffff8", 16), 64 bits)
  io.request.write := isStore(send); io.request.atomicAdd := isAtomicAdd(send)
  io.request.data := storeData(send).asBits; io.request.mask := masks(send)
  when(io.request.valid && !io.request.ready) { requestHeld := True; heldRequest := send }
  when(io.request.fire) { requestHeld := False; states(send) := ApeMemoryLeaseState.WAIT }
  val reply = io.response.id.resize(log2Up(entries))
  val replyOwned = io.response.id < entries && states(reply) === ApeMemoryLeaseState.WAIT && epochs(reply) === io.response.epoch
  io.response.ready := True
  val merged = Bits(64 bits)
  merged := io.response.data
  for (b <- 0 until 8) when(forwarding(reply)(b)) { merged(b*8, 8 bits) := forwardData(reply)(b*8, 8 bits) }
  when(io.response.fire) {
    when(replyOwned) {
      values(reply) := Mux(isStore(reply) && !isAtomicAdd(reply), U(0, 64 bits),
        (merged.asUInt |>> (addresses(reply)(2 downto 0) << 3)).resize(64))
      errors(reply) := io.response.error; states(reply) := ApeMemoryLeaseState.DONE
    }.otherwise { rejectCount := rejectCount + 1 }
  }
  val done = Mux(resultHeld, heldResult, OHToUInt(OHMasking.first(dones)))
  io.result.valid := dones.orR
  io.result.identity := owners(done); io.result.data := values(done)
  io.result.store := isStore(done) && !isAtomicAdd(done)
  io.result.atomicAdd := isAtomicAdd(done); io.result.error := errors(done)
  when(io.result.valid && !io.result.ready) { resultHeld := True; heldResult := done }
  when(io.result.fire) {
    resultHeld := False
    val ownerRow = io.rows(owners(done).slot)
    when(isStore(done) || isAtomicAdd(done) || !ownerRow.live ||
      ownerRow.identity.generation =/= owners(done).generation ||
      ownerRow.identity.destination =/= owners(done).destination) {
      states(done) := ApeMemoryLeaseState.FREE
      reported(done) := False
    }.otherwise { reported(done) := True }
  }
  for (a <- 0 until entries; b <- a + 1 until entries) {
    assert(free(a) || free(b) || owners(a).slot =/= owners(b).slot, "ROB slot has duplicate memory leases")
  }
  when(requestHeld) { assert(sends(heldRequest), "held memory request lost its owner") }
  when(resultHeld) { assert(dones(heldResult), "held memory completion lost its owner") }
}
