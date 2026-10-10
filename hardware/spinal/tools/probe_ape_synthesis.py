#!/usr/bin/env python3
"""Technology-independent synthesis probe of an already verified APE artifact.

This diagnostic counts a register/mux implementation, including instruction
storage. It is neither a SRAM implementation nor a timing/area/PPA signoff gate.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

HW = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rob", type=int, choices=(4, 8, 16), default=8)
    parser.add_argument("--prediction", choices=("off", "bimodal"), default="bimodal")
    args = parser.parse_args()
    gate_path = HW / "build/ape/validation.json"
    gate = json.loads(gate_path.read_text())
    if gate["status"] != "passed" or gate["source_sha256"] != gate["source_sha256_after"]:
        raise ValueError("A passing current-source APE gate is required")
    for name, digest in gate["source_sha256"].items():
        if sha(HW / name) != digest: raise ValueError("Stale APE source: " + name)
    relative = f"build/ape/rtl/r{args.rob}-{args.prediction}/ApeCore.v"
    rtl = HW / relative
    if sha(rtl) != gate["artifact_sha256"][relative]: raise ValueError("Stale generated RTL")
    out = HW / "build/ape_synthesis" / f"r{args.rob}-{args.prediction}"
    out.mkdir(parents=True, exist_ok=True)
    gate_snapshot = out / "ape-gate.json"
    gate_snapshot.write_bytes(gate_path.read_bytes())
    yosys = HW / ".tools/ape-formal/bin/yowasp-yosys"
    env = dict(os.environ)
    env["YOWASP_CACHE_DIR"] = str(HW / ".tools/ape-formal/cache")
    report = {"schema": 1, "status": "running", "S03_complete": False,
              "claim_class": "technology_independent_synthesis_diagnostic",
              "started_utc": datetime.now(timezone.utc).isoformat(),
              "source_sha256": {**gate["source_sha256"], "tools/probe_ape_synthesis.py": sha(Path(__file__))},
              "configuration": {"rob_entries": args.rob, "prediction": args.prediction, "program_words": 1024,
                                "physical_registers": 64, "issue_width": 1, "execution_stages": 2, "generation_bits": 2},
              "generated_rtl_sha256": sha(rtl), "ape_gate_sha256": sha(gate_path),
              "constraints": {"flow": "Yosys generic, flattened, memory_map, no ABC",
                              "memory": "All storage mapped to flip-flops/muxes; no SRAM macros",
                              "clock_target_ns": None, "cell_library": None, "interconnect_model": None},
              "limits": ["Diagnostic only; does not justify a final performance-core design point",
                         "Longest topological path counts generic cells, not propagation delay or clock frequency",
                         "Includes 1024-word instruction storage and debug observation logic; not the large-tool memory capacity",
                         "Not a technology-mapped area, placed/routed implementation, SRAM integration or energy estimate"]}

    def save():
        (out / "validation.json").write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        report["yosys"] = subprocess.check_output([str(yosys), "-V"], env=env, text=True).strip()
        script = (f"read_verilog {relative}; synth -top ApeCore -flatten -noabc; check -assert; "
                  f"tee -o {out.relative_to(HW)}/stat.json stat -json; "
                  "ltp -noff; "
                  f"write_json {out.relative_to(HW)}/netlist.json")
        command = [str(yosys), "-Q", "-T", "-p", script]
        report["command"] = ["yowasp-yosys", "-Q", "-T", "-p", script]; save()
        with (out / "synthesis.log").open("w") as log:
            subprocess.run(command, cwd=HW, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=600)
        text = (out / "synthesis.log").read_text()
        paths = re.findall(r"longest topological path.*?length[= :]\s*(\d+)", text, re.I)
        # Preserve the original log even when a different Yosys version changes
        # diagnostic wording; a missing parsed count is not fabricated as zero.
        report["longest_path_generic_cells"] = max(map(int, paths)) if paths else None
        report["statistics"] = json.loads((out / "stat.json").read_text())
        report["evidence_sha256"] = {str(p.relative_to(HW)): sha(p) for p in
                                      (rtl, gate_snapshot, out / "synthesis.log", out / "stat.json", out / "netlist.json")}
        for name, digest in report["source_sha256"].items():
            if sha(HW / name) != digest: raise ValueError("Source changed during synthesis: " + name)
        if sha(gate_path) != report["ape_gate_sha256"]: raise ValueError("APE gate changed during synthesis")
        report["status"] = "passed_diagnostic"
    except Exception as error:
        report.update(status="failed_or_inconclusive", error=str(error)); raise
    finally:
        report["finished_utc"] = datetime.now(timezone.utc).isoformat(); save()
    print("Generic synthesis diagnostic complete: " + str(out / "validation.json"))


if __name__ == "__main__":
    main()
