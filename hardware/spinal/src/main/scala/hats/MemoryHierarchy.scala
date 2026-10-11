package hats

import spinal.core._
import spinal.lib._

/** Physical-address cache boundary. Not a DRAM PHY or a coherence protocol. */
case class MemoryHierarchyConfig(sets: Int = 16, lineBytes: Int = 32,
                                 mshrs: Int = 4, clientIdBits: Int = 8,
                                 epochBits: Int = 8, wordPoison: Boolean = false) {
  require(sets >= 2 && isPow2(sets))
  require(lineBytes >= 16 && lineBytes <= 128 && isPow2(lineBytes))
  require(mshrs >= 2 && mshrs <= 16 && isPow2(mshrs))
  require(clientIdBits >= 1 && epochBits >= 2)
  val setBits = log2Up(sets)
  val lineShift = log2Up(lineBytes)
  val lineBits = lineBytes * 8
  val words = lineBytes / 8
  val wordBits = log2Up(words)
  val slotBits = log2Up(mshrs)
}

case class CacheWordRequest(c: MemoryHierarchyConfig) extends Bundle {
  val id = UInt(c.clientIdBits bits)
  val epoch = UInt(c.epochBits bits)
  val address = UInt(64 bits)
  val write = Bool()
  // HATS cache-side atomic add: operand is in data; response returns old value.
  // Kept distinct from ordinary stores so the line update is indivisible.
  val atomicAdd = Bool()
  val data = Bits(64 bits)
  val mask = Bits(8 bits)
}

case class CacheWordResponse(c: MemoryHierarchyConfig) extends Bundle {
  val id = UInt(c.clientIdBits bits)
  val epoch = UInt(c.epochBits bits)
  val data = Bits(64 bits)
  val error = Bool()
}

case class CacheLineRequest(c: MemoryHierarchyConfig) extends Bundle {
  val slot = UInt(c.slotBits bits)
  val generation = UInt(c.epochBits bits)
  val address = UInt(64 bits)
  val write = Bool()
  val data = Vec(Bits(64 bits), c.words)
  val poison = if (c.wordPoison) Bits(c.words bits) else null
}

case class CacheLineResponse(c: MemoryHierarchyConfig) extends Bundle {
  val slot = UInt(c.slotBits bits)
  val generation = UInt(c.epochBits bits)
  val write = Bool()
  val data = Vec(Bits(64 bits), c.words)
  val error = Bool()
  val poison = if (c.wordPoison) Bits(c.words bits) else null
}

object CacheMissState extends SpinalEnum {
  val FREE, WRITEBACK, WAIT_WRITEBACK, REFILL, WAIT_REFILL, RESPONSE = newElement()
}

/** Write-back, write-allocate L1. One owner per cache index; misses at distinct
  * indices overlap, responses reorder, and hits proceed under unrelated misses.
  * All external irreversible requests require authorization before this port.
  */
