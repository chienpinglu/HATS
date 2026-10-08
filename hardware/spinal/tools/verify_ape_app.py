"""Fresh compiled diff -> APE RTL -> independent Spike and edit-script validation."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

import bootstrap_spike as spike
from build_ape_app import ROOT, OUT
from check_ape_diff import check_output
from compare_ape_spike import compare, read_trace
from verify_ape import CONFIGS, hashes
from toolchain import java_path


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    inputs = list((ROOT / "examples/ape_app").glob("*")) + list((ROOT / "src").rglob("Ape*.scala"))
    inputs += list((ROOT / "tools").glob("*ape_app*")) + list((ROOT / "tools").glob("*spike*"))
    inputs += [ROOT / p for p in ("tools/check_ape_diff.py", "tools/assemble_ape.py", "tools/verify_ape.py",
                                  "tools/toolchain.py", "tools/sbtw", "build.sbt", "project/build.properties",
                                  "project/repositories", "examples/ape/kernel.c")]
    initial = hashes(inputs)
    report = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
              "claim": "Bounded line-diff application executed entirely on APE RTL",
              "path": "LP64 ELF -> code/data loader -> runtime startup -> APE RTL -> memory edit script",
              "source_sha256": initial,
              "limits": ["Original bounded diff, not Git/GNU diff or a compiler/Python port",
                         "Host compiles, loads inputs, models memory and checks results; no host diff fallback",
                         "Fixed 4KiB code, 64KiB data; no OS, dynamic linking, heap, MMU or protection claim",
                         "Simulator cycles are diagnostics, not speedup or PPA"]}
    path = OUT / "validation.json"

    def save():
        path.write_text(json.dumps(report, indent=2) + "\n")

    save()
    try:
        report["reference_build"] = spike.check()
        subprocess.run([sys.executable, "tools/build_ape_app.py"], cwd=ROOT, check=True, timeout=180)
        subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tools", "-p", "test_ape_app.py", "-v"],
                       cwd=ROOT, check=True, timeout=60)
        manifest = json.loads((OUT / "manifest.json").read_text())
        report["application"] = manifest
        cases = manifest["cases"]
        if len(cases) != 12 or len({c["name"] for c in cases}) != 12:
            raise RuntimeError("Incomplete application case set")
        artifacts = [p for p in OUT.iterdir() if p.is_file() and
                     (p.suffix in (".o", ".elf", ".bin", ".old", ".new", ".hex", ".txt", ".properties") or
                      p.name == "manifest.json")]
        evidence = hashes(artifacts)
        golden, memories = {}, {}
        external = OUT / "spike"
        external.mkdir(exist_ok=True)
        for case in cases:
            name = case["name"]
            trace, raw = external / f"{name}.jsonl", external / f"{name}.log"
            with trace.open("w") as stdout, (external / f"{name}.stderr").open("w") as stderr:
                subprocess.run([str(spike.BINARY), str(OUT / "code.hex"), "0", "1", "0", str(raw),
                                str(OUT / f"{name}.bin"), "90112"], stdout=stdout, stderr=stderr, check=True, timeout=60)
            golden[name] = read_trace(trace)
            terminal = golden[name][-1]
            if terminal != {"kind": "trap", "pc": str(manifest["profile"]["symbols"]["ape_exit"]),
                            "cause": 3, "value": str(case["expected_status"])}:
                raise RuntimeError(f"Reference application failed: {name}: {terminal}")
            memory = bytearray((OUT / f"{name}.bin").read_bytes())
            for event in golden[name]:
                if event["kind"] == "memory" and event["write"]:
                    addr, size = int(event["address"])-0x10000, event["bytes"]
                    if event["error"] or not 0 <= addr <= 65536-size:
                        raise RuntimeError("Invalid reference memory effect")
                    memory[addr:addr+size] = int(event["data"]).to_bytes(size, "little")
            check_output(memory, (OUT / f"{name}.old").read_bytes(), (OUT / f"{name}.new").read_bytes(), case["expected_status"])
            memories[name] = memory
            evidence.update(hashes([trace, raw]))
        print("All 12 application cases passed external execution and output checks; running RTL matrix", flush=True)
        for n, mode in CONFIGS:
            folder = OUT / f"r{n}-{mode}"
            folder.mkdir(exist_ok=True)
            (folder / "validation.json").write_text('{"status":"not_run"}\n')
        command = ["bash", "tools/sbtw", "Test / compile"]
        command += [f"Test / runMain hats.ApeApplicationSim {n} {mode}" for n, mode in CONFIGS]
        env = dict(os.environ)
        env["PATH"] = "/opt/homebrew/bin:" + env.get("PATH", "")
        report["command"] = command
        report["verilator"] = subprocess.check_output(["verilator", "--version"], env=env, text=True).strip()
        report["java"] = subprocess.check_output([java_path(), "-version"], stderr=subprocess.STDOUT, text=True).splitlines()[0]
        with (OUT / "verification.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        results = []
        for n, mode in CONFIGS:
            folder = OUT / f"r{n}-{mode}"
            suite_path = folder / "validation.json"
            generated = OUT / f"sim/r{n}-{mode}/tmp/job_1/ApeCore.v"
            if not generated.is_file():
                raise RuntimeError("Missing application simulation RTL")
            evidence.update(hashes([generated]))
            suite = json.loads(suite_path.read_text())
            expected = [(c["name"], i) for c in cases for i in (0, 1)]
            if (suite["status"], suite["rob_entries"], suite["prediction"]) != ("passed", n, mode) or \
                    [(r["name"], r["invocation"]) for r in suite["results"]] != expected:
                raise RuntimeError("Incomplete RTL application matrix")
            evidence.update(hashes([suite_path]))
            for case in cases:
                name = case["name"]
                for i in (0, 1):
                    trace = folder / f"{name}-{i}.arch.jsonl"
                    memory_path = folder / f"{name}-{i}.memory.bin"
                    matched = compare(read_trace(trace), golden[name])
                    memory = memory_path.read_bytes()
                    if memory != memories[name]:
                        raise RuntimeError("Full final memory differs from independent reference")
                    output = check_output(memory, (OUT / f"{name}.old").read_bytes(),
                                          (OUT / f"{name}.new").read_bytes(), case["expected_status"])
                    diagnostic = next(r for r in suite["results"] if (r["name"], r["invocation"]) == (name, i))
                    if diagnostic["result"] != case["expected_status"] or diagnostic["retired"] != matched["retirements"]:
                        raise RuntimeError("RTL diagnostic and trace disagree")
                    results.append({**diagnostic, "rob_entries": n, "prediction": mode, "comparison": matched, "output": output})
                    evidence.update(hashes([trace, memory_path]))
        report["results"] = results
        report["runs_passed"] = len(results)
        report["matched_retirements"] = sum(r["comparison"]["retirements"] for r in results)
        report["matched_memory_events"] = sum(r["comparison"]["memory_events"] for r in results)
        report["max_stack_bytes"] = max(r["stack_bytes"] for r in results)
        report["evidence_sha256"] = evidence
        for name, sha in evidence.items():
            if spike.digest(ROOT / name) != sha:
                raise RuntimeError(f"Application evidence changed during run: {name}")
        if hashes(inputs) != initial or spike.check() != report["reference_build"]:
            raise RuntimeError("Sources/reference changed during application run")
        if len(results) != 144:
            raise RuntimeError("Incomplete invocation count")
        report["status"] = "passed"
    except Exception as error:
        report["status"] = "failed"; report["error"] = str(error)
        raise
    finally:
        report["source_sha256_after"] = hashes(inputs)
        report["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(f"APE application PASS: {report['runs_passed']} RTL invocations; exact Spike and minimum-edit output checks")


if __name__ == "__main__":
    main()
