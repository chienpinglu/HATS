#!/usr/bin/env python3
"""Source-bound owner-controller RTL gate and dual-engine top elaboration."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from toolchain import java_path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as f:
        value = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            value.update(chunk)
        return value.hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ppe-application-dir",required=True,type=Path,
      help="source-bound delimiter_256_g0 case directory from the passing PPE I/D-L1 gate")
    args=parser.parse_args()
    ppe_app_dir=args.ppe_application_dir.resolve()
    ppe_build_dir=ppe_app_dir.parents[1]
    ppe_gate_path=ppe_build_dir/"gate.json"
    if not ppe_gate_path.is_file():raise ValueError("PPE application case has no source-bound parent gate")
    ppe_gate=json.loads(ppe_gate_path.read_text())
    if (ppe_gate.get("status")!="passed_partial_integration" or not ppe_gate.get("instruction_cache") or
        ppe_gate.get("source_sha256")!=ppe_gate.get("source_sha256_after") or
        ppe_gate.get("delimiter_application",{}).get("status")!="passed" or
        ppe_gate.get("delimiter_application",{}).get("groups_completed")!=32):
        raise ValueError("Requires a passing, source-stable PPE I/D-L1 gate with the 32-group delimiter oracle")
    ppe_input_hashes={}
    for name in ("case.properties","code.hex","memory.bin","reference.json"):
        path=ppe_app_dir/name
        relative=str(path.relative_to(ppe_build_dir))
        if not path.is_file() or ppe_gate.get("input_sha256",{}).get(relative)!=digest(path):
            raise ValueError(f"PPE application input is missing or not bound by its parent gate: {relative}")
        ppe_input_hashes[relative]=digest(path)
    ppe_initial=(ppe_app_dir/"memory.bin").read_bytes()
    ppe_expected=bytearray(ppe_initial)
    for offset,value in enumerate(ppe_initial[256:512]):
        ppe_expected[1024+offset]=int(value in b"{}[]:,")
    ppe_expected_sha=hashlib.sha256(ppe_expected).hexdigest()
    delimiter_result=ppe_gate.get("delimiter_application",{})
    if (delimiter_result.get("input_sha256")!=digest(ppe_app_dir/"memory.bin") or
        delimiter_result.get("output_sha256")!=ppe_expected_sha):
        raise ValueError("PPE gate output oracle does not match its bound delimiter input and byte transform")
    out=ROOT/"build/s04"/f"ownership-{time.time_ns()}"; out.mkdir(parents=True)
    sources=sorted(set((ROOT/"src/main/scala/hats").glob("*.scala"))|
                   set((ROOT/"src/test/scala/hats").glob("*.scala"))|
                   {ROOT/p for p in ("tools/verify_ownership.py","tools/toolchain.py","tools/sbtw","build.sbt",
                      "project/build.properties","project/repositories",
                      "formal/OwnershipAssumptions.svfrag","formal/verify_ownership_formal.py")})
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sources}
    env=dict(os.environ);env["PATH"]="/opt/homebrew/bin:"+env.get("PATH","")
    tools={}
    for name,cmd in (("java",[java_path(),"-version"]),("verilator",["verilator","--version"]),
                     ("cxx",["c++","--version"]),("make",["make","--version"])):
        path=Path(subprocess.check_output(["which",cmd[0]],env=env,text=True).strip()).resolve()
        version=subprocess.run(cmd,env=env,text=True,capture_output=True,check=True)
        tools[name]={"path":str(path),"sha256":digest(path),"version":(version.stdout+version.stderr).strip()}
    classpath_export=ROOT/"target/streams/test/fullClasspath/_global/streams/export"
    class_files = [ROOT/"target/scala-2.13/test-classes/hats/MemoryOwnershipControllerSim$.class",
      ROOT/"target/scala-2.13/classes/hats/GenerateApePpeSharedMemory$.class",
      ROOT/"target/scala-2.13/test-classes/hats/ApePpeSharedMemorySim$.class"]
    relevant_sources = [ROOT/"src/test/scala/hats/MemoryOwnershipControllerSim.scala",
      ROOT/"src/main/scala/hats/GenerateApePpeSharedMemory.scala",
      ROOT/"src/test/scala/hats/ApePpeSharedMemorySim.scala"]
    if not classpath_export.is_file() or not all(p.is_file() for p in class_files) or any(
      c.stat().st_mtime < s.stat().st_mtime for c,s in zip(class_files,relevant_sources)):
        raise ValueError("Fresh compiled ownership simulation classes are unavailable; compile outside the restricted sbt server")
    classpath=classpath_export.read_text().strip()
    if not classpath or any(not Path(item).exists() for item in classpath.split(":")):
        raise ValueError("sbt test classpath export contains missing entries")
    java=java_path()
    java_commands=[
      [java,"-Xmx3G","-XX:ActiveProcessorCount=4","-cp","<sbt-test-classpath>",
       "hats.MemoryOwnershipControllerSim",str(out/"controller")],
      [java,"-Xmx3G","-XX:ActiveProcessorCount=4","-cp","<sbt-test-classpath>",
       "hats.GenerateApePpeSharedMemory",str(out/"system-rtl")],
      [java,"-Xmx3G","-XX:ActiveProcessorCount=4","-cp","<sbt-test-classpath>",
       "hats.ApePpeSharedMemorySim",str(out/"dual-engine"),str(ppe_app_dir)]]
    command={"execution":"direct Java using previously compiled current-source test classes",
      "direct_java_mains":java_commands,
      "classpath_export":"target/streams/test/fullClasspath/_global/streams/export"}
    report={"schema":1,"status":"running","issue":5,"S04_complete":False,
      "claim_class":"actual_owner_controller_RTL_and_dual_engine_system_elaboration",
      "source_sha256":hashes,"tools":tools,"command":command,"started_utc":datetime.now(timezone.utc).isoformat(),
      "ppe_application_gate":str(ppe_gate_path.relative_to(ROOT)),"ppe_application_gate_sha256":digest(ppe_gate_path),
      "ppe_application_input_sha256":ppe_input_hashes,
      "limits":["Two engine tasks are submitted by the host in sequence; no CP/task runtime is claimed",
        "Exclusive whole-RAM ownership only; no virtual memory or shared atomic serialization is claimed",
        "PPE device requests use a behavioral service; physical peripheral protocol and system-wide I/O litmus coverage remain open",
        "Assertions and finite RTL protocol simulation are not a formal proof"]}
    path=out/"gate.json"
    def save():path.write_text(json.dumps(report,indent=2)+"\n")
    save();print(f"Owner-controller gate: {path}",flush=True)
    try:
        with (out/"run.log").open("w") as log:
            for java_command in java_commands:
                actual=[item if item!="<sbt-test-classpath>" else classpath for item in java_command]
                log.write("\nDirect Java main: "+" ".join(actual)+"\n");log.flush()
                subprocess.run(actual,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900)
            report["classpath_export_sha256"]=digest(classpath_export)
        evidence=json.loads((out/"controller/validation.json").read_text())
        if evidence["status"]!="passed": raise ValueError("Owner-controller result failed")
        if evidence["accepted"]!=2 or evidence["completed"]!=2 or evidence["rejected"]!=2 or evidence["handoffs"]!=2 or evidence["failed_handoffs"]!=1:
            raise ValueError("Owner-controller accounting mismatch")
        if not list((out/"system-rtl").glob("*.v")):raise ValueError("Dual-engine top did not generate Verilog")
        system=json.loads((out/"dual-engine/validation.json").read_text())
        launch_race=json.loads((out/"dual-engine/launch-race.json").read_text())
        if (system["status"]!="passed" or system["ape_halts"]!=5 or system["ppe_completions"]!=1
            or system["ape_rd3_values"][:4]!=[42,48,48,51] or system.get("ape_atomic_old_values")!=[48]
            or system.get("ppe_atomic_final_value")!="48" or system.get("final_shared_value")!="51"
            or system["ownership_handoffs"]!=4
            or system.get("ppe_application_groups")!=32
            or system.get("ppe_application_faults")!=1
            or system.get("ppe_application_fault_write_attempts",0)<1
            or system.get("ppe_application_fault_output_unchanged") is not True
            or system.get("ppe_application_line_requests",0)<1
            or system.get("ppe_application_architectural_accesses")!=608
            or system.get("ppe_application_matches_independent_memory_oracle") is not True
            or system.get("ppe_application_output_sha256")!=ppe_gate.get("delimiter_application",{}).get("output_sha256")
            or system.get("quiescent_system_resets")!=2 or system.get("value_after_quiescent_reset")!="51"
            or system.get("ppe_application_reset_readback_matches") is not True
            or system.get("ppe_application_reset_readback_value")!=str(int.from_bytes(ppe_initial[0x300:0x308],"little"))
            or system["line_requests"]!=system["line_completions"]
            or system.get("lower_backpressure_cycles",0)<1 or system.get("max_lower_outstanding",0)<4
            or system.get("response_reorders",0)<1
            or system.get("ape_conflict_load_addresses") != [1024,1536,2048,2560]
            or system.get("ape_conflict_line_refills") != [1024,1536,2048,2560]
            or system.get("ape_conflict_set_index") != 0
            or system.get("ape_byte_alias_verified") is not True
            or system.get("ape_partial_storebacking_word") != "10752"
            or system.get("handoffs_requested_with_live_lines")!=1
            or system.get("handoff_drain_wait_cycles",0)<1
            or system.get("ppe_device_requests") != 2 or system.get("ppe_device_completions") != 2
            or system.get("ppe_device_reads") != 1 or system.get("ppe_device_writes") != 1
            or system.get("ppe_device_backpressure_cycles",0)<1
            or system.get("ppe_clean_before_device") is not True
            or system.get("ppe_device_register_value") != "102"):
            raise ValueError("Actual dual-engine shared-memory check failed")
        if (launch_race.get("simultaneous_launch_presentations") != 1
            or launch_race.get("ape_nonowner_stall_cycles",0) < 1
            or launch_race.get("ppe_nonowner_stall_cycles",0) < 1
            or launch_race.get("pending_ape_accepted_after_handoff") is not True
            or launch_race.get("pending_ppe_accepted_after_handoff") is not True):
            raise ValueError(f"Owner-gated ready/valid launch admission failed: {launch_race}")
        if {str(p.relative_to(ROOT)):digest(p) for p in sources}!=hashes:raise ValueError("Source changed during gate")
        for t in tools.values():
            if digest(Path(t["path"]))!=t["sha256"]:raise ValueError("Tool changed during gate")
        generated=list(out.rglob("*.v")); report.update(status="passed_integration",result=evidence,system_result=system,
          generated_rtl_sha256={str(p.relative_to(out)):digest(p) for p in generated},
          simulation_evidence_sha256={str(p.relative_to(out)):digest(p) for p in
            (out/"controller/validation.json",out/"dual-engine/validation.json",out/"dual-engine/launch-race.json")},
          run_log_sha256=digest(out/"run.log"))
    except Exception as error:
        report.update(status="failed",error=str(error));raise
    finally:
        report["source_sha256_after"]={str(p.relative_to(ROOT)):digest(p) for p in sources}
        report["finished_utc"]=datetime.now(timezone.utc).isoformat();save()
    print("Owner transfer and dual-engine top gates passed; Issue #5 remains open",flush=True)


if __name__=="__main__":main()
