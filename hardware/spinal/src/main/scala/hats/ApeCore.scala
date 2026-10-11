package hats

import spinal.core._
import spinal.lib._

/** HATS Application Processing Engine: RV64I-subset, not yet a privileged CPU.
  * Single dispatch/retire; configurable one/two-lane issue; physical-register renaming; oldest-ready OoO issue.
  * Registered execution with qualified completion; checkpointed branch recovery.
  * Legacy memory is head-only; the optional S04 LSQ issues owned-RAM loads OoO.
  */
case class ApeConfig(robEntries: Int = 8, programWords: Int = 1024,
                     prediction: Boolean = true, predictorEntries: Int = 16,
                     physicalRegisters: Int = 64, earlyRecovery: Boolean = true,
                     branchCheckpoints: Int = 4, executionStages: Int = 2,
                     generationBits: Int = 2, issueWidth: Int = 1,
                     memoryHierarchy: Option[MemoryHierarchyConfig] = None,
                     memoryQueueEntries: Int = 8, instructionCache: Boolean = false,
                     deviceRegions: Seq[(BigInt, BigInt)] = Seq.empty) {
  require(robEntries >= 4 && isPow2(robEntries))
  require(programWords >= 16 && isPow2(programWords))
  require(predictorEntries >= 2 && isPow2(predictorEntries))
  require(physicalRegisters >= 33 && physicalRegisters <= 256)
  require(branchCheckpoints >= 1 && branchCheckpoints <= robEntries)
  require(executionStages >= 2 && executionStages <= 32)
  require(generationBits >= 1 && generationBits <= 4)
  require(issueWidth >= 1 && issueWidth <= 2)
  require(!instructionCache || memoryHierarchy.nonEmpty)
  require(deviceRegions.forall { case (start, end) => start >= 0 && start < end && end <= (BigInt(1) << 64) })
  val physicalTagBits = log2Up(physicalRegisters)
  val tagBits = log2Up(robEntries)
  val codeBits = log2Up(programWords)
}

case class ApeIssueEvent(c: ApeConfig) extends Bundle {
  val pc = UInt(64 bits)
  val identity = ApeExecutionIdentity(c)
}

class ApeCore(c: ApeConfig = ApeConfig()) extends Component {
  // Architectural wrapper: the reusable backend currently accepts exactly one
  // complete semantic operation for each ROB/instruction identity.
  require(ApeRv64Profile.operationsPerInstruction == 1)
  val io = new Bundle {
    val program = slave Flow(new Bundle {
      val index = UInt(c.codeBits bits)
      val instruction = Bits(32 bits)
    })
    val launch = slave Stream(new Bundle {
      val pc, argument, base, limit = UInt(64 bits)
      val writable = Bool()
    })
    val memory = master Stream(new Bundle {
      val address, data = UInt(64 bits)
      val size = UInt(2 bits) // log2(bytes); data is right-justified
      val write = Bool()
    })
    val response = slave Stream(new Bundle {
      val data = UInt(64 bits) // right-justified, extension is performed by the core
      val error = Bool()
    })
    val cacheRequest = if (c.memoryHierarchy.nonEmpty) master Stream(CacheWordRequest(c.memoryHierarchy.get)) else null
    val cacheResponse = if (c.memoryHierarchy.nonEmpty) slave Stream(CacheWordResponse(c.memoryHierarchy.get)) else null
    val systemFence = if (c.memoryHierarchy.nonEmpty) master Stream(Bool()) else null
    val systemFenceResult = if (c.memoryHierarchy.nonEmpty) slave Stream(Bool()) else null
    val fetchRequest = if (c.instructionCache) master Stream(CacheWordRequest(c.memoryHierarchy.get)) else null
    val fetchResponse = if (c.instructionCache) slave Stream(CacheWordResponse(c.memoryHierarchy.get)) else null
    val instructionInvalidate = if (c.instructionCache) in Bool() else null
    val fetchRequests, fetchDiscarded, fetchFaults = out UInt(64 bits)
    val memoryOutstanding = out UInt(log2Up(c.memoryQueueEntries + 1) bits)
    val memoryAllocated, memoryForwarded, memoryPartialForwarded, memoryUnknownStalls, memoryFenceStalls = out UInt(64 bits)
    val memorySpeculativeLoads, memoryReplays = out UInt(64 bits)
    val memoryDiscarded = out UInt(64 bits)
    val memoryLeasedRows = out Bits(c.robEntries bits)
    val memoryReplayPending = out Bool()
    val memoryReplayStoreRetired = out Bool()
    val memoryHead = out UInt(c.tagBits bits)
    val memoryReplayStoreSlot = out UInt(c.tagBits bits)
    val halt = master Stream(new Bundle {
      val pc, value = UInt(64 bits)
      val cause = UInt(4 bits) // standard synchronous exception cause numbers
    })
    val retired = master Flow(new Bundle {
      val pc = UInt(64 bits)
      val instruction = Bits(32 bits)
      val rd = UInt(5 bits)
      val writes = Bool()
      val value = UInt(64 bits)
    })
    val retiredNext = out UInt(64 bits)
    // Architectural memory effects, distinct from speculative/line transport.
    // Range/alignment faults never became memory operations and emit no event.
    val memoryRetired = master Flow(new Bundle {
      val address, data = UInt(64 bits)
      val size = UInt(2 bits)
      val write, error = Bool()
    })
    // Compatibility port observes lane zero only; all-lane consumers use issues.
    val issued = master Flow(ApeIssueEvent(c))
    val issues = out Vec(Flow(ApeIssueEvent(c)), c.issueWidth)
    val issueCount = out UInt(log2Up(c.issueWidth + 1) bits)
    val readyCount = out UInt(log2Up(c.robEntries + 1) bits)
    val completionBlocked, robBlocked = out Bool()
    val finished = master Flow(new Bundle { val pc = UInt(64 bits) })
    val redirect = master Flow(new Bundle { val from, to = UInt(64 bits) })
    val predicted = master Flow(new Bundle {
      val pc, next = UInt(64 bits)
      val slot = UInt(c.tagBits bits)
      val generation = UInt(c.generationBits bits)
      val destination = UInt(c.physicalTagBits bits)
      val writes = Bool()
    })
    val resolved = master Flow(new Bundle {
      val pc, predictedNext, actualNext = UInt(64 bits)
      val slot = UInt(c.tagBits bits)
      val fault, olderMemory = Bool()
      val olderInstructions = UInt(c.tagBits bits)
    })
    val squashed = out Bits(c.robEntries bits)
    val controlRetired = master Flow(new Bundle {
      val pc, predictedNext, actualNext = UInt(64 bits)
      val conditional, taken = Bool()
      val slot = UInt(c.tagBits bits)
    })
    val busy = out Bool()
    val occupancy = out UInt(log2Up(c.robEntries + 1) bits)
    val physicalFree = out UInt(log2Up(c.physicalRegisters + 1) bits)
    val renameBlocked = out Bool()
    val checkpointBlocked = out Bool()
    val checkpointsUsed = out UInt(log2Up(c.robEntries + 1) bits)
    val executionBlocked, generationBlocked = out Bool()
    val completion = master Flow(new Bundle {
      val slot = UInt(c.tagBits bits)
      val generation = UInt(c.generationBits bits)
      val accepted = Bool()
    })
  }