class NonBlockingL1(c: MemoryHierarchyConfig = MemoryHierarchyConfig()) extends Component {
  val io = new Bundle {
    val request = slave Stream(CacheWordRequest(c))
    val response = master Stream(CacheWordResponse(c))
    val lower = master Stream(CacheLineRequest(c))
    val reply = slave Stream(CacheLineResponse(c))
    val drain = in Bool()
    val idle, clean = out Bool()
    val flush = slave Stream(Bool()) // true: clean+invalidate; false: clean only
    val flushed = master Stream(Bool()) // true: error, ownership must not transfer
    val outstanding = out UInt(log2Up(c.mshrs + 1) bits)
    val hits, misses, writebacks, refills, rejectedReplies, setStalls, fullStalls = out UInt(64 bits)
  }
  val valid, dirty = Vec.fill(c.sets)(RegInit(False))
  val tags = Vec.fill(c.sets)(Reg(UInt((64 - c.lineShift) bits)) init 0)
  val lines = Vec.fill(c.sets)(Reg(Bits(c.lineBits bits)) init 0)
  // A successful line transfer may contain individual unusable words. Preserve
  // that metadata on writeback; it is not a whole-line transport failure.
  val poisoned = if (c.wordPoison) Vec.fill(c.sets)(Reg(Bits(c.words bits)) init 0) else null
  val states = Vec.fill(c.mshrs)(Reg(CacheMissState()) init CacheMissState.FREE)
  val owners = Vec.fill(c.mshrs)(Reg(CacheWordRequest(c)))
  val indices = Vec.fill(c.mshrs)(Reg(UInt(c.setBits bits)) init 0)
  val generations = Vec.fill(c.mshrs)(Reg(UInt(c.epochBits bits)) init 0)
  val resultData = Vec.fill(c.mshrs)(Reg(Bits(64 bits)) init 0)
  val resultError, maintenance = Vec.fill(c.mshrs)(RegInit(False))
  val cleaning, invalidate = RegInit(False)
  val cleanIndex = Reg(UInt(c.setBits bits)) init 0
  val flushValid, flushError = RegInit(False)
  io.flushed.valid := flushValid; io.flushed.payload := flushError
  when(io.flushed.fire) { flushValid := False }
  val free = Bits(c.mshrs bits)
  for (i <- 0 until c.mshrs) free(i) := states(i) === CacheMissState.FREE
  val allocated = OHToUInt(OHMasking.first(free))
  val busy = ~free
  io.outstanding := CountOne(busy).resize(io.outstanding.getWidth)
  io.idle := !busy.orR && !cleaning && !flushValid
  io.clean := !dirty.asBits.orR // idle alone does not authorize a lossless reset
  io.flush.ready := io.idle
  when(io.flush.fire) { cleaning := True; invalidate := io.flush.payload; cleanIndex := 0; flushError := False }

  val reqIndex = io.request.address(c.lineShift + c.setBits - 1 downto c.lineShift)
  val reqTag = io.request.address(63 downto c.lineShift)
  val reqWord = io.request.address(c.lineShift - 1 downto 3)
  val conflict = (0 until c.mshrs).map(i => busy(i) && indices(i) === reqIndex).reduce(_ || _)
  val duplicate = (0 until c.mshrs).map(i => busy(i) && !maintenance(i) &&
    owners(i).id === io.request.id && owners(i).epoch === io.request.epoch).reduce(_ || _)
  val hit = valid(reqIndex) && tags(reqIndex) === reqTag
  val aligned = io.request.address(2 downto 0) === 0
  val hitPoison = if (c.wordPoison) poisoned(reqIndex)(reqWord) else False
  io.request.ready := free.orR && !conflict && !duplicate && !io.drain && !cleaning && !flushValid && !io.flush.valid
  def word(line: Bits, offset: UInt): Bits = line.subdivideIn(64 bits)(offset)
  def merge(line: Bits, offset: UInt, value: Bits, mask: Bits): Bits = {
    val merged = Bits(c.lineBits bits)
    merged := line
    for (w <- 0 until c.words; b <- 0 until 8) {
      when(offset === w && mask(b)) { merged((w*8+b)*8, 8 bits) := value(b*8, 8 bits) }
    }
    merged
  }
  val hitCount, missCount, wbCount, fillCount, rejectCount, setCount, fullCount = Reg(UInt(64 bits)) init 0
  io.hits := hitCount; io.misses := missCount; io.writebacks := wbCount; io.refills := fillCount
  io.rejectedReplies := rejectCount; io.setStalls := setCount; io.fullStalls := fullCount
  when(io.request.valid && conflict) { setCount := setCount + 1 }
  when(io.request.valid && !free.orR) { fullCount := fullCount + 1 }
  when(io.request.fire) {
    owners(allocated) := io.request.payload; indices(allocated) := reqIndex
    generations(allocated) := generations(allocated) + 1
    maintenance(allocated) := False
    resultError(allocated) := !aligned || (io.request.atomicAdd && (!io.request.write || io.request.mask =/= B(255, 8 bits)))
    resultData(allocated) := B(0, 64 bits)
    when(!aligned) { states(allocated) := CacheMissState.RESPONSE }
      .elsewhen(hit) {
        hitCount := hitCount + 1
        states(allocated) := CacheMissState.RESPONSE
        resultError(allocated) := hitPoison || (io.request.atomicAdd && (!io.request.write || io.request.mask =/= B(255, 8 bits)))
        val oldWord = word(lines(reqIndex), reqWord).asUInt
        when(!io.request.write && !hitPoison) { resultData(allocated) := oldWord.asBits }
        when(io.request.atomicAdd && !hitPoison && aligned && io.request.mask === B(255, 8 bits)) {
          resultData(allocated) := oldWord.asBits
          lines(reqIndex) := merge(lines(reqIndex), reqWord, (oldWord + io.request.data.asUInt).asBits, B(255, 8 bits))
          dirty(reqIndex) := True
        }
        when(io.request.write && io.request.mask.orR && !hitPoison && !io.request.atomicAdd) {
          when(!io.request.atomicAdd && aligned) {
            lines(reqIndex) := merge(lines(reqIndex), reqWord, io.request.data, io.request.mask)
            dirty(reqIndex) := True
          }
        }
      }.otherwise {
        missCount := missCount + 1
        states(allocated) := Mux(valid(reqIndex) && dirty(reqIndex), CacheMissState.WRITEBACK, CacheMissState.REFILL)
      }
  }

