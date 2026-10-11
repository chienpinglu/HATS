package hats

import spinal.core._
import spinal.lib._

/** Verification top exposing the selected ROB8/P48 APE LSQ contract. */
class ApeLoadStoreQueueFormalTop extends Component {
  val c = ApeConfig(robEntries = 8, physicalRegisters = 48, memoryQueueEntries = 8,
    memoryHierarchy = Some(MemoryHierarchyConfig(sets = 8, lineBytes = 32, mshrs = 4, epochBits = 2)))
  val m = c.memoryHierarchy.get
  val queue = new ApeLoadStoreQueue(c, m, c.memoryQueueEntries)
  val io = new Bundle {
    val rows = in Vec(ApeMemoryRow(c), c.robEntries)
    val head = in UInt(c.tagBits bits)
    val enable = in Bool()
    val replayPending, replayStoreRetired = in Bool()
    val replayStore = in UInt(c.tagBits bits)
    val replay = out Bool()
    val replayStoreSlot = out UInt(c.tagBits bits)
    val accepted = master Flow(UInt(c.tagBits bits))
    val result = master Stream(ApeMemoryResult(c))
    val request = master Stream(CacheWordRequest(m))
    val response = slave Stream(CacheWordResponse(m))
    val reusable = out Bits(c.robEntries bits)
    val leasedRows = out Bits(c.robEntries bits)
    val idle = out Bool()
    val outstanding = out UInt(log2Up(c.memoryQueueEntries + 1) bits)
    val allocated, forwarded, partialForwarded, unknownStoreStalls, fenceStalls, rejected = out UInt(64 bits)
    val speculativeLoads, replays = out UInt(64 bits)
  }
  queue.io.rows := io.rows; queue.io.head := io.head; queue.io.enable := io.enable
  queue.io.replayPending := io.replayPending; queue.io.replayStore := io.replayStore
  queue.io.replayStoreRetired := io.replayStoreRetired
  io.replay := queue.io.replay; io.replayStoreSlot := queue.io.replayStoreSlot
  io.accepted.valid := queue.io.accepted.valid; io.accepted.payload := queue.io.accepted.payload
  io.result.valid := queue.io.result.valid; io.result.payload := queue.io.result.payload
  queue.io.result.ready := io.result.ready
  io.request.valid := queue.io.request.valid; io.request.payload := queue.io.request.payload
  queue.io.request.ready := io.request.ready
  queue.io.response.valid := io.response.valid; queue.io.response.payload := io.response.payload
  io.response.ready := queue.io.response.ready
  io.reusable := queue.io.reusable; io.leasedRows := queue.io.leasedRows
  io.idle := queue.io.idle; io.outstanding := queue.io.outstanding
  io.allocated := queue.io.allocated; io.forwarded := queue.io.forwarded
  io.partialForwarded := queue.io.partialForwarded; io.unknownStoreStalls := queue.io.unknownStoreStalls
  io.fenceStalls := queue.io.fenceStalls; io.rejected := queue.io.rejected
  io.speculativeLoads := queue.io.speculativeLoads; io.replays := queue.io.replays
}

object GenerateApeLoadStoreQueueFormal extends App {
  val out = java.nio.file.Paths.get(args.headOption.getOrElse("build/s04/ape-lsq-formal-rtl"))
  SpinalConfig(targetDirectory = out.toString, defaultConfigForClockDomains = ClockDomainConfig(resetKind = SYNC))
    .generateVerilog(new ApeLoadStoreQueueFormalTop)
}
