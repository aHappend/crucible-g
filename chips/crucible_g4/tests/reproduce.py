#!/usr/bin/env python3
"""Representative clean-directory execution using only the copied source bundle."""

from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution import Run, compile_top, simulate_top
from leaves import compile_leaves, leaf_vectors, simulate_leaves
from scenarios import PARAMETERS, directed
from synthesis import synthesis


def main():
    root = Path(__file__).resolve().parents[1]
    run = Run(root, "reproduction")
    try:
        run.versions(("python3", "iverilog", "vvp", "verilator"))
        workload = directed(PARAMETERS[1], compact=True)
        for simulator in ("iverilog", "verilator"):
            executable = compile_top(run, PARAMETERS[1], simulator, stem=simulator)
            simulate_top(run, executable, workload, f"{simulator}-run")
            executable = compile_leaves(run, simulator, stem=f"{simulator}-leaves")
            simulate_leaves(run, executable, leaf_vectors(compact=True), f"{simulator}-leaves-run")
        synthesis(run, configurations=[PARAMETERS[0]])
    except Exception as error:
        run.finish(error)
        print(f"FAIL reproduction: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    run.finish()
    print(f"PASS reproduction receipt={run.relative(run.folder / 'receipt.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