  // Locked round-robin arbitration: selection cannot change while stalled.
  def select(candidates: Bits, cursor: UInt): UInt = {
    val rotated = Bits(c.mshrs bits)
    for (offset <- 0 until c.mshrs) rotated(offset) := candidates((cursor + offset).resize(c.slotBits))
    (cursor + OHToUInt(OHMasking.first(rotated))).resize(c.slotBits)
  }
  val sendable, respondable = Bits(c.mshrs bits)
  for (i <- 0 until c.mshrs) {
    sendable(i) := states(i) === CacheMissState.WRITEBACK || states(i) === CacheMissState.REFILL
    respondable(i) := states(i) === CacheMissState.RESPONSE
  }
  val lowerHeld, responseHeld = RegInit(False)
  val lowerSlot, responseSlot, lowerCursor, responseCursor = Reg(UInt(c.slotBits bits)) init 0
  val sending = Mux(lowerHeld, lowerSlot, select(sendable, lowerCursor))
  val responding = Mux(responseHeld, responseSlot, select(respondable, responseCursor))
  val sendingIndex = indices(sending)
  io.lower.valid := sendable.orR
  io.lower.slot := sending; io.lower.generation := generations(sending)
  io.lower.write := states(sending) === CacheMissState.WRITEBACK
  io.lower.address := ((owners(sending).address |>> c.lineShift) << c.lineShift).resize(64)
  when(io.lower.write) { io.lower.address := (tags(sendingIndex).resize(64) << c.lineShift).resize(64) }
  io.lower.data.assignFromBits(lines(sendingIndex))
  if (c.wordPoison) io.lower.poison := poisoned(sendingIndex)
  when(io.lower.valid && !io.lower.ready) { lowerHeld := True; lowerSlot := sending }
  when(io.lower.fire) {
    lowerHeld := False; lowerCursor := sending + 1
    states(sending) := Mux(io.lower.write, CacheMissState.WAIT_WRITEBACK, CacheMissState.WAIT_REFILL)
    when(io.lower.write) { wbCount := wbCount + 1 }.otherwise { fillCount := fillCount + 1 }
  }
  io.response.valid := respondable.orR
  io.response.id := owners(responding).id; io.response.epoch := owners(responding).epoch
  io.response.data := resultData(responding); io.response.error := resultError(responding)
  when(io.response.valid && !io.response.ready) { responseHeld := True; responseSlot := responding }
  when(io.response.fire) {
    responseHeld := False; responseCursor := responding + 1; states(responding) := CacheMissState.FREE
  }