  val code = if (!c.instructionCache) Mem(Bits(32 bits), c.programWords) else null
  val fetcher = if (c.instructionCache) Some(new CachedInstructionFetch(c.memoryHierarchy.get)) else None
  val active = RegInit(False)
  val halted = RegInit(False)
  val haltPc, haltValue = Reg(UInt(64 bits)) init 0
  val haltCause = Reg(UInt(4 bits)) init 0
  val fetchPc, dataBase, dataLimit = Reg(UInt(64 bits)) init 0
  val canWrite = RegInit(False)
  val head, tail = Reg(UInt(c.tagBits bits)) init 0
  val count = Reg(UInt(log2Up(c.robEntries + 1) bits)) init 0
  val rename = new ApeRename(ApeRv64Profile.registers, c.physicalRegisters, c.robEntries, c.branchCheckpoints)
  val checkpointed, recovered = Vec.fill(c.robEntries)(RegInit(False))
  val destinationTag = Vec.fill(c.robEntries)(Reg(UInt(c.physicalTagBits bits)) init 0)
  val generation = Vec.fill(c.robEntries)(Reg(UInt(c.generationBits bits)) init 0)
  val live, issued, done, prepared, sent, fault, writes, src1Ready, src2Ready =
    Vec.fill(c.robEntries)(RegInit(False))
  val cause = Vec.fill(c.robEntries)(Reg(ApeFaultKind()) init ApeFaultKind.NONE)
  val pc, value, address, src1, src2, immediate, actualNext, predictedNext, sequentialNext =
    Vec.fill(c.robEntries)(Reg(UInt(64 bits)) init 0)
  val taken = Vec.fill(c.robEntries)(RegInit(False))
  val instruction = Vec.fill(c.robEntries)(Reg(Bits(32 bits)) init 0)
  val rd = Vec.fill(c.robEntries)(Reg(UInt(5 bits)) init 0)
  val tag1, tag2 = Vec.fill(c.robEntries)(Reg(UInt(c.physicalTagBits bits)) init 0)
  val op = Vec.fill(c.robEntries)(Reg(ApeOp()) init ApeOp.ILLEGAL)
  val systemFenceSent, systemFenceDone = Vec.fill(c.robEntries)(RegInit(False))
  val branchCondition = Vec.fill(c.robEntries)(Reg(ApeBranchCondition()) init ApeBranchCondition.EQ)
  val memorySize = Vec.fill(c.robEntries)(Reg(UInt(2 bits)) init 0)
  val loadSigned = Vec.fill(c.robEntries)(RegInit(False))
  val useImmediate, narrow32 = Vec.fill(c.robEntries)(RegInit(False))
  val resultExtension = Vec.fill(c.robEntries)(Reg(ApeResultExtension()) init ApeResultExtension.FULL)

