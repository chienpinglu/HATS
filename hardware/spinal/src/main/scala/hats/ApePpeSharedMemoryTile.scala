package hats

import spinal.core._
import spinal.lib._

/** The first system-level boundary: exactly one engine owns ordinary,
  * line-cacheable RAM at a time. A handoff blocks new work, waits for that
  * engine and its tagged line ledger to drain, cleans/invalidates D then I,
  * and changes owner only on successful maintenance acknowledgement.
  */
class ApePpeSharedMemoryTile(m: MemoryHierarchyConfig = MemoryHierarchyConfig(wordPoison = true),
  apeConfig: ApeConfig = ApeConfig(physicalRegisters = 48, robEntries = 8, issueWidth = 1),
  ppeInstructionBase: BigInt = 0x100000,
  forbiddenRegions: Seq[(BigInt, BigInt)] = Seq.empty,
  deviceRegions: Seq[(BigInt, BigInt)] = Seq.empty,
  ppeDeviceRegions: Seq[(BigInt, BigInt)] = Seq.empty) extends Component {
  val ape = new ApeCachedDataTile(m, apeConfig, instructionCache = true, forbiddenRegions = forbiddenRegions,
    deviceRegions = deviceRegions)
  val ppe = new PpeCachedDataTile(m, instructionCache = true, instructionBase = ppeInstructionBase,
    deviceRegions = ppeDeviceRegions)
  val authority = new MemoryOwnershipController(m)
  val io = new Bundle {
    val apeProgram = slave Flow(cloneOf(ape.io.program.payload))
    val apeLaunch = slave Stream(cloneOf(ape.io.launch.payload))
    val apeHalt = master Stream(cloneOf(ape.io.halt.payload))
    val apeRetired = master Flow(cloneOf(ape.io.retired.payload))
    val apeMemoryRetired = master Flow(cloneOf(ape.io.memoryRetired.payload))
    val apeForwarded, apePartialForwarded, apeCacheHits, apeCacheMisses = out UInt(64 bits)
    val ppeProgram = slave Stream(cloneOf(ppe.io.program.payload))
    val ppeLaunch = slave Stream(cloneOf(ppe.io.launch.payload))
    val ppeCompletion = master Stream(cloneOf(ppe.io.completion.payload))
    val ppeRetired = master Flow(cloneOf(ppe.io.retired.payload))
    val ppeAccess = master Flow(cloneOf(ppe.io.access.payload))
    val lower = master Stream(OwnedLineRequest(m))
    val reply = slave Stream(OwnedLineResponse(m))
    val deviceRequest = master Stream(CacheWordRequest(m))
    val deviceResponse = slave Stream(CacheWordResponse(m))
    val ppeDeviceRequest = master Stream(CacheWordRequest(m))
    val ppeDeviceResponse = slave Stream(CacheWordResponse(m))
    val handoff = slave Stream(Bool())
    val handoffResult = master Stream(OwnershipResult())
    val owner = out Bool()
    val ownershipGeneration = out UInt(32 bits)
    val idle = out Bool()
    val accepted, completed, rejected, denied, handoffs, handoffFailures = out UInt(64 bits)
  }
  ape.io.program << io.apeProgram
  io.deviceRequest << ape.io.deviceRequest
  ape.io.deviceResponse << io.deviceResponse
  io.ppeDeviceRequest << ppe.io.deviceRequest
  ppe.io.deviceResponse << io.ppeDeviceResponse
  ppe.io.program << io.ppeProgram
  ppe.io.inspectScratch := 0 // The combined-system contract hides debug-only scratch inspection.
  authority.io.handoff << io.handoff
  io.owner := authority.io.owner; io.ownershipGeneration := authority.io.generation
  io.handoffResult << authority.io.result
  io.idle := authority.io.idle && ape.io.idle && ppe.io.idle
  io.accepted := authority.io.accepted; io.completed := authority.io.completed
  io.rejected := authority.io.rejected; io.denied := authority.io.denied
  io.handoffs := authority.io.handoffs; io.handoffFailures := authority.io.handoffFailures
  ape.io.launch.valid := io.apeLaunch.valid && !authority.io.owner && authority.io.run
  ape.io.launch.payload := io.apeLaunch.payload
  io.apeLaunch.ready := ape.io.launch.ready && !authority.io.owner && authority.io.run
  ppe.io.launch.valid := io.ppeLaunch.valid && authority.io.owner && authority.io.run
  ppe.io.launch.payload := io.ppeLaunch.payload
  io.ppeLaunch.ready := ppe.io.launch.ready && authority.io.owner && authority.io.run
  val apeOwnerGeneration, ppeOwnerGeneration = Reg(UInt(32 bits)) init 0
  when(io.apeLaunch.fire) { apeOwnerGeneration := authority.io.generation }
  when(io.ppeLaunch.fire) { ppeOwnerGeneration := authority.io.generation }
  io.apeHalt << ape.io.halt; io.apeRetired := ape.io.retired; io.apeMemoryRetired := ape.io.memoryRetired
  io.ppeCompletion << ppe.io.completion; io.ppeRetired := ppe.io.retired; io.ppeAccess := ppe.io.access
  io.apeForwarded := ape.io.forwarded; io.apePartialForwarded := ape.io.partialForwarded
  io.apeCacheHits := ape.io.hits; io.apeCacheMisses := ape.io.misses
  authority.io.clientIdle := ppe.io.idle ## ape.io.idle
  val linePorts = Seq(ape.io.lower, ppe.io.lower)
  val sourcePorts = Seq(ape.io.lowerSource, ppe.io.lowerSource)
  val flushPorts = Seq(ape.io.flush, ppe.io.flush)
  val flushResultPorts = Seq(ape.io.flushed, ppe.io.flushed)
  val replyPorts = Seq(ape.io.reply, ppe.io.reply)
  val replySourcePorts = Seq(ape.io.replySource, ppe.io.replySource)
  for (e <- 0 until 2) {
    val req = authority.io.requests(e)
    req.valid := linePorts(e).valid
    req.source := sourcePorts(e)
    req.ownerGeneration := (if (e == 0) apeOwnerGeneration else ppeOwnerGeneration)
    req.transfer := linePorts(e).payload
    linePorts(e).ready := req.ready
    flushPorts(e).valid := authority.io.flush(e).valid
    flushPorts(e).payload := authority.io.flush(e).payload
    authority.io.flush(e).ready := flushPorts(e).ready
    authority.io.flushed(e).valid := flushResultPorts(e).valid
    authority.io.flushed(e).payload := flushResultPorts(e).payload
    flushResultPorts(e).ready := authority.io.flushed(e).ready
    replyPorts(e).valid := authority.io.responses(e).valid
    replySourcePorts(e) := authority.io.responses(e).source
    replyPorts(e).payload := authority.io.responses(e).transfer
    authority.io.responses(e).ready := replyPorts(e).ready
  }
  authority.io.lower.ready := io.lower.ready
  io.lower.valid := authority.io.lower.valid; io.lower.payload := authority.io.lower.payload
  authority.io.reply.valid := io.reply.valid; authority.io.reply.payload := io.reply.payload
  io.reply.ready := authority.io.reply.ready
}
