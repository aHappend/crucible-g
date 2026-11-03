#!/usr/bin/env python3
"""Portable L1 entry point. Native timing/STA/HIL remain shared-runtime gates."""

import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from execution import Run, compile_top, simulate_top
from leaves import compile_leaves, leaf_vectors, simulate_leaves
from scenarios import PARAMETERS, directed, seeded
from synthesis import synthesis
from defects import defects
from portable import portable


def behavior(run):
    run.versions(("python3", "iverilog", "vvp", "verilator"))
    references = sorted((run.root / "crucible_g3_reference/rtl").glob("*.sv"))
    assert len(references) == 22, "expected 22 supplied parent RTL modules"
    for reference in references:
        assert reference.read_bytes() == (run.root / "rtl" / reference.name).read_bytes(), reference.name
    small = PARAMETERS[1]
    smoke = directed(small, compact=True)
    for simulator in ("iverilog", "verilator"):
        executable = compile_top(run, small, simulator, stem=f"smoke-{simulator}")
        simulate_top(run, executable, smoke, f"smoke-{simulator}-run")
        executable = compile_leaves(run, simulator, stem=f"leaves-{simulator}")
        simulate_leaves(run, executable, leaf_vectors(compact=simulator == "iverilog"),
                        f"leaves-{simulator}-run")
    for index, parameters in enumerate(PARAMETERS):
        executable = compile_top(run, parameters, "verilator", stem=f"configuration-{index}")
        simulate_top(run, executable, directed(parameters), f"directed-{index}")
        if index in (2, 3):
            for seed in (1, 17, 93):
                coverage = simulate_top(run, executable, seeded(parameters, seed), f"seed-{index}-{seed}")
                assert coverage[f"seed.{seed}.ray"] >= 256
                assert coverage[f"seed.{seed}.scene"] >= 16
                assert all(coverage[f"seed.{seed}.tree.{tree}"] >= 1 for tree in range(12))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=("behavior", "synthesis", "defects", "portable"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for suite in ([args.suite] if args.suite else ["behavior", "synthesis", "defects", "portable"]):
        run = Run(root, suite)
        try:
            if suite == "behavior":
                behavior(run)
            elif suite == "synthesis":
                synthesis(run)
            elif suite == "defects":
                defects(run)
            elif suite == "portable":
                portable(run)
            else:
                raise AssertionError(f"unrecognized suite: {suite}")
        except Exception as error:
            run.finish(error)
            print(f"FAIL {suite}: {error}; receipt={run.relative(run.folder / 'receipt.json')}", file=sys.stderr)
            return 1
        run.finish()
        print(f"PASS {suite}: receipt={run.relative(run.folder / 'receipt.json')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