  val requestValid, waiting = RegInit(False)
  val requestAddress, requestData = Reg(UInt(64 bits)) init 0
  val requestSize = Reg(UInt(2 bits)) init 0
  val requestWrite = RegInit(False)
  val memoryTag = Reg(UInt(c.tagBits bits)) init 0

  val lsq = c.memoryHierarchy.map(m => new ApeLoadStoreQueue(c, m, c.memoryQueueEntries))
  val memoryIdle, memoryResponseFire, memoryResponseAccepted, memoryResponseError, memoryResponseWrite,
    memoryResponseAtomic = Bool()
  val memoryResponseData = UInt(64 bits)
  val responseTag = UInt(c.tagBits bits)
  val memoryReusable = Bits(c.robEntries bits)
  val discardCount = Reg(UInt(64 bits)) init 0
  val replayPending, replayStoreRetired = RegInit(False)
  val replayStoreSlot = Reg(UInt(c.tagBits bits)) init 0
  val replaySignal = Bool()
  val replayStoreSignal = UInt(c.tagBits bits)
  val replayFlush = Bool()
  val fetchIdle = Bool()
  if (fetcher.isEmpty) {
    fetchIdle := True
    io.fetchRequests := 0; io.fetchDiscarded := 0; io.fetchFaults := 0
  } else {
    val f = fetcher.get
    io.fetchRequest << f.io.request; f.io.response << io.fetchResponse
    f.io.pc := fetchPc
    f.io.accessible := fetchPc(1 downto 0) === 0 && fetchPc < BigInt(c.programWords) * 4
    f.io.clear := io.launch.fire || io.instructionInvalidate || replayFlush
    fetchIdle := f.io.idle
    io.fetchRequests := f.io.requests; io.fetchDiscarded := f.io.discarded; io.fetchFaults := f.io.faults
    when(io.instructionInvalidate) { assert(!active && !halted, "instruction publication while APE is active") }
  }
  io.memoryDiscarded := discardCount
  if (lsq.isEmpty) {
    discardCount := 0
    memoryIdle := !requestValid && !waiting
    memoryResponseFire := io.response.fire; memoryResponseAccepted := io.response.fire
    memoryResponseError := io.response.error; memoryResponseData := io.response.data
    memoryResponseWrite := requestWrite; memoryResponseAtomic := False; responseTag := memoryTag
    memoryReusable.setAll()
    io.memoryLeasedRows := 0
    io.memoryOutstanding := (requestValid || waiting).asUInt.resized
    io.memoryAllocated := 0; io.memoryForwarded := 0; io.memoryPartialForwarded := 0
    io.memoryUnknownStalls := 0; io.memoryFenceStalls := 0
    io.memorySpeculativeLoads := 0; io.memoryReplays := 0
    replaySignal := False; replayStoreSignal := 0
  } else {
    val q = lsq.get
    io.cacheRequest << q.io.request; q.io.response << io.cacheResponse
    q.io.head := head
    for (i <- 0 until c.robEntries) {
      q.io.rows(i).live := live(i)
      q.io.rows(i).prepared := prepared(i)
      q.io.rows(i).sent := sent(i)
      q.io.rows(i).store := op(i) === ApeOp.STORE || op(i) === ApeOp.ATOMIC_ADD_D
      q.io.rows(i).fence := op(i) === ApeOp.FENCE
      q.io.rows(i).atomicAdd := op(i) === ApeOp.ATOMIC_ADD_D
      val accessBytes = (U(1, 65 bits) |<< memorySize(i)).resize(65)
      val accessEnd = address(i).resize(65) + accessBytes
      q.io.rows(i).device := c.deviceRegions.map { case (start, end) =>
        address(i).resize(65) < U(end, 65 bits) && accessEnd > U(start, 65 bits)
      }.foldLeft(False)(_ || _)
      q.io.rows(i).identity.slot := i
      q.io.rows(i).identity.generation := generation(i)
      q.io.rows(i).identity.destination := destinationTag(i)
      q.io.rows(i).address := address(i); q.io.rows(i).data := src2(i)
      q.io.rows(i).size := memorySize(i)
    }
    q.io.result.ready := True
    q.io.replayPending := replayPending
    q.io.replayStore := replayStoreSlot
    q.io.replayStoreRetired := replayStoreRetired
    replaySignal := q.io.replay
    memoryIdle := q.io.idle; memoryReusable := q.io.reusable
    io.memoryLeasedRows := q.io.leasedRows
    memoryResponseFire := q.io.result.fire
    memoryResponseError := q.io.result.error; memoryResponseData := q.io.result.data
    memoryResponseWrite := q.io.result.store; memoryResponseAtomic := q.io.result.atomicAdd
    responseTag := q.io.result.identity.slot
    io.memoryOutstanding := q.io.outstanding
    io.memoryAllocated := q.io.allocated; io.memoryForwarded := q.io.forwarded
    io.memoryPartialForwarded := q.io.partialForwarded
    io.memoryUnknownStalls := q.io.unknownStoreStalls; io.memoryFenceStalls := q.io.fenceStalls
    io.memorySpeculativeLoads := q.io.speculativeLoads; io.memoryReplays := q.io.replays
    replayStoreSignal := q.io.replayStoreSlot
    when(q.io.accepted.valid) { sent(q.io.accepted.payload) := True }
  }

