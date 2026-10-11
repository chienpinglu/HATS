package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files,Paths}
import scala.collection.mutable

/** Actual APE program writes shared RAM, PPE receives ownership and reads then
  * updates it, and APE reacquires ownership and reads the final value. The only
  * host behavior is a byte-backed external line service and task submission.
  */
object ApePpeSharedMemorySim extends App {
  require(args.length==2,"output directory and source-bound PPE delimiter application directory required")
  val out=Paths.get(args(0));val ppeApplicationDir=Paths.get(args(1));Files.createDirectories(out)
  val m=MemoryHierarchyConfig(wordPoison=true)
  val ppeBase=0x100000
  val ppeDevice=0x20000
  val memory=Array.fill[Byte](2*1024*1024)(0)
  def putWord(address:Int,value:BigInt,n:Int):Unit=for(b<-0 until n)memory(address+b)=((value>>(8*b))&255).toByte
  def getWord(address:Int,n:Int):BigInt=(0 until n).foldLeft(BigInt(0))((v,b)=>v|(BigInt(memory(address+b)&255)<<(8*b)))
  def addi(rd:Int,rs:Int,imm:Int):BigInt=(BigInt(imm&0xfff)<<20)|(BigInt(rs)<<15)|(BigInt(rd)<<7)|0x13
  def sd(rs2:Int,rs1:Int,imm:Int):BigInt={val x=BigInt(imm&0xfff);((x>>5)<<25)|(BigInt(rs2)<<20)|(BigInt(rs1)<<15)|(BigInt(3)<<12)|((x&31)<<7)|0x23}
  def ld(rd:Int,rs1:Int,imm:Int):BigInt=(BigInt(imm&0xfff)<<20)|(BigInt(rs1)<<15)|(BigInt(3)<<12)|(BigInt(rd)<<7)|3
  def lbu(rd:Int,rs1:Int,imm:Int):BigInt=(BigInt(imm&0xfff)<<20)|(BigInt(rs1)<<15)|(BigInt(4)<<12)|(BigInt(rd)<<7)|3
  def sb(rs2:Int,rs1:Int,imm:Int):BigInt={val x=BigInt(imm&0xfff);((x>>5)<<25)|(BigInt(rs2)<<20)|(BigInt(rs1)<<15)|((x&31)<<7)|0x23}
  def amoadd(rd:Int,rs1:Int,rs2:Int):BigInt=(BigInt(rs2)<<20)|(BigInt(rs1)<<15)|(BigInt(3)<<12)|(BigInt(rd)<<7)|0x2f
  val apeFence=BigInt("0ff0000f",16)
  // Four distinct lines separated by 16 cache lines map to the same D-L1 set.
  val conflictLoadAddresses=Vector(0x400,0x600,0x800,0xa00)
  val apeCode=Vector(addi(1,0,42),addi(2,0,0x300),ld(4,2,0x100),ld(5,2,0x120),
    ld(6,2,0x140),ld(7,2,0x300),ld(8,2,0x500),ld(9,2,0x700),
    sb(1,2,0x101),lbu(10,2,0x101),sd(1,2,0),apeFence,ld(3,2,0),BigInt("00100073",16),
    addi(2,0,0x300),ld(3,2,0),BigInt("00100073",16),
    addi(1,0,3),addi(2,0,0x300),amoadd(3,2,1),apeFence,ld(4,2,0),BigInt("00100073",16))
  apeCode.zipWithIndex.foreach{case(w,i)=>putWord(i*4,w,4)}
  def pi(op:Int,d:Int=0,a:Int=0,b:Int=0,width:Int=3,imm:Long=0):BigInt=
    BigInt(op)|(BigInt(d)<<8)|(BigInt(a)<<13)|(BigInt(b)<<18)|(BigInt(width)<<26)|((BigInt(imm)&BigInt("ffffffff",16))<<32)
  val ppeCode=Vector(pi(1,d=8,imm=0x300),pi(1,d=9,imm=43),pi(32,d=9,a=8),pi(35,width=0),pi(36,width=0),
    pi(1,d=8,imm=ppeDevice),pi(1,d=9,imm=0x66),pi(32,d=9,a=8),pi(31,d=11,a=8),
    pi(1,d=8,imm=0x300),pi(31,d=12,a=8),
    pi(1,d=8,imm=0x300),pi(1,d=9,imm=5),pi(38,d=13,a=8,b=9,width=3),pi(31,d=14,a=8,width=3),pi(37,a=14,width=0))
  ppeCode.zipWithIndex.foreach{case(w,i)=>putWord(ppeBase+i*8,w,8)}
  val ppeApplicationProperties=scala.io.Source.fromFile(ppeApplicationDir.resolve("case.properties").toFile)
    .getLines().map(_.split("=",2)).map(a=>a(0)->BigInt(a(1))).toMap
  val ppeApplicationCode=Files.readAllLines(ppeApplicationDir.resolve("code.hex")).toArray.toVector
    .map(v=>BigInt(v.toString,16))
  val ppeApplicationInitial=Files.readAllBytes(ppeApplicationDir.resolve("memory.bin"))
  val ppeApplicationExpected=ppeApplicationInitial.clone()
  val delimiterBytes="{}[]:,".getBytes("US-ASCII").map(_&255).toSet
  for(n<-0 until 256)ppeApplicationExpected(1024+n)=
    (if(delimiterBytes.contains(ppeApplicationInitial(256+n)&255))1 else 0).toByte
  require(ppeApplicationProperties("groups")==32 && ppeApplicationProperties("codeWords")==ppeApplicationCode.size &&
    ppeApplicationInitial.length==ppeApplicationExpected.length && ppeApplicationInitial.length<=memory.length,
    "unexpected PPE delimiter application fixture dimensions")
  case class Line(source:Int,ownerGeneration:BigInt,slot:Int,generation:BigInt,address:Int,write:Boolean,data:Vector[BigInt],poison:Int,due:Int,sequence:Int)
  val pending=mutable.ArrayBuffer[Line]()
  case class Device(id:Int,epoch:Int,address:BigInt,write:Boolean,data:BigInt,mask:Int,due:Int)
  val pendingDevice=mutable.ArrayBuffer[Device]()
  var cycles=0;var accepted=0;var completed=0;var apeHalts=0;var ppeCompletions=0
  var handoffsRequestedWithLiveLines=0;var handoffDrainWaitCycles=0
  var ppeApplicationMode=false;var ppeCompletionHeld=false;var ppeApplicationCompletions=0
  var totalSuccessfulHandoffs=0;var ppeApplicationLineRequests=0;var ppeApplicationAccesses=0;var ppeApplicationOutputSha256=""
  var apePartialStorebackingWord=""
  var ppeApplicationOutputBytes=Array.emptyByteArray;var ppeApplicationResetReadback=BigInt(0)
  var ppeApplicationFaults=0;var ppeApplicationFaultWriteAttempts=0
  var quiescentSystemResets=0;var valueAfterQuiescentReset=BigInt(0)
  var ppeDeviceAccepted=0;var ppeDeviceCompleted=0;var ppeDeviceReads=0;var ppeDeviceWrites=0;var ppeDeviceStalls=0
  var ppeDeviceValue=BigInt(0);var ppeCleanBeforeDevice=true;var heldPpeDevice:Option[Device]=None
  var ownerLaunchRaces=0;var apeLaunchStallCycles=0;var ppeLaunchStallCycles=0
  var pendingApeLaunchAcceptedAfterHandoff=false;var pendingPpeLaunchAcceptedAfterHandoff=false
  var apeLaunchHandshakes=0;var ppeLaunchHandshakes=0
  var apeFenceRetirements=0;var ppeFenceRetirements=0;var ppeBarrierRetirements=0
  val apeResults=mutable.ArrayBuffer[BigInt]();val apeMemory=mutable.ArrayBuffer[(BigInt,BigInt,Boolean)]()
  val apeAtomicOldValues=mutable.ArrayBuffer[BigInt]()
  val apeConflictLineRequests=mutable.ArrayBuffer[Int]()
  val ppeMemory=mutable.ArrayBuffer[(BigInt,BigInt,Boolean)]()
  val external=mutable.ArrayBuffer[(Int,Boolean,BigInt,BigInt)]()
  val apeTrace=mutable.ArrayBuffer[(BigInt,BigInt,BigInt)]()
  var lowerBackpressure=0;var maxLowerOutstanding=0;var responseReorders=0;var lastCompletedSequence = -1
  SimConfig.withVerilator.addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(out.resolve("sim").toString).compile(new ApePpeSharedMemoryTile(m,
      ppeDeviceRegions=Seq((BigInt(ppeDevice),BigInt(ppeDevice+8)))))
    .doSim("ape_ppe_owned_memory") { dut =>
      def edge():Unit={dut.clockDomain.risingEdge();sleep(5);dut.clockDomain.fallingEdge();sleep(5);cycles+=1}
      dut.clockDomain.clockSim #= false;dut.clockDomain.assertReset()
      dut.io.apeProgram.valid #= false;dut.io.apeProgram.index #= 0;dut.io.apeProgram.instruction #= 0
      dut.io.apeLaunch.valid #= false;dut.io.apeLaunch.pc #= 0;dut.io.apeLaunch.argument #= 0
      dut.io.apeLaunch.base #= 0;dut.io.apeLaunch.limit #= 4096;dut.io.apeLaunch.writable #= true
      dut.io.apeHalt.ready #= true
      dut.io.ppeProgram.valid #= false;dut.io.ppeProgram.index #= 0;dut.io.ppeProgram.instruction #= 0
      dut.io.ppeLaunch.valid #= false;dut.io.ppeLaunch.task #= 7;dut.io.ppeLaunch.epoch #= 1
      dut.io.ppeLaunch.argument #= 0;dut.io.ppeLaunch.argumentBytes #= 0;dut.io.ppeLaunch.addressSpace #= 2
      dut.io.ppeLaunch.generation #= 3;dut.io.ppeLaunch.group #= 0;dut.io.ppeLaunch.groups #= 1
      dut.io.ppeLaunch.budget #= 100000;dut.io.ppeLaunch.base #= 0;dut.io.ppeLaunch.limit #= ppeBase+4096
      dut.io.ppeLaunch.writable #= true;dut.io.ppeLaunch.codeWords #= ppeCode.size;dut.io.ppeLaunch.scratchBytes #= 0
      dut.io.ppeCompletion.ready #= false;dut.io.handoff.valid #= false;dut.io.handoff.payload #= true
      dut.io.ppeDeviceRequest.ready #= false;dut.io.ppeDeviceResponse.valid #= false
      dut.io.ppeDeviceResponse.id #= 0;dut.io.ppeDeviceResponse.epoch #= 0
      dut.io.ppeDeviceResponse.data #= 0;dut.io.ppeDeviceResponse.error #= false
      dut.io.handoffResult.ready #= false;dut.io.lower.ready #= false;dut.io.reply.valid #= false
      dut.io.reply.source #= 0;dut.io.reply.ownerGeneration #= 0;dut.io.reply.transfer.slot #= 0
      dut.io.reply.transfer.generation #= 0;dut.io.reply.transfer.write #= false
      dut.io.reply.transfer.data.foreach(_ #= 0);dut.io.reply.transfer.poison #= 0;dut.io.reply.transfer.error #= false
      for(_<-0 until 4)edge();dut.clockDomain.deassertReset();edge()
      for((w,i)<-apeCode.zipWithIndex){dut.io.apeProgram.valid #= true;dut.io.apeProgram.index #= i;dut.io.apeProgram.instruction #= w;edge()}
      dut.io.apeProgram.valid #= false
      for((w,i)<-ppeCode.zipWithIndex){dut.io.ppeProgram.valid #= true;dut.io.ppeProgram.index #= i;dut.io.ppeProgram.instruction #= w
        sleep(1);assert(dut.io.ppeProgram.ready.toBoolean);edge()}
      dut.io.ppeProgram.valid #= false
      def tick():Unit={
        dut.io.lower.ready #= (cycles%5!=1 && cycles%7!=0)
        dut.io.ppeDeviceRequest.ready #= (ppeDeviceStalls>=3 && cycles%4!=1)
        if(dut.io.ppeDeviceRequest.valid.toBoolean && !dut.io.ppeDeviceRequest.ready.toBoolean)ppeDeviceStalls+=1
        val dueDevice=pendingDevice.indices.find(i=>pendingDevice(i).due<=cycles)
        dut.io.ppeDeviceResponse.valid #= dueDevice.nonEmpty
        dueDevice.foreach{i=>val r=pendingDevice(i);dut.io.ppeDeviceResponse.id #= r.id
          dut.io.ppeDeviceResponse.epoch #= r.epoch;dut.io.ppeDeviceResponse.data #= ppeDeviceValue
          dut.io.ppeDeviceResponse.error #= false}
        if(dut.io.lower.valid.toBoolean && !dut.io.lower.ready.toBoolean)lowerBackpressure+=1
        val ready=pending.indices.filter(i=>pending(i).due<=cycles).lastOption
        dut.io.reply.valid #= ready.nonEmpty
        ready.foreach{i=>val r=pending(i);dut.io.reply.source #= r.source;dut.io.reply.ownerGeneration #= r.ownerGeneration
          dut.io.reply.transfer.slot #= r.slot;dut.io.reply.transfer.generation #= r.generation
          dut.io.reply.transfer.write #= r.write
          dut.io.reply.transfer.error #= false;dut.io.reply.transfer.poison #= r.poison
          if(r.address==0x300)external+=((r.address,r.write,getWord(r.address,8),r.ownerGeneration))
          for(w<-0 until m.words)dut.io.reply.transfer.data(w) #= getWord(r.address+w*8,8)}
        sleep(1)
        heldPpeDevice.foreach(r=>assert(dut.io.ppeDeviceRequest.valid.toBoolean &&
          dut.io.ppeDeviceRequest.id.toInt==r.id && dut.io.ppeDeviceRequest.epoch.toInt==r.epoch &&
          dut.io.ppeDeviceRequest.address.toBigInt==r.address && dut.io.ppeDeviceRequest.write.toBoolean==r.write &&
          dut.io.ppeDeviceRequest.data.toBigInt==r.data && dut.io.ppeDeviceRequest.mask.toInt==r.mask,
          "combined PPE device request changed under backpressure"))
        heldPpeDevice=if(dut.io.ppeDeviceRequest.valid.toBoolean && !dut.io.ppeDeviceRequest.ready.toBoolean)
          Some(Device(dut.io.ppeDeviceRequest.id.toInt,dut.io.ppeDeviceRequest.epoch.toInt,
            dut.io.ppeDeviceRequest.address.toBigInt,dut.io.ppeDeviceRequest.write.toBoolean,
            dut.io.ppeDeviceRequest.data.toBigInt,dut.io.ppeDeviceRequest.mask.toInt,cycles)) else None
        val completionDelay=if(accepted%2==0)40 else 4
        val line=if(dut.io.lower.valid.toBoolean)Some(Line(dut.io.lower.source.toInt,dut.io.lower.ownerGeneration.toBigInt,
          dut.io.lower.transfer.slot.toInt,dut.io.lower.transfer.generation.toBigInt,dut.io.lower.transfer.address.toBigInt.toInt,
          dut.io.lower.transfer.write.toBoolean,dut.io.lower.transfer.data.map(_.toBigInt).toVector,dut.io.lower.transfer.poison.toInt,cycles+completionDelay,accepted))else None
        ready.foreach{i=>if(dut.io.reply.ready.toBoolean){val r=pending.remove(i);completed+=1
          if(r.sequence<lastCompletedSequence)responseReorders+=1
          lastCompletedSequence=math.max(lastCompletedSequence,r.sequence)
          if(r.write)for(w<-0 until m.words;b<-0 until 8)memory(r.address+w*8+b)=((r.data(w)>>(b*8))&255).toByte}}
        line.filter(_=>dut.io.lower.ready.toBoolean).foreach{r=>
          assert(r.address>=0 && r.address+m.lineBytes<=memory.length && r.address%m.lineBytes==0)
          assert(!pending.exists(p=>p.source==r.source && p.slot==r.slot),"system released a live lower slot")
          if(r.write)for(w<-0 until m.words;b<-0 until 8)memory(r.address+w*8+b)=((r.data(w)>>(b*8))&255).toByte
          if(r.address==0x300)external+=((r.address,r.write,r.data.head,r.ownerGeneration))
          if(r.source==1 && conflictLoadAddresses.contains(r.address))apeConflictLineRequests+=r.address
          pending+=r;accepted+=1;maxLowerOutstanding=math.max(maxLowerOutstanding,pending.size)
        }
        dueDevice.foreach{i=>if(dut.io.ppeDeviceResponse.ready.toBoolean){pendingDevice.remove(i);ppeDeviceCompleted+=1}}
        if(dut.io.ppeDeviceRequest.valid.toBoolean && dut.io.ppeDeviceRequest.ready.toBoolean){
          val req=Device(dut.io.ppeDeviceRequest.id.toInt,dut.io.ppeDeviceRequest.epoch.toInt,
            dut.io.ppeDeviceRequest.address.toBigInt,dut.io.ppeDeviceRequest.write.toBoolean,
            dut.io.ppeDeviceRequest.data.toBigInt,dut.io.ppeDeviceRequest.mask.toInt,cycles+5)
          assert(req.address==ppeDevice && req.mask==255,s"unexpected integrated PPE device request $req")
          ppeCleanBeforeDevice &&= getWord(0x300,8)==43
          if(req.write){ppeDeviceValue=req.data;ppeDeviceWrites+=1}else ppeDeviceReads+=1
          pendingDevice+=req;ppeDeviceAccepted+=1
        }
      if(dut.io.apeRetired.valid.toBoolean && dut.io.apeRetired.writes.toBoolean && dut.io.apeRetired.rd.toInt==3)
          apeResults+=dut.io.apeRetired.value.toBigInt
        if(dut.io.apeRetired.valid.toBoolean && dut.io.apeRetired.writes.toBoolean && dut.io.apeRetired.rd.toInt==3 &&
          dut.io.apeRetired.instruction.toBigInt == amoadd(3,2,1)) apeAtomicOldValues+=dut.io.apeRetired.value.toBigInt
        if(dut.io.apeRetired.valid.toBoolean) {
          val retiredInstruction=dut.io.apeRetired.instruction.toBigInt
          if(retiredInstruction==apeFence) {
            val expectedFenceValue=if(dut.io.apeRetired.pc.toBigInt<48) BigInt(42) else BigInt(51)
            assert(getWord(0x300,8)==expectedFenceValue,s"integrated APE FENCE retired before its writeback was visible below D-L1: expected=$expectedFenceValue backing=${getWord(0x300,8)} pc=${dut.io.apeRetired.pc.toBigInt} events=$external")
            apeFenceRetirements+=1
          }
          apeTrace+=((dut.io.apeRetired.pc.toBigInt,retiredInstruction,dut.io.apeRetired.value.toBigInt))
        }
        if(dut.io.apeMemoryRetired.valid.toBoolean)
          apeMemory+=((dut.io.apeMemoryRetired.address.toBigInt,dut.io.apeMemoryRetired.data.toBigInt,dut.io.apeMemoryRetired.write.toBoolean))
        if(dut.io.ppeAccess.valid.toBoolean)
          ppeMemory+=((dut.io.ppeAccess.address.toBigInt,dut.io.ppeAccess.data.toBigInt,dut.io.ppeAccess.write.toBoolean))
        if(dut.io.ppeRetired.valid.toBoolean) {
          val op=(dut.io.ppeRetired.instruction.toBigInt&255).toInt
          if(op==35 || op==36) {
            assert(getWord(0x300,8)==43,s"integrated PPE op $op retired before its writeback was visible below D-L1")
            if(op==35) ppeFenceRetirements+=1 else ppeBarrierRetirements+=1
          }
        }
        if(dut.io.apeHalt.valid.toBoolean)apeHalts+=1
        if(dut.io.ppeCompletion.valid.toBoolean&&ppeCompletions==0){assert(pending.isEmpty,"PPE completion preceded lower service drain");ppeCompletions+=1}
        if(dut.io.ppeCompletion.valid.toBoolean && ppeApplicationMode && !ppeCompletionHeld){
          assert(pending.isEmpty,"integrated PPE application completion preceded lower line-service drain")
          ppeApplicationCompletions+=1;ppeCompletionHeld=true
        }
        if(dut.io.ppeCompletion.valid.toBoolean && dut.io.ppeCompletion.ready.toBoolean)ppeCompletionHeld=false
        if(dut.io.apeLaunch.valid.toBoolean && dut.io.apeLaunch.ready.toBoolean)apeLaunchHandshakes+=1
        else if(dut.io.apeLaunch.valid.toBoolean)apeLaunchStallCycles+=1
        if(dut.io.ppeLaunch.valid.toBoolean && dut.io.ppeLaunch.ready.toBoolean)ppeLaunchHandshakes+=1
        else if(dut.io.ppeLaunch.valid.toBoolean)ppeLaunchStallCycles+=1
        edge();assert(cycles<100000,"whole-system memory test timeout")
      }
      def launchApe(pc:Int):Unit={dut.io.apeLaunch.pc #= pc;dut.io.apeLaunch.valid #= true
        var n=0;while(!dut.io.apeLaunch.ready.toBoolean&&n<30){tick();n+=1};assert(dut.io.apeLaunch.ready.toBoolean)
        tick();dut.io.apeLaunch.valid #= false}
      def launchPpe():Unit={dut.io.ppeLaunch.valid #= true
        var n=0;while(!dut.io.ppeLaunch.ready.toBoolean&&n<30){tick();n+=1};assert(dut.io.ppeLaunch.ready.toBoolean)
        tick();dut.io.ppeLaunch.valid #= false}
      def raceLaunches(apeOwner:Boolean,apePc:Int=0):Unit={
        dut.io.apeLaunch.pc #= apePc;dut.io.apeLaunch.valid #= true;dut.io.ppeLaunch.valid #= true;sleep(1)
        assert(dut.io.apeLaunch.ready.toBoolean==apeOwner && dut.io.ppeLaunch.ready.toBoolean==(!apeOwner),
          s"simultaneous launch admission violated owner=$apeOwner apeReady=${dut.io.apeLaunch.ready.toBoolean} ppeReady=${dut.io.ppeLaunch.ready.toBoolean}")
        val apeBefore=apeLaunchHandshakes;val ppeBefore=ppeLaunchHandshakes
        ownerLaunchRaces+=1;tick()
        if(apeOwner){assert(apeLaunchHandshakes==apeBefore+1 && ppeLaunchHandshakes==ppeBefore)
          dut.io.apeLaunch.valid #= false}
        else {assert(ppeLaunchHandshakes==ppeBefore+1 && apeLaunchHandshakes==apeBefore)
          dut.io.ppeLaunch.valid #= false}
      }
      def finishApe():Unit={val before=apeHalts;var n=0;while(apeHalts==before&&n<30000){tick();n+=1};assert(apeHalts>before)}
      def finishPpe():Unit={var n=0;while(ppeCompletions==0&&n<30000){tick();n+=1};assert(ppeCompletions>0)}
      def handoff(owner:Boolean,requireLiveDrain:Boolean=false):Unit={
        val priorOwner=dut.io.owner.toBoolean;val priorGeneration=dut.io.ownershipGeneration.toBigInt
        val priorHandoffs=dut.io.handoffs.toBigInt
        val hadLiveLines=pending.nonEmpty && accepted>completed
        if(requireLiveDrain)assert(hadLiveLines,"live-drain handoff requested without outstanding external line traffic")
        dut.io.handoff.payload #= owner;dut.io.handoff.valid #= true
        var n=0;while(!dut.io.handoff.ready.toBoolean&&n<100){tick();n+=1};assert(dut.io.handoff.ready.toBoolean)
        tick();dut.io.handoff.valid #= false;n=0
        if(requireLiveDrain){
          handoffsRequestedWithLiveLines+=1
          assert(!dut.io.handoffResult.valid.toBoolean && dut.io.owner.toBoolean==priorOwner &&
            dut.io.ownershipGeneration.toBigInt==priorGeneration && dut.io.handoffs.toBigInt==priorHandoffs,
            "ownership changed or acknowledged before live line traffic drained")
          assert(!dut.io.apeLaunch.ready.toBoolean && !dut.io.ppeLaunch.ready.toBoolean && !dut.io.idle.toBoolean,
            "handoff failed to block launches and report non-idle while draining")
        }
        while(!dut.io.handoffResult.valid.toBoolean&&n<30000){tick();if(accepted>completed)handoffDrainWaitCycles+=1;n+=1}
        assert(dut.io.handoffResult.valid.toBoolean && !dut.io.handoffResult.failed.toBoolean &&
          dut.io.handoffResult.owner.toBoolean==owner,
          s"ownership handoff to $owner failed: valid=${dut.io.handoffResult.valid.toBoolean} failed=${dut.io.handoffResult.failed.toBoolean} owner=${dut.io.handoffResult.owner.toBoolean} generation=${dut.io.handoffResult.generation.toBigInt} cycle=$cycles")
        totalSuccessfulHandoffs+=1
        if(requireLiveDrain)assert(accepted==completed && pending.isEmpty,
          "live-drain handoff acknowledged before the behavioral lower-line service drained")
        dut.io.handoffResult.ready #= true;tick();dut.io.handoffResult.ready #= false
      }
      assert(!dut.io.owner.toBoolean)
      raceLaunches(apeOwner=true)
      var liveTrafficWait=0
      while((pending.size<2 || apeHalts!=0) && liveTrafficWait<10000){tick();liveTrafficWait+=1}
      assert(pending.size>=2 && apeHalts==0,
        s"could not establish live APE line traffic for ownership handoff: pending=${pending.size} halts=$apeHalts")
      handoff(true,requireLiveDrain=true)
      assert(apeHalts==1 && apeResults.last==42 && apeFenceRetirements==1)
      assert(dut.io.owner.toBoolean && dut.io.ownershipGeneration.toBigInt==1 && getWord(0x300,8)==42)
      var ppeLaunchWait=0;while(ppeLaunchHandshakes==0 && ppeLaunchWait<30){tick();ppeLaunchWait+=1}
      assert(ppeLaunchHandshakes==1,"held non-owner PPE launch was not accepted after ownership transfer")
      pendingPpeLaunchAcceptedAfterHandoff=true;dut.io.ppeLaunch.valid #= false
      finishPpe();assert(dut.io.ppeCompletion.value.toBigInt==48,s"PPE completion ${dut.io.ppeCompletion.value.toBigInt} status=${dut.io.ppeCompletion.status.toBigInt} cause=${dut.io.ppeCompletion.cause.toBigInt} pc=${dut.io.ppeCompletion.pc.toBigInt} accesses=$ppeMemory")
      assert(ppeMemory.exists(x=>x==(BigInt(0x300),BigInt(43),true)))
      assert(ppeMemory.exists(x=>x==(BigInt(ppeDevice),BigInt(0x66),true)) &&
        ppeMemory.exists(x=>x==(BigInt(ppeDevice),BigInt(0x66),false)),s"missing integrated PPE device observations: $ppeMemory")
      assert(ppeDeviceAccepted==2 && ppeDeviceCompleted==2 && ppeDeviceReads==1 && ppeDeviceWrites==1 &&
        ppeDeviceStalls>0 && ppeCleanBeforeDevice && pendingDevice.isEmpty,
        s"integrated PPE device coverage incomplete: accepted=$ppeDeviceAccepted completed=$ppeDeviceCompleted reads=$ppeDeviceReads writes=$ppeDeviceWrites stalls=$ppeDeviceStalls clean=$ppeCleanBeforeDevice pending=$pendingDevice")
      dut.io.ppeCompletion.ready #= true;tick();dut.io.ppeCompletion.ready #= false
      val apeBeforeHandoff=apeLaunchHandshakes
      dut.io.apeLaunch.pc #= 56;dut.io.apeLaunch.valid #= true;sleep(1)
      assert(!dut.io.apeLaunch.ready.toBoolean,"non-owner APE launch was admitted while PPE owned memory")
      tick();tick()
      handoff(false);assert(!dut.io.owner.toBoolean && dut.io.ownershipGeneration.toBigInt==2 && getWord(0x300,8)==48)
      var apeLaunchWait=0;while(apeLaunchHandshakes==apeBeforeHandoff && apeLaunchWait<30){tick();apeLaunchWait+=1}
      assert(apeLaunchHandshakes==apeBeforeHandoff+1,"held non-owner APE launch was not accepted after ownership transfer")
      pendingApeLaunchAcceptedAfterHandoff=true;dut.io.apeLaunch.valid #= false
      finishApe();assert(apeResults.last==48,s"APE observed ${apeResults.last}, expected PPE's 48; values=$apeResults external=$external backing=${getWord(0x300,8)} events=$apeMemory trace=$apeTrace hits=${dut.io.apeCacheHits.toBigInt} misses=${dut.io.apeCacheMisses.toBigInt}")
      launchApe(68);finishApe()
      assert(apeAtomicOldValues.last==48 && getWord(0x300,8)==51,
        s"cross-engine atomic handoff failed: old=${apeAtomicOldValues.lastOption} backing=${getWord(0x300,8)} trace=$apeTrace memory=$apeMemory")
      assert(ppeFenceRetirements==1 && ppeBarrierRetirements==1)
      assert(apeMemory.exists(x=>x==(BigInt(0x300),BigInt(48),false)))
      assert(apeMemory.exists(x=>x==(BigInt(0x401),BigInt(42),true)) &&
        apeMemory.exists(x=>x==(BigInt(0x401),BigInt(42),false)),
        s"integrated APE byte-store/load alias failed: $apeMemory")
      assert(getWord(0x400,8)==(BigInt(42)<<8),
        s"partial-byte update was not preserved by conflict replacement and ownership clean: ${getWord(0x400,8)}")
      apePartialStorebackingWord=getWord(0x400,8).toString
      val observedConflictLoads=apeMemory.collect{
        case (address,_,false) if conflictLoadAddresses.contains(address.toInt)=>address.toInt
      }.distinct.sorted
      val requestedConflictLines=apeConflictLineRequests.distinct.sorted
      assert(observedConflictLoads==conflictLoadAddresses.sorted,
        s"integrated APE did not retire every conflict-set load: observed=$observedConflictLoads expected=${conflictLoadAddresses.sorted}")
      assert(requestedConflictLines==conflictLoadAddresses.sorted &&
        requestedConflictLines.forall(a=>(a/m.lineBytes)%m.sets==0),
        s"integrated D-L1 did not refill all four conflicting lines: observed=$requestedConflictLines expected=${conflictLoadAddresses.sorted}")
      assert(dut.io.handoffs.toBigInt==2 && dut.io.accepted.toBigInt==dut.io.completed.toBigInt && pending.isEmpty && pendingDevice.isEmpty)
      assert(lowerBackpressure>0,"integrated line interface never experienced request backpressure")
      assert(dut.io.idle.toBoolean && getWord(0x300,8)==51,
        "warm reset must begin only after all engine and fabric work drains and clean data is visible")
      dut.clockDomain.assertReset(); for(_<-0 until 4) edge(); dut.clockDomain.deassertReset(); edge()
      quiescentSystemResets+=1
      launchApe(56); finishApe()
      assert(apeResults.last==51 && getWord(0x300,8)==51,
        s"quiescent system reset lost the committed shared value: observed=${apeResults.lastOption} backing=${getWord(0x300,8)}")
      valueAfterQuiescentReset=apeResults.last

      // Reinitialize external memory from the bound PPE case and run all 32
      // actual task groups through the combined ownership/cache hierarchy.
      for(i<-ppeApplicationInitial.indices)memory(i)=ppeApplicationInitial(i)
      ppeApplicationCode.zipWithIndex.foreach{case(w,i)=>putWord(ppeBase+i*8,w,8)}
      handoff(true)
      // Negative integrated case: descriptor and input are in range, but the
      // output object is not. The vector store must fault without publishing
      // any output byte; the same task then runs successfully at full bounds.
      val p=ppeApplicationProperties
      val outputBeforeFault=memory.slice(1024,1280).toVector
      val accessesBeforeFault=ppeMemory.size
      dut.io.ppeLaunch.task #= p("task").toInt;dut.io.ppeLaunch.epoch #= 99
      dut.io.ppeLaunch.argument #= p("argument");dut.io.ppeLaunch.argumentBytes #= p("argumentBytes").toInt
      dut.io.ppeLaunch.addressSpace #= p("addressSpace").toInt;dut.io.ppeLaunch.generation #= p("generation").toInt
      dut.io.ppeLaunch.group #= 0;dut.io.ppeLaunch.groups #= p("groups").toInt
      dut.io.ppeLaunch.budget #= 1000000;dut.io.ppeLaunch.base #= p("base")
      dut.io.ppeLaunch.limit #= 512;dut.io.ppeLaunch.writable #= true
      dut.io.ppeLaunch.codeWords #= p("codeWords").toInt;dut.io.ppeLaunch.scratchBytes #= p("scratchBytes").toInt
      launchPpe();var faultWait=0
      while(!dut.io.ppeCompletion.valid.toBoolean&&faultWait<30000){tick();faultWait+=1}
      assert(dut.io.ppeCompletion.valid.toBoolean && dut.io.ppeCompletion.status.toInt==2 &&
        dut.io.ppeCompletion.cause.toInt!=0 && pending.isEmpty && accepted==completed,
        s"integrated PPE bounds violation did not fault precisely after draining: status=${dut.io.ppeCompletion.status.toInt} cause=${dut.io.ppeCompletion.cause.toInt} pending=${pending.size}")
      ppeApplicationFaults+=1
      val faultEvents=ppeMemory.drop(accessesBeforeFault)
      ppeApplicationFaultWriteAttempts+=faultEvents.count(_._3)
      val changedOutput=(1024 until 1280).filter(i=>memory(i)!=outputBeforeFault(i-1024)).take(16)
      assert(changedOutput.isEmpty,
        s"integrated PPE bounds fault changed output bytes $changedOutput; store-shaped access events=${faultEvents.filter(_._3).take(16)}")
      dut.io.ppeCompletion.ready #= true;tick();dut.io.ppeCompletion.ready #= false
      ppeApplicationMode=true
      val acceptedBeforePpeApplication=accepted
      val firstApplicationAccess=ppeMemory.size
      for(group<-0 until ppeApplicationProperties("groups").toInt){
        dut.io.ppeLaunch.task #= p("task").toInt;dut.io.ppeLaunch.epoch #= 100+group
        dut.io.ppeLaunch.argument #= p("argument");dut.io.ppeLaunch.argumentBytes #= p("argumentBytes").toInt
        dut.io.ppeLaunch.addressSpace #= p("addressSpace").toInt;dut.io.ppeLaunch.generation #= p("generation").toInt
        dut.io.ppeLaunch.group #= group;dut.io.ppeLaunch.groups #= p("groups").toInt
        dut.io.ppeLaunch.budget #= 1000000;dut.io.ppeLaunch.base #= p("base")
        dut.io.ppeLaunch.limit #= p("limit");dut.io.ppeLaunch.writable #= (p("writable")!=0)
        dut.io.ppeLaunch.codeWords #= p("codeWords").toInt;dut.io.ppeLaunch.scratchBytes #= p("scratchBytes").toInt
        val target=ppeApplicationCompletions+1
        launchPpe();var n=0
        while(ppeApplicationCompletions<target && n<30000){tick();n+=1}
        assert(ppeApplicationCompletions==target && dut.io.ppeCompletion.valid.toBoolean &&
          dut.io.ppeCompletion.status.toInt==1,
          s"integrated PPE application group $group failed: completions=$ppeApplicationCompletions status=${dut.io.ppeCompletion.status.toInt} cause=${dut.io.ppeCompletion.cause.toInt}")
        dut.io.ppeCompletion.ready #= true;tick();dut.io.ppeCompletion.ready #= false
      }
      assert(ppeApplicationCompletions==32 && ppeMemory.size>firstApplicationAccess,
        s"integrated PPE application did not complete all groups/accesses: groups=$ppeApplicationCompletions accesses=${ppeMemory.size-firstApplicationAccess}")
      ppeApplicationAccesses=ppeMemory.size-firstApplicationAccess
      handoff(false)
      assert(!dut.io.owner.toBoolean && dut.io.ownershipGeneration.toBigInt==2,
        "PPE application return handoff did not advance the ownership epoch")
      assert(dut.io.idle.toBoolean && accepted==completed && pending.isEmpty,
        "system reset must be withheld until PPE clean handoff and lower-line accounting are quiescent")
      val ppeApplicationDiffs=(0 until ppeApplicationExpected.length)
        .filter(i=>memory(i)!=ppeApplicationExpected(i)).take(24)
        .map(i=>s"$i:${memory(i)&255}->${ppeApplicationExpected(i)&255}")
      assert(ppeApplicationDiffs.isEmpty,
        s"integrated PPE application output differs from independent byte-for-byte oracle after clean handoff; first diffs=$ppeApplicationDiffs accesses=${ppeMemory.size-firstApplicationAccess} lineRequests=${accepted-acceptedBeforePpeApplication}")
      ppeApplicationLineRequests=accepted-acceptedBeforePpeApplication
      ppeApplicationOutputSha256=java.security.MessageDigest.getInstance("SHA-256")
        .digest(memory.take(ppeApplicationExpected.length)).map(b=>f"${b&0xff}%02x").mkString
      ppeApplicationOutputBytes=memory.take(ppeApplicationExpected.length)
      val sharedWordBeforeFinalReset=getWord(0x300,8)
      apeCode.zipWithIndex.foreach{case(w,i)=>putWord(i*4,w,4)}
      dut.clockDomain.assertReset();for(_<-0 until 4)edge();dut.clockDomain.deassertReset();edge()
      quiescentSystemResets+=1
      launchApe(56);finishApe()
      ppeApplicationResetReadback=apeResults.last
      assert(ppeApplicationResetReadback==sharedWordBeforeFinalReset,
        s"post-PPE quiescent reset lost the cleaned shared word: observed=$ppeApplicationResetReadback expected=$sharedWordBeforeFinalReset")
    }
  assert(apeHalts==5 && ppeCompletions==1 && ppeApplicationCompletions==32 && totalSuccessfulHandoffs==4 &&
    apeResults.contains(42) && apeResults.contains(48) && apeResults.contains(51) && apeAtomicOldValues==Seq(BigInt(48)))
  val conflictLoads=apeMemory.collect{case (address,_,false) if conflictLoadAddresses.contains(address.toInt)=>address.toInt}.distinct.sorted
  val conflictRefills=apeConflictLineRequests.distinct.sorted
  Files.write(out.resolve("ppe_application_output.bin"),ppeApplicationOutputBytes)
  Files.writeString(out.resolve("launch-race.json"),s"""{"simultaneous_launch_presentations":$ownerLaunchRaces,"ape_nonowner_stall_cycles":$apeLaunchStallCycles,"ppe_nonowner_stall_cycles":$ppeLaunchStallCycles,"pending_ape_accepted_after_handoff":$pendingApeLaunchAcceptedAfterHandoff,"pending_ppe_accepted_after_handoff":$pendingPpeLaunchAcceptedAfterHandoff}
""")
  Files.writeString(out.resolve("validation.json"),s"""{"status":"passed","cycles":$cycles,"ape_halts":$apeHalts,"ppe_completions":$ppeCompletions,"ppe_application_faults":$ppeApplicationFaults,"ppe_application_fault_write_attempts":$ppeApplicationFaultWriteAttempts,"ppe_application_fault_output_unchanged":true,"ppe_application_groups":$ppeApplicationCompletions,"ppe_application_line_requests":$ppeApplicationLineRequests,"ppe_application_architectural_accesses":$ppeApplicationAccesses,"ppe_application_output_sha256":"$ppeApplicationOutputSha256","ppe_application_matches_independent_memory_oracle":true,"ppe_application_reset_readback_matches":${ppeApplicationResetReadback==getWord(0x300,8)},"ppe_application_reset_readback_value":"$ppeApplicationResetReadback","ape_fence_retirements":$apeFenceRetirements,"ppe_fence_retirements":$ppeFenceRetirements,"ppe_barrier_retirements":$ppeBarrierRetirements,"ape_rd3_values":[${apeResults.mkString(",")}],"ape_atomic_old_values":[${apeAtomicOldValues.mkString(",")}],"ppe_atomic_final_value":"48","final_shared_value":"51","ape_memory_events":${apeMemory.size},"ppe_memory_events":${ppeMemory.size},"ape_conflict_load_addresses":[${conflictLoads.mkString(",")}],"ape_conflict_line_refills":[${conflictRefills.mkString(",")}],"ape_conflict_set_index":${(conflictLoadAddresses.head/m.lineBytes)%m.sets},"ape_byte_alias_verified":true,"ape_partial_storebacking_word":"$apePartialStorebackingWord","line_requests":$accepted,"line_completions":$completed,"lower_backpressure_cycles":$lowerBackpressure,"max_lower_outstanding":$maxLowerOutstanding,"response_reorders":$responseReorders,"ownership_handoffs":$totalSuccessfulHandoffs,"handoffs_requested_with_live_lines":$handoffsRequestedWithLiveLines,"handoff_drain_wait_cycles":$handoffDrainWaitCycles,"quiescent_system_resets":$quiescentSystemResets,"value_after_quiescent_reset":"$valueAfterQuiescentReset","observed_shared_value_after_ape":42,"observed_shared_value_after_ppe":48,"ppe_device_requests":$ppeDeviceAccepted,"ppe_device_completions":$ppeDeviceCompleted,"ppe_device_reads":$ppeDeviceReads,"ppe_device_writes":$ppeDeviceWrites,"ppe_device_backpressure_cycles":$ppeDeviceStalls,"ppe_clean_before_device":$ppeCleanBeforeDevice,"ppe_device_register_value":"$ppeDeviceValue","claim_class":"dual_engine_shared_memory_with_actual_PPE_delimiter_application"}\n""")
}
