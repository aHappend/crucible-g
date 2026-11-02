#!/usr/bin/env python3
"""Portable, self-contained CRUCIBLE-G5 L1 verification entry point."""

import argparse
import json
from pathlib import Path
import shutil
import sys
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import Run
import compatibility
import g5_behavior
import leaf_checks
import parameters
import synthesis_matrix


def child_check(run, script, stem, flags=()):
    out, err, _ = run.execute(["python3", "tests/"+script, "--output-root",
                              str(run.directory), *flags], stem, timeout=1200)
    notices = [json.loads(line) for line in out.read_text().splitlines()
               if line.startswith('{"receipt":')]
    assert len(notices) == 1 and notices[0]["exit_code"] == 0
    path = Path(notices[0]["receipt"])
    result = json.loads(path.read_text())
    assert result["exit_code"] == 0 and result["source_unchanged"]
    assert result["source_sha256"] == run.receipt["source_sha256"]
    run.receipt.setdefault("components", []).append({
        "component": stem, "receipt": str(path), "stdout": str(out), "stderr": str(err)})
    return result


def clean_reproduction(run):
    directory = run.directory / ("clean-"+uuid.uuid4().hex)
    directory.mkdir()
    for name in run.receipt["source_sha256"]:
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(name, target)
    argv = ["python3", "tests/verify.py", "--output-root", "evidence/l1", "--reproduction"]
    out, err, _ = run.execute(argv, "clean-reproduction", cwd=directory, timeout=1200)
    notices = [json.loads(line) for line in out.read_text().splitlines()
               if line.startswith('{"receipt":')]
    assert len(notices) == 1 and notices[0]["exit_code"] == 0
    path = directory / notices[0]["receipt"]
    result = json.loads(path.read_text())
    assert result["exit_code"] == 0 and result["source_unchanged"]
    assert result["source_sha256"] == run.receipt["source_sha256"]
    assert result["mode"] == "reproduction" and result["leaf_cases"]
    assert result["campaigns"] and result["synthesis"]
    run.receipt["clean_reproduction"] = {
        "cwd": str(directory), "argv": argv, "receipt": str(path),
        "stdout": str(out), "stderr": str(err), "input_sha256": result["source_sha256"]}


def verify(args):
    run = Run(args.output_root, "run", ["python3", "tests/verify.py", *sys.argv[1:]],
              repair_of=args.repair_of)
    try:
        run.snapshot()
        versions = {}
        for tool, flag in (("iverilog", "-V"), ("vvp", "-V"), ("verilator", "--version"),
                           ("c++", "--version"), ("make", "--version"), ("yosys", "-V")):
            out, err, _ = run.execute([tool, flag], "version-"+tool)
            versions[tool] = {"argv": [tool, flag], "stdout": str(out), "stderr": str(err)}
        run.receipt["tool_versions"] = versions
        run.receipt["mode"] = "reproduction" if args.reproduction else "compact-matrix"
        run.receipt["leaf_cases"] = leaf_checks.check(run, compact=args.reproduction)
        if args.reproduction:
            run.receipt["campaigns"] = g5_behavior.check(
                run, cells=("singleton",), seeds=(17,), compact=True)
            run.receipt["synthesis"] = synthesis_matrix.check(run, reproduction=True)
        else:
            run.receipt["parameter_cases"] = parameters.check(run)
            child_check(run, "interpolator_probe.py", "inherited-signed-rational")
            run.receipt["campaigns"] = g5_behavior.check(run, compact=True)
            run.receipt["compatibility"] = compatibility.check(run)
            mutations = child_check(run, "mutations.py", "seven-executable-mutants")
            assert len(mutations["detected_mutants"]) == 7
            assert all(m["compiled"] and m["simulation_exit_code"] == 1
                       and "NUMERICAL tag=" in m["mismatch"] for m in mutations["detected_mutants"])
            run.receipt["synthesis"] = synthesis_matrix.check(run)
            clean_reproduction(run)
        receipt = run.finish(0)
        code = run.receipt["exit_code"]
    except (AssertionError, RuntimeError, OSError, ValueError, TimeoutError, KeyError) as error:
        receipt = run.finish(1, error=error)
        code = 1
    print(json.dumps({"receipt": str(receipt), "exit_code": code}), flush=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="evidence/l1")
    parser.add_argument("--reproduction", action="store_true",
                        help="bounded delivery-path subset; disables recursive copying only")
    parser.add_argument("--repair-of", help="project-relative receipt of an earlier failed run")
    sys.exit(verify(parser.parse_args()))