  io.busy := active || halted
  io.occupancy := count
  io.memoryReplayPending := replayPending
  io.memoryReplayStoreRetired := replayStoreRetired
  io.memoryHead := head
  io.memoryReplayStoreSlot := replayStoreSlot
  io.launch.ready := !active && !halted && memoryIdle && fetchIdle
  io.halt.valid := halted && memoryIdle && fetchIdle
  io.halt.pc := haltPc
  io.halt.value := haltValue
  io.halt.cause := haltCause
  io.memory.valid := requestValid
  io.memory.address := requestAddress
  io.memory.data := requestData
  io.memory.size := requestSize
  io.memory.write := requestWrite
  io.response.ready := waiting
  if (!c.instructionCache) when(io.program.valid && !io.busy) { code.write(io.program.index, io.program.instruction) }
  when(io.halt.fire) { halted := False }

  val fenceHead = active && count =/= 0 && op(head) === ApeOp.FENCE
  replayFlush := replayPending && replayStoreRetired && memoryIdle && fetchIdle
  val retiring = active && count =/= 0 && done(head) && (!Bool(c.memoryHierarchy.nonEmpty) || !fenceHead || systemFenceDone(head)) &&
    (!replayPending || !replayStoreRetired)
  if (c.memoryHierarchy.nonEmpty) {
    io.systemFence.valid := fenceHead && done(head) && !systemFenceSent(head) && !fault(head)
    io.systemFence.payload := False // clean-only; do not invalidate data or instruction lines
    io.systemFenceResult.ready := fenceHead && systemFenceSent(head) && !systemFenceDone(head)
    when(io.systemFence.fire) { systemFenceSent(head) := True }
    when(io.systemFenceResult.fire) {
      systemFenceDone(head) := True
      when(io.systemFenceResult.payload) { fault(head) := True; cause(head) := ApeFaultKind.STORE_ACCESS }
    }
  }
  val redirecting = retiring && !fault(head) && actualNext(head) =/= predictedNext(head) && !Bool(c.earlyRecovery)
  val stopping = retiring && fault(head)
  val flushing = redirecting || stopping || replayFlush
  lsq.foreach { q =>
    memoryResponseAccepted := memoryResponseFire && active && !flushing && live(responseTag) && !done(responseTag) &&
      generation(responseTag) === q.io.result.identity.generation && destinationTag(responseTag) === q.io.result.identity.destination
    when(memoryResponseFire && !memoryResponseAccepted) { discardCount := discardCount + 1 }
  }
  io.retired.valid := retiring && !fault(head)
  io.retired.pc := pc(head)
  io.retired.instruction := instruction(head)
  io.retired.rd := rd(head)
  io.retired.writes := writes(head)
  io.retired.value := value(head)
  io.retiredNext := actualNext(head)
  io.memoryRetired.valid := retiring && prepared(head) &&
    (op(head) === ApeOp.LOAD || op(head) === ApeOp.STORE || op(head) === ApeOp.ATOMIC_ADD_D)
  io.memoryRetired.address := address(head); io.memoryRetired.size := memorySize(head)
  io.memoryRetired.write := op(head) === ApeOp.STORE || op(head) === ApeOp.ATOMIC_ADD_D
  io.memoryRetired.error := fault(head)
  io.memoryRetired.data := Mux(op(head) === ApeOp.STORE || op(head) === ApeOp.ATOMIC_ADD_D,
    src2(head), Mux(fault(head), U(0, 64 bits), value(head)))
  io.controlRetired.valid := io.retired.valid &&
    (op(head) === ApeOp.BRANCH || op(head) === ApeOp.JUMP_RELATIVE || op(head) === ApeOp.JUMP_REGISTER)
  io.controlRetired.pc := pc(head)
  io.controlRetired.predictedNext := predictedNext(head)
  io.controlRetired.actualNext := actualNext(head)
  io.controlRetired.conditional := op(head) === ApeOp.BRANCH
  io.controlRetired.taken := taken(head)
  io.controlRetired.slot := head

