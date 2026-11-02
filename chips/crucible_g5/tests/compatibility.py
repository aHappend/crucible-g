"""Inherited public streams and external memory side effects, independently derived."""

import argparse
from collections import Counter
import json
from pathlib import Path
import random
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from execution import Run, compile_stream, summary
from legacy_oracle import Raster, Texture, bvh_query, shader, signed, splats
from oracle import MASK, Primitive, Q, completion, lbvh, packet, record, words64
from scenarios import Campaign, SEEDS, Z_TRIANGLE


DRAW = (2, 3, 6, 7, 258, 259, 262, 263, 514, 515, 518, 519, 770, 771, 774, 775)
IDENTITY = [Q if r == c else 0 for r in range(4) for c in range(4)]


class Compatibility:
    def __init__(self, seed, parameters):
        self.seed, self.rng, self.parameters = seed, random.Random(seed), parameters
        self.tag, self.cases = 0, []
        self.raster = Raster(parameters["TILE_LOG2"])
        self.width, self.height = min(3, parameters["MAX_WIDTH"]), min(3, parameters["MAX_HEIGHT"])
        self.framebuffer = {}

    def add(self, opcode, payload=(), metadata=0, expected=None, coverage="legacy"):
        self.tag += 1
        command = packet(self.tag, opcode, payload, metadata)
        if callable(expected):
            expected = expected(self.tag)
        assert expected
        case = {"command": command, "expected": expected, "texture": [], "dma": [],
                "coverage": coverage, "opcode": opcode}
        self.cases.append(case)
        return case

    def state(self, opcode, payload=(), metadata=0, status=0, dma=()):
        case = self.add(opcode, payload, metadata, expected=lambda tag: [
            [3, tag, status, *([0]*9), sum(not beat[4] for beat in dma), 0, 0, 0]],
                        coverage="g3-state")
        case["dma"] = list(dma)
        return case

    def clear_depth(self, depth24=False):
        self.tag += 1
        op = 5 if depth24 else 4
        response = self.raster.clear(self.tag, self.width, self.height, depth24)
        self.cases.append({"command": packet(self.tag, op, metadata=self.height << 16 | self.width),
                           "expected": response, "texture": [], "dma": [],
                           "coverage": "g2-clear", "opcode": op})

    def geometry(self, variant=0):
        vertices = [(-Q, Q, Q//4, Q), (Q, Q, Q//4, Q), (-Q, -Q, Q//4, Q)]
        if variant == 1:
            vertices[1], vertices[2] = vertices[2], vertices[1]
        elif variant == 2:
            vertices[0] = (-2*Q, Q//2, Q//4, Q)
        elif variant == 3:
            vertices = [(Q//3, Q//3, Q//4, Q)]*3
        elif variant == 4:
            vertices = [(x, y, -Q, w) for x, y, z, w in vertices]
        elif variant == 5:
            vertices = [(x+2*Q, y, z, w) for x, y, z, w in vertices]
        elif variant == 6:
            vertices = [(x, y, z, 2*Q) for x, y, z, w in vertices]
        elif variant == 7:
            vertices = [(Q, -Q, Q//4, Q), (-Q, -Q, Q//4, Q), (Q, Q, Q//4, Q)]
        return vertices

    def draw(self, opcode, variant=0, texture=None, program=0, texture_error=False, uv=None):
        self.tag += 1
        vertices = self.geometry(variant)
        matrix = list(IDENTITY)
        if variant == 8:
            matrix[3], matrix[7] = -Q//3, Q//5
        attributes = [(-Q//4+i*Q//2, Q//3-i*Q//5,
                       self.rng.randrange(-Q, 2*Q), self.rng.randrange(Q+1),
                       self.rng.randrange(Q+1), self.rng.randrange(Q+1)) for i in range(3)]
        if uv is not None:
            attributes = [(*uv, *attrs[2:]) for attrs in attributes]
        op = opcode & ~512
        expected = self.raster.draw(self.tag, self.width, self.height, op, matrix, vertices,
                                    None if op in (0, 1) else attributes)
        command = [self.tag, self.height << 16 | self.width, opcode, *matrix,
                   *(c & MASK for v in vertices for c in v)]
        if opcode not in (0, 1):
            command += [a & MASK for attrs in attributes for a in attrs]
        case = {"command": command, "expected": expected, "texture": [], "dma": [],
                "coverage": "g"+str(3 if opcode & 512 else 1 if op in (0, 1) else 2)+"-draw",
                "opcode": opcode}
        if opcode & 512:
            output, hits, misses, failed = [], 0, 0, False
            for pixel in expected[:-1]:
                if failed:
                    continue
                filtered = 0
                if program & 1:
                    filtered, h, m, beats, error = texture.sample(pixel[7], pixel[8], texture_error)
                    hits += h
                    misses += m
                    case["texture"].extend(beats)
                    if error:
                        failed = True
                        continue
                x, y = pixel[2] & 255, (pixel[2] >> 8) & 255
                destination = self.framebuffer[x, y]
                source = shader(pixel[9:13], filtered, destination, program & ~4)
                final = shader(pixel[9:13], filtered, destination, program)
                self.framebuffer[x, y] = final
                output.append([2, *pixel[1:], filtered, source, final])
            done = expected[-1]
            output.append([3, self.tag, 5 if failed else done[2], len(output),
                           *done[4:10], hits, misses, 0, 0, 0, 0])
            case["expected"] = output
        self.cases.append(case)

    def framebuffer_clear(self, rgba):
        self.state(1026, [rgba], self.height << 16 | self.width)
        self.framebuffer = {(x, y): rgba for y in range(self.height) for x in range(self.width)}

    def export(self, error=False):
        beats = []
        tile = 1 << self.parameters["TILE_LOG2"]
        pixels = [(x, y) for ty in range(0, self.height, tile)
                  for tx in range(0, self.width, tile)
                  for y in range(ty, min(ty+tile, self.height))
                  for x in range(tx, min(tx+tile, self.width))]
        for x, y in pixels:
                beats.append((0x4000+y*64+x*4, self.framebuffer[x, y], 15,
                              int(x == self.width-1 and y == self.height-1), int(error)))
                if error:
                    break
        self.state(1027, [0x4000, 64], self.height << 16 | self.width,
                   5 if error else 0, beats)

    def raster_cases(self, sequences=16):
        self.add(0, metadata=0, expected=lambda tag: [[1, tag, 1, 0, 0, 0]],
                 coverage="g1-invalid")
        for i in range(sequences):
            self.draw(i & 1, i % 9)
        self.draw(0, 0)
        first = {r[2] for r in self.cases[-1]["expected"][:-1]}
        self.draw(0, 7)
        second = {r[2] for r in self.cases[-1]["expected"][:-1]}
        assert not first & second and len(first | second) == self.width*self.height
        self.add(0xDEADBEEF, metadata=self.height << 16 | self.width,
                 expected=lambda tag: [[1, tag, 1, 0, 0, 0]], coverage="unknown-opcode")
        self.add(4, metadata=0, expected=lambda tag: [[1, tag, 1, *([0]*10)]],
                 coverage="g2-invalid-clear")
        for opcode in DRAW[:8]:
            self.clear_depth(bool(opcode & 1))
            self.draw(opcode, (opcode >> 1) % 3)
            self.draw(opcode, (opcode >> 1) % 3)
        for i in range(sequences):
            self.clear_depth(bool(i & 1))
            self.draw(DRAW[i % 8], i % 9)
        for opcode in DRAW:
            kind = 3 if opcode & 512 else 1
            size = 16 if opcode & 512 else 13
            case = self.add(opcode, metadata=0, expected=lambda tag, kind=kind, size=size: [
                [kind, tag, 1, *([0]*(size-3))]], coverage="draw-invalid")
            case["command"] += [0]*18

    def texture_cases(self, sequences=16):
        for opcode, payload, metadata in ((1024, [1, 4], 0x10001),
                                          (1025, [1 << 15], 0),
                                          (1026, [0], 0),
                                          (1027, [3, 4], 0x10001)):
            self.state(opcode, payload, metadata, status=1)
        self.state(1027, [0x4000, 64], self.height << 16 | self.width, status=4)
        programs = [0, 1, 3, 4 | (2 << 3) | (3 << 6) | (1 << 9),
                    7 | (4 << 3) | (5 << 6) | (2 << 9) | (3 << 12)]
        for i in range(sequences):
            opcode = DRAW[8+i % 8]
            program = programs[i % len(programs)]
            self.clear_depth(bool(opcode & 1))
            self.framebuffer_clear(self.rng.getrandbits(32))
            texture = Texture(7, 5)
            self.state(1024, [texture.base, texture.stride], texture.height << 16 | texture.width)
            self.state(1025, [program])
            self.draw(opcode, i % 3, texture, program)
            self.export()
        self.clear_depth()
        self.framebuffer_clear(0x12345678)
        texture = Texture(7, 5)
        self.state(1024, [texture.base, texture.stride], texture.height << 16 | texture.width)
        self.state(1025, [1])
        self.draw(514, texture=texture, program=1, texture_error=True)
        self.export(error=True)
        self.export()
        texture = Texture(9, 5)
        self.state(1024, [texture.base, texture.stride], texture.height << 16 | texture.width)
        for uv in ((0, 0), (4*Q+Q//2, 3*Q+Q//2), (8*Q, 0), (0, 0)):
            self.clear_depth()
            self.draw(514, texture=texture, program=1, uv=uv)
            self.cases[-1]["coverage"] = "g3-cache-crossing-collision"
        texture = Texture(9, 5)
        self.state(1024, [texture.base, texture.stride], texture.height << 16 | texture.width)
        self.clear_depth()
        self.draw(514, texture=texture, program=1, uv=(4*Q+Q//2, 3*Q+Q//2), texture_error=18)
        self.cases[-1]["coverage"] = "g3-partial-refill-error"
        self.export()

    def bvh_cases(self, sequences=16):
        nodes = {}

        def write(index, leaf, left=0, right=0, identity=0, bounds=(-Q, -Q, Q, Q, Q, 2*Q),
                  status=0):
            self.add(0x800, [index, leaf, left, right, identity, *bounds],
                     expected=lambda tag: [record(0x40000000, tag, status, [0x800, index])],
                     coverage="g4-bvh-write")
            if status == 0:
                nodes[index] = (leaf, left, right, identity, bounds)

        def ray(root, origin, direction, low=0, high=4*Q, any_hit=False):
            values, status = bvh_query(nodes, root, origin, direction, low, high, any_hit,
                                       self.parameters["STACK_DEPTH"])
            self.add(0x801, [root, int(any_hit), *origin, *direction, *words64(low), *words64(high)],
                     expected=lambda tag: [record(0x40000001, tag, status, values)],
                     coverage="g4-bvh-query")

        ray(0, (0, 0, 0), (0, 0, Q))
        ray(MASK, (0, 0, 0), (0, 0, Q))
        write(self.parameters["MAX_NODES"], 1, status=1)
        write(0, 1, identity=9)
        for i in range(sequences):
            ray(0, (self.rng.choice([-Q-1, -Q, 0, Q, Q+1]), 0, 0),
                (0, 0, self.rng.choice([0, 1, -1, Q])), any_hit=bool(i & 1))
        if self.parameters["MAX_NODES"] >= 3:
            write(0, 0, 1, 2, bounds=(-Q, -Q, Q, Q, Q, 4*Q))
            write(1, 1, identity=9, bounds=(-Q, -Q, 2*Q, Q, Q, 3*Q))
            write(2, 1, identity=3)
            ray(0, (0, 0, 0), (0, 0, Q))
            write(1, 1, identity=3)
            ray(0, (0, 0, 0), (0, 0, Q))
            write(0, 0, 0, 2)
            ray(0, (0, 0, 0), (0, 0, Q))
        if self.parameters["MAX_NODES"] >= 7 and self.parameters["STACK_DEPTH"] == 3:
            for i in range(4):
                write(i, 0, i+1, 6)
            write(4, 1, identity=1)
            write(6, 1, identity=2)
            ray(0, (0, 0, 0), (0, 0, Q))
            self.cases[-1]["coverage"] = "g4-stack-capacity"
        thin = (-Q, -Q, 1, Q, Q, 1)
        write(0, 1, identity=7, bounds=thin)
        ray(0, (0, 0, 0), (0, 0, 3), high=Q)
        ray(0, (0, 0, 2), (0, 0, -3), high=Q)
        p = Primitive(0, 9, Z_TRIANGLE)
        self.add(0x900, p.write(0)[3:14],
                 expected=lambda tag: [completion(tag, 0x900, 1)], coverage="g5-separation")
        tree = lbvh([p])
        self.add(0x901, [1], expected=lambda tag: [
            tree[0].response(tag), completion(tag, 0x901, 1, [1, 0])], coverage="g5-separation")
        ray(0, (0, 0, 0), (0, 0, 3), high=Q)
        self.add(0x903, [0, 16384, 16384, 0, 0, 0, 3, *words64(0), *words64(Q)],
                 expected=lambda tag: [record(0x50000010, tag, payload=[
                     1, 21845, 0, 16384, 16384, 9, 0, 1, 1])], coverage="g5-separation")
        for payload in ([0, 2, *([0]*6), *words64(0), *words64(Q)],
                        [0, 0, *([0]*6), *words64(-1), *words64(Q)]):
            self.add(0x801, payload, expected=lambda tag: [
                record(0x40000001, tag, 1, [0, MASK, MASK, 0, 0, 0, 0])],
                coverage="g4-bvh-invalid")

    def splat_cases(self, sequences=16):
        self.add(0x811, [1, 0, 0], self.height << 16 | self.width,
                 expected=lambda tag: [record(0x40000003, tag, 2, [0, 1, 0, 0])],
                 coverage="g4-splat-uninitialized")
        self.add(0x810, [0, 0, 0, 0, -1 & MASK, 0, 4096, Q, 0],
                 expected=lambda tag: [record(0x40000000, tag, 1, [0x810, 0])],
                 coverage="g4-splat-invalid")
        self.add(0x811, [0, 0, 0], metadata=0,
                 expected=lambda tag: [record(0x40000003, tag, 1, [0, 0, 0, 0])],
                 coverage="g4-render-invalid")
        for sequence in range(sequences):
            n = min(sequence % 4, self.parameters["MAX_SPLATS"])
            scene = {}
            for i in range(n):
                key = [9, 3, 3][i]
                mean = (2048, 2048) if sequence % 3 == 0 else (
                    self.rng.randrange(-4096, 16384), self.rng.randrange(-4096, 16384))
                conic = (4096, -1024 if i & 1 else 1024, 8192)
                opacity = Q if sequence % 3 == 0 else self.rng.randrange(Q+1)
                rgb = self.rng.getrandbits(24)
                scene[i] = key, mean, conic, opacity, rgb
                self.add(0x810, [i, key, *mean, *conic, opacity, rgb],
                         expected=lambda tag, i=i: [record(0x40000000, tag, payload=[0x810, i])],
                         coverage="g4-splat-write")
            epsilon, background = (1 if sequence % 3 == 0 else 32768), self.rng.getrandbits(24)
            pixels, evaluations, early = splats(self.width, self.height, scene, epsilon, background)
            self.add(0x811, [n, epsilon, background], self.height << 16 | self.width,
                     expected=lambda tag, pixels=pixels, n=n, evaluations=evaluations, early=early: [
                         *(record(0x40000002, tag, payload=p) for p in pixels),
                         record(0x40000003, tag, payload=[len(pixels), n, evaluations, early])],
                     coverage="g4-splat-render")

    def generate(self, compact=False):
        self.raster_cases(4 if compact else 16)
        self.texture_cases(5 if compact else 16)
        self.bvh_cases(4 if compact else 16)
        self.splat_cases(4 if compact else 16)

    def write(self, path):
        with path.open("w") as out:
            for case in self.cases:
                expected = [w for r in case["expected"] for w in r]
                out.write(f'{len(case["command"])} {len(expected)} '
                          f'{len(case["texture"])} {len(case["dma"])}\n')
                for values in (case["command"], expected, *case["texture"], *case["dma"]):
                    out.write(" ".join(f"{w & MASK:08x}" for w in values)+"\n")


def check(run, seeds=SEEDS, compact=False):
    parameters = Campaign("nonpower", 17).parameters
    binary = compile_stream(run, parameters, "compatibility-compile",
                            driver="compatibility_driver.cpp")
    results = []
    for seed in seeds:
        campaign = Compatibility(seed, parameters)
        campaign.generate(compact)
        fixture = run.directory / ("compatibility-seed"+str(seed)+".txt")
        campaign.write(fixture)
        out, err, _ = run.execute([str(binary), str(fixture)], "compatibility-seed"+str(seed),
                                 timeout=1200)
        measured = summary(out)
        assert measured["commands"] == len(campaign.cases)
        assert measured["comparisons"] == sum(len(r) for c in campaign.cases for r in c["expected"])
        assert measured["texture"] == sum(len(c["texture"]) for c in campaign.cases) > 0
        assert measured["dma"] == sum(len(c["dma"]) for c in campaign.cases) > 0
        assert measured["bus_stalls"] > 0
        opcodes = Counter(c["opcode"] for c in campaign.cases)
        assert set(DRAW).issubset(opcodes)
        assert {0, 1, 4, 5, 1024, 1025, 1026, 1027, 0x800, 0x801, 0x810, 0x811}.issubset(opcodes)
        entry = {"seed": seed, "parameters": parameters, "measured_coverage": measured,
                 "completed_bins": dict(Counter(c["coverage"] for c in campaign.cases)),
                 "opcode_counts": dict(opcodes), "fixture": str(fixture),
                 "fixture_sha256": run.hash_file(fixture), "stdout": str(out), "stderr": str(err)}
        results.append(entry)
        run.receipt["compatibility"] = results
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="evidence/preparation")
    parser.add_argument("--seed", type=int, choices=SEEDS)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--repair-of")
    args = parser.parse_args()
    run = Run(args.output_root, "compatibility", ["python3", "tests/compatibility.py", *sys.argv[1:]],
              repair_of=args.repair_of)
    try:
        run.snapshot()
        results = check(run, [args.seed] if args.seed else SEEDS, args.compact)
        path = run.finish(0, compatibility=results)
        code = 0
    except (AssertionError, RuntimeError, OSError, ValueError, TimeoutError) as error:
        path = run.finish(1, error=error)
        code = 1
    print(json.dumps({"receipt": str(path), "exit_code": code}), flush=True)
    sys.exit(code)
