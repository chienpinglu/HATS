#!/usr/bin/env python3
"""Source-bound early mapped-area/comb-path study, not placed/routed clock/PPA.

Synthesizes actual SpinalHDL APE variants with a fixed 1024-word FF/mux code
store. ABC checks each extracted combinational network against its mapped
network before estimating delay with a pinned research Liberty library.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from bootstrap_ape_timing import HW, OUT as TOOLS, ABC, LIBRARY, LIBRARY_SHA, LICENSE_SHA, sha, require, source_hashes

REPO = HW.parents[1]
sys.path.insert(0, str(REPO / "workloads/s03"))
from compare import POINTS


def parse_delay(text):
    values = re.findall(r"Delay\s*=\s*([0-9.]+)\s*ps", text)
    require(len(values) == 1 and float(values[0]) > 0, "Expected one positive ABC Liberty delay in ps")
    return float(values[0])


def blif_interface(path):
    lines = path.read_text().replace("\\\n", " ").splitlines()
    ports = {}
    for kind in (".inputs", ".outputs"):
        declarations = [line.split()[1:] for line in lines if line.startswith(kind + " ")]
        require(len(declarations) == 1 and declarations[0] and len(set(declarations[0])) == len(declarations[0]),
                "Ambiguous BLIF interface: " + kind)
        ports[kind] = declarations[0]
    require(not any(line.startswith(".latch ") for line in lines), "Expected combinational network")
    return ports


def final_equivalence(text):
    # The modern engine can be undecided before its automatic legacy fallback
    # proves the reduced miter. Only the final explicit outcome is authoritative.
    outcomes = re.findall(r"Networks are (equivalent|NOT EQUIVALENT|UNDECIDED|undecided)[^\n]*", text)
    return bool(outcomes) and outcomes[-1] == "equivalent"


def validate_aiger_header(path, interface):
    with path.open("rb") as stream:
        header = stream.readline().decode("ascii").split()
    require(header[0] == "aig" and len(header) >= 6, "Missing binary AIG artifact")
    require(int(header[2]) == len(interface[".inputs"]) and int(header[3]) == 0
            and int(header[4]) == len(interface[".outputs"]), "AIG conversion changed interface or sequential scope")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", nargs="+", choices=[p[0] for p in POINTS], default=[p[0] for p in POINTS])
    parser.add_argument("--jobs", type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    require(len(set(args.points)) == len(args.points), "Duplicate design point")
    points = [p for p in POINTS if p[0] in args.points]
    out = HW / "build/ape_technology" / str(time.time_ns())
    out.mkdir(parents=True)
    path = out / "validation.json"
    tool_path = TOOLS / "tools.json"
    tool = json.loads(tool_path.read_text())
    require(tool["status"] == "built" and tool["abc_executable_sha256"] == sha(ABC), "Run bootstrap_ape_timing.py")
    require(tool["abc_source_sha256"] == source_hashes(), "ABC source changed since build")
    require(sha(LIBRARY) == LIBRARY_SHA and sha(LIBRARY.parent / "LICENSE") == LICENSE_SHA, "Library lock mismatch")
    gates = {}
    for name, expected in (("ape_semantics", "passed"), ("ape_multi", "passed_with_profile_differences")):
        gp = HW / "build" / name / "gate.json"
        gate = json.loads(gp.read_text())
        require(gate["status"] == expected and gate["source_sha256"] == gate["source_sha256_after"], "Missing stable component/candidate gate")
        require(all(sha(HW / n) == h for n, h in gate["source_sha256"].items()), "Stale source gate: " + name)
        snapshot = out / (name + "-gate.json")
        snapshot.write_bytes(gp.read_bytes())
        gates[str(snapshot.relative_to(REPO))] = sha(snapshot)
    source_paths = list((HW / "src").rglob("Ape*.scala"))
    source_paths += [HW / p for p in ("build.sbt", "project/build.properties", "project/repositories", "tools/sbtw", "tools/toolchain.py",
                                    "tools/probe_ape_technology.py", "tools/bootstrap_ape_timing.py", "tools/test_ape_technology.py")]
    source_paths += [REPO / "workloads/s03/compare.py"]
    sources = {str(p.relative_to(REPO)): sha(p) for p in source_paths}
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
    env["YOWASP_CACHE_DIR"] = str(HW / ".tools/ape-formal/cache")
    yosys = HW / ".tools/ape-formal/bin/yowasp-yosys"
    report = {"schema": 1, "status": "running", "issue": 4, "S03_complete": False,
              "claim_class": "early_Liberty_mapped_area_and_combinational_boundary_delay",
              "started_utc": datetime.now(timezone.utc).isoformat(), "source_sha256": sources,
              "tool_manifest": tool, "tool_manifest_sha256": sha(tool_path), "gate_snapshots_sha256": gates,
              "yosys": subprocess.check_output([str(yosys), "-V"], env=env, text=True).strip(),
              "yosys_wasm_sha256": sha(next((HW / ".tools/ape-formal/lib").glob("python*/site-packages/yowasp_yosys/yosys.wasm"))),
              "points": points, "fixed": {"program_words": 1024, "checkpoints": 4, "execution_stages": 2,
                                           "generation_bits": 2, "dispatch_width": 1, "writeback_width": 1, "retire_width": 1},
              "constraints": {"library": "NangateOpenCellLibrary_typical", "library_sha256": LIBRARY_SHA,
                              "mapping_delay_target_ps": 1000, "boundary_driver": "BUF_X1", "boundary_load_fF": 5,
                              "clock_constraints": None, "wire_model": "no extracted parasitics; library wire-load model if present",
                              "memory": "All memories mapped to FF/mux logic, including code and physical registers",
                              "observation": "All original core trace/counter outputs retained"},
              "limits": ["Non-manufacturable generic research library; no process or foundry commitment",
                         "ABC combinational-boundary delay is not a setup/hold STA report or achievable clock period",
                         "DFF clock-to-Q, setup/hold, clock-tree skew, placement/routing, PVT closure and SRAM macros not modeled",
                         "1024-word probe differs in code-memory capacity from the 65536-word real-tool design",
                         "Mapped cell area includes FF code memory and debug outputs; not die area or power/energy",
                         "Combinational equivalence is not whole-core sequential equivalence or instruction correctness",
                         "ROB entries also size fused reservation rows; independent queue sizing is not implemented"]}

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    def run(command, directory, name, timeout=900):
        with (directory / (name + ".log")).open("w") as log:
            subprocess.run(command, cwd=directory, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=timeout)
        return (directory / (name + ".log")).read_text()

    def elaborate(point):
        label, rob, prf, width, prediction, predictor = point
        dest = out / label
        dest.mkdir()
        command = ["bash", str(HW / "tools/sbtw"), "compile",
                   f"runMain hats.ApeDesignPointGenerate {dest / 'rtl'} {rob} {prf} {width} {prediction} {predictor} 1024 4"]
        # sbt working directory is the project, not the generated artifact directory.
        for attempt in range(3):
            log_path = dest / f"elaboration-{attempt}.log"
            with log_path.open("w") as log:
                result = subprocess.run(command, cwd=HW, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=240)
            if result.returncode == 0:
                require((dest / "rtl/ApeCore.v").is_file(), "Elaboration produced no core")
                return
            text = log_path.read_text()
            # Retry only the known local boot-socket race with another sbt job;
            # Scala/Spinal/RTL failures remain immediate errors, not hidden retries.
            require("BootServerSocket" in text and "Address already in use" in text and attempt < 2,
                    "Elaboration failed; inspect " + str(log_path))
            time.sleep(5)

    def study(point):
        label, rob, prf, width, prediction, predictor = point
        dest = out / label
        (dest / "abc.constr").write_text("set_driving_cell BUF_X1\nset_load 5\n")
        script = (f"read_verilog {dest / 'rtl/ApeCore.v'}; synth -top ApeCore -flatten -noabc; "
                  f"dfflibmap -liberty {LIBRARY}; "
                  f"abc -liberty {LIBRARY} -constr abc.constr -D 1000 -nocleanup -showtmp; clean; "
                  f"tee -o stat.json stat -json -liberty {LIBRARY}; "
                  "write_verilog -noattr mapped.v; write_json mapped.json; "
                  f"read_liberty -lib {LIBRARY}; check -assert")
        (dest / "synthesis.ys").write_text(script + "\n")
        run([str(yosys), "-Q", "-T", "-l", "yosys.log", "-s", "synthesis.ys"], dest, "synthesis-stdout")
        statistics = json.loads((dest / "stat.json").read_text())
        design = statistics["design"]
        require(design["area"] > 0 and design["sequential_area"] > 0 and design["num_memories"] == 0, "Missing mapped logic/storage area")
        unsupported = [n for n in design["num_cells_by_type"] if n.startswith("$") and n != "$scopeinfo"]
        require(not unsupported, "Unmapped synthesis cells: " + str(unsupported))
        networks = sorted(dest.glob("_tmp_yosys-abc-*/output.blif"))
        require(len(networks) == 1, "Expected a single flattened combinational network")
        network = networks[0]
        original = network.with_name("input.blif")
        interface = blif_interface(original)
        require(interface == blif_interface(network), "Positional CEC requires identical ordered PI/PO names")
        conversion = (f"read_lib {LIBRARY}; read_blif {original}; strash; write_aiger before.aig; "
                      f"read_blif {network}; strash; write_aiger after.aig")
        run([str(ABC), "-s", "-c", conversion], dest, "comb-aig-conversion")
        for name in ("before.aig", "after.aig"):
            validate_aiger_header(dest / name, interface)
        ceccmd = "&cec -T 300 -v before.aig after.aig"
        cec = run([str(ABC), "-s", "-c", ceccmd], dest, "comb-equivalence", timeout=900)
        require(final_equivalence(cec), "Mapped combinational equivalence not proven")
        timingcmd = f"read_lib {LIBRARY}; read_blif {network}; read_constr -v abc.constr; stime -p; print_stats"
        timing = run([str(ABC), "-s", "-c", timingcmd], dest, "comb-timing")
        delay = parse_delay(timing)
        row = {"point": point, "generated_rtl_sha256": sha(dest / "rtl/ApeCore.v"), "statistics": statistics,
               "mapped_area_library_units": design["area"], "sequential_area_library_units": design["sequential_area"],
               "mapped_cells": design["num_cells"], "comb_boundary_delay_ps": delay,
               "meets_comb_mapping_target": delay <= 1000,
               "comb_equivalence": "passed", "synthesis_command": script, "abc_aig_conversion_command": conversion,
               "comb_interface": {"inputs": len(interface[".inputs"]), "outputs": len(interface[".outputs"]),
                                  "identical_ordered_names": True, "abstracted_internal_logic": False, "latches": 0},
               "abc_equivalence_command": ceccmd, "abc_timing_command": timingcmd}
        artifacts = [p for p in dest.rglob("*") if p.is_file()]
        row["evidence_sha256"] = {str(p.relative_to(REPO)): sha(p) for p in artifacts}
        (dest / "validation.json").write_text(json.dumps(row, indent=2) + "\n")
        print(f"Mapped {label}: area {design['area']}, comb boundary {delay} ps; equivalence passed; not achieved clock", flush=True)
        return row

    save()
    print("Early technology study: " + str(path), flush=True)
    try:
        # Tool-path controls, not a substitute for any actual-core proof.
        controls = out / "proof-controls"
        controls.mkdir()
        (controls / "and.blif").write_text(".model and_gate\n.inputs a b\n.outputs q\n.names a b q\n11 1\n.end\n")
        (controls / "or.blif").write_text(".model or_gate\n.inputs a b\n.outputs q\n.names a b q\n1- 1\n-1 1\n.end\n")
        run([str(ABC), "-s", "-c", "read_blif and.blif; strash; write_aiger and.aig; read_blif or.blif; strash; write_aiger or.aig"],
            controls, "conversion")
        positive = run([str(ABC), "-s", "-c", "&cec and.aig and.aig"], controls, "positive")
        negative = run([str(ABC), "-s", "-c", "&cec and.aig or.aig"], controls, "negative")
        require(final_equivalence(positive) and not final_equivalence(negative) and "Networks are NOT EQUIVALENT" in negative,
                "Equivalence tool-path controls failed")
        report["proof_controls"] = {"positive": "equivalent", "negative": "not_equivalent",
                                    "scope": "Toy solver-path controls, not a mutated-core coverage score"}
        report["control_artifacts_sha256"] = {str(p.relative_to(REPO)): sha(p) for p in controls.iterdir() if p.is_file()}
        save()
        # Generate serially before starting independent synthesis workers. Running
        # two sbt boot servers for this project at once can race on its IPC socket.
        for point in points:
            elaborate(point)
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            rows = []
            futures = [pool.submit(study, point) for point in points]
            try:
                for future in as_completed(futures):
                    rows.append(future.result())
                    rows.sort(key=lambda r: points.index(tuple(r["point"])))
                    report["results"] = rows; save()
            except BaseException:
                for future in futures:
                    future.cancel()
                raise
        require(all(sha(REPO / n) == h for n, h in sources.items()), "Source changed during synthesis study")
        require(sha(ABC) == tool["abc_executable_sha256"] and sha(LIBRARY) == LIBRARY_SHA, "Tools changed during study")
        for row in rows:
            require(all(sha(REPO / n) == h for n, h in row["evidence_sha256"].items()), "Physical artifact changed")
        report["status"] = "passed_early_estimate"
    except Exception as error:
        report.update(status="failed_or_inconclusive", error=str(error))
        raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()


if __name__ == "__main__":
    main()
