package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import scala.collection.mutable
import scala.util.matching.Regex

/** Replays architectural memory events captured from actual APE application RTL
  * through the real NonBlockingL1 RTL. The external line service is behavioral.
  */
object MemoryTraceReplaySim extends App {
  require(args.length == 5, "trace initial-memory final-memory output sets mshrs")
  val tracePath=Paths.get(args(0)); val initialPath=Paths.get(args(1)); val finalPath=Paths.get(args(2))
  val out=Paths.get(args(3)); Files.createDirectories(out)
  val sets=args(4).split(":")(0).toInt; val mshrs=args(4).split(":")(1).toInt
  val lineBytes=32; val base=0x10000
  val m=MemoryHierarchyConfig(sets=sets,lineBytes=lineBytes,mshrs=mshrs,clientIdBits=8,epochBits=8)
  case class Op(address:Int,bytes:Int,write:Boolean,data:BigInt)
  val event:Regex="""\{"kind":"memory","address":"(\d+)","bytes":(\d+),"write":(true|false),"data":"(\d+)","error":(true|false)\}""".r
  val operations=Files.readAllLines(tracePath).toArray.toVector.map(_.toString).collect {
    case event(a,n,w,d,e) =>
      require(e=="false",s"application trace contains a memory error: $tracePath")
      Op(a.toInt,n.toInt,w=="true",BigInt(d))
  }
  require(operations.nonEmpty,s"no APE memory events in $tracePath")
  val initial=Files.readAllBytes(initialPath); val expected=Files.readAllBytes(finalPath)
  require(initial.length==65536 && expected.length==65536)
  val backing=initial.clone()
  case class Lower(slot:Int,generation:Int,address:Int,write:Boolean,data:Vector[BigInt],due:Int)
  val pending=mutable.ArrayBuffer[Lower]()
  var cycle=0; var accepted=0; var completed=0; var lowerAccepted=0; var lowerCompleted=0
  var lowerWrites=0; var lowerReads=0; var backpressure=0; var maxOutstanding=0
  var flushSeen=false
  var hits=BigInt(0); var misses=BigInt(0); var writebacks=BigInt(0); var refills=BigInt(0)
  def read(bytes:Array[Byte],address:Int,count:Int):BigInt=
    (0 until count).foldLeft(BigInt(0))((v,i)=>v|(BigInt(bytes(address-base+i)&255)<<(8*i)))
  def write(bytes:Array[Byte],address:Int,count:Int,data:BigInt,mask:BigInt):Unit=
    for(i<-0 until count if mask.testBit(i))bytes(address-base+i)=((data>>(8*i))&255).toByte
  val compiled=SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(out.resolve("rtl").toString).compile(new NonBlockingL1(m))
  compiled.doSim(s"ape_trace_s${sets}_m${mshrs}") { dut =>
    def edge():Unit={dut.clockDomain.risingEdge();sleep(5);dut.clockDomain.fallingEdge();sleep(5);cycle+=1}
    dut.clockDomain.clockSim #= false; dut.clockDomain.assertReset()
    dut.io.request.valid #= false; dut.io.request.id #= 0; dut.io.request.epoch #= 0
    dut.io.request.address #= 0; dut.io.request.write #= false; dut.io.request.atomicAdd #= false
    dut.io.request.data #= 0; dut.io.request.mask #= 0; dut.io.response.ready #= true
    dut.io.lower.ready #= false; dut.io.reply.valid #= false; dut.io.reply.slot #= 0
    dut.io.reply.generation #= 0; dut.io.reply.write #= false; dut.io.reply.error #= false
    dut.io.reply.data.foreach(_ #= 0); dut.io.flush.valid #= false; dut.io.flush.payload #= false
    dut.io.flushed.ready #= true; dut.io.drain #= false
    for(_<-0 until 4)edge();dut.clockDomain.deassertReset();edge()

    def tick(offered:Option[(Int,Op)],flush:Boolean=false):Option[BigInt]={
      dut.io.request.valid #= offered.nonEmpty
      offered.foreach{case(id,o)=>dut.io.request.id #= id;dut.io.request.epoch #= 0
        dut.io.request.address #= (o.address & ~7);dut.io.request.write #= o.write;dut.io.request.atomicAdd #= false
        val off=o.address&7;dut.io.request.data #= ((o.data<<(off*8))&BigInt("ffffffffffffffff",16))
        dut.io.request.mask #= (((1<<o.bytes)-1)<<off)}
      dut.io.lower.ready #= (cycle%5!=1 && cycle%7!=0)
      dut.io.flush.valid #= flush;dut.io.flush.payload #= false
      val due=pending.indices.filter(i=>pending(i).due<=cycle).lastOption
      dut.io.reply.valid #= due.nonEmpty
      due.foreach{i=>val p=pending(i);dut.io.reply.slot #= p.slot;dut.io.reply.generation #= p.generation
        dut.io.reply.write #= p.write;dut.io.reply.error #= false
        for(w<-0 until m.words)dut.io.reply.data(w) #= read(backing,p.address+w*8,8)}
      sleep(1)
      if(dut.io.lower.valid.toBoolean && !dut.io.lower.ready.toBoolean)backpressure+=1
      val lower=if(dut.io.lower.valid.toBoolean)Some(Lower(dut.io.lower.slot.toInt,dut.io.lower.generation.toInt,
        dut.io.lower.address.toBigInt.toInt,dut.io.lower.write.toBoolean,
        dut.io.lower.data.map(_.toBigInt).toVector,cycle+7+(lowerAccepted%5)))else None
      lower.foreach{p=>require(p.address>=base && p.address+lineBytes<=base+backing.length && p.address%lineBytes==0)}
      var observed:Option[BigInt]=None
      if(dut.io.response.valid.toBoolean){
        observed=Some(dut.io.response.data.toBigInt)
      }
      if(due.nonEmpty && dut.io.reply.ready.toBoolean){val p=pending.remove(due.get);lowerCompleted+=1
        if(p.write){
          for(w<-0 until m.words)write(backing,p.address+w*8,8,p.data(w),BigInt(255))
          lowerWrites+=1
        }else lowerReads+=1}
      if(lower.nonEmpty && dut.io.lower.ready.toBoolean){val p=lower.get
        pending+=p;lowerAccepted+=1;maxOutstanding=math.max(maxOutstanding,pending.size)}
      val reqFire=offered.nonEmpty && dut.io.request.ready.toBoolean
      if(reqFire)accepted+=1
      if(dut.io.response.valid.toBoolean && dut.io.response.ready.toBoolean){
        offered.foreach{case(id,_)=>assert(dut.io.response.id.toInt==id && dut.io.response.epoch.toInt==0,
          "L1 response identity mismatch")}
        completed+=1
      }
      val flushDone=flush && dut.io.flushed.valid.toBoolean
      if(flushDone)assert(!dut.io.flushed.payload.toBoolean)
      flushSeen ||= flushDone
      edge()
      if(flushDone)Some(BigInt(0))else observed
    }
    for((op,index)<-operations.zipWithIndex){
      require(op.address>=base && op.address+op.bytes<=base+backing.length && Set(1,2,4,8)(op.bytes),s"bad trace op $op")
      val offset=op.address-base
      val expectedLoad=if(op.write)BigInt(0) else read(backing,op.address,op.bytes)
      if(!op.write)require(expectedLoad==op.data,s"trace replay memory ordering diverged at event $index: $op got=$expectedLoad")
      val requestData=op.data
      var sent=false;var got:Option[BigInt]=None;var guard=0
      while(got.isEmpty && guard<20000){
        val before=accepted
        got=tick(if(sent)None else Some((index & 255)->op))
        if(accepted>before)sent=true
        guard+=1
      }
      assert(got.nonEmpty,s"cache trace replay timed out at operation $index")
      if(!op.write){val shifted=(got.get>>(8*(op.address&7)))&((BigInt(1)<<(8*op.bytes))-1)
        assert(shifted==op.data,s"L1 load mismatch at event $index expected=${op.data} got=$shifted")}
      if(op.write)write(backing,op.address,op.bytes,requestData,(BigInt(1)<<op.bytes)-1)
      hits=dut.io.hits.toBigInt;misses=dut.io.misses.toBigInt
      writebacks=dut.io.writebacks.toBigInt;refills=dut.io.refills.toBigInt
    }
    var flushed=false;var guard=0
    while(!flushSeen && guard<20000){
      tick(None,flush=true)
      guard+=1
    }
    flushed=flushSeen
    assert(flushed && pending.isEmpty && dut.io.idle.toBoolean,s"final D-L1 clean failed pending=$pending")
    assert(backing.sameElements(expected),s"final cache replay memory differs from actual APE output for $tracePath")
    require(accepted==operations.size && completed==operations.size)
  }
  Files.writeString(out.resolve("validation.json"),
    s"""{"status":"passed","trace":"${tracePath.toString}","trace_sha256":"${sha(tracePath)}","sets":$sets,"line_bytes":$lineBytes,"mshrs":$mshrs,"application_memory_events":${operations.size},"accepted":$accepted,"completed":$completed,"cycles":$cycle,"lower_accepted":$lowerAccepted,"lower_completed":$lowerCompleted,"lower_reads":$lowerReads,"lower_writebacks":$lowerWrites,"lower_backpressure_cycles":$backpressure,"max_lower_outstanding":$maxOutstanding,"hits":"$hits","misses":"$misses","writebacks":"$writebacks","refills":"$refills","final_memory_matches_application":true,"claim_class":"actual_ApeCore_application_trace_replayed_through_NonBlockingL1_RTL_with_behavioral_line_service"}\n""")
  println(s"APE application memory trace passed through $sets-set/$mshrs-MSHR L1 RTL: ${operations.size} events")

  def sha(p:java.nio.file.Path):String={
    val md=java.security.MessageDigest.getInstance("SHA-256");md.digest(Files.readAllBytes(p)).map(b=>f"${b&0xff}%02x").mkString
  }
}
