"""Compiled G5 matrix component with completed-transaction coverage accounting."""

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import Run, compile_stream, summary
from scenarios import Campaign, CELLS, SEEDS


def compare_campaign(run, binary, campaign, stem):
    fixture = run.directory / (stem+".fixture.txt")
    campaign.write_fixture(fixture)
    stdout, stderr, _ = run.execute([str(binary), str(fixture)], stem+"-behavior", timeout=1200)
    measured = summary(stdout)
    normal = [case for case in campaign.cases if not case.abort]
    assert measured["commands"] == len(normal), "not every public transaction completed"
    assert measured["comparisons"] == sum(16*len(case.expected) for case in normal)
    assert measured["aborts"] == sum(case.abort for case in campaign.cases)
    assert measured["stalls"] >= 16*len(normal)
    coverage = Counter(case.coverage for case in campaign.cases)
    entry = {"cell": campaign.cell, "parameters": campaign.parameters, "seed": campaign.seed,
             "fixture": str(fixture), "fixture_sha256": run.hash_file(fixture),
             "measured_coverage": measured, "completed_bins": dict(coverage),
             "quality": campaign.quality, "stdout": str(stdout), "stderr": str(stderr)}
    run.receipt.setdefault("campaigns", []).append(entry)
    return entry


def check(run, cells=CELLS, seeds=SEEDS, compact=False):
    entries = []
    for cell in cells:
        configuration = Campaign(cell, seeds[0])
        binary = compile_stream(run, configuration.parameters, "compile-"+cell)
        for seed in seeds:
            campaign = Campaign(cell, seed)
            campaign.state_errors()
            campaign.frame_errors()
            campaign.triangles(32 if compact else 256)
            campaign.scenes(6 if compact else 32)
            campaign.witnesses()
            campaign.queries(24 if compact else 128)
            campaign.frames(8, 2 if compact else 4,
                            full_image=not compact and cell == "maximum" and seed == 17)
            campaign.resets()
            entry = compare_campaign(run, binary, campaign, cell+"-seed"+str(seed))
            bins = entry["completed_bins"]
            assert bins["lbvh-scene"] >= (6 if compact else 32)
            assert bins["triangle"] >= (32 if compact else 256)
            assert bins["query"] >= (24 if compact else 128) and bins["outward-witness"] == 2
            assert bins["axis-outward-witness"] == 10
            assert bins["svgf-axis-capacity"] == 2
            assert bins["deep-radix-tree"] == bins["signed-odd-midpoint"] == 1
            assert bins["svgf-directed"] >= 24
            assert bins["svgf-random"] >= (6 if compact else 12)
            assert all(bins["reset-"+phase] >= 1 for phase in (
                "intake", "dispatch", "arithmetic", "response", "memory", "build", "filtering"))
            assert campaign.quality and all(
                10*filtered <= 9*noisy for filtered, noisy in zip(
                    campaign.quality[0]["filtered_squared_error"],
                    campaign.quality[0]["noisy_squared_error"]))
            entries.append(entry)
    return entries


def run(args):
    run = Run(args.output_root, "g5-behavior",
              ["python3", "tests/g5_behavior.py", *sys.argv[1:]], repair_of=args.repair_of)
    try:
        run.snapshot()
        versions = {}
        for tool, flag in (("verilator", "--version"), ("c++", "--version"), ("make", "--version")):
            out, err, _ = run.execute([tool, flag], "version-"+tool)
            versions[tool] = {"stdout": str(out), "stderr": str(err)}
        entries = check(run, [args.cell] if args.cell else CELLS,
                        [args.seed] if args.seed is not None else SEEDS, args.compact)
        path = run.finish(0, tool_versions=versions, campaigns=entries)
        code = 0
    except (AssertionError, RuntimeError, OSError, ValueError, TimeoutError) as error:
        path = run.finish(1, error=error)
        code = 1
    print(json.dumps({"receipt": str(path), "exit_code": code}), flush=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="evidence/preparation")
    parser.add_argument("--cell", choices=CELLS)
    parser.add_argument("--seed", type=int, choices=SEEDS)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--repair-of")
    sys.exit(run(parser.parse_args()))
