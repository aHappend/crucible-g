"""Independent weighted-rational proof of the localized inherited port repair."""

import argparse
import hashlib
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparation import inventory


def packed(values, width):
    return sum((v & ((1 << width) - 1)) << (i * width)
               for i, v in enumerate(values))


def run(args):
    directory = Path(args.output_root) / ("interpolator-" + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    receipt = {"argv": ["python3", "tests/interpolator_probe.py", *sys.argv[1:]],
               "cwd": ".", "start_time": time.time(), "source_sha256": inventory(Path.cwd()),
               "repair_of": args.repair_of, "commands": []}
    rng = random.Random(41)
    fixture = directory / "fixture.txt"
    vectors = []
    for index in range(96):
        lambdas = ([65536, 0, 0] if index == 0 else [0, 65536, 0] if index == 1
                   else [0, 0, 65536] if index == 2 else
                   [rng.randrange(65537) for _ in range(3)])
        qs = [rng.choice([1, 65536, (1 << 41) - 1]) for _ in range(3)]
        attributes = [rng.choice([-(1 << 31), (1 << 31) - 1, -1, 0, 1,
                                  rng.randrange(-(1 << 31), 1 << 31)]) for _ in range(18)]
        weights = [l * q for l, q in zip(lambdas, qs)]
        denominator = sum(weights)
        assert denominator > 0
        expected = [sum(weights[v] * attributes[v * 6 + a] for v in range(3)) //
                    denominator for a in range(6)]
        vectors.append((*lambdas, packed(qs, 41), packed(attributes, 32),
                        packed(expected, 32)))
    fixture.write_text("".join(" ".join(f"{v:x}" for v in row) + "\n" for row in vectors))
    receipt["fixture_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()
    for name in receipt["source_sha256"]:
        target = directory / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(name, target)

    def execute(argv, stem):
        item = {"argv": argv, "cwd": ".", "start_time": time.time(), "timeout_s": 600,
                "stdout": str(directory / (stem + ".stdout.txt")),
                "stderr": str(directory / (stem + ".stderr.txt"))}
        receipt["commands"].append(item)
        try:
            with Path(item["stdout"]).open("w") as out, Path(item["stderr"]).open("w") as err:
                child = subprocess.run(argv, stdout=out, stderr=err, timeout=600, check=False)
            item.update(exit_code=child.returncode, timed_out=False)
            if child.returncode:
                raise RuntimeError(f"{stem} exit {child.returncode}")
        except subprocess.TimeoutExpired:
            item.update(exit_code=None, timed_out=True)
            raise RuntimeError(f"{stem} timeout") from None
        finally:
            item.update(end_time=time.time(), settled=True)

    try:
        execute(["iverilog", "-V"], "version-iverilog")
        execute(["vvp", "-V"], "version-vvp")
        binary = directory / "simulation.vvp"
        execute(["iverilog", "-g2012", "-Wall", "-s", "interpolator_tb",
                 "-o", str(binary), "tests/interpolator_tb.sv",
                 "rtl/g2_interpolator.sv", "rtl/g2_divider.sv"], "compile")
        execute(["vvp", str(binary), "+fixture=" + str(fixture)], "simulation")
        lines = (directory / "simulation.stdout.txt").read_text().splitlines()
        summaries = [line for line in lines if line.startswith("SUMMARY ")]
        assert len(summaries) == 1, "missing completed assertions"
        coverage = dict(field.split("=") for field in summaries[0].split()[1:])
        assert int(coverage["commands"]) == len(vectors)
        assert int(coverage["comparisons"]) == 6 * len(vectors)
        receipt.update(exit_code=0, measured_coverage=coverage,
                       tool_versions={"iverilog": str(directory / "version-iverilog.stdout.txt"),
                                      "vvp": str(directory / "version-vvp.stderr.txt")})
    except (RuntimeError, AssertionError, OSError) as error:
        receipt.update(exit_code=1, error=str(error))
    finally:
        receipt.update(end_time=time.time(),
                       source_unchanged=receipt["source_sha256"] == inventory(Path.cwd()))
        (directory / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": str(directory / "receipt.json"),
                      "exit_code": receipt["exit_code"]}), flush=True)
    return receipt["exit_code"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="evidence/preparation")
    parser.add_argument("--repair-of", default=(
        "evidence/preparation/synthesis-g2_interpolator-468d80f04527486b97ca22dcef385d59/"
        "receipt.json"))
    sys.exit(run(parser.parse_args()))
