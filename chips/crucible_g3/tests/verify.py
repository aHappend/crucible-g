#!/usr/bin/env python3
"""Portable L1 checks. Native timing and hardware gates are runtime-owned."""

import argparse
import json
from pathlib import Path
import random
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import Evidence
from model import bilinear, pack, shader

ROOT = Path(__file__).resolve().parents[1]


def leaf_vectors(path, seed, count):
    rng = random.Random(seed)
    vectors = []
    for i in range(count):
        texels = [rng.getrandbits(32) for _ in range(4)]
        fx, fy = rng.randrange(65536), rng.randrange(65536)
        vertex = [rng.randrange(-65536, 131073) for _ in range(4)]
        texture, destination = rng.getrandbits(32), rng.getrandbits(32)
        factors = [rng.randrange(6) for _ in range(4)]
        program = rng.randrange(8) | sum(f << s for f, s in zip(factors, (3, 6, 9, 12)))
        if i < 72:
            a, b = divmod(i % 36, 6)
            vertex = [17000, 43000, 61000, 37000]
            destination = pack([71, 139, 211, 91], 8)
            texture = pack([231, 53, 117, 173], 8)
            program = 7 | (a << (3 if i < 36 else 9)) | (
                b << (6 if i < 36 else 12)) | (
                (1 << 9) if i < 36 else (1 << 3))
        elif i < 100:
            vertex = [(-1, 0, 32768, 65536, 65537, -2**31, 2**31-1)[(i+j) % 7]
                      for j in range(4)]
            program = (i & 7) | (1 << 3) | (1 << 6) | (1 << 9) | (1 << 12)
            fx, fy = ((0, 1, 32768, 65535)[i % 4],
                      (0, 1, 32768, 65535)[i//4 % 4])
        values = [pack(texels, 32), fx, fy, pack(vertex, 32), texture, destination,
                  program, bilinear(texels, fx, fy),
                  shader(vertex, texture, destination, program)]
        vectors.append(" ".join(f"{v:x}" for v in values)+f" {2+i%5}")
    path.write_text("\n".join(vectors)+"\n")
    return count


def compile_sim(evidence, top, bench, sources, name, verilator=False, parameters=()):
    work = evidence.path / name
    work.mkdir()
    if verilator:
        executable = work / "obj" / ("V"+top)
        evidence.run(["verilator", "--binary", "--timing", "-Wno-fatal",
                      "--top-module", top, "-j", "2", "--Mdir",
                      evidence.relative(work / "obj"), *parameters,
                      *[evidence.relative(x) for x in sources],
                      evidence.relative(bench)], name+"-compile")
    else:
        executable = work / "simulation.vvp"
        evidence.run(["iverilog", "-g2012", "-Wall", "-s", top, "-o",
                      evidence.relative(executable), *parameters,
                      *[evidence.relative(x) for x in sources],
                      evidence.relative(bench)], name+"-compile")
    return executable


def leaves(evidence, compact=False):
    sources = [ROOT / "rtl/g3_bilinear.sv", ROOT / "rtl/g3_shader_pipeline.sv"]
    runs = []
    executable = compile_sim(evidence, "leaf_tb", ROOT / "tests/leaf_tb.sv",
                             sources, "leaf-icarus")
    vectors = evidence.path / "leaf-smoke.txt"
    leaf_vectors(vectors, 17, 100)
    out, _, _ = evidence.run(["vvp", evidence.relative(executable),
                             "+vectors="+evidence.relative(vectors)], "leaf-icarus-run")
    assert "SUMMARY leaf compared=100" in out, out
    runs.append({"simulator": "icarus", "seed": 17, "compared": 100})
    if not compact:
        executable = compile_sim(evidence, "leaf_tb", ROOT / "tests/leaf_tb.sv",
                                 sources, "leaf-verilator", True)
        for seed in (17, 89, 233):
            vectors = evidence.path / f"leaf-{seed}.txt"
            leaf_vectors(vectors, seed, 356)
            out, _, _ = evidence.run([evidence.relative(executable),
                                     "+vectors="+evidence.relative(vectors)],
                                    f"leaf-verilator-{seed}")
            assert "SUMMARY leaf compared=356" in out, out
            runs.append({"simulator": "verilator", "seed": seed, "compared": 356})
        shutil.rmtree(executable.parent)
    return runs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("behavior", "defects", "synthesis", "reproduce"),
                        required=True)
    parser.add_argument("--probe", choices=("leaves",))
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    evidence = Evidence(ROOT, args.probe or args.suite, ["python3", "tests/verify.py"]+sys.argv[1:],
                        preparation=bool(args.probe), repair_of=args.repair_of)
    try:
        if args.probe == "leaves":
            evidence.versions(("python3", "iverilog", "vvp", "verilator", "make", "g++"))
            runs = leaves(evidence)
        else:
            raise RuntimeError("Verification implementation incomplete: integrated coverage, "
                               "mutants, synthesis and reproduction are not yet ready.")
        evidence.finish("passed", runs=runs)
        print(json.dumps({"status": "passed", "receipt": evidence.relative(evidence.path / "receipt.json")}))
        return 0
    except Exception as exc:
        evidence.finish("failed", error=str(exc))
        print(json.dumps({"status": "failed", "error": str(exc),
                          "receipt": evidence.relative(evidence.path / "receipt.json")}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
