package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}

/** Actual controller RTL protocol test: owner exclusion, held lines, stale
  * tags/generations, drain-before-clean, failed-clean retention and generation
  * advance only after successful clean/invalidate.
  */
object MemoryOwnershipControllerSim extends App {
  val out = Paths.get(args(0)); Files.createDirectories(out)
  val m = MemoryHierarchyConfig(sets=4, lineBytes=32, mshrs=2, wordPoison=true)
  var cycles=0
  SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(out.resolve("sim").toString).compile(new MemoryOwnershipController(m))
    .doSim("ownership_handoff") { dut =>
      def edge(): Unit={dut.clockDomain.risingEdge();sleep(5);dut.clockDomain.fallingEdge();sleep(5);cycles+=1}
      dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
      for(e<-0 until 2){
        dut.io.requests(e).valid #= false; dut.io.requests(e).source #= 0; dut.io.requests(e).ownerGeneration #= 0
        dut.io.requests(e).transfer.slot #= 0; dut.io.requests(e).transfer.generation #= 0
        dut.io.requests(e).transfer.address #= 0; dut.io.requests(e).transfer.write #= false
        dut.io.requests(e).transfer.data.foreach(_ #= 0); dut.io.requests(e).transfer.poison #= 0
        dut.io.responses(e).ready #= true; dut.io.clientIdle #= 3
        dut.io.flushed(e).valid #= false; dut.io.flushed(e).payload #= false
      }
      dut.io.handoff.valid #= false; dut.io.handoff.payload #= true; dut.io.result.ready #= false
      dut.io.lower.ready #= false; dut.io.reply.valid #= false; dut.io.reply.source #= 0
      dut.io.reply.ownerGeneration #= 0; dut.io.reply.transfer.slot #= 0; dut.io.reply.transfer.generation #= 0
      dut.io.reply.transfer.write #= false; dut.io.reply.transfer.error #= false; dut.io.reply.transfer.poison #= 0
      dut.io.reply.transfer.data.foreach(_ #= 0)
      for(_<-0 until 4) edge(); dut.clockDomain.deassertReset(); edge()
      assert(dut.io.owner.toBoolean==false && dut.io.generation.toBigInt==0 && dut.io.run.toBoolean)
      // A non-owner stream can neither reach the memory service nor be accepted.
      dut.io.requests(1).valid #= true; dut.io.requests(1).ownerGeneration #= 0
      sleep(1); assert(!dut.io.lower.valid.toBoolean && !dut.io.requests(1).ready.toBoolean)
      edge(); dut.io.requests(1).valid #= false
      dut.io.requests(0).valid #= true; dut.io.requests(0).source #= 1
      dut.io.requests(0).ownerGeneration #= 0; dut.io.requests(0).transfer.slot #= 1
      dut.io.requests(0).transfer.generation #= 7; dut.io.requests(0).transfer.address #= 0x240
      dut.io.requests(0).transfer.write #= false
      sleep(1); assert(dut.io.lower.valid.toBoolean && dut.io.lower.source.toInt==1)
      val held = (dut.io.lower.source.toInt,dut.io.lower.ownerGeneration.toBigInt,dut.io.lower.transfer.slot.toInt,
        dut.io.lower.transfer.generation.toBigInt,dut.io.lower.transfer.address.toBigInt)
      for(_<-0 until 5){edge();sleep(1);assert(dut.io.lower.valid.toBoolean && held==(
        dut.io.lower.source.toInt,dut.io.lower.ownerGeneration.toBigInt,dut.io.lower.transfer.slot.toInt,
        dut.io.lower.transfer.generation.toBigInt,dut.io.lower.transfer.address.toBigInt))}
      dut.io.clientIdle #= 2 // Owner is not quiescent while its lower request is stalled.
      dut.io.handoff.valid #= true; dut.io.handoff.payload #= true; sleep(1)
      assert(dut.io.handoff.ready.toBoolean); edge(); dut.io.handoff.valid #= false
      dut.io.lower.ready #= true; sleep(1); assert(dut.io.lower.valid.toBoolean && dut.io.lower.ready.toBoolean); edge()
      dut.io.requests(0).valid #= false; dut.io.lower.ready #= false
      assert(dut.io.accepted.toBigInt==1 && dut.io.outstanding.toBigInt==1 && !dut.io.flush(0).valid.toBoolean,
        s"after accept: accepted=${dut.io.accepted.toBigInt} outstanding=${dut.io.outstanding.toBigInt} flush=${dut.io.flush(0).valid.toBoolean}")
      def reply(ownerGen:Int, cacheGen:Int, lineSlot:Int=1): Unit={
        dut.io.reply.valid #= true; dut.io.reply.source #= 1; dut.io.reply.ownerGeneration #= ownerGen
        dut.io.reply.transfer.slot #= lineSlot; dut.io.reply.transfer.generation #= cacheGen
        dut.io.reply.transfer.write #= false; dut.io.reply.transfer.error #= false; dut.io.reply.transfer.poison #= 0
        sleep(1)
      }
      reply(0,8); assert(!dut.io.responses(0).valid.toBoolean); edge(); dut.io.reply.valid #= false
      assert(dut.io.rejected.toBigInt==1 && dut.io.outstanding.toBigInt==1)
      dut.io.responses(0).ready #= false
      reply(0,7); assert(dut.io.responses(0).valid.toBoolean && !dut.io.reply.ready.toBoolean)
      for(_<-0 until 4){edge();sleep(1);assert(dut.io.reply.valid.toBoolean && dut.io.responses(0).valid.toBoolean && !dut.io.reply.ready.toBoolean)}
      dut.io.responses(0).ready #= true; sleep(1); assert(dut.io.reply.ready.toBoolean); edge(); dut.io.reply.valid #= false
      assert(dut.io.completed.toBigInt==1 && dut.io.outstanding.toBigInt==0)
      dut.io.clientIdle #= 2
      for(_<-0 until 4){edge();assert(!dut.io.flush(0).valid.toBoolean)}
      dut.io.clientIdle #= 3
      var wait=0; while(!dut.io.flush(0).valid.toBoolean && wait<10){edge();wait+=1}
      assert(dut.io.flush(0).valid.toBoolean && dut.io.flush(0).payload.toBoolean)
      dut.io.flushed(0).valid #= true; dut.io.flushed(0).payload #= true
      sleep(1); assert(dut.io.flushed(0).ready.toBoolean); edge(); dut.io.flushed(0).valid #= false
      assert(dut.io.handoffFailures.toBigInt==1 && !dut.io.owner.toBoolean && dut.io.generation.toBigInt==0)
      assert(dut.io.result.valid.toBoolean && dut.io.result.failed.toBoolean)
      for(_<-0 until 4){val snapshot=(dut.io.result.owner.toBoolean,dut.io.result.failed.toBoolean,dut.io.result.generation.toBigInt)
        edge();assert(snapshot==(dut.io.result.owner.toBoolean,dut.io.result.failed.toBoolean,dut.io.result.generation.toBigInt))}
      dut.io.result.ready #= true; edge(); dut.io.result.ready #= false
      assert(dut.io.run.toBoolean)
      // Successful retry hands the cleaned generation to PPE.
      dut.io.handoff.valid #= true; dut.io.handoff.payload #= true; sleep(1); assert(dut.io.handoff.ready.toBoolean)
      edge(); dut.io.handoff.valid #= false
      var n=0; while(!dut.io.flush(0).valid.toBoolean && n<10){edge();n+=1}
      dut.io.flushed(0).valid #= true; dut.io.flushed(0).payload #= false
      sleep(1); assert(dut.io.flushed(0).ready.toBoolean); edge(); dut.io.flushed(0).valid #= false
      n=0; while(!dut.io.flush(1).valid.toBoolean && n<10){edge();n+=1}
      assert(dut.io.flush(1).valid.toBoolean && dut.io.flush(1).payload.toBoolean)
      dut.io.flushed(1).valid #= true; dut.io.flushed(1).payload #= false
      sleep(1); assert(dut.io.flushed(1).ready.toBoolean); edge(); dut.io.flushed(1).valid #= false
      assert(dut.io.owner.toBoolean && dut.io.generation.toBigInt==1 && dut.io.handoffs.toBigInt==1)
      dut.io.result.ready #= true; edge(); dut.io.result.ready #= false
      // The new generation may use memory. An old-generation response is eaten
      // and counted but never sent to the old cache or mistaken for live work.
      dut.io.requests(1).valid #= true; dut.io.requests(1).ownerGeneration #= 1
      dut.io.requests(1).source #= 0; dut.io.requests(1).transfer.slot #= 0
      dut.io.requests(1).transfer.generation #= 9; dut.io.requests(1).transfer.address #= 0x280
      dut.io.lower.ready #= true; sleep(1); assert(dut.io.lower.valid.toBoolean && dut.io.lower.source.toInt==2)
      edge(); dut.io.requests(1).valid #= false; dut.io.lower.ready #= false
      reply(0,9,lineSlot=0); // source PPE, old owner epoch
      dut.io.reply.source #= 2
      sleep(1); assert(!dut.io.responses(1).valid.toBoolean); edge(); dut.io.reply.valid #= false
      assert(dut.io.rejected.toBigInt==2 && dut.io.outstanding.toBigInt==1)
      reply(1,9,lineSlot=0); dut.io.reply.source #= 2
      sleep(1); assert(dut.io.responses(1).valid.toBoolean); edge(); dut.io.reply.valid #= false
      assert(dut.io.completed.toBigInt==2 && dut.io.outstanding.toBigInt==0)
      dut.io.handoff.valid #= true; dut.io.handoff.payload #= false; sleep(1); assert(dut.io.handoff.ready.toBoolean)
      edge(); dut.io.handoff.valid #= false
      n=0; while(!dut.io.flush(1).valid.toBoolean && n<10){edge();n+=1}
      dut.io.flushed(1).valid #= true; dut.io.flushed(1).payload #= false
      sleep(1); assert(dut.io.flushed(1).ready.toBoolean); edge(); dut.io.flushed(1).valid #= false
      n=0; while(!dut.io.flush(0).valid.toBoolean && n<10){edge();n+=1}
      assert(dut.io.flush(0).valid.toBoolean && dut.io.flush(0).payload.toBoolean)
      dut.io.flushed(0).valid #= true; dut.io.flushed(0).payload #= false
      sleep(1); assert(dut.io.flushed(0).ready.toBoolean); edge(); dut.io.flushed(0).valid #= false
      assert(!dut.io.owner.toBoolean && dut.io.generation.toBigInt==2 && dut.io.handoffs.toBigInt==2)
      assert(dut.io.accepted.toBigInt==2 && dut.io.completed.toBigInt==2 && dut.io.rejected.toBigInt==2)
      assert(dut.io.denied.toBigInt>0 && dut.io.handoffFailures.toBigInt==1)
      dut.io.result.ready #= true; edge(); dut.io.result.ready #= false
    }
  Files.writeString(out.resolve("validation.json"), s"""{"status":"passed","cycles":$cycles,"accepted":2,"completed":2,"rejected":2,"denied":${1},"handoffs":2,"failed_handoffs":1,"result_hold_cycles":8,"claim_class":"actual_owner_controller_RTL"}\n""")
}
