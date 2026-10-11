package hats

import spinal.core._
import spinal.core.sim._
import java.nio.file.{Files, Paths}
import java.nio.charset.StandardCharsets
import java.security.MessageDigest
import scala.collection.mutable
import scala.util.Random

/** Run the selected Tree-sitter tool image through real APE I/D-L1 + LSQ RTL.
  * Both the external line service and backing RAM are testbench models.
  */
object ApeCachedToolSim extends App {
  require(args.length == 7, "parser-folder output-directory sets mshrs case-name warm-start-image warm-start-code")
  val root=Paths.get(args(0));val out=Paths.get(args(1));val sets=args(2).toInt;val mshrs=args(3).toInt;val caseName=args(4)
  val caseDir=root.resolve(caseName);val invocation=0;val warmPath=Paths.get(args(5));val codePath=Paths.get(args(6))
  Files.createDirectories(out)
  def read(name:String)=Files.readAllBytes(root.resolve(name))
  val code=Files.readAllBytes(codePath);val data=read("data.bin");val properties=Files.readAllLines(root.resolve("runtime.properties")).toArray.toVector
    .map(_.toString.split("=",2)).map(p=>p(0)->p(1).toLong).toMap
  require(code.length==0x40000 && data.length==0x1000000 && caseDir.resolve("trace.jsonl").toFile.isFile)
  val m=MemoryHierarchyConfig(sets=sets,lineBytes=32,mshrs=mshrs,epochBits=4)
  val config=ApeConfig(robEntries=8,programWords=65536,prediction=true,physicalRegisters=48,
    memoryHierarchy=Some(m),instructionCache=true)
  val compiled=SimConfig.withVerilator.addSimulatorFlag("-MAKEFLAGS -j1").addSimulatorFlag("-CFLAGS -DWData=EData")
    .workspacePath(out.resolve("rtl").toString).compile(new ApeCachedDataTile(m,config,instructionCache=true))
  compiled.doSim(s"$caseName-$invocation",seed=0x5e04){dut=>
    def edge():Unit={dut.clockDomain.risingEdge();sleep(5);dut.clockDomain.fallingEdge();sleep(5)}
    case class Request(source:Int,slot:Int,generation:Int,address:Int,write:Boolean,data:Vector[BigInt],sequence:Int)
    case class Pending(request:Request,due:Int)
    val memory=Files.readAllBytes(warmPath)
    require(memory.length==data.length,"warm-start RAM image size mismatch")
    def overlay(file:String,address:Int):Unit={val bytes=Files.readAllBytes(caseDir.resolve(file));System.arraycopy(bytes,0,memory,address-0x100000,bytes.length)}
    overlay("args.bin",0x180000);overlay("old.bin",0x181000);overlay("new.bin",0x1c1000)
    // The warm-start image is Spike-derived; the output poison mirrors the
    // independent direct-run harness so untouched result bytes are observable.
    val expected=Files.readAllBytes(out.resolve("expected-memory.bin"))
    val expectedResult=Files.readAllBytes(caseDir.resolve("result.bin"))
    require(expected.length==memory.length && expectedResult.length==0xf0000)
    val pending=mutable.ArrayBuffer.empty[Pending];val rng=new Random(0x5e04)
    val trace=Files.newBufferedWriter(out.resolve("cached.trace.jsonl"),StandardCharsets.UTF_8)
    var sequence=0;var cycle=0;var accepted=0;var completed=0;var reordered=0;var maxOutstanding=0;var retiredCount=0
    var maxCacheOutstanding=0;var maxFabricOutstanding=0;var halted=false;var flushing=false;var flushed=false;var lastPc=BigInt(0)
    var held:Option[Request]=None
    dut.clockDomain.clockSim #= false;dut.clockDomain.assertReset()
    dut.io.program.valid #= false;dut.io.program.index #= 0;dut.io.program.instruction #= 0
    dut.io.launch.valid #= false;dut.io.launch.pc #= 0;dut.io.launch.argument #= 0x180000
    dut.io.launch.base #= 0x100000;dut.io.launch.limit #= 0x1100000;dut.io.launch.writable #= true
    dut.io.halt.ready #= false;dut.io.lower.ready #= false
    dut.io.reply.valid #= false;dut.io.reply.slot #= 0;dut.io.reply.generation #= 0;dut.io.reply.write #= false
    dut.io.reply.data.foreach(_ #= 0);dut.io.reply.error #= false;dut.io.replySource #= 0
    dut.io.flush.valid #= false;dut.io.flush.payload #= false;dut.io.flushed.ready #= true
    dut.io.deviceResponse.valid #= false;dut.io.deviceResponse.id #= 0;dut.io.deviceResponse.epoch #= 0
    dut.io.deviceResponse.data #= 0;dut.io.deviceResponse.error #= false
    for(_<-0 until 4)edge();dut.clockDomain.deassertReset();edge()
    // The instruction-cache profile fetches the ELF image only from the lower
    // service; the unused programming Flow is deliberately left inactive.
    dut.io.program.valid #= false;dut.io.launch.valid #= true;sleep(1);assert(dut.io.launch.ready.toBoolean);edge();dut.io.launch.valid #= false
    val maxCycles=30000000
    while(!flushed && cycle<maxCycles){
      dut.io.lower.ready #= (cycle%5>=2 && rng.nextInt(4)!=0)
      val due=pending.indices.filter(i=>pending(i).due<=cycle).lastOption
      dut.io.reply.valid #= due.nonEmpty
      due.foreach(i=>{
        val r=pending(i).request;dut.io.replySource #= r.source;dut.io.reply.slot #= r.slot
        dut.io.reply.generation #= r.generation;dut.io.reply.write #= r.write;dut.io.reply.error #= false
        for(w<-0 until m.words){
          val base=r.address+w*8
          val v=(0 until 8).foldLeft(BigInt(0)){(a,b)=>
            val byte=if(r.source==0){if(base+b>=0&&base+b<code.length)code(base+b)&255 else 0}
              else {require(base+b>=0x100000&&base+b<0x1100000);memory(base+b-0x100000)&255}
            a|(BigInt(byte)<<(8*b))
          };dut.io.reply.data(w) #= v
        }
      })
      dut.io.flush.valid #= halted && !flushing;dut.io.halt.ready #= halted
      sleep(1)
      maxCacheOutstanding=maxCacheOutstanding.max(dut.io.cacheOutstanding.toInt)
      maxFabricOutstanding=maxFabricOutstanding.max(dut.io.fabricOutstanding.toInt)
      if(dut.io.memoryRetired.valid.toBoolean){
        val bytes=1<<dut.io.memoryRetired.size.toInt;val mask=(BigInt(1)<<(bytes*8))-1
        trace.write(s"""{"kind":"memory","address":"${dut.io.memoryRetired.address.toBigInt}","bytes":$bytes,"write":${dut.io.memoryRetired.write.toBoolean},"data":"${dut.io.memoryRetired.data.toBigInt&mask}","error":${dut.io.memoryRetired.error.toBoolean}}""");trace.newLine()
      }
      if(dut.io.retired.valid.toBoolean){
        retiredCount+=1
        lastPc=dut.io.retired.pc.toBigInt
        val writes=dut.io.retired.writes.toBoolean;val rd=if(writes)dut.io.retired.rd.toInt else 0
        val value=if(writes)dut.io.retired.value.toBigInt else BigInt(0)
        trace.write(s"""{"kind":"retire","pc":"${dut.io.retired.pc.toBigInt}","instruction":${dut.io.retired.instruction.toLong},"writes":$writes,"rd":$rd,"value":"$value","next":"${dut.io.retiredNext.toBigInt}"}""");trace.newLine()
      }
      if(dut.io.halt.valid.toBoolean && !halted){
        assert(dut.io.halt.cause.toInt==3&&dut.io.halt.pc.toBigInt==properties("exit_pc"))
        assert(pending.isEmpty&&dut.io.outstanding.toInt==0,"Tree-sitter halt before memory drain")
        trace.write(s"""{"kind":"trap","pc":"${dut.io.halt.pc.toBigInt}","cause":3,"value":"${dut.io.halt.value.toBigInt}"}""");trace.newLine();halted=true
      }
      if(dut.io.flush.valid.toBoolean&&dut.io.flush.ready.toBoolean)flushing=true
      if(dut.io.flushed.valid.toBoolean){
        assert(!dut.io.flushed.payload.toBoolean&&dut.io.clean.toBoolean,"APE cache clean failed")
        if(!memory.sameElements(expected))Files.write(out.resolve("failure-memory.bin"),memory)
        assert(memory.sameElements(expected),"post-clean full backing RAM differs from independently reconstructed Spike final state")
        assert(memory.slice(0x210000-0x100000,0x300000-0x100000).sameElements(expectedResult),"post-clean Tree-sitter output differs from independent tool oracle")
        flushed=true
      }
      if(due.nonEmpty&&dut.io.reply.ready.toBoolean){
        val i=due.get;val r=pending.remove(i).request
        if(i!=pending.length)reordered+=1
        if(r.write){require(r.source==1);for(w<-0 until m.words;b<-0 until 8)memory(r.address+w*8+b-0x100000)=((r.data(w)>>(8*b))&255).toByte}
        completed+=1
      }
      val request=if(dut.io.lower.valid.toBoolean)Some(Request(dut.io.lowerSource.toInt,dut.io.lower.slot.toInt,
        dut.io.lower.generation.toInt,dut.io.lower.address.toBigInt.toInt,dut.io.lower.write.toBoolean,
        dut.io.lower.data.map(_.toBigInt).toVector,sequence))else None
      held.foreach(previous=>assert(request.contains(previous.copy(sequence=request.map(_.sequence).getOrElse(previous.sequence))),"line request changed under backpressure"))
      held=if(!dut.io.lower.ready.toBoolean)request else None
      if(request.nonEmpty&&dut.io.lower.ready.toBoolean){
        val r=request.get
        if(r.source==0)assert(!r.write&&r.address>=0&&r.address+m.lineBytes<=code.length,"I-L1 escaped executable image")
        else assert(r.address>=0x100000&&r.address+m.lineBytes<=0x1100000,"D-L1 escaped backing RAM")
        assert(!pending.exists(p=>p.request.source==r.source&&p.request.slot==r.slot),"duplicate live cache-line identity")
        pending+=Pending(r,cycle+5+rng.nextInt(15));sequence+=1;accepted+=1;maxOutstanding=maxOutstanding.max(pending.size)
      }
      edge();cycle+=1
      if(cycle%1000000==0)println(s"Tree-sitter cached progress case=$caseName cycles=$cycle retired=$retiredCount lastPc=${if(retiredCount==0)"none" else lastPc.toString} busy=${dut.io.coreBusy.toBoolean} rob=${dut.io.robOccupancy.toInt} leases=${dut.io.memoryLeasedRows.toBigInt.toString(16)} replay=${dut.io.memoryReplayPending.toBoolean} memoryHead=${dut.io.memoryHead.toInt} outstanding=${dut.io.outstanding.toInt} cache=${dut.io.cacheOutstanding.toInt} fabric=${dut.io.fabricOutstanding.toInt} lowerValid=${dut.io.lower.valid.toBoolean} lines=$accepted/$completed pending=${pending.size}")
    }
    trace.close()
    assert(flushed&&pending.isEmpty&&accepted==completed&&dut.io.idle.toBoolean,
      s"cached Tree-sitter run failed to halt, clean, or drain before $maxCycles cycles: retired=$retiredCount lines=$accepted/$completed pending=${pending.size}")
    Files.write(out.resolve("final-memory.bin"),memory)
    val outputBytes=memory.slice(0x210000-0x100000,0x300000-0x100000)
    val outputHash=MessageDigest.getInstance("SHA-256").digest(outputBytes).map(b=>f"${b&255}%02x").mkString
    Files.writeString(out.resolve("validation.json"),
      s"""{"status":"passed","claim_class":"real_Tree_sitter_tool_on_APE_LSQ_I_D_L1_RTL","case":"$caseName","invocation":$invocation,"cycles":$cycle,"retired":$retiredCount,"line_requests":$accepted,"line_completions":$completed,"output_sha256":"$outputHash","full_final_memory_matches_spike_reconstructed_state":true,"architectural_trace":"cached.trace.jsonl","external_service":"behavioral variable-latency line memory; not calibrated HBM/LPDDR"}\n""")
  }
  ApeSimArtifactCleanup.discardVerilatorBuildTree(out.resolve("rtl"), "ApeCachedDataTile")
}
