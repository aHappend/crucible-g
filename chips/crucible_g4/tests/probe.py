#!/usr/bin/env python3
"""Bounded advisory probe reusing the admitted behavior suite's actual checker."""

import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import Run, compile_top, simulate_top
from leaves import compile_leaves, leaf_vectors, simulate_leaves
from scenarios import PARAMETERS, directed
from synthesis import synthesis
from defects import MUTATIONS, execute_mutation


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulator", choices=("iverilog", "verilator"), default="iverilog")
    parser.add_argument("--repair-of")
    parser.add_argument("--focus", choices=("top", "leaves", "synthesis", "mutation"), default="top")
    parser.add_argument("--mutation", choices=tuple(mutation[0] for mutation in MUTATIONS),
                        default="off_diagonal_conic")
    args = parser.parse_args()
    run = Run(Path(__file__).resolve().parents[1], f"public-{args.focus}", preparation=True,
              repair_of=args.repair_of)
    run.receipt["argv"] = ["python3", "tests/probe.py", *sys.argv[1:]]
    run.receipt["cwd"] = "."
    run.save()
    try:
        if args.focus == "mutation":
            run.versions(("python3", "verilator"))
            workload = directed(PARAMETERS[1], compact=True)
            executable = compile_top(run, PARAMETERS[1], "verilator", stem="clean-control")
            simulate_top(run, executable, workload, "clean-control-run")
            mutation = next(item for item in MUTATIONS if item[0] == args.mutation)
            execute_mutation(run, mutation)
            run.receipt["comparisons"]["mutation"] = {
                "name": args.mutation, "functional_mismatch": True, "clean_control": True}
            run.save()
        elif args.focus == "synthesis":
            synthesis(run, configurations=[PARAMETERS[0]])
        elif args.focus == "top":
            run.versions(("python3", args.simulator, *(("vvp",) if args.simulator == "iverilog" else ())))
            executable = compile_top(run, PARAMETERS[1], args.simulator)
            simulate_top(run, executable, directed(PARAMETERS[1], compact=True), "smoke")
        else:
            run.versions(("python3", args.simulator, *(("vvp",) if args.simulator == "iverilog" else ())))
            executable = compile_leaves(run, args.simulator)
            simulate_leaves(run, executable, leaf_vectors(compact=True))
    except Exception as error:
        run.finish(error)
        print(f"FAIL {error}; receipt={run.relative(run.folder / 'receipt.json')}", file=sys.stderr)
        return 1
    run.finish()
    print(f"PASS receipt={run.relative(run.folder / 'receipt.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