  // Reservation rows are shared with ROB storage; arbitration sees only owner
  // readiness/age, not instruction encoding or RISC-V architectural registers.
  val ready = Bits(c.robEntries bits)
  for (slot <- 0 until c.robEntries) {
    ready(slot) := live(slot) && !issued(slot) && src1Ready(slot) && src2Ready(slot)
  }
  val executions = Seq.fill(c.issueWidth)(new ApeExecute(c))
  executions.foreach(_.io.clear := flushing || io.launch.fire)
  val result = Stream(ApeExecutionResult(c))
  if (c.issueWidth == 1) {
    result << executions.head.io.result
  } else {
    val preferSecond = RegInit(False)
    val held = RegInit(False)
    val heldSecond = RegInit(False)
    val second = Mux(held, heldSecond, executions(1).io.result.valid &&
      (!executions(0).io.result.valid || preferSecond))
    result.valid := Mux(second, executions(1).io.result.valid, executions(0).io.result.valid)
    result.payload := Mux(second, executions(1).io.result.payload, executions(0).io.result.payload)
    executions(0).io.result.ready := result.ready && !second
    executions(1).io.result.ready := result.ready && second
    when(result.valid && !result.ready) { held := True; heldSecond := second }
    when(result.fire) { held := False; preferSecond := !second }
    when(flushing || io.launch.fire) { held := False; preferSecond := False }
  }
  result.ready := !memoryResponseFire
  val completed = result.payload
  val completedSlot = completed.identity.slot
  val completedOffset = (completedSlot - head).resize(c.tagBits)
  val ownership = new ApeCompletionGuard(c)
  ownership.io.candidate := completed.identity
  ownership.io.ownerLive := live(completedSlot)
  ownership.io.ownerIssued := issued(completedSlot)
  ownership.io.ownerComplete := done(completedSlot) || prepared(completedSlot)
  ownership.io.ownerGeneration := generation(completedSlot)
  ownership.io.ownerDestination := destinationTag(completedSlot)
  for (lane <- 0 until c.issueWidth; stage <- 0 until c.executionStages) {
    ownership.io.pending(lane * c.executionStages + stage) := executions(lane).io.pending(stage)
  }
  val ownsCompletion = ownership.io.qualified
  val complete = active && result.fire && ownsCompletion && !flushing
  io.completion.valid := result.fire
  io.completion.slot := completedSlot
  io.completion.generation := completed.identity.generation
  io.completion.accepted := complete
  val earlyRedirect = Bool(c.earlyRecovery) && complete && completed.control && !completed.fault &&
    completed.next =/= predictedNext(completedSlot)
  when(replaySignal && !replayPending && !earlyRedirect && !redirecting && !stopping) {
    replayPending := True
    replayStoreRetired := False
    replayStoreSlot := replayStoreSignal
  }
  // A violating store can itself be at the ROB head on the cycle its overlap
  // is detected. In that case replayPending/replayStoreSlot still contain the
  // previous cycle's values, while the store may retire immediately. Capture
  // that same-cycle checkpoint retirement or replayPending would wait forever
  // for a store that has already left the ROB.
  when((replayPending && retiring && head === replayStoreSlot) ||
    (replaySignal && retiring && head === replayStoreSignal)) {
    replayStoreRetired := True
  }
  when(earlyRedirect || redirecting || stopping) {
    replayPending := False
    replayStoreRetired := False
  }
  lsq.foreach(_.io.enable := active && !flushing && !earlyRedirect)
  fetcher.foreach(_.io.enable := active && !flushing && !earlyRedirect && !replayPending)
  val scheduler = new ApeIssueScheduler(c.robEntries, c.issueWidth)
  scheduler.io.enable := active && !flushing && !earlyRedirect
  scheduler.io.head := head
  scheduler.io.ready := ready
  for (lane <- 0 until c.issueWidth) {
    val execution = executions(lane)
    val selected = scheduler.io.grant(lane).payload
    scheduler.io.laneReady(lane) := execution.io.request.ready
    execution.io.request.valid := scheduler.io.grant(lane).valid
    execution.io.request.identity.slot := selected
    execution.io.request.identity.generation := generation(selected)
    execution.io.request.identity.destination := destinationTag(selected)
    execution.io.request.op := op(selected)
    execution.io.request.branch := branchCondition(selected)
    execution.io.request.a := src1(selected)
    execution.io.request.b := src2(selected)
    execution.io.request.immediate := immediate(selected)
    execution.io.request.pc := pc(selected)
    execution.io.request.sequentialNext := sequentialNext(selected)
    execution.io.request.indirectTargetMask := U(ApeRv64Profile.indirectTargetMask, 64 bits)
    execution.io.request.alignmentMask := U(ApeRv64Profile.alignmentMask, 64 bits)
    execution.io.request.base := dataBase
    execution.io.request.limit := dataLimit
    execution.io.request.useImmediate := useImmediate(selected)
    execution.io.request.narrow32 := narrow32(selected)
    execution.io.request.resultExtension := resultExtension(selected)
    execution.io.request.writable := canWrite
    val isAtomicAdd = op(selected) === ApeOp.ATOMIC_ADD_D
    val atomicDevice = c.deviceRegions.map { case (start, end) =>
      src1(selected).resize(65) < U(end, 65 bits) &&
        (src1(selected).resize(65) + 8) > U(start, 65 bits)
    }.foldLeft(False)(_ || _)
    val atomicUnsupported = if (c.memoryHierarchy.isEmpty) isAtomicAdd else False
    execution.io.request.fault := fault(selected) || (isAtomicAdd && (atomicDevice || atomicUnsupported))
    execution.io.request.faultKind := Mux(fault(selected), cause(selected),
      Mux(isAtomicAdd && atomicUnsupported, ApeFaultKind.ILLEGAL,
        Mux(isAtomicAdd && atomicDevice, ApeFaultKind.STORE_ACCESS, ApeFaultKind.NONE)))
    execution.io.request.memorySize := memorySize(selected)
    io.issues(lane).valid := execution.io.request.fire
    io.issues(lane).pc := pc(selected)
    io.issues(lane).identity := execution.io.request.identity
    when(execution.io.request.fire) {
      assert(live(selected) && !issued(selected), "issue without a live unissued owner")
      issued(selected) := True
    }
  }
  io.issued := io.issues(0)
  io.issueCount := scheduler.io.issueCount
  io.readyCount := scheduler.io.readyCount
  io.executionBlocked := scheduler.io.enable && ready.orR && scheduler.io.issueCount === 0
  io.completionBlocked := executions.map(e => e.io.result.valid && !e.io.result.ready).reduce(_ || _)
  io.robBlocked := active && count === c.robEntries && !flushing && !earlyRedirect
  io.redirect.valid := redirecting || earlyRedirect || replayFlush
  io.redirect.from := Mux(earlyRedirect, pc(completedSlot), pc(head))
  io.redirect.to := Mux(earlyRedirect, completed.next, Mux(replayFlush, pc(head), actualNext(head)))
  io.resolved.valid := complete && completed.control && !fault(completedSlot)
  io.resolved.pc := pc(completedSlot)
  io.resolved.predictedNext := predictedNext(completedSlot)
  io.resolved.actualNext := completed.next
  io.resolved.slot := completedSlot
  io.resolved.fault := completed.fault
  io.resolved.olderInstructions := completedOffset
  io.resolved.olderMemory := !memoryIdle && completedSlot =/= head
  for (i <- 0 until c.robEntries) {
    val age = (U(i, c.tagBits bits) - head).resize(c.tagBits)
    io.squashed(i) := (earlyRedirect && live(i) && age > completedOffset) || (replayFlush && live(i))
  }

