package hats

import spinal.core._
import spinal.lib._

/** PPE I/D-cache integration. The caller owns whole padded cache
  * lines around the descriptor's byte-granular object. Configured device
  * apertures bypass D-L1 after a clean-only drain. The default data-only mode
  * preserves the original increment; instructionCache=true removes loader RAM.
  */
class PpeCachedDataTile(m: MemoryHierarchyConfig = MemoryHierarchyConfig(wordPoison = true),
                        instructionCache: Boolean = false, instructionBase: BigInt = 0x100000,
                        deviceRegions: Seq[(BigInt, BigInt)] = Seq.empty) extends Component {
  require(m.wordPoison)
  require(deviceRegions.forall { case (start, end) => start >= 0 && start < end &&
    start % 8 == 0 && end % 8 == 0 && end <= (BigInt(1) << 64) },
    "PPE device regions must be half-open, 64-bit-word aligned apertures")
  val core = new PpeCore(PpeConfig(memoryHierarchy = Some(m), instructionCache = instructionCache, instructionBase = instructionBase))
  val cache = new NonBlockingL1(m)
  val instructions = if (instructionCache) Some(new NonBlockingL1(m)) else None
  val fabric = if (instructionCache) Some(new CacheLineFabric(m)) else None
  val io = new Bundle {
    val program = slave Stream(cloneOf(core.io.program.payload))
    val launch = slave Stream(cloneOf(core.io.launch.payload))
    val completion = master Stream(cloneOf(core.io.completion.payload))
    val retired = master Flow(cloneOf(core.io.retired.payload))
    val access = master Flow(cloneOf(core.io.access.payload))
    val scalar = out Vec(UInt(64 bits), 32)
    val vector = out Vec(Vec(UInt(64 bits), 8), 32)
    val predicate = out Vec(Bits(8 bits), 8)
    val activeMask = out Bits(8 bits)
    val depth = out UInt(4 bits)
    val inspectScratch = in UInt(9 bits)
    val scratchData = out Bits(64 bits)
    val busy, waiting, idle, clean = out Bool()
    val lower = master Stream(CacheLineRequest(m))
    val reply = slave Stream(CacheLineResponse(m))
    val deviceRequest = master Stream(CacheWordRequest(m))
    val deviceResponse = slave Stream(CacheWordResponse(m))
    val flush = slave Stream(Bool())
    val flushed = master Stream(Bool())
    val wordAccepted = master Flow(CacheWordRequest(m))
    val outstanding = out UInt(4 bits)
    val cacheOutstanding = out UInt(log2Up(m.mshrs + 1) bits)
    val words, lanes, rejectedReplies, scratchParallel, hits, misses, refills, writebacks = out UInt(64 bits)
    val lowerSource = if (instructionCache) out UInt(1 bits) else null
    val replySource = if (instructionCache) in UInt(1 bits) else null
    val instructionHits, instructionMisses, fetchRequests, fetchDiscarded, fetchFaults = out UInt(64 bits)
    val fabricOutstanding = out UInt(log2Up(2*m.mshrs+1) bits)
    val fabricAccepted, fabricCompleted, fabricRejected = out UInt(64 bits)
  }
  val hierarchyIdle, maintenanceBusy = Bool()
  core.io.program << io.program
  core.io.launch.valid := io.launch.valid && hierarchyIdle && !maintenanceBusy && !io.flush.valid
  core.io.launch.payload := io.launch.payload
  io.launch.ready := core.io.launch.ready && hierarchyIdle && !maintenanceBusy && !io.flush.valid
  io.completion << core.io.completion; io.retired := core.io.retired; io.access := core.io.access
  io.scalar := core.io.scalar; io.vector := core.io.vector; io.predicate := core.io.predicate
  io.activeMask := core.io.activeMask; io.depth := core.io.depth
  core.io.inspectScratch := io.inspectScratch; io.scratchData := core.io.scratchData
  io.busy := core.io.busy; io.waiting := core.io.waiting
  core.io.memory.ready := False; core.io.response.valid := False
  core.io.response.payload.assignFromBits(B(0, core.io.response.payload.getBitsWidth bits))
  val deviceState = Reg(UInt(3 bits)) init 0 // idle, clean, issue, wait, response
  val deviceRequestPayload = Reg(CacheWordRequest(m))
  val deviceResponsePayload = Reg(CacheWordResponse(m))
  val deviceAddress = core.io.cacheRequest.address
  val deviceHit = deviceRegions.map { case (start, end) =>
    deviceAddress >= U(start, 64 bits) && deviceAddress < U(end, 64 bits)
  }.foldLeft(False)(_ || _)
  cache.io.request.valid := core.io.cacheRequest.valid && !deviceHit && deviceState === 0
  cache.io.request.payload := core.io.cacheRequest.payload
  core.io.cacheRequest.ready := Mux(deviceHit, deviceState === 0,
    cache.io.request.ready && deviceState === 0)
  when(core.io.cacheRequest.fire && deviceHit) {
    deviceRequestPayload := core.io.cacheRequest.payload
    when(core.io.cacheRequest.atomicAdd) {
      deviceResponsePayload.id := core.io.cacheRequest.id
      deviceResponsePayload.epoch := core.io.cacheRequest.epoch
      deviceResponsePayload.data := 0
      deviceResponsePayload.error := True
      deviceState := 4
    }.otherwise { deviceState := 1 }
  }
  io.deviceRequest.valid := deviceState === 2
  io.deviceRequest.payload := deviceRequestPayload
  when(io.deviceRequest.fire) { deviceState := 3 }
  val deviceResponseMatches = io.deviceResponse.id === deviceRequestPayload.id &&
    io.deviceResponse.epoch === deviceRequestPayload.epoch
  io.deviceResponse.ready := deviceState === 3 && deviceResponseMatches
  when(io.deviceResponse.fire) {
    deviceResponsePayload := io.deviceResponse.payload
    deviceState := 4
  }
  core.io.cacheResponse.valid := Mux(deviceState === 4, True, cache.io.response.valid)
  core.io.cacheResponse.payload := Mux(deviceState === 4, deviceResponsePayload, cache.io.response.payload)
  cache.io.response.ready := core.io.cacheResponse.ready && deviceState =/= 4
  when(core.io.cacheResponse.fire && deviceState === 4) { deviceState := 0 }
  cache.io.drain := False
  if (!instructionCache) {
    io.lower << cache.io.lower; cache.io.reply << io.reply
    val maintenance = Reg(UInt(2 bits)) init 0
    val maintenanceFence, maintenanceDevice, maintenanceError = RegInit(False)
    val externalRequest = io.flush.valid && !core.io.busy && !core.io.systemFence.valid
    val fenceRequest = core.io.systemFence.valid && !io.flush.valid
    val deviceCleanRequest = deviceState === 1
    cache.io.flush.valid := maintenance === 0 && hierarchyIdle && (externalRequest || fenceRequest || deviceCleanRequest)
    cache.io.flush.payload := Mux(fenceRequest || deviceCleanRequest, False, io.flush.payload)
    io.flush.ready := maintenance === 0 && cache.io.flush.ready && !core.io.busy &&
      !core.io.systemFence.valid && !deviceCleanRequest
    core.io.systemFence.ready := maintenance === 0 && cache.io.flush.ready && hierarchyIdle &&
      !io.flush.valid && !deviceCleanRequest
    when(cache.io.flush.fire) {
      maintenance := 1; maintenanceFence := fenceRequest; maintenanceDevice := deviceCleanRequest
      maintenanceError := False
    }
    cache.io.flushed.ready := maintenance === 1 && (maintenanceDevice ||
      Mux(maintenanceFence, core.io.systemFenceResult.ready, io.flushed.ready))
    io.flushed.valid := maintenance === 1 && !maintenanceFence && !maintenanceDevice && cache.io.flushed.valid
    io.flushed.payload := cache.io.flushed.payload
    core.io.systemFenceResult.valid := maintenance === 1 && maintenanceFence && cache.io.flushed.valid
    core.io.systemFenceResult.payload := cache.io.flushed.payload
    when(cache.io.flushed.fire) {
      when(maintenanceDevice) {
        deviceResponsePayload.id := deviceRequestPayload.id
        deviceResponsePayload.epoch := deviceRequestPayload.epoch
        deviceResponsePayload.data := 0
        deviceResponsePayload.error := cache.io.flushed.payload
        deviceState := Mux(cache.io.flushed.payload, U(4, 3 bits), U(2, 3 bits))
      }
      maintenance := 0
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
    val state = Reg(UInt(3 bits)) init 0
    val invalidateData, error, maintenanceFence, maintenanceDevice = RegInit(False)
    val deviceCleanRequest = deviceState === 1
    maintenanceBusy := state =/= 0
    io.flush.ready := state === 0 && !core.io.busy && hierarchyIdle && !core.io.systemFence.valid && !deviceCleanRequest
    core.io.systemFence.ready := state === 0 && hierarchyIdle && !io.flush.valid && !deviceCleanRequest
    when(io.flush.fire || core.io.systemFence.fire || (deviceCleanRequest && hierarchyIdle)) {
      state := 1; maintenanceFence := core.io.systemFence.fire; maintenanceDevice := deviceCleanRequest
      invalidateData := io.flush.payload && !core.io.systemFence.fire && !deviceCleanRequest; error := False
    }
    cache.io.flush.valid := state === 1; cache.io.flush.payload := invalidateData
    cache.io.flushed.ready := state === 2
    i.io.flush.valid := state === 3; i.io.flush.payload := True
    i.io.flushed.ready := state === 4
    core.io.instructionInvalidate := i.io.flushed.fire && !i.io.flushed.payload
    when(cache.io.flush.fire) { state := 2 }
    when(cache.io.flushed.fire) {
      when(maintenanceDevice) {
        when(cache.io.flushed.payload) {
          deviceResponsePayload.id := deviceRequestPayload.id; deviceResponsePayload.epoch := deviceRequestPayload.epoch
          deviceResponsePayload.data := 0; deviceResponsePayload.error := True; deviceState := 4
        }.otherwise { deviceState := 2 }
        state := 0
      }.elsewhen(cache.io.flushed.payload) { error := True; state := 5 }
        .otherwise { state := Mux(maintenanceFence, U(5, 3 bits), U(3, 3 bits)) }
    }
    when(i.io.flush.fire) { state := 4 }
    when(i.io.flushed.fire) { error := i.io.flushed.payload; state := 5 }
    io.flushed.valid := state === 5 && !maintenanceFence; io.flushed.payload := error
    core.io.systemFenceResult.valid := state === 5 && maintenanceFence
    core.io.systemFenceResult.payload := error
    when((io.flushed.fire && !maintenanceFence) || core.io.systemFenceResult.fire) { state := 0 }
    when(i.io.request.fire) { assert(!i.io.request.write, "PPE I-cache received a store") }
    when(f.io.lower.fire && f.io.lower.source === 0) {
      assert(!f.io.lower.transfer.write && f.io.lower.transfer.address >= instructionBase &&
        f.io.lower.transfer.address < instructionBase + 8192, "PPE instruction request escaped its owned region")
    }
  }
  io.idle := !core.io.busy && hierarchyIdle && !maintenanceBusy && deviceState === 0; io.clean := cache.io.clean
  io.wordAccepted.valid := cache.io.request.fire; io.wordAccepted.payload := cache.io.request.payload
  io.outstanding := core.io.memoryOutstanding; io.cacheOutstanding := cache.io.outstanding
  io.words := core.io.memoryWords; io.lanes := core.io.memoryLanes
  io.rejectedReplies := core.io.memoryRejected; io.scratchParallel := core.io.scratchParallel
  io.hits := cache.io.hits; io.misses := cache.io.misses
  io.refills := cache.io.refills; io.writebacks := cache.io.writebacks
  io.fetchRequests := core.io.fetchRequests; io.fetchDiscarded := core.io.fetchDiscarded; io.fetchFaults := core.io.fetchFaults
}
