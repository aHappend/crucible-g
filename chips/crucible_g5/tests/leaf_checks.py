"""Compact four-state leaf and integrated portability checks."""

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import Run, summary
from oracle import Primitive, Q, Sample
from scenarios import Campaign, SEEDS, Z_TRIANGLE, morton_vectors


def check(run, compact=False):
    results = []
    binary = run.directory / "morton.vvp"
    run.execute(["iverilog", "-g2012", "-Wall", "-s", "morton_tb",
                 "-o", str(binary), "tests/morton_tb.sv", "rtl/g5_morton.sv"], "morton-compile")
    for seed in (17,) if compact else SEEDS:
        vectors = morton_vectors(seed, 64 if compact else 4096)
        fixture = run.directory / ("morton-seed"+str(seed)+".txt")
        fixture.write_text("".join(f"{xyz:08x} {code:08x}\n" for xyz, code in vectors))
        stdout, stderr, _ = run.execute(["vvp", str(binary), "+fixture="+str(fixture)],
                                       "morton-seed"+str(seed))
        measured = summary(stdout)
        assert measured["commands"] == len(vectors) and measured["comparisons"] == len(vectors)
        assert measured["cycles"] <= 500000
        results.append({"top": "g5_morton", "seed": seed, "fixture": str(fixture),
                        "fixture_sha256": run.hash_file(fixture), "measured_coverage": measured,
                        "stdout": str(stdout), "stderr": str(stderr)})
    campaign = Campaign("nonpower", 17)
    nodes = campaign.build([Primitive(0, 9, Z_TRIANGLE)], "portability-build")
    campaign.ray(nodes, (16384, 16384, 0), (0, 0, 3))
    campaign.triangles(2)
    campaign.frame(1, 1, [Sample(Q, 2*Q)], reset=True, coverage="portability-svgf")
    fixture = run.directory / "stream.fixture.txt"
    campaign.write_fixture(fixture)
    binary = run.directory / "stream.vvp"
    sources = sorted(str(p) for p in Path("rtl").glob("*.sv"))
    run.execute(["iverilog", "-g2012", "-Wall", "-s", "stream_tb", "-o", str(binary),
                 *[f"-Pstream_tb.{k}={v}" for k, v in campaign.parameters.items()],
                 "tests/stream_tb.sv", *sources], "stream-compile")
    stdout, stderr, _ = run.execute(["vvp", str(binary), "+fixture="+str(fixture)], "stream-behavior")
    measured = summary(stdout)
    assert measured["commands"] == len(campaign.cases)
    assert measured["comparisons"] == sum(16*len(case.expected) for case in campaign.cases)
    assert measured["cycles"] <= 500000 and measured["max_stall"] >= 16
    results.append({"top": "crucible_g5_top", "parameters": campaign.parameters,
                    "fixture": str(fixture), "fixture_sha256": run.hash_file(fixture),
                    "measured_coverage": measured, "stdout": str(stdout), "stderr": str(stderr)})
    return results


def run(args):
    run = Run(args.output_root, "leaf", ["python3", "tests/leaf_checks.py", *sys.argv[1:]])
    try:
        run.snapshot()
        versions = {}
        for tool in ("iverilog", "vvp"):
            out, err, _ = run.execute([tool, "-V"], "version-"+tool)
            versions[tool] = {"stdout": str(out), "stderr": str(err)}
        results = check(run, args.compact)
        path = run.finish(0, tool_versions=versions, leaf_cases=results)
        code = 0
    except (AssertionError, RuntimeError, OSError, ValueError, TimeoutError) as error:
        path = run.finish(1, error=error)
        code = 1
    print(json.dumps({"receipt": str(path), "exit_code": code}), flush=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="evidence/preparation")
    parser.add_argument("--compact", action="store_true")
    sys.exit(run(parser.parse_args()))