  val loadValue = UInt(64 bits)
  loadValue := memoryResponseData
  switch(memorySize(responseTag)) {
    is(0) { loadValue := Mux(loadSigned(responseTag), memoryResponseData(7 downto 0).asSInt.resize(64).asUInt, memoryResponseData(7 downto 0).resize(64)) }
    is(1) { loadValue := Mux(loadSigned(responseTag), memoryResponseData(15 downto 0).asSInt.resize(64).asUInt, memoryResponseData(15 downto 0).resize(64)) }
    is(2) { loadValue := Mux(loadSigned(responseTag), memoryResponseData(31 downto 0).asSInt.resize(64).asUInt, memoryResponseData(31 downto 0).resize(64)) }
  }
  // One broadcast port. A memory response backpressures execution completion.
  val cdbValid = (complete && !completed.memory && !completed.fault && writes(completedSlot)) ||
    (memoryResponseAccepted && !memoryResponseError && !memoryResponseWrite && writes(responseTag))
  val cdbTag = destinationTag(Mux(memoryResponseFire, responseTag, completedSlot))
  val cdbValue = Mux(memoryResponseFire, loadValue, completed.value)
  io.finished.valid := (complete && (!completed.memory || completed.fault)) || memoryResponseAccepted
  io.finished.pc := Mux(memoryResponseFire, pc(responseTag), pc(completedSlot))

  when(complete) {
    actualNext(completedSlot) := completed.next
    taken(completedSlot) := completed.taken
    address(completedSlot) := completed.address
    value(completedSlot) := completed.value
    fault(completedSlot) := completed.fault
    cause(completedSlot) := completed.faultKind
    checkpointed(completedSlot) := False
    recovered(completedSlot) := earlyRedirect
    when(completed.memory && !completed.fault) { prepared(completedSlot) := True }
      .otherwise { done(completedSlot) := True }
  }
  for (i <- 0 until c.robEntries) {
    when(cdbValid && live(i)) {
      when(!src1Ready(i) && tag1(i) === cdbTag) { src1Ready(i) := True; src1(i) := cdbValue }
      when(!src2Ready(i) && tag2(i) === cdbTag) { src2Ready(i) := True; src2(i) := cdbValue }
    }
  }
  // Preserve the S03 head-only transport as an explicit regression profile.
  if (lsq.isEmpty) {
    when(active && count =/= 0 && prepared(head) && !sent(head) && !requestValid && !waiting && !flushing) {
      requestValid := True
      requestAddress := address(head)
      requestData := src2(head)
      requestSize := memorySize(head)
      requestWrite := op(head) === ApeOp.STORE
      memoryTag := head
      sent(head) := True
    }
    when(io.memory.fire) { requestValid := False; waiting := True }
    when(io.response.fire) { waiting := False }
  }
  when(memoryResponseAccepted) {
    done(responseTag) := True
    value(responseTag) := loadValue
    fault(responseTag) := memoryResponseError
    cause(responseTag) := ApeFaultKind.NONE
    when(memoryResponseError) { cause(responseTag) := Mux(memoryResponseWrite || memoryResponseAtomic,
      ApeFaultKind.STORE_ACCESS, ApeFaultKind.LOAD_ACCESS) }
  }

