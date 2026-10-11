package hats

import spinal.core._
import spinal.lib._

/** S04 cache integration. Default preserves the initial data-only increment;
  * instructionCache=true removes program RAM and uses real I/D L1s and fabric.
  * The caller exclusively owns the entire line-aligned cacheable RAM region;
  * configured forbiddenRegions are assertion-guarded at the cache request edge.
  * Configured deviceRegions use a serialized uncached request/response port after
  * D-L1 clean. This is not a coherence or atomicity mechanism.
  */
class ApeCachedDataTile(m: MemoryHierarchyConfig = MemoryHierarchyConfig(),
                        configuration: ApeConfig = ApeConfig(physicalRegisters = 48),
                        instructionCache: Boolean = false,
                        forbiddenRegions: Seq[(BigInt, BigInt)] = Seq.empty,
                        deviceRegions: Seq[(BigInt, BigInt)] = Seq.empty) extends Component {
  require(configuration.programWords * 4 >= m.lineBytes)
  require(forbiddenRegions.forall { case (start, end) => start >= 0 && start < end && end <= (BigInt(1) << 64) })
  require(deviceRegions.forall { case (start, end) =>
    (start >= 0 && start < end && end <= (BigInt(1) << 64) && start % 8 == 0 && end % 8 == 0)
  }, "device regions must be 64-bit-word aligned")
  val core = new ApeCore(configuration.copy(memoryHierarchy = Some(m), instructionCache = instructionCache,
    deviceRegions = configuration.deviceRegions ++ deviceRegions))
  val cache = new NonBlockingL1(m)
  val instructions = if (instructionCache) Some(new NonBlockingL1(m)) else None
  val fabric = if (instructionCache) Some(new CacheLineFabric(m)) else None
  val io = new Bundle {
    val program = slave Flow(cloneOf(core.io.program.payload))
    val launch = slave Stream(cloneOf(core.io.launch.payload))
    val halt = master Stream(cloneOf(core.io.halt.payload))
    val retired = master Flow(cloneOf(core.io.retired.payload))
    val retiredNext = out UInt(64 bits)
    val memoryRetired = master Flow(cloneOf(core.io.memoryRetired.payload))
    val lower = master Stream(CacheLineRequest(m))
    val reply = slave Stream(CacheLineResponse(m))
    val deviceRequest = master Stream(CacheWordRequest(m))
    val deviceResponse = slave Stream(CacheWordResponse(m))
    val lowerSource = if (instructionCache) out UInt(1 bits) else null
    val replySource = if (instructionCache) in UInt(1 bits) else null
    val flush = slave Stream(Bool())
    val flushed = master Stream(Bool())
    val wordAccepted = master Flow(CacheWordRequest(m))
    val idle, clean = out Bool()
    val outstanding = out UInt(log2Up(configuration.memoryQueueEntries + 1) bits)
    val robOccupancy = out UInt(log2Up(configuration.robEntries + 1) bits)
    val coreBusy = out Bool()
    val memoryLeasedRows = out Bits(configuration.robEntries bits)
    val memoryReplayPending = out Bool()
    val memoryReplayStoreRetired = out Bool()
    val memoryHead = out UInt(log2Up(configuration.robEntries) bits)
    val memoryReplayStoreSlot = out UInt(log2Up(configuration.robEntries) bits)
    val cacheOutstanding = out UInt(log2Up(m.mshrs + 1) bits)
    val allocated, forwarded, partialForwarded, unknownStoreStalls, fenceStalls, discarded = out UInt(64 bits)
    val speculativeLoads, memoryReplays = out UInt(64 bits)
    val hits, misses, refills, writebacks = out UInt(64 bits)
    val instructionHits, instructionMisses, fetchRequests, fetchDiscarded, fetchFaults = out UInt(64 bits)
    val fabricOutstanding = out UInt(log2Up(2 * m.mshrs + 1) bits)
    val fabricAccepted, fabricCompleted, fabricRejected = out UInt(64 bits)
  }
  val hierarchyIdle, maintenanceBusy = Bool()
  core.io.program << io.program
  core.io.launch.valid := io.launch.valid && hierarchyIdle && !maintenanceBusy && !io.flush.valid
  core.io.launch.payload := io.launch.payload
  io.launch.ready := core.io.launch.ready && hierarchyIdle && !maintenanceBusy && !io.flush.valid
  when(core.io.launch.fire) {
    assert(io.launch.base(m.lineShift - 1 downto 0) === 0 && io.launch.limit(m.lineShift - 1 downto 0) === 0,
      "cacheable region must contain complete lines")
  }
  io.halt << core.io.halt; io.retired := core.io.retired
  io.robOccupancy := core.io.occupancy; io.coreBusy := core.io.busy
  io.memoryLeasedRows := core.io.memoryLeasedRows
  io.memoryReplayPending := core.io.memoryReplayPending
  io.memoryReplayStoreRetired := core.io.memoryReplayStoreRetired
  io.memoryHead := core.io.memoryHead
  io.memoryReplayStoreSlot := core.io.memoryReplayStoreSlot
  io.retiredNext := core.io.retiredNext; io.memoryRetired := core.io.memoryRetired
  core.io.memory.ready := False
  core.io.response.valid := False; core.io.response.data := 0; core.io.response.error := False
  val deviceState = Reg(UInt(3 bits)) init 0 // idle, clean, issue, wait, response
  val deviceRequestPayload = Reg(CacheWordRequest(m))
  val deviceResponsePayload = Reg(CacheWordResponse(m))
  val cacheAccess = core.io.cacheRequest
  val deviceHit = deviceRegions.map { case (start, end) =>
    val lowByte = cacheAccess.payload.address.resize(65) + OHToUInt(OHMasking.first(cacheAccess.payload.mask)).resize(65)
    val highByte = cacheAccess.payload.address.resize(65) +
      (U(7, 65 bits) - OHToUInt(OHMasking.first(cacheAccess.payload.mask.reversed)).resize(65))
    cacheAccess.payload.mask.orR && lowByte < U(end, 65 bits) && highByte >= U(start, 65 bits)
  }.foldLeft(False)(_ || _)
  val deviceStart = cacheAccess.valid && deviceHit && deviceState === 0
  cache.io.request.valid := cacheAccess.valid && !deviceHit && deviceState === 0
  cache.io.request.payload := cacheAccess.payload
  cacheAccess.ready := Mux(deviceHit, deviceState === 0, cache.io.request.ready && deviceState === 0)
  when(deviceStart && cacheAccess.ready) {
    deviceRequestPayload := cacheAccess.payload
    deviceState := 1
  }
  io.deviceRequest.valid := deviceState === 2
  io.deviceRequest.payload := deviceRequestPayload
  when(io.deviceRequest.fire) { deviceState := 3 }
  val deviceResponseMatches = io.deviceResponse.id === deviceRequestPayload.id &&
    io.deviceResponse.epoch === deviceRequestPayload.epoch
  io.deviceResponse.ready := deviceState === 3 && deviceResponseMatches
  when(io.deviceResponse.fire) { deviceResponsePayload := io.deviceResponse.payload; deviceState := 4 }
  core.io.cacheResponse.valid := Mux(deviceState === 4, True, cache.io.response.valid)
  core.io.cacheResponse.payload := Mux(deviceState === 4, deviceResponsePayload, cache.io.response.payload)
  cache.io.response.ready := core.io.cacheResponse.ready && deviceState =/= 4
  when(core.io.cacheResponse.fire && deviceState === 4) { deviceState := 0 }
  // The cacheable-RAM path must never absorb device or reserved apertures.
  // Reject any access whose byte interval overlaps a configured forbidden region.
  for ((start, end) <- forbiddenRegions) {
    val byteAddress = cacheAccess.payload.address.resize(65) + OHToUInt(OHMasking.first(cacheAccess.payload.mask)).resize(65)
    val highestByte = cacheAccess.payload.address.resize(65) + (U(7, 65 bits) - OHToUInt(OHMasking.first(cacheAccess.payload.mask.reversed)).resize(65))
    val overlaps = cacheAccess.payload.mask.orR && byteAddress < U(end, 65 bits) && highestByte >= U(start, 65 bits)
    when(cacheAccess.valid && overlaps) {
      assert(False, "APE cache request overlaps forbidden device/reserved region")
    }
  }
  cache.io.drain := False
  val deviceCleanRequest = deviceState === 1
  if (!instructionCache) {
    io.lower << cache.io.lower; cache.io.reply << io.reply
    val maintenance = Reg(UInt(2 bits)) init 0
    val maintenanceFence, maintenanceError = RegInit(False)
    val maintenanceDevice = RegInit(False)
    val externalRequest = io.flush.valid && !core.io.busy && !core.io.systemFence.valid
    val fenceRequest = core.io.systemFence.valid && !io.flush.valid
    cache.io.flush.valid := maintenance === 0 && hierarchyIdle && (externalRequest || fenceRequest || deviceCleanRequest)
    cache.io.flush.payload := Mux(fenceRequest || deviceCleanRequest, False, io.flush.payload)
    io.flush.ready := maintenance === 0 && cache.io.flush.ready && !core.io.busy && !core.io.systemFence.valid && !deviceCleanRequest
    core.io.systemFence.ready := maintenance === 0 && cache.io.flush.ready && hierarchyIdle && !io.flush.valid && !deviceCleanRequest
    when(cache.io.flush.fire) {
      maintenance := 1; maintenanceFence := fenceRequest; maintenanceDevice := deviceCleanRequest; maintenanceError := False
    }
    cache.io.flushed.ready := maintenance === 1 && (maintenanceDevice ||
      Mux(maintenanceFence, core.io.systemFenceResult.ready, io.flushed.ready))
    io.flushed.valid := maintenance === 1 && !maintenanceFence && !maintenanceDevice && cache.io.flushed.valid
    io.flushed.payload := cache.io.flushed.payload
    core.io.systemFenceResult.valid := maintenance === 1 && maintenanceFence && cache.io.flushed.valid
    core.io.systemFenceResult.payload := cache.io.flushed.payload
    when(cache.io.flushed.fire) {
      maintenance := 0
      when(maintenanceDevice) {
        when(cache.io.flushed.payload) {
          deviceResponsePayload.id := deviceRequestPayload.id; deviceResponsePayload.epoch := deviceRequestPayload.epoch
          deviceResponsePayload.data := 0; deviceResponsePayload.error := True; deviceState := 4
        }.otherwise { deviceState := 2 }
      }
    }
    hierarchyIdle := cache.io.idle; maintenanceBusy := False
    io.instructionHits := 0; io.instructionMisses := 0; io.fabricOutstanding := 0
    io.fabricAccepted := 0; io.fabricCompleted := 0; io.fabricRejected := 0
  } else {
    val i = instructions.get; val f = fabric.get
    i.io.request << core.io.fetchRequest; core.io.fetchResponse << i.io.response
    i.io.drain := False
    f.io.requests(0) << i.io.lower; i.io.reply << f.io.responses(0)
    f.io.requests(1) << cache.io.lower; cache.io.reply << f.io.responses(1)
    io.lower.valid := f.io.lower.valid; io.lower.payload := f.io.lower.transfer
    io.lowerSource := f.io.lower.source; f.io.lower.ready := io.lower.ready
    f.io.reply.valid := io.reply.valid; f.io.reply.transfer := io.reply.payload
    f.io.reply.source := io.replySource; io.reply.ready := f.io.reply.ready
    hierarchyIdle := cache.io.idle && i.io.idle && f.io.idle
    io.instructionHits := i.io.hits; io.instructionMisses := i.io.misses
    io.fabricOutstanding := f.io.outstanding
    io.fabricAccepted := f.io.accepted; io.fabricCompleted := f.io.completed; io.fabricRejected := f.io.rejected
    // Ordered publication: D clean (optionally invalidate), then I invalidate,
    // then clear the frontend word buffer. Any error prevents successful ACK.
    val state = Reg(UInt(3 bits)) init 0
    val invalidateData, error, maintenanceFence = RegInit(False)
    val maintenanceDevice = RegInit(False)
    maintenanceBusy := state =/= 0
    io.flush.ready := state === 0 && !core.io.busy && hierarchyIdle && !core.io.systemFence.valid && !deviceCleanRequest
    core.io.systemFence.ready := state === 0 && hierarchyIdle && !io.flush.valid && !deviceCleanRequest
    when(io.flush.fire || core.io.systemFence.fire || (deviceCleanRequest && hierarchyIdle)) {
      state := 1; maintenanceFence := core.io.systemFence.fire; maintenanceDevice := deviceCleanRequest
      invalidateData := io.flush.payload && !core.io.systemFence.fire; error := False
    }
    cache.io.flush.valid := state === 1
    cache.io.flush.payload := invalidateData
    cache.io.flushed.ready := state === 2
    i.io.flush.valid := state === 3; i.io.flush.payload := True
    i.io.flushed.ready := state === 4
    core.io.instructionInvalidate := i.io.flushed.fire && !i.io.flushed.payload
    when(cache.io.flush.fire) { state := 2 }
    when(cache.io.flushed.fire) {
      when(maintenanceDevice) {
        state := 0
        when(cache.io.flushed.payload) {
          deviceResponsePayload.id := deviceRequestPayload.id; deviceResponsePayload.epoch := deviceRequestPayload.epoch
          deviceResponsePayload.data := 0; deviceResponsePayload.error := True; deviceState := 4
        }.otherwise { deviceState := 2 }
      }.otherwise {
        when(cache.io.flushed.payload) { error := True; state := 5 }
          .otherwise { state := Mux(maintenanceFence, U(5, 3 bits), U(3, 3 bits)) }
      }
    }
    when(i.io.flush.fire) { state := 4 }
    when(i.io.flushed.fire) { error := i.io.flushed.payload; state := 5 }
    io.flushed.valid := state === 5 && !maintenanceFence && !maintenanceDevice; io.flushed.payload := error
    core.io.systemFenceResult.valid := state === 5 && maintenanceFence && !maintenanceDevice
    core.io.systemFenceResult.payload := error
    when((io.flushed.fire && !maintenanceFence && !maintenanceDevice) ||
      (core.io.systemFenceResult.fire && !maintenanceDevice)) { state := 0 }
    when(i.io.request.fire) { assert(!i.io.request.write, "instruction cache received a store") }
    when(f.io.lower.fire && f.io.lower.source === 0) {
      assert(!f.io.lower.transfer.write && f.io.lower.transfer.address < BigInt(configuration.programWords) * 4,
        "instruction transaction escaped the code region")
    }
  }
  io.wordAccepted.valid := cache.io.request.fire; io.wordAccepted.payload := cache.io.request.payload
  io.idle := !core.io.busy && hierarchyIdle && !maintenanceBusy; io.clean := cache.io.clean
  io.outstanding := core.io.memoryOutstanding; io.cacheOutstanding := cache.io.outstanding
  io.allocated := core.io.memoryAllocated; io.forwarded := core.io.memoryForwarded
  io.partialForwarded := core.io.memoryPartialForwarded; io.unknownStoreStalls := core.io.memoryUnknownStalls
  io.speculativeLoads := core.io.memorySpeculativeLoads; io.memoryReplays := core.io.memoryReplays
  io.fenceStalls := core.io.memoryFenceStalls; io.discarded := core.io.memoryDiscarded
  io.hits := cache.io.hits; io.misses := cache.io.misses
  io.refills := cache.io.refills; io.writebacks := cache.io.writebacks
  io.fetchRequests := core.io.fetchRequests; io.fetchDiscarded := core.io.fetchDiscarded; io.fetchFaults := core.io.fetchFaults
}
