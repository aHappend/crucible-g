"""Seven disposable executable defects, checked by unchanged public-pin oracles."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import Run, compile_stream, summary
from oracle import Primitive, Q, Sample, triangle_command
from scenarios import Campaign, Z_TRIANGLE


MUTANTS = (
    ("morton-xz", "g5_morton.sv", (
        ("interleaved[3*i]=xyz[i]", "interleaved[3*i]=xyz[20+i]"),
        ("interleaved[3*i+2]=xyz[20+i]", "interleaved[3*i+2]=xyz[i]"))),
    ("duplicate-tie", "g5_lbvh.sv", (
        ("sort_data={primitive_q[509:480],scan}", "sort_data={primitive_q[509:480],~scan}"),
        ("leaf_slot<=sorted_q[7:0]", "leaf_slot<=~sorted_q[7:0]"))),
    ("bound-union", "g5_lbvh.sv", (
        ("node_work[320+i*32 +:32]<=min_choose[i] ?",
         "node_work[320+i*32 +:32]<=!min_choose[i] ?"),)),
    ("triangle-barycentric", "g5_ray_triangle.sv", (
        ("record[192 +:32]<=div_quotient[31:0]",
         "record[192 +:32]<=div_quotient[31:0] ^ 32'd1"),)),
    ("triangle-culling", "g5_ray_triangle.sv", (
        ("command[96] && numerators[0][127]", "!command[96] && numerators[0][127]"),)),
    ("svgf-edge-gate", "g5_svgf.sv", (
        ("if (!surface_depth_ok || surface_dot<17'd32768) state<=TAP_NEXT",
         "if (1'b0) state<=TAP_NEXT"),)),
    ("stale-reset-history", "g5_svgf.sv", (
        ("frame_active<=0; history_valid<=0; history_bank<=0; plane_source<=0;",
         "frame_active<=0; plane_source<=0;"),
        ("width<=0; height<=0; history_width<=0; history_height<=0; pixels<=0;",
         "width<=0; height<=0; pixels<=0;"))),
)


def fixture():
    campaign = Campaign("nonpower", 17)
    xyz = (-(1 << 31), 0, (1 << 31)-1)
    campaign.build([Primitive(0, 9, (xyz, xyz, xyz))], "mutation-morton")
    campaign.witnesses()
    campaign.triangles(24)
    campaign.frame(2, 1, [Sample(Q, 2*Q, Q), Sample(Q+1024, 2*Q+2048, Q+4097)],
                   reset=True, coverage="mutation-depth-gate")
    campaign.frame(1, 1, [Sample(Q, 2*Q)], reset=True, coverage="mutation-prior-history")
    campaign.abort(triangle_command(0, (0, 0, 0), (0, 0, 1), Z_TRIANGLE),
                   0, "stale-history", partial=10)
    campaign.frame(1, 1, [Sample(3*Q, 6*Q)], coverage="mutation-reset-ghost")
    return campaign


def run(args):
    run = Run(args.output_root, "mutations",
              ["python3", "tests/mutations.py", *sys.argv[1:]])
    results = []
    try:
        run.snapshot()
        version, _, _ = run.execute(["verilator", "--version"], "version-verilator")
        run.receipt["tool_versions"] = {"verilator": version.read_text().strip()}
        campaign = fixture()
        stimulus = run.directory / "fixture.txt"
        campaign.write_fixture(stimulus)
        run.receipt["fixture_sha256"] = run.hash_file(stimulus)
        baseline = compile_stream(run, campaign.parameters, "baseline")
        stdout, _, _ = run.execute([str(baseline), str(stimulus)], "baseline-behavior")
        measured = summary(stdout)
        assert measured["commands"] == sum(not c.abort for c in campaign.cases)
        assert measured["aborts"] == 1
        for name, filename, changes in MUTANTS:
            if args.mutant and args.mutant != name:
                continue
            directory = run.directory / (name+"-"+hashlib.sha256(name.encode()).hexdigest()[:12])
            directory.mkdir()
            for source in Path("rtl").glob("*.sv"):
                shutil.copyfile(source, directory/source.name)
            source = directory/filename
            original = source.read_text()
            mutated = original
            for before, after in changes:
                assert mutated.count(before) == 1, f"mutation anchor is not unique: {name}"
                mutated = mutated.replace(before, after)
            source.write_text(mutated)
            sources = sorted(str(p) for p in directory.glob("*.sv"))
            binary = compile_stream(run, campaign.parameters, name, sources)
            stdout, stderr, exit_code = run.execute([str(binary), str(stimulus)],
                                                    name+"-behavior", expected_exit=None)
            diagnostic = stderr.read_text()
            assert exit_code == 1 and "NUMERICAL tag=" in diagnostic, (
                "mutant was not rejected by an executed numerical comparison: " + name)
            assert "SUMMARY " not in stdout.read_text(), "failed mutant claimed completion"
            results.append({"id": name, "file": filename,
                            "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
                            "mutant_sha256": hashlib.sha256(mutated.encode()).hexdigest(),
                            "compiled": True, "simulation_exit_code": exit_code,
                            "mismatch": diagnostic.strip(), "stdout": str(stdout),
                            "stderr": str(stderr)})
        assert len(results) == (1 if args.mutant else 7)
        path = run.finish(0, baseline_coverage=measured, detected_mutants=results)
        code = 0
    except (AssertionError, RuntimeError, OSError, ValueError, TimeoutError) as error:
        path = run.finish(1, error=error, detected_mutants=results)
        code = 1
    print(json.dumps({"receipt": str(path), "exit_code": code}), flush=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="evidence/preparation")
    parser.add_argument("--mutant", choices=[m[0] for m in MUTANTS])
    sys.exit(run(parser.parse_args()))