  val fetched = Bits(32 bits)
  if (fetcher.isEmpty) fetched := code.readAsync(fetchPc(c.codeBits + ApeRv64Profile.instructionShift - 1 downto ApeRv64Profile.instructionShift))
  else fetched := Mux(fetchPc(2), fetcher.get.io.word(63 downto 32), fetcher.get.io.word(31 downto 0))
  val frontend = new ApeRv64Frontend(fetched, fetchPc, c.programWords)
  val decode = frontend.decoded
  val fetchFault = frontend.fetchFault || (if (fetcher.nonEmpty) fetcher.get.io.error else False)
  val fetchAvailable = if (fetcher.nonEmpty) fetcher.get.io.available else True
  val dispatchNeedsRegister = decode.destination && !fetchFault
  val dispatchNeedsCheckpoint = Bool(c.earlyRecovery) && decode.valid && !fetchFault &&
    (decode.op === ApeOp.BRANCH || decode.op === ApeOp.JUMP_RELATIVE || decode.op === ApeOp.JUMP_REGISTER)
  val checkpointReady = !dispatchNeedsCheckpoint || rename.io.checkpointAvailable
  // Finite generation counters are safe even under unbounded backpressure:
  // never allocate a (slot, generation) still carried by any pipeline token.
  val nextGeneration = (generation(tail) + 1).resize(c.generationBits)
  ownership.io.allocationSlot := tail
  ownership.io.allocationGeneration := nextGeneration
  val generationCollision = !ownership.io.allocationSafe || !memoryReusable(tail)
  val dispatchCandidate = active && count < c.robEntries && !flushing && !earlyRedirect && !replayPending && fetchAvailable
  io.generationBlocked := dispatchCandidate && generationCollision
  val dispatchEligible = dispatchCandidate && !generationCollision
  io.physicalFree := rename.io.freeCount
  io.checkpointsUsed := rename.io.checkpointsUsed
  io.checkpointBlocked := dispatchEligible && !checkpointReady
  io.renameBlocked := dispatchEligible && checkpointReady && dispatchNeedsRegister && !rename.io.allocate.ready
  val dispatch = dispatchEligible && checkpointReady &&
    (!dispatchNeedsRegister || rename.io.allocate.ready)
  rename.io.clear := io.launch.fire
  rename.io.argument := io.launch.argument
  rename.io.source(0) := decode.rs1; rename.io.source(1) := decode.rs2
  rename.io.sourceUsed(0) := decode.use1 && decode.valid && !fetchFault
  rename.io.sourceUsed(1) := decode.use2 && decode.valid && !fetchFault
  rename.io.allocate.valid := dispatchEligible && checkpointReady && dispatchNeedsRegister
  rename.io.allocate.payload := decode.rd
  rename.io.writeback.valid := cdbValid
  rename.io.writeback.tag := cdbTag; rename.io.writeback.value := cdbValue
  rename.io.commit.valid := retiring && !fault(head) && writes(head)
  rename.io.commit.architectural := rd(head); rename.io.commit.physical := destinationTag(head)
  rename.io.recover := flushing
  rename.io.checkpoint.valid := dispatch && dispatchNeedsCheckpoint
  rename.io.checkpoint.payload := tail
  rename.io.resolve.valid := complete && checkpointed(completedSlot)
  rename.io.resolve.slot := completedSlot
  rename.io.resolve.redirect := earlyRedirect
  rename.io.squash := io.squashed
  val predictor = new ApeBranchPredictor(c.prediction, c.predictorEntries, ApeRv64Profile.instructionShift)
  predictor.io.clear := io.launch.fire
  predictor.io.pc := fetchPc
  predictor.io.sequentialNext := frontend.sequentialNext
  predictor.io.target := fetchPc + decode.imm
  predictor.io.conditional := decode.valid && !fetchFault && decode.op === ApeOp.BRANCH
  predictor.io.directJump := decode.valid && !fetchFault && decode.op === ApeOp.JUMP_RELATIVE
  predictor.io.update.valid := io.controlRetired.valid && io.controlRetired.conditional
  predictor.io.update.pc := pc(head)
  predictor.io.update.taken := taken(head)
  io.predicted.valid := dispatch
  io.predicted.pc := fetchPc
  io.predicted.next := predictor.io.next
  io.predicted.slot := tail
  io.predicted.generation := nextGeneration
  io.predicted.destination := rename.io.allocatedTag
  io.predicted.writes := dispatchNeedsRegister
  when(retiring) {
    live(head) := False
    head := head + 1
  }
    when(dispatch) {
    generation(tail) := nextGeneration
    live(tail) := True; issued(tail) := False; done(tail) := False
    prepared(tail) := False; sent(tail) := False
    systemFenceSent(tail) := False; systemFenceDone(tail) := False
    checkpointed(tail) := dispatchNeedsCheckpoint; recovered(tail) := False
    pc(tail) := fetchPc; instruction(tail) := fetched
    rd(tail) := decode.rd; writes(tail) := decode.destination && !fetchFault
    op(tail) := decode.op
    when(!decode.valid) { op(tail) := ApeOp.ILLEGAL }
    immediate(tail) := decode.imm; useImmediate(tail) := decode.immediate
    narrow32(tail) := decode.narrow32; resultExtension(tail) := frontend.resultExtension
    sequentialNext(tail) := frontend.sequentialNext
    branchCondition(tail) := decode.branch
    memorySize(tail) := decode.memorySize; loadSigned(tail) := decode.loadSigned
    destinationTag(tail) := rename.io.allocatedTag
    src1Ready(tail) := rename.io.sourceReady(0); src1(tail) := rename.io.sourceValue(0); tag1(tail) := rename.io.sourceTag(0)
    src2Ready(tail) := rename.io.sourceReady(1); src2(tail) := rename.io.sourceValue(1); tag2(tail) := rename.io.sourceTag(1)
    fault(tail) := fetchFault
    cause(tail) := Mux(fetchFault, frontend.fetchFaultKind, ApeFaultKind.NONE)
    tail := tail + 1
    predictedNext(tail) := predictor.io.next
    fetchPc := predictor.io.next
  }
  when(dispatch =/= retiring) {
    when(dispatch) { count := count + 1 }.otherwise { count := count - 1 }
  }
  // Keep the resolving branch and all older work, including pending head memory.
  when(earlyRedirect) {
    assert(checkpointed(completedSlot), "early redirect without checkpoint ownership")
    for (i <- 0 until c.robEntries) {
      when(io.squashed(i)) {
        live(i) := False; done(i) := False; issued(i) := False
        prepared(i) := False; sent(i) := False; checkpointed(i) := False
      }
    }
    tail := completedSlot + 1
    count := completedOffset.resize(count.getWidth) + 1 - retiring.asUInt.resize(count.getWidth)
    fetchPc := completed.next
  }
  // All older instructions have retired; restore the committed physical map.
  when(flushing) {
    for (i <- 0 until c.robEntries) { live(i) := False; done(i) := False; checkpointed(i) := False }
    head := 0; tail := 0; count := 0
    fetchPc := Mux(replayFlush, pc(head), actualNext(head))
    when(stopping) {
      active := False; halted := True
      haltPc := pc(head); haltCause := ApeRv64Profile.encodeFault(cause(head)); haltValue := rename.io.committedArgument
    }
    when(replayFlush) {
      active := True; halted := False
      replayPending := False; replayStoreRetired := False
    }
  }
  when(io.launch.fire) {
    active := True
    fetchPc := io.launch.pc; dataBase := io.launch.base; dataLimit := io.launch.limit
    canWrite := io.launch.writable
    head := 0; tail := 0; count := 0
    for (i <- 0 until c.robEntries) {
      live(i) := False; done(i) := False; issued(i) := False
      prepared(i) := False; sent(i) := False
      systemFenceSent(i) := False; systemFenceDone(i) := False
      checkpointed(i) := False; recovered(i) := False
    }
  }