  val replySlot = io.reply.slot
  val replyIndex = indices(replySlot)
  val waitingWrite = states(replySlot) === CacheMissState.WAIT_WRITEBACK
  val waitingRead = states(replySlot) === CacheMissState.WAIT_REFILL
  val matches = io.reply.generation === generations(replySlot) &&
    ((waitingWrite && io.reply.write) || (waitingRead && !io.reply.write))
  io.reply.ready := True
  val cleanStep = Bool(); cleanStep := False
  when(io.reply.fire) {
    when(!matches) { rejectCount := rejectCount + 1 }
      .otherwise {
        when(io.reply.error) {
          when(maintenance(replySlot)) {
            states(replySlot) := CacheMissState.FREE
            cleaning := False; flushValid := True; flushError := True
          }.otherwise { states(replySlot) := CacheMissState.RESPONSE; resultError(replySlot) := True }
        }.elsewhen(waitingWrite) {
          dirty(replyIndex) := False
          when(maintenance(replySlot)) {
            when(invalidate) { valid(replyIndex) := False }
            states(replySlot) := CacheMissState.FREE; cleanStep := True
          }.otherwise { valid(replyIndex) := False; states(replySlot) := CacheMissState.REFILL }
        }.otherwise {
          val requested = owners(replySlot)
          val offset = requested.address(c.lineShift - 1 downto 3)
          val badWord = if (c.wordPoison) io.reply.poison(offset) else False
          val validAtomic = !requested.atomicAdd || (requested.write && requested.mask === B(255, 8 bits) && requested.address(2 downto 0) === 0)
          val commitStore = requested.write && !badWord && validAtomic
          val oldWord = word(io.reply.data.asBits, offset).asUInt
          val committedData = Mux(requested.atomicAdd, (oldWord + requested.data.asUInt).asBits, requested.data)
          valid(replyIndex) := True; dirty(replyIndex) := commitStore && requested.mask.orR
          tags(replyIndex) := requested.address(63 downto c.lineShift)
          if (c.wordPoison) poisoned(replyIndex) := io.reply.poison
          lines(replyIndex) := Mux(commitStore, merge(io.reply.data.asBits, offset, committedData, requested.mask), io.reply.data.asBits)
          resultData(replySlot) := Mux(requested.atomicAdd && commitStore, oldWord.asBits,
            Mux(requested.write || badWord, B(0, 64 bits), oldWord.asBits))
          resultError(replySlot) := badWord || !validAtomic; states(replySlot) := CacheMissState.RESPONSE
        }
      }
  }
  when(cleaning && !busy.orR) {
    when(valid(cleanIndex) && dirty(cleanIndex)) {
      indices(allocated) := cleanIndex; maintenance(allocated) := True
      generations(allocated) := generations(allocated) + 1
      owners(allocated).assignFromBits(B(0, owners(allocated).getBitsWidth bits))
      states(allocated) := CacheMissState.WRITEBACK
    }.otherwise {
      when(invalidate) { valid(cleanIndex) := False }
      cleanStep := True
    }
  }
  when(cleanStep) {
    when(cleanIndex === c.sets - 1) { cleaning := False; flushValid := True }
      .otherwise { cleanIndex := cleanIndex + 1 }
  }

  for (i <- 0 until c.mshrs; j <- i + 1 until c.mshrs) {
    assert(!(busy(i) && busy(j) && indices(i) === indices(j)), "cache index has multiple active owners")
    assert(!(busy(i) && busy(j) && !maintenance(i) && !maintenance(j) &&
      owners(i).id === owners(j).id && owners(i).epoch === owners(j).epoch), "duplicate client transaction ownership")
  }
  for (s <- 0 until c.sets) assert(!dirty(s) || valid(s), "dirty cache line is invalid")
  when(lowerHeld) { assert(sendable(lowerSlot), "held lower request lost its owner") }
  when(responseHeld) { assert(respondable(responseSlot), "held response lost its owner") }
  when(io.reply.fire && matches) { assert(busy(replySlot), "reply without a live MSHR") }
}
