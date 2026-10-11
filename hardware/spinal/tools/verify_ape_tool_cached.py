#!/usr/bin/env python3
"""Run a source-bound Tree-sitter target case through actual APE I/D-L1 RTL."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from toolchain import java_path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from compare_ape_spike import compare, read_trace


def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1<<20),b""):h.update(block)
    return h.hexdigest()


def require(value,message):
    if not value:raise ValueError(message)


def final_memory(app,case,spike_trace):
    image=bytearray((app/"data.bin").read_bytes())
    require(len(image)==0x1000000,"Tree-sitter data image size mismatch")
    for name,address in (("args.bin",0x180000),("old.bin",0x181000),("new.bin",0x1c1000)):
        value=(app/case/name).read_bytes();start=address-0x100000;image[start:start+len(value)]=value
    image[0x210000-0x100000:0x300000-0x100000]=b"\xcc"*(0xf0000)
    trace=read_trace(spike_trace)
    for event in trace:
        if event["kind"]!="memory" or not event["write"]:continue
        require(not event["error"],"valid Tree-sitter Spike run contains a faulting store")
        address=int(event["address"]);size=event["bytes"];start=address-0x100000
        require(address>=0x100000 and start+size<=len(image),"Spike store escaped Tree-sitter RAM")
        image[start:start+size]=int(event["data"]).to_bytes(size,"little")
    return image


def trace_snapshot(app,case,setup_trace):
    """Recover RAM at a Spike-authored parser-entry marker."""
    image=bytearray((app/"data.bin").read_bytes())
    for name,address in (("args.bin",0x180000),("old.bin",0x181000),("new.bin",0x1c1000)):
        value=(app/case/name).read_bytes();start=address-0x100000;image[start:start+len(value)]=value
    for event in map(json.loads,Path(setup_trace).read_text().splitlines()):
        if event.get("kind")=="parser_start": return image
        if event.get("kind")!="memory" or not event["write"]: continue
        address=int(event["address"]);size=event["bytes"];start=address-0x100000
        require(not event["error"] and address>=0x100000 and start+size<=len(image),
          "Spike setup trace contains a faulting/out-of-RAM write")
        image[start:start+size]=int(event["data"]).to_bytes(size,"little")
    raise ValueError("Spike setup trace has no parser-start marker")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application-dir",required=True,type=Path,
      help="parser directory from a current-source S02 Tree-sitter verify_rtl.py run")
    parser.add_argument("--case",default="scalars-incremental")
    parser.add_argument("--sets",type=int,default=64)
    parser.add_argument("--mshrs",type=int,default=4)
    parser.add_argument("--warm-start-image",type=Path,
      help="Spike-derived RAM exactly at parser entry; defaults to warm-start-memory.bin beside the parser image")
    parser.add_argument("--evidence-output",type=Path,default=REPO/"workloads/evidence/S04-APE-TOOL-CACHED-INCREMENT.json")
    args=parser.parse_args();app=args.application_dir.resolve();case=args.case
    case_dir=app/case;parent=app.parent;rtl_gate=parent/"rtl-validation.json";reference_gate=parent/"validation.json"
    require(rtl_gate.is_file() and reference_gate.is_file(),"Current-source Tree-sitter reference gates are required")
    direct=json.loads(rtl_gate.read_text());reference=json.loads(reference_gate.read_text())
    require(direct.get("status")=="passed" and direct.get("ape_rtl_execution") is True,
      "Tree-sitter direct APE gate is not a pass")
    require((case,"0") in {(r.get("case"),str(r.get("invocation"))) for r in direct.get("comparisons",[])},
      "Direct APE gate does not include the selected invocation")
    require(reference.get("status")=="passed" and direct.get("reference_report_sha256")==sha(reference_gate),
      "Tree-sitter Spike reference report is stale or failed")
    reference_sources=reference.get("source_sha256",{})
    require(bool(reference_sources),"Tree-sitter Spike gate lacks its source manifest")
    for name,digest in reference_sources.items():
        source=(REPO/name).resolve()
        require(source.is_relative_to(REPO) and source.is_file() and sha(source)==digest,
          "Tree-sitter reference source is stale: "+name)
    setup_gate=app/"setup-validation.json"
    setup_manifest=json.loads(setup_gate.read_text()) if setup_gate.is_file() else {}
    setup_name=case+"-setup"
    setup_trace=app/setup_name/"trace.jsonl"
    require(setup_manifest.get("status")=="passed" and
      setup_manifest.get("snapshots",{}).get(case,{}).get("status")=="passed",
      "Spike parser-entry snapshot gate is missing")
    spike_trace=case_dir/"trace.jsonl"
    direct_trace=app/"rtl-r8-bimodal"/f"{case}-0.trace.jsonl"
    files=[rtl_gate,reference_gate,app/"code.bin",app/"data.bin",app/"runtime.properties",
      case_dir/"args.bin",case_dir/"old.bin",case_dir/"new.bin",case_dir/"result.bin",spike_trace,setup_trace,direct_trace]
    require(all(p.is_file() for p in files),"A required source-bound Tree-sitter artifact is missing")
    require(compare(read_trace(direct_trace),read_trace(spike_trace))["status"]=="matched",
      "Current direct APE Tree-sitter trace does not match Spike")
    expected=final_memory(app,case,spike_trace)
    warm_source=(args.warm_start_image or (app/f"warm-start-memory-{case}.bin")).resolve()
    warm=bytearray(warm_source.read_bytes())
    require(len(warm)==0x1000000,"Warm-start RAM image must be exactly 16 MiB")
    require(warm==trace_snapshot(app,case,setup_trace),"Warm-start image differs from Spike's setup prefix")
    # Match the direct-run service's output-region poison so untouched bytes
    # remain observable and the full-RAM oracle has the same initial state.
    warm[0x210000-0x100000:0x300000-0x100000]=b"\xcc"*0xf0000
    require(expected[0x210000-0x100000:0x300000-0x100000]==(case_dir/"result.bin").read_bytes(),
      "Spike-reconstructed final output region differs from the independent Tree-sitter result image")
    out=ROOT/"build/s04"/f"cached-tool-{time.time_ns()}";out.mkdir(parents=True)
    expected_path=out/"expected-memory.bin";expected_path.write_bytes(expected)
    warm_path=out/"warm-start-memory.bin";warm_path.write_bytes(warm)
    warm_code=bytearray((app/"code.bin").read_bytes())
    # Spike's setup trace proves BSS has already been cleared. Replace only the
    # startup loop's taken/not-taken test with an unconditional local jump over
    # that redundant clear loop; all other instructions, including stack setup
    # and call into ape_main, execute on APE RTL from PC zero.
    original=int.from_bytes(warm_code[0x1c:0x20],"little")
    require(original==0x0062f863,"Tree-sitter startup BSS-loop instruction changed")
    warm_code[0x1c:0x20]=(0x0100006f).to_bytes(4,"little")
    warm_code_path=out/"warm-start-code.bin";warm_code_path.write_bytes(warm_code)
    input_hashes={str(p.relative_to(REPO)):sha(p) for p in files}
    input_hashes[str(expected_path.relative_to(REPO))]=sha(expected_path)
    input_hashes[str(warm_path.relative_to(REPO))]=sha(warm_path)
    input_hashes[str(warm_code_path.relative_to(REPO))]=sha(warm_code_path)
    sources=sorted(set((ROOT/"src/main/scala/hats").glob("*.scala"))|
      set((ROOT/"src/test/scala/hats").glob("*.scala"))|
      {ROOT/p for p in ("tools/verify_ape_tool_cached.py","tools/compare_ape_spike.py","tools/toolchain.py",
        "tools/sbtw","build.sbt","project/build.properties","project/repositories")})
    source_hashes={str(p.relative_to(ROOT)):sha(p) for p in sources}
    env=dict(os.environ);env["PATH"]="/opt/homebrew/bin:"+env.get("PATH","")
    tools={}
    for name,cmd in (("java",[java_path(),"-version"]),("verilator",["verilator","--version"]),
      ("cxx",["c++","--version"]),("make",["make","--version"])):
        executable=Path(subprocess.check_output(["which",cmd[0]],env=env,text=True).strip()).resolve()
        result=subprocess.run(cmd,env=env,text=True,capture_output=True,check=True)
        tools[name]={"path":str(executable),"sha256":sha(executable),"version":(result.stdout+result.stderr).strip()}
    classpath_export=ROOT/"target/streams/test/fullClasspath/_global/streams/export"
    class_file=ROOT/"target/scala-2.13/test-classes/hats/ApeCachedToolSim$.class"
    core_file=ROOT/"target/scala-2.13/classes/hats/ApeCore.class"
    require(classpath_export.is_file() and class_file.is_file() and core_file.is_file() and
      class_file.stat().st_mtime >= (ROOT/"src/test/scala/hats/ApeCachedToolSim.scala").stat().st_mtime and
      core_file.stat().st_mtime >= (ROOT/"src/main/scala/hats/ApeCore.scala").stat().st_mtime,
      "Fresh compiled cached-tool test classes are unavailable; compile outside the restricted sbt server")
    classpath=classpath_export.read_text().strip()
    require(bool(classpath),"sbt Test classpath export is empty")
    command=[java_path(),"-cp","<sbt-Test-fullClasspath>","hats.ApeCachedToolSim",str(app),str(out),
      str(args.sets),str(args.mshrs),case,str(warm_path),str(warm_code_path)]
    report={"schema":1,"issue":5,"status":"running","S04_complete":False,
      "claim_class":"real_Tree_sitter_tool_on_APE_LSQ_I_D_L1_RTL",
      "application_dir":str(app.relative_to(REPO)),"case":case,"sets":args.sets,"mshrs":args.mshrs,
      "direct_gate_sha256":sha(rtl_gate),"spike_reference_sha256":sha(spike_trace),
      "reference_source_sha256":reference_sources,
      "source_sha256":source_hashes,"input_sha256":input_hashes,"tools":tools,"command":command,
      "external_service_model":"behavioral variable-latency line memory; not calibrated HBM/LPDDR",
      "started_utc":datetime.now(timezone.utc).isoformat()}
    gate=out/"gate.json"
    def save():gate.write_text(json.dumps(report,indent=2)+"\n")
    save()
    try:
        with (out/"run.log").open("w") as log:
            subprocess.run([java_path(),"-cp",classpath,*command[3:]],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1800)
        result=json.loads((out/"validation.json").read_text())
        require(result.get("status")=="passed" and result.get("line_requests")==result.get("line_completions")>0,
          "Cached Tree-sitter RTL result failed its drain/accounting checks")
        actual=read_trace(out/"cached.trace.jsonl");spike=read_trace(spike_trace)
        start=next((i for i,e in enumerate(spike) if e["kind"]=="retire" and e["pc"]=="52"),None)
        require(start is not None,"Spike reference has no parser-entry retirement")
        expected_suffix=spike[start:]
        actual_start=next((i for i,e in enumerate(actual) if e["kind"]=="retire" and e["pc"]=="52"),None)
        require(actual_start is not None,"Cached APE trace has no parser-entry retirement")
        comparison=compare(actual[actual_start:],expected_suffix)
        require(comparison["status"]=="matched","Cached APE Tree-sitter architectural trace differs from Spike")
        require((out/"final-memory.bin").read_bytes()==expected,"Cached APE final backing memory differs from Spike-reconstructed full RAM")
        require(source_hashes=={str(p.relative_to(ROOT)):sha(p) for p in sources},"RTL or gate source changed during cached Tree-sitter run")
        require(input_hashes=={str(p.relative_to(REPO)):sha(p) for p in files}|{str(expected_path.relative_to(REPO)):sha(expected_path),
          str(warm_path.relative_to(REPO)):sha(warm_path),str(warm_code_path.relative_to(REPO)):sha(warm_code_path)},
          "Tree-sitter or reconstructed oracle input changed during run")
        for t in tools.values():require(sha(Path(t["path"]))==t["sha256"],"Tool changed during cached Tree-sitter run")
        rtl=list((out/"rtl").rglob("ApeCachedDataTile.v"))
        require(bool(rtl),"Generated cached APE I/D-L1 RTL is missing")
        report.update(status="passed_cached_tool",result=result,architectural_comparison=comparison,
          generated_rtl_sha256={str(p.relative_to(out)):sha(p) for p in rtl},
          cached_trace_sha256=sha(out/"cached.trace.jsonl"),final_memory_sha256=sha(out/"final-memory.bin"),
          run_log_sha256=sha(out/"run.log"),limits=["Parser-phase warm-start profile skips the already Spike-validated BSS-clear loop; cold-start direct APE remains separately checked",
            "One Tree-sitter case/invocation; broaden the workload matrix before S04 closure",
            "External memory is behavioral; this is not measured or calibrated HBM/LPDDR bandwidth"])
    except Exception as error:
        report.update(status="failed",error=str(error));raise
    finally:
        report["source_sha256_after"]={str(p.relative_to(ROOT)):sha(p) for p in sources}
        report["finished_utc"]=datetime.now(timezone.utc).isoformat();save()
    report["gate_path"]=str(gate.relative_to(REPO));save()
    evidence={**report,"gate_sha256":sha(gate)}
    args.evidence_output.parent.mkdir(parents=True,exist_ok=True)
    args.evidence_output.write_text(json.dumps(evidence,indent=2)+"\n")
    print(f"Source-bound cached Tree-sitter pass: {gate}")


if __name__=="__main__":main()
