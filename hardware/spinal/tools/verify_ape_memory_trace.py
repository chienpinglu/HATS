#!/usr/bin/env python3
"""Run and bind an actual APE-application memory trace across L1 RTL points."""
from datetime import datetime, timezone
import hashlib
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from toolchain import java_path

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent.parent


def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):h.update(chunk)
    return h.hexdigest()


def require(value,message):
    if not value:raise ValueError(message)


def validate_report(report):
    require(report.get("status")=="passed_trace_design_points" and report.get("S04_complete") is False,
            "APE trace report status/scope mismatch")
    rows=report.get("runs",[])
    require([(r.get("sets"),r.get("mshrs")) for r in rows]==[(8,2),(16,4),(32,8)],
            "APE trace report is missing matched design points")
    digests={r.get("trace_sha256") for r in rows};counts={r.get("application_memory_events") for r in rows}
    require(len(digests)==1 and len(counts)==1 and None not in digests and None not in counts,
            "APE design points did not use the same nonempty trace")
    count=next(iter(counts))
    require(count>0 and all(r.get("accepted")==r.get("completed")==count and
            r.get("final_memory_matches_application") is True and r.get("cycles",0)>0 and
            r.get("lower_accepted")==r.get("lower_completed") and
            len(r.get("generated_rtl_sha256",""))==64 and len(r.get("validation_sha256",""))==64
            for r in rows),"APE trace point lacks traffic, final-state, or generated-RTL witnesses")
    require(bool(report.get("application_gate_sha256")) and report.get("input_sha256") and
            report.get("source_sha256")==report.get("source_sha256_after") and report.get("tools"),
            "APE trace report lacks source/input/tool identity")
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-output",type=Path,
                        default=REPO/"workloads/evidence/S04-APE-APPLICATION-TRACE-DESIGN-POINTS.json")
    parser.add_argument("--use-local-compiled-classpath",action="store_true",
                        help="run the three RTL replays using the existing exported SpinalSim test classpath")
    args=parser.parse_args()
    app=ROOT/"build/ape_app"
    app_gate_path=app/"validation.json"
    app_gate=json.loads(app_gate_path.read_text())
    require(app_gate.get("status")=="passed" and app_gate.get("runs_passed")==144,
            "Current APE application RTL/Spike gate is required")
    require(app_gate.get("source_sha256")==app_gate.get("source_sha256_after"),"APE application sources changed during run")
    trace=app/"r8-bimodal/repo_source_edit-0.arch.jsonl"
    initial=app/"repo_source_edit.bin"
    final=app/"r8-bimodal/repo_source_edit-0.memory.bin"
    app_evidence=app_gate["evidence_sha256"]
    inputs={str(app_gate_path.relative_to(REPO)):sha(app_gate_path)}
    for path in (trace,initial,final):
        app_rel=str(path.relative_to(ROOT));repo_rel=str(path.relative_to(REPO))
        require(app_rel in app_evidence and app_evidence[app_rel]==sha(path),
                f"APE application artifact is not bound by its gate: {app_rel}")
        inputs[repo_rel]=sha(path)
    events=[json.loads(row) for row in trace.read_text().splitlines() if '"kind":"memory"' in row]
    app_row=next(r for r in app_gate["results"] if r["name"]=="repo_source_edit" and
                 r["invocation"]==0 and r["rob_entries"]==8 and r["prediction"]=="bimodal")
    require(len(events)==app_row["memory_requests"],"Trace event count differs from the APE application gate")
    require(len(events)>1000,"Application memory trace is unexpectedly small")
    out=ROOT/"build/s04"/f"ape-trace-{time.time_ns()}";out.mkdir(parents=True)
    source_paths=[ROOT/p for p in (
        "src/main/scala/hats/MemoryHierarchy.scala","src/test/scala/hats/MemoryTraceReplaySim.scala",
        "tools/verify_ape_memory_trace.py","tools/toolchain.py","tools/sbtw","build.sbt",
        "project/build.properties","project/repositories")]
    source_hashes={str(p.relative_to(ROOT)):sha(p) for p in source_paths}
    env=dict(os.environ);env["PATH"]="/opt/homebrew/bin:"+env.get("PATH","")
    tools={}
    for name,command in (("java",[java_path(),"-version"]),("verilator",["verilator","--version"]),
                         ("cxx",["c++","--version"]),("make",["make","--version"])):
        exe=Path(subprocess.check_output(["which",command[0]],env=env,text=True).strip()).resolve()
        v=subprocess.run(command,env=env,text=True,capture_output=True,check=True)
        tools[name]={"path":str(exe),"sha256":sha(exe),"version":(v.stdout+v.stderr).strip()}
    configs=((8,2),(16,4),(32,8));commands=["Test / compile"]
    for sets,mshrs in configs:
        dest=out/f"s{sets}-m{mshrs}"
        commands.append(f"Test / runMain hats.MemoryTraceReplaySim {trace.relative_to(ROOT)} {initial.relative_to(ROOT)} "
                        f"{final.relative_to(ROOT)} {dest.relative_to(ROOT)} {sets}:{mshrs}")
    gate={"schema":1,"issue":5,"status":"running","S04_complete":False,
          "claim_class":"actual_ApeCore_application_memory_trace_replayed_through_NonBlockingL1_RTL",
          "application_gate_sha256":sha(app_gate_path),"input_sha256":inputs,"source_sha256":source_hashes,
          "tools":tools,"command":commands,"service_model":"fixed ready pattern and 7+(lower ordinal mod 5) response-cycle delay",
          "started_utc":datetime.now(timezone.utc).isoformat(),"runs":[]}
    report_path=out/"gate.json"
    def save():report_path.write_text(json.dumps(gate,indent=2)+"\n")
    save()
    try:
        with (out/"run.log").open("w") as log:
            if not args.use_local_compiled_classpath:
                subprocess.run(["bash","tools/sbtw",*commands],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                               check=True,timeout=900)
            else:
                classpath_export=ROOT/"target/streams/test/fullClasspath/_global/streams/export"
                require(classpath_export.is_file(),"sbt test classpath export is missing")
                classpath=classpath_export.read_text().strip()
                require(classpath and all(Path(item).exists() for item in classpath.split(":")),
                        "sbt test classpath export contains missing entries")
                for sets,mshrs in configs:
                    dest=out/f"s{sets}-m{mshrs}"
                    actual=[java_path(),"-Xmx3G","-XX:ActiveProcessorCount=4","-cp",classpath,
                            "hats.MemoryTraceReplaySim",str(trace),str(initial),str(final),str(dest),f"{sets}:{mshrs}"]
                    log.write("Direct Java main: "+" ".join(actual)+"\n");log.flush()
                    subprocess.run(actual,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=1200)
        for sets,mshrs in configs:
            run_dir=out/f"s{sets}-m{mshrs}"
            validation=run_dir/"validation.json"
            rtl=run_dir/"rtl/tmp/job_1/NonBlockingL1.v"
            require(rtl.is_file(),f"generated L1 RTL is missing for {sets}/{mshrs}")
            evidence=json.loads(validation.read_text())
            require(evidence.get("status")=="passed" and (evidence.get("sets"),evidence.get("mshrs"))==(sets,mshrs),
                    "L1 trace replay failed or used the wrong point")
            require(evidence.get("trace_sha256")==inputs[str(trace.relative_to(REPO))] and
                    evidence.get("application_memory_events")==len(events) and
                    evidence.get("final_memory_matches_application") is True and
                    evidence.get("accepted")==evidence.get("completed")==len(events),
                    "Trace, architectural-event count, or final-state binding mismatch")
            gate["runs"].append({**evidence,"validation_path":str(validation.relative_to(REPO)),
                                  "validation_sha256":sha(validation),
                                  "generated_rtl_sha256":sha(rtl),
                                  "generated_rtl":str(rtl.relative_to(REPO))})
        require(len({run["trace_sha256"] for run in gate["runs"]})==1,"Design points used different APE traces")
        require(len({run["application_memory_events"] for run in gate["runs"]})==1,"Design points executed different event counts")
        require(gate["source_sha256"]=={str(p.relative_to(ROOT)):sha(p) for p in source_paths},
                "Trace-replay source changed during the design-point run")
        for tool in tools.values():require(sha(Path(tool["path"]))==tool["sha256"],"Tool changed during design-point run")
        require({str(p.relative_to(ROOT)):sha(p) for p in source_paths}==source_hashes,
                "Trace-replay source changed during the design-point run")
        input_now={str(app_gate_path.relative_to(REPO)):sha(app_gate_path),
                   **{str(p.relative_to(REPO)):sha(p) for p in (trace,initial,final)}}
        require(input_now==inputs,"APE application inputs changed during the design-point run")
        gate["status"]="passed_trace_design_points"
    except Exception as error:
        gate["status"]="failed";gate["error"]=str(error)
        raise
    finally:
        gate["source_sha256_after"]={str(p.relative_to(ROOT)):sha(p) for p in source_paths}
        gate["run_log_sha256"]=sha(out/"run.log") if (out/"run.log").is_file() else None
        gate["finished_utc"]=datetime.now(timezone.utc).isoformat();save()
    validate_report(gate)
    gate["build_gate_path"]=str(report_path.relative_to(REPO))
    save()
    evidence={**gate,
              "build_gate_sha256":sha(report_path)}
    args.evidence_output.parent.mkdir(parents=True,exist_ok=True)
    args.evidence_output.write_text(json.dumps(evidence,indent=2)+"\n")
    print(f"Verified APE application trace L1 design points: {report_path}")


if __name__=="__main__":main()
