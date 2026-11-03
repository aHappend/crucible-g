"""Bounded advisory public-pin probes; not a replacement for mandatory L1."""

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

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from oracle import (Primitive, Q, Sample, completion, lbvh, packet, query, record,
                    svgf, triangle, triangle_command, triangle_record, words64)
from scenarios import Campaign, CELLS


def cases(name, cell="nonpower", seed=17):
    vertices = ((0, 0, 1), (Q, 0, 1), (0, Q, 1))
    origin, direction = (16384, 16384, 0), (0, 0, 3)
    if name in ("g5-campaign", "state-errors", "query-boundaries", "svgf-campaign",
                "reset-campaign"):
        campaign = Campaign(cell, seed)
        if name in ("g5-campaign", "state-errors"):
            campaign.state_errors()
        if name == "g5-campaign":
            campaign.triangles()
            campaign.scenes()
        if name in ("g5-campaign", "query-boundaries"):
            campaign.witnesses()
            campaign.queries()
        if name in ("g5-campaign", "svgf-campaign"):
            campaign.frames()
        if name == "reset-campaign":
            campaign.resets()
        for case in campaign.cases:
            yield case.command, case.expected, case.latency
    elif name == "triangle":
        result = triangle(origin, direction, vertices, 0, Q)
        assert result == (0, 1, 21845, 16384, 16384)
        yield triangle_command(1, origin, direction, vertices), [triangle_record(1, result)], 16384
    elif name == "triangle-extrema":
        rng = random.Random(17)
        endpoints = [-(1 << 31), (1 << 31) - 1, -Q, -1, 0, 1, Q]
        for tag in range(1, 257):
            if tag < 129:
                v = tuple(tuple(rng.choice(endpoints) for _ in range(3)) for _ in range(3))
                o = tuple(rng.choice(endpoints) for _ in range(3))
                d = tuple(rng.choice(endpoints) for _ in range(3))
            else:
                z = rng.randrange(-Q, Q)
                v = ((-Q, -Q, z), (Q, -Q, z), (-Q, Q, z))
                o = (rng.randrange(-Q, Q), rng.randrange(-Q, Q), z - rng.randrange(1, Q))
                d = (0, 0, rng.choice([1, 3, Q, (1 << 31) - 1]))
            cull = tag & 1
            tmax = (1 << 63) - 1
            result = triangle(o, d, v, 0, tmax, cull)
            yield triangle_command(tag, o, d, v, 0, tmax, cull), [
                triangle_record(tag, result)], 16384
    elif name == "witness":
        p = Primitive(0, 9, vertices)
        yield p.write(1), [completion(1, 0x900, 1)], 64
        nodes = lbvh([p])
        yield packet(2, 0x901, [1]), [nodes[0].response(2),
              completion(2, 0x901, 1, [1, 0])], 64 + 38 * 24 + 128
        for tag, o, d in [(3, origin, direction), (4, (16384, 16384, 2), (0, 0, -3))]:
            result = query(nodes, o, d)
            assert result == [1, 21845, 0, 16384, 16384, 9, 0, 1, 1]
            yield packet(tag, 0x903, [0, *o, *d, *words64(0), *words64(Q)]), [
                record(0x50000010, tag, payload=result)], -1
    elif name == "equal-bin":
        ps = [Primitive(i, identity, tuple((x, y, i + 1) for x, y, _ in vertices))
              for i, identity in enumerate((9, 3))]
        for p in ps:
            yield p.write(p.slot + 1), [completion(p.slot + 1, 0x900, 1)], 64
        nodes = lbvh(ps)
        yield packet(3, 0x901, [2]), [*(n.response(3) for n in nodes),
              completion(3, 0x901, 2, [3, 0])], 64 + 38 * 32 + 128 * 3
        d = (0, 0, 262144)
        result = query(nodes, origin, d)
        assert result == [1, 0, 0, 16384, 16384, 3, 1, 3, 2]
        yield packet(4, 0x903, [0, *origin, *d, *words64(0), *words64(Q)]), [
            record(0x50000010, 4, payload=result)], -1
    elif name == "lbvh":
        rng = random.Random(41)
        tag = 0
        for scene in range(32):
            count = scene % 4
            ps = []
            for slot in range(count):
                if scene % 3 == 0:
                    xyz = tuple(rng.choice([-(1 << 31), -1, 0, (1 << 31) - 1])
                                for _ in range(3))
                    v = (xyz, xyz, xyz)
                else:
                    v = tuple(tuple(rng.randrange(-(1 << 31), 1 << 31)
                                    for _ in range(3)) for _ in range(3))
                p = Primitive(slot, rng.choice([0, 3, (1 << 31), (1 << 32) - 1]), v)
                ps.append(p)
                tag += 1
                yield p.write(tag), [completion(tag, 0x900, 1)], 64
            nodes = lbvh(ps)
            tag += 1
            yield packet(tag, 0x901, [count]), [*(n.response(tag) for n in nodes),
                  completion(tag, 0x901, count, [len(nodes), 0 if count else (1 << 32) - 1])], (
                      64 + 38 * (8 * count + 16) + 128 * (2 * count - 1) if count else 64)
            for node in nodes:
                tag += 1
                yield packet(tag, 0x902, [node.index]), [node.response(tag)], 4
            tag += 1
            o = (0, 0, -(1 << 31))
            d = (0, 0, (1 << 31) - 1)
            yield packet(tag, 0x903, [0, *o, *d, *words64(0), *words64((1 << 63) - 1)]), [
                record(0x50000010, tag, payload=query(nodes, o, d, 0, (1 << 63) - 1))], -1
    elif name.startswith("svgf"):
        width = 1 if name == "svgf-singleton" else 3
        height = 3 if name == "svgf-square" else 1
        history = None
        tag = 0
        for frame in range(8 if name == "svgf-guides" else 2):
            tag += 1
            yield packet(tag, 0x920, metadata=(height << 16) | width), [
                completion(tag, 0x920, width * height)], 64
            if name == "svgf-guides":
                rng = random.Random(17 + frame)
                normals = [(0, 0, 32768), (0, 32768, 0), (18919, 18919, 18919),
                           (23170, 0, 23170), (-23170, 0, 23170)]
                samples = [Sample(rng.randrange(1 << 24), rng.randrange(1 << 24),
                                  rng.choice([Q, Q + 4096, Q + 4097]),
                                  rng.choice(normals), rng.choice([(0, 0), (1, 0), (-1, 0)]))
                           for i in range(width * height)]
            else:
                samples = [Sample((i + 1 + frame) * 12345, (10 - i + frame) * 32768)
                           for i in range(width * height)]
            for x, sample in enumerate(samples):
                tag += 1
                yield sample.write(tag, x % width, x // width), [completion(tag, 0x921, 1)], 64
            values, variances, accepted, history = svgf(width, height, samples, history)
            tag += 1
            expected = [record(0x50000020, tag, payload=[
                x % width, x // width, *values[x], *variances[x], accepted[x]])
                for x in range(width * height)]
            expected.append(completion(tag, 0x922, width * height, [3, sum(accepted)]))
            yield packet(tag, 0x922), expected, 64 + 25600 * width * height
    else:
        raise ValueError(name)


def inventory(root):
    paths = [p for pattern in ("rtl/*.sv", "design/*.md", "tests/*",
                              "crucible_g4_reference/rtl/*.sv")
             for p in root.glob(pattern) if p.is_file()]
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths)}


def run(args):
    root = Path.cwd()
    output = Path(args.output_root)
    output.mkdir(parents=True, exist_ok=True)
    directory = output / ("public-" + args.case + "-" + uuid.uuid4().hex)
    directory.mkdir()
    receipt_path = directory / "receipt.json"
    receipt = {"schema": 1, "argv": ["python3", "tests/preparation.py", *sys.argv[1:]],
               "cwd": ".", "start_time": time.time(), "source_sha256": inventory(root),
               "commands": [], "tool_versions": {}, "repair_of": args.repair_of}
    snapshot = directory / "source"
    for name in receipt["source_sha256"]:
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    fixture = directory / "fixture.txt"
    transactions = list(cases(args.case, args.cell, args.seed))
    with fixture.open("w") as f:
        for command, expected, latency in transactions:
            f.write(f"{len(command) if expected else -len(command)} {len(expected)} {latency}\n")
            f.write(" ".join(f"{w:08x}" for w in command) + "\n")
            for response in expected:
                f.write(" ".join(f"{w:08x}" for w in response) + "\n")
    receipt["fixture_sha256"] = hashlib.sha256(fixture.read_bytes()).hexdigest()

    def execute(argv, stem, timeout):
        stdout, stderr = directory / (stem + ".stdout.txt"), directory / (stem + ".stderr.txt")
        item = {"argv": argv, "cwd": ".", "start_time": time.time(), "timeout_s": timeout,
                "stdout": str(stdout), "stderr": str(stderr)}
        receipt["commands"].append(item)
        with stdout.open("w") as out, stderr.open("w") as err:
            try:
                result = subprocess.run(argv, stdout=out, stderr=err, timeout=timeout, check=False)
                item.update(exit_code=result.returncode, timed_out=False)
            except subprocess.TimeoutExpired:
                item.update(exit_code=None, timed_out=True)
                raise RuntimeError(f"tool timeout: {stem}") from None
            except OSError as error:
                item.update(exit_code=None, timed_out=False, launch_error=str(error))
                raise
            finally:
                item.update(end_time=time.time(), settled=True)
        if item["exit_code"] != 0:
            raise RuntimeError(f"{stem} exit {item['exit_code']}; see {stdout} and {stderr}")
        return stdout

    try:
        versions = (("iverilog", "-V"), ("vvp", "-V")) if args.simulator == "icarus" else (
            ("verilator", "--version"), ("c++", "--version"), ("make", "--version"))
        for tool, flag in versions:
            execute([tool, flag], "version-" + tool, 60)
            receipt["tool_versions"][tool] = {
                "stdout": str(directory / ("version-" + tool + ".stdout.txt")),
                "stderr": str(directory / ("version-" + tool + ".stderr.txt"))}
        rtl = sorted(str(p.relative_to(root)) for p in root.glob("rtl/*.sv"))
        parameters = Campaign(args.cell, args.seed).parameters if args.case in (
            "g5-campaign", "state-errors", "query-boundaries", "svgf-campaign",
            "reset-campaign") else dict(
                MAX_WIDTH=7, MAX_HEIGHT=5, TILE_LOG2=1, MAX_NODES=7, MAX_SPLATS=5,
                STACK_DEPTH=3, MAX_PRIMITIVES=3, SVGF_MAX_WIDTH=3, SVGF_MAX_HEIGHT=3)
        receipt["parameters"] = parameters
        receipt["seed"] = args.seed
        if args.simulator == "icarus":
            binary = str(directory / "simulation.vvp")
            execute(["iverilog", "-g2012", "-Wall", "-s", "stream_tb", "-o", binary,
                     *[f"-Pstream_tb.{key}={value}" for key, value in parameters.items()],
                     "tests/stream_tb.sv", *rtl], "compile", 600)
            stdout = execute(["vvp", binary, "+fixture=" + str(fixture)], "simulation", 600)
        else:
            obj = directory / "compile-obj"
            obj.mkdir()
            shutil.copyfile(root / "tests/stream_driver.cpp", obj / "stream_driver.cpp")
            execute(["verilator", "--cc", "--exe", "--build", "-j", "2", "-Wno-fatal",
                     "--top-module", "crucible_g5_top", "--Mdir", str(obj),
                     *[f"-G{key}={value}" for key, value in parameters.items()],
                     *rtl, "stream_driver.cpp"], "compile", 1200)
            binary = directory / "simulation"
            shutil.copy2(obj / "Vcrucible_g5_top", binary)
            stdout = execute([str(binary), str(fixture)], "simulation", 1200)
            shutil.rmtree(obj)
        summaries = [line for line in stdout.read_text().splitlines() if line.startswith("SUMMARY ")]
        if len(summaries) != 1:
            raise RuntimeError("simulation missing completed assertions/coverage")
        measured = {key: int(value) for key, value in
                    (field.split("=") for field in summaries[0].split()[1:])}
        if measured["commands"] != sum(bool(expected) for _, expected, _ in transactions):
            raise RuntimeError("simulation did not compare every requested transaction")
        if args.case == "reset-campaign" and measured.get("aborts") != 7:
            raise RuntimeError("simulation did not exercise every reset phase")
        receipt["measured_coverage"] = measured
        receipt["exit_code"] = 0
    except (RuntimeError, OSError, ValueError) as error:
        receipt.update(exit_code=1, error=str(error))
    finally:
        receipt["end_time"] = time.time()
        receipt["source_unchanged"] = receipt["source_sha256"] == inventory(root)
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"receipt": str(receipt_path), "exit_code": receipt["exit_code"]}), flush=True)
    return receipt["exit_code"]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=["triangle", "triangle-extrema", "witness", "equal-bin",
                                          "lbvh", "svgf-singleton", "svgf-line", "svgf-square",
                                          "svgf-guides", "g5-campaign", "state-errors",
                                          "query-boundaries", "svgf-campaign",
                                          "reset-campaign"], required=True)
    parser.add_argument("--cell", choices=CELLS, default="nonpower")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--simulator", choices=["icarus", "verilator"], default="icarus")
    parser.add_argument("--output-root", default="evidence/preparation")
    parser.add_argument("--repair-of")
    sys.exit(run(parser.parse_args()))