  // Structural invariants are checked by the RTL simulator, not just the oracle.
  assert(CountOne(live.asBits).resize(count.getWidth) === count, "ROB occupancy mismatch")
  assert(!(requestValid && waiting), "request and response phases overlap")
  assert(CountOne(checkpointed.asBits) === rename.io.checkpointsUsed, "checkpoint ownership differs from ROB")
  when(dispatch) { assert(!generationCollision, "generation reused while a completion lease survives") }
  when(complete) { assert(!done(completedSlot) && !prepared(completedSlot), "duplicate execution completion") }
  when(io.retired.valid && Bool(c.earlyRecovery) && actualNext(head) =/= predictedNext(head)) {
    assert(recovered(head), "mispredicted branch reached retirement without early recovery")
  }
  when(requestValid || waiting) {
    assert(active && live(head) && memoryTag === head && !fault(head),
      "external effect escaped the non-speculative head")
  }
}

object GenerateApe extends App {
  for (n <- Seq(4, 8, 16); prediction <- Seq(false, true)) {
    val mode = if (prediction) "bimodal" else "off"
    SpinalConfig(targetDirectory = s"build/ape/rtl/r$n-$mode")
      .generateVerilog(new ApeCore(ApeConfig(robEntries = n, prediction = prediction)))
  }
}
