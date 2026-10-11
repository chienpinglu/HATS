package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import scala.collection.mutable
import scala.util.Random

/** Independent byte-store oracle. No DUT tags/data/MSHR state is inspected.
  * External latency is modeled; the cache/controller under test is actual RTL.
  */
object NonBlockingL1Sim extends App {
  val root = Paths.get(args.headOption.getOrElse("build/s04/l1"))
  Files.createDirectories(root)
  Files.writeString(root.resolve("validation.json"), "{\"status\":\"running\"}\n")
  val reports = mutable.ArrayBuffer[String]()
  for ((sets, lineBytes, mshrs) <- Seq((4, 16, 2), (8, 32, 4), (16, 64, 8))) {
    val c = MemoryHierarchyConfig(sets, lineBytes, mshrs, clientIdBits = 8, epochBits = 2)
    val folder = root.resolve(s"s$sets-l$lineBytes-m$mshrs")
    var summary = ""
    SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
      .workspacePath(folder.toString).compile(new NonBlockingL1(c)).doSim("protocol", seed = 0x53404 + sets) { dut =>
        val rng = new Random(0x53404 + sets)
        val size = 65536
        val initial = Array.tabulate[Byte](size)(i => ((i * 71 + (i >>> 5) * 13) & 255).toByte)
        val architectural = initial.clone()
        val external = initial.clone()
        case class Request(sequence: Int, id: Int, epoch: Int, address: Int, write: Boolean,
                           data: BigInt, mask: Int, atomicAdd: Boolean, error: Boolean)
        case class Lower(slot: Int, generation: Int, address: Int, write: Boolean, data: BigInt)
        case class Pending(request: Lower, due: Int, error: Boolean)
        case class Response(id: Int, epoch: Int, data: BigInt, error: Boolean)
        case class Step(accepted: Boolean, flushAccepted: Boolean, flushResult: Option[Boolean])
        val outstanding = mutable.Map[(Int, Int), Request]()
        val lower = mutable.ArrayBuffer[Pending]()
        var sequence, cycle, accepted, completed, reads, writes, errors, atomicAdds = 0
        var maxOutstanding, maxLower, reorders, lowerReorders, stale, lowerStalls, responseStalls, drainChecks = 0
        var flushes, flushFailures, resets, hitsUnderMiss = 0
        var staleGenerations, stalePhases, flushStalls, busWrites, busReads = 0
        val seenGenerations = mutable.Set[Int]()
        val savedCounters = mutable.Map[String, BigInt]().withDefaultValue(BigInt(0))
        var failReads = Set.empty[Int]
        var failWrites = Set.empty[Int]
        var heldLower: Option[Lower] = None
        var heldResponse: Option[Response] = None
        var heldFlush: Option[Boolean] = None
        def counters(): Map[String, BigInt] = Map("hits" -> dut.io.hits.toBigInt, "misses" -> dut.io.misses.toBigInt,
          "writebacks" -> dut.io.writebacks.toBigInt, "refills" -> dut.io.refills.toBigInt,
          "rejected_replies" -> dut.io.rejectedReplies.toBigInt, "set_stalls" -> dut.io.setStalls.toBigInt,
          "full_stalls" -> dut.io.fullStalls.toBigInt)
        def saveCounters(): Unit = counters().foreach { case (k, v) => savedCounters(k) = savedCounters(k) + v }
        def read(bytes: Array[Byte], address: Int, count: Int): BigInt =
          (0 until count).foldLeft(BigInt(0))((v, b) => v | (BigInt(bytes(address+b) & 255) << (b*8)))
        def write(bytes: Array[Byte], address: Int, count: Int, data: BigInt, mask: BigInt): Unit =
          for (b <- 0 until count if mask.testBit(b)) bytes(address+b) = ((data >> (b*8)) & 255).toByte
        def request(address: Int, store: Boolean = false, data: BigInt = 0, mask: Int = 255,
                    atomicAdd: Boolean = false, error: Boolean = false): Request = {
          val r = Request(sequence, sequence & 255, (sequence >>> 8) & 3, address, store, data, mask, atomicAdd, error)
          sequence += 1; r
        }
        def edge(): Unit = {
          dut.clockDomain.risingEdge(); sleep(5); dut.clockDomain.fallingEdge(); sleep(5)
        }
        def initialize(): Unit = {
          dut.io.request.valid #= false; dut.io.request.id #= 0; dut.io.request.epoch #= 0
          dut.io.request.address #= 0; dut.io.request.write #= false; dut.io.request.atomicAdd #= false
          dut.io.request.data #= 0; dut.io.request.mask #= 0
          dut.io.response.ready #= false; dut.io.lower.ready #= false
          dut.io.reply.valid #= false; dut.io.reply.slot #= 0; dut.io.reply.generation #= 0
          dut.io.reply.write #= false; dut.io.reply.data.foreach(_ #= 0); dut.io.reply.error #= false
          dut.io.flush.valid #= false; dut.io.flush.payload #= false; dut.io.flushed.ready #= false
          dut.io.drain #= false
        }
        dut.clockDomain.clockSim #= false; initialize(); dut.clockDomain.assertReset()
        for (_ <- 0 until 4) edge()
        dut.clockDomain.deassertReset(); edge()

        def tick(offered: Option[Request] = None, consume: Boolean = true, replies: Boolean = true,
                 flush: Option[Boolean] = None, takeFlush: Boolean = true, drain: Boolean = false,
                 ready: Boolean = true): Step = {
          dut.io.request.valid #= offered.nonEmpty
          offered.foreach { r =>
            dut.io.request.id #= r.id; dut.io.request.epoch #= r.epoch; dut.io.request.address #= r.address
            dut.io.request.write #= r.write; dut.io.request.atomicAdd #= r.atomicAdd
            dut.io.request.data #= r.data; dut.io.request.mask #= r.mask
          }
          dut.io.response.ready #= consume
          dut.io.lower.ready #= (ready && cycle % 7 >= 2 && rng.nextInt(4) != 0)
          dut.io.drain #= drain
          dut.io.flush.valid #= flush.nonEmpty; dut.io.flush.payload #= flush.getOrElse(false)
          dut.io.flushed.ready #= takeFlush
          val due = if (replies) lower.indices.filter(i => lower(i).due <= cycle) else Seq.empty[Int]
          val selected = due.lastOption // Deliberately prefer the younger ready request.
          val corrupt = selected.nonEmpty && rng.nextInt(7) == 0
          val corruptGeneration = corrupt && rng.nextBoolean()
          dut.io.reply.valid #= selected.nonEmpty
          selected.foreach { i =>
            val p = lower(i); val r = p.request
            dut.io.reply.slot #= r.slot
            dut.io.reply.generation #= (if (corruptGeneration) (r.generation + 1) & 3 else r.generation)
            dut.io.reply.write #= (if (corrupt && !corruptGeneration) !r.write else r.write)
            for (w <- 0 until c.words)
              dut.io.reply.data(w) #= (if (r.write || p.error) BigInt(0) else read(external, r.address + w*8, 8))
            dut.io.reply.error #= p.error
          }
          sleep(1)
          val previousHits = dut.io.hits.toBigInt
          val pendingBefore = lower.nonEmpty
          val bus = if (dut.io.lower.valid.toBoolean) {
            val address = dut.io.lower.address.toBigInt
            assert(address >= 0 && address + lineBytes <= size, "lower address escaped the test memory")
            Some(Lower(dut.io.lower.slot.toInt, dut.io.lower.generation.toInt, address.toInt, dut.io.lower.write.toBoolean,
              dut.io.lower.data.zipWithIndex.foldLeft(BigInt(0)) { case (value, (word, i)) => value | (word.toBigInt << (i*64)) }))
          } else None
          heldLower.foreach(r => assert(bus.contains(r), s"lower payload changed while stalled at $cycle"))
          heldLower = if (!dut.io.lower.ready.toBoolean) bus else None
          if (heldLower.nonEmpty) lowerStalls += 1
          val response = if (dut.io.response.valid.toBoolean) Some(Response(dut.io.response.id.toInt,
            dut.io.response.epoch.toInt, dut.io.response.data.toBigInt, dut.io.response.error.toBoolean)) else None
          heldResponse.foreach(r => assert(response.contains(r), s"client response changed while held at $cycle"))
          heldResponse = if (!consume) response else None
          if (heldResponse.nonEmpty) responseStalls += 1
          val flushResponse = if (dut.io.flushed.valid.toBoolean) Some(dut.io.flushed.payload.toBoolean) else None
          heldFlush.foreach(r => assert(flushResponse.contains(r), "held maintenance result changed"))
          heldFlush = if (!takeFlush) flushResponse else None
          if (heldFlush.nonEmpty) flushStalls += 1
          if (response.nonEmpty && consume) {
            val r = response.get
            val original = outstanding.remove((r.id, r.epoch)).getOrElse(sys.error("lost/duplicate/unowned cache response"))
            assert(r.error == original.error, s"wrong fault for $original: $r")
            if (r.error) errors += 1
            else if (original.atomicAdd) {
              val old = read(architectural, original.address, 8)
              assert(r.data == old, s"atomic-add returned old=$old, got=${r.data} for $original")
              write(architectural, original.address, 8, (old + original.data) & BigInt("ffffffffffffffff", 16), 255)
              writes += 1; atomicAdds += 1
            } else if (original.write) {
              assert(r.data == 0); write(architectural, original.address, 8, original.data, BigInt(original.mask)); writes += 1
            } else {
              assert(r.data == read(architectural, original.address, 8), s"load mismatch for $original: $r")
              reads += 1
            }
            if (outstanding.values.exists(_.sequence < original.sequence)) reorders += 1
            completed += 1
          }
          val tookRequest = offered.nonEmpty && dut.io.request.ready.toBoolean
          if (drain || flush.nonEmpty) {
            assert(!dut.io.request.ready.toBoolean, "drain/maintenance admitted new work"); drainChecks += 1
          }
          if (tookRequest) {
            val r = offered.get; assert(!outstanding.contains((r.id, r.epoch)))
            outstanding((r.id, r.epoch)) = r; accepted += 1
          }
          if (selected.nonEmpty) {
            assert(dut.io.reply.ready.toBoolean)
            if (corrupt) {
              stale += 1
              if (corruptGeneration) staleGenerations += 1 else stalePhases += 1
            }
            else {
              val i = selected.get; val p = lower.remove(i)
              if (i > 0) lowerReorders += 1
              if (p.request.write && !p.error)
                write(external, p.request.address, lineBytes, p.request.data, (BigInt(1) << lineBytes) - 1)
            }
          }
          if (bus.nonEmpty && dut.io.lower.ready.toBoolean) {
            val r = bus.get
            assert(r.address % lineBytes == 0 && r.address >= 0 && r.address + lineBytes <= size)
            assert(!lower.exists(_.request.slot == r.slot), "MSHR sent overlapping lower transfers")
            if (r.write) assert(r.data == read(architectural, r.address, lineBytes), "writeback differs from completed architectural writes")
            if (r.write) busWrites += 1 else busReads += 1
            seenGenerations += r.generation
            val error = if (r.write) failWrites(r.address) else failReads(r.address)
            lower += Pending(r, cycle + 6 + rng.nextInt(35), error)
          }
          maxOutstanding = maxOutstanding.max(outstanding.size); maxLower = maxLower.max(lower.size)
          val flushAccepted = flush.nonEmpty && dut.io.flush.ready.toBoolean
          val flushResult = if (dut.io.flushed.valid.toBoolean && takeFlush) Some(dut.io.flushed.payload.toBoolean) else None
          edge(); cycle += 1
          if (dut.io.hits.toBigInt > previousHits && pendingBefore) hitsUnderMiss += 1
          assert(cycle < 200000, "cache test deadlock")
          Step(tookRequest, flushAccepted, flushResult)
        }
        def run(items: Seq[Request], holdResponses: Int = 0, holdReplies: Int = 0): Unit = {
          var position = 0; val begin = cycle
          while (position < items.size || outstanding.nonEmpty || lower.nonEmpty) {
            if (tick(items.lift(position), consume = cycle - begin >= holdResponses,
              replies = cycle - begin >= holdReplies).accepted) position += 1
          }
          assert(dut.io.idle.toBoolean)
        }
        def flush(invalidate: Boolean, error: Boolean = false): Unit = {
          var admitted, finished = false
          val begin = cycle
          while (!finished) {
            val result = tick(flush = if (admitted) None else Some(invalidate), takeFlush = cycle - begin >= 20)
            admitted ||= result.flushAccepted
            result.flushResult.foreach { observed => assert(observed == error); finished = true }
          }
          assert(admitted && dut.io.idle.toBoolean && lower.isEmpty && outstanding.isEmpty)
          flushes += 1; if (error) flushFailures += 1
          assert(dut.io.clean.toBoolean == !error, "cache clean state disagrees with maintenance outcome")
          if (!error) assert(external.sameElements(architectural), "clean did not publish complete cache contents")
        }

        // Fill every MSHR, hold responses, hit different lines under misses and
        // force same-index alias stalls. The final stream wraps client epochs.
        run((0 until mshrs + 2).map(i => request(i * lineBytes)), holdResponses = 100, holdReplies = 80)
        run(Seq(request(0, true, BigInt("8877665544332211", 16), 0x5a), request(0),
          request(sets * lineBytes), request(0), request(3, error = true)))
        // Cache-side fetch-add is a single indivisible update. Sequentially
        // queued clients observe the prior value and leave one exact total.
        val initialAtomicWord = read(architectural, 8, 8)
        run(Seq(request(8, true, 1, atomicAdd = true), request(8, true, 2, atomicAdd = true),
          request(8, true, 3, atomicAdd = true), request(8), request(8, true, 99, mask = 15, atomicAdd = true, error = true), request(8)))
        assert(read(architectural, 8, 8) == initialAtomicWord + 6, "atomic-add serialization lost an update")
        assert(atomicAdds == 3, s"expected three committed atomic updates, observed $atomicAdds")
        flush(invalidate = false)
        val coldAtomicAddress = 40 * lineBytes
        val oldColdAtomicWord = read(architectural, coldAtomicAddress, 8)
        run(Seq(request(coldAtomicAddress, true, 9, atomicAdd = true), request(coldAtomicAddress)))
        assert(read(architectural, coldAtomicAddress, 8) == oldColdAtomicWord + 9,
          "atomic add after a cold refill did not update the word")
        flush(invalidate = false)
        for (_ <- 0 until 30) {
          val cold = (2 + rng.nextInt(40)) * sets * lineBytes
          run(Seq(request(0), request(cold + lineBytes), request(0)))
        }
        val random = (0 until 3000).map { _ =>
          val address = (rng.nextInt(96) * lineBytes + rng.nextInt(c.words) * 8)
          request(address, rng.nextBoolean(), BigInt(64, rng), rng.nextInt(256))
        }
        run(random)
        flush(invalidate = false)
        // A clean without invalidation retains a recently accessed line.
        run(Seq(request(0))); flush(invalidate = false)
        val afterClean = dut.io.refills.toBigInt
        run(Seq(request(0))); assert(dut.io.refills.toBigInt == afterClean)
        flush(invalidate = true)
        run(Seq(request(0))); assert(dut.io.refills.toBigInt == afterClean + 1)

        // Failed refill does not install data or commit the requested store.
        flush(invalidate = true)
        val faultLine = 128 * lineBytes
        failReads = Set(faultLine)
        run(Seq(request(faultLine, true, 12345, error = true), request(faultLine, error = true)))
        failReads = Set.empty; run(Seq(request(faultLine)))
        // Failed dirty eviction preserves the only up-to-date copy.
        run(Seq(request(0, true, 0x12345678)))
        assert(dut.io.idle.toBoolean && !dut.io.clean.toBoolean, "idle must not imply dirty data has been published")
        failWrites = Set(0)
        run(Seq(request(sets * lineBytes, error = true), request(0)))
        flush(invalidate = true, error = true)
        run(Seq(request(0)))
        failWrites = Set.empty; flush(invalidate = true)

        // Drain must block new admission but continue accepted work. Offer
        // maintenance before the active miss completes; it must wait for drain.
        val last = request(256 * lineBytes)
        var admitted = false
        while (!admitted) admitted = tick(Some(last), replies = false).accepted
        for (_ <- 0 until 15) tick(Some(request(0)), replies = false, drain = true)
        flush(invalidate = true)
        assert(dut.io.idle.toBoolean && dut.io.clean.toBoolean)
        saveCounters()
        initialize(); dut.clockDomain.assertReset(); for (_ <- 0 until 4) edge()
        dut.clockDomain.deassertReset(); edge(); resets += 1
        run(Seq(request(0), request(lineBytes)))
        flush(invalidate = true)
        saveCounters()
        assert(accepted == completed && outstanding.isEmpty && lower.isEmpty)
        assert(maxOutstanding == mshrs && maxLower == mshrs, "full MSHR/concurrent misses not exercised")
        assert(reorders > 0 && lowerReorders > 0 && stale > 0 && responseStalls > 0 && lowerStalls > 0)
        assert(hitsUnderMiss > 0 && drainChecks > 0 && errors == 5 && flushFailures == 1 && resets == 1)
        assert(staleGenerations > 0 && stalePhases > 0 && flushStalls > 0 && seenGenerations.size == 4)
        assert(savedCounters("hits") + savedCounters("misses") == accepted - 1)
        assert(savedCounters("writebacks") == busWrites && savedCounters("refills") == busReads && savedCounters("rejected_replies") == stale)
        assert(savedCounters("set_stalls") > 0 && savedCounters("full_stalls") > 0)
        val measured = savedCounters.toSeq.sortBy(_._1).map { case (k, v) => s"\"$k\":$v" }.mkString(",")
        summary = s"""{"sets":$sets,"line_bytes":$lineBytes,"mshrs":$mshrs,"generation_bits":2,"cycles":$cycle,"accepted":$accepted,"completed":$completed,"reads":$reads,"writes":$writes,"atomic_adds":$atomicAdds,"faulted_requests":$errors,"max_client_outstanding":$maxOutstanding,"max_lower_outstanding":$maxLower,"client_reorders":$reorders,"lower_reorders":$lowerReorders,"stale_replies":$stale,"stale_generations":$staleGenerations,"stale_phases":$stalePhases,"observed_generations":${seenGenerations.size},"lower_stall_cycles":$lowerStalls,"response_stall_cycles":$responseStalls,"flush_stall_cycles":$flushStalls,"hits_under_miss":$hitsUnderMiss,"drain_checks":$drainChecks,"flushes":$flushes,"failed_flushes":$flushFailures,"quiescent_resets":$resets,"observed_lower_reads":$busReads,"observed_lower_writes":$busWrites,"counters":{$measured}}"""
      }
    reports += summary
  }
  Files.writeString(root.resolve("validation.json"), s"""{"status":"passed","issue":5,"S04_complete":false,"claim_class":"actual_nonblocking_L1_component_RTL","configurations":[${reports.mkString(",")}],"limits":["Standalone cache/controller evidence; APE/PPE instruction integration and complete architectural atomic ISA support remain required","Cache-side 64-bit atomic-add primitive is tested; no system-wide coherence or multi-cache atomic serialization is claimed","Modeled whole-line external service; not measured DRAM performance","Reset only after drain and clean; no asynchronous fabric cancellation"]}
""")
  println("Nonblocking L1 RTL component matrix passed; S04 integration is not complete")
}
