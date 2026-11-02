"""Independent legal endpoints and executable invalid-parameter diagnostics."""

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import Run, summary
from scenarios import CELLS, PARAMETERS


LIMITS = dict(zip(PARAMETERS, ((1, 256), (1, 256), (0, 4), (1, 256), (1, 256),
                               (1, 64), (1, 128), (1, 64), (1, 64))))


def check(run, compact=False):
    cases = [("cell-"+name, dict(zip(PARAMETERS, values)), True)
             for name, values in CELLS.items()]
    if not compact:
        for key, (low, high) in LIMITS.items():
            cases += [(key+"-lower", {key: low}, True),
                      (key+"-upper", {key: high}, True),
                      (key+"-illegal-low", {key: -1 if key == "TILE_LOG2" else 0}, False),
                      (key+"-illegal-high", {key: high+1}, False)]
    results = []
    run.receipt["parameter_cases"] = results
    sources = sorted(str(p) for p in Path("rtl").glob("*.sv"))
    for name, parameters, legal in cases:
        binary = run.directory / (name+".vvp")
        run.execute(["iverilog", "-g2012", "-Wall", "-s", "parameter_tb",
                     "-o", str(binary), *[f"-Pparameter_tb.{k}={v}" for k, v in parameters.items()],
                     "tests/parameter_tb.sv", *sources], name+"-compile")
        stdout, stderr, code = run.execute(["vvp", str(binary)], name+"-behavior",
                                          expected_exit=0 if legal else None)
        if legal:
            measured = summary(stdout)
            assert measured["commands"] == 1 and measured["comparisons"] == 6
        else:
            assert code != 0 and "PARAMETER ERROR:" in stdout.read_text()+stderr.read_text(), (
                "missing explicit invalid-parameter diagnostic: "+name)
            measured = {"explicit_parameter_diagnostic": 1}
        results.append({"case": name, "parameters": parameters, "legal": legal,
                        "simulation_exit_code": code, "measured_coverage": measured,
                        "stdout": str(stdout), "stderr": str(stderr)})
    return results


def run(args):
    run = Run(args.output_root, "parameters", ["python3", "tests/parameters.py", *sys.argv[1:]])
    results = []
    try:
        run.snapshot()
        versions = {}
        for tool in ("iverilog", "vvp"):
            out, err, _ = run.execute([tool, "-V"], "version-"+tool)
            versions[tool] = {"stdout": str(out), "stderr": str(err)}
        results = check(run, args.compact)
        path = run.finish(0, tool_versions=versions, parameter_cases=results)
        code = 0
    except (RuntimeError, AssertionError, OSError, ValueError, TimeoutError) as error:
        results = run.receipt.get("parameter_cases", results)
        path = run.finish(1, error=error, parameter_cases=results)
        code = 1
    print(json.dumps({"receipt": str(path), "exit_code": code}), flush=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="evidence/preparation")
    parser.add_argument("--compact", action="store_true")
    sys.exit(run(parser.parse_args()))
