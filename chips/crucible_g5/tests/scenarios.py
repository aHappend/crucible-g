"""Public-command fixtures derived from the frozen mathematical contract."""

from dataclasses import dataclass
from itertools import permutations
import random

from oracle import (MASK, Primitive, Q, Sample, completion, lbvh, morton, packet,
                    query, record, svgf, triangle, triangle_command, triangle_record,
                    words64)


CELLS = {
    "singleton": (1, 1, 0, 1, 1, 1, 1, 1, 1),
    "nonpower": (7, 5, 1, 7, 5, 3, 3, 7, 5),
    "default": (256, 256, 3, 64, 64, 16, 64, 32, 32),
    "mixed": (17, 13, 4, 31, 17, 7, 17, 17, 13),
    "maximum": (256, 256, 4, 256, 256, 64, 128, 64, 64),
}
PARAMETERS = ("MAX_WIDTH", "MAX_HEIGHT", "TILE_LOG2", "MAX_NODES", "MAX_SPLATS",
              "STACK_DEPTH", "MAX_PRIMITIVES", "SVGF_MAX_WIDTH", "SVGF_MAX_HEIGHT")
SEEDS = (17, 41, 89)
Z_TRIANGLE = ((0, 0, 1), (Q, 0, 1), (0, Q, 1))


@dataclass
class Case:
    command: list
    expected: list
    latency: int
    coverage: str
    abort: bool = False


class Campaign:
    def __init__(self, cell, seed):
        self.cell = cell
        self.parameters = dict(zip(PARAMETERS, CELLS[cell]))
        self.seed = seed
        self.rng = random.Random(seed)
        self.tag = 0
        self.cases = []
        self.quality = []

    def add(self, opcode, payload=(), metadata=0, expected=None, latency=64,
            coverage="ack", status=0, count=0, extra=(), kind=0x50000000):
        self.tag += 1
        command = packet(self.tag, opcode, payload, metadata)
        if expected is None:
            expected = ([completion(self.tag, opcode, count, extra)] if status == 0 else
                        [record(kind, self.tag, status)])
        elif callable(expected):
            expected = expected(self.tag)
        case = Case(command, expected, latency, coverage)
        self.cases.append(case)
        return case

    def write(self, p):
        return self.add(0x900, p.write(0)[3:14], count=1, coverage="primitive-write")

    def build(self, primitives, coverage="lbvh-scene"):
        for p in primitives:
            self.write(p)
        nodes = lbvh(primitives)
        n = len(primitives)
        self.add(0x901, [n], latency=64 + 38 * (8*n+16) + 128 * (2*n-1) if n else 64,
                 expected=lambda tag: [*(node.response(tag) for node in nodes),
                     completion(tag, 0x901, n, [len(nodes), 0 if n else MASK])],
                 coverage=coverage)
        for node in nodes:
            self.add(0x902, [node.index], latency=4,
                     expected=lambda tag, node=node: [node.response(tag)], coverage="node-read")
        return nodes

    def ray(self, nodes, origin, direction, tmin=0, tmax=Q, cull=0, coverage="query"):
        result = query(nodes, origin, direction, tmin, tmax, cull)
        return self.add(0x903, [cull, *origin, *direction, *words64(tmin), *words64(tmax)],
                        expected=lambda tag: [record(0x50000010, tag, payload=result)],
                        latency=-1, coverage=coverage)

    def triangles(self, count=256):
        endpoints = [-(1 << 31), (1 << 31)-1, -Q, -1, 0, 1, Q]
        directed = [
            ((16384, 16384, 0), (0, 0, 3), Z_TRIANGLE, 0, Q, 0),
            ((16384, 16384, 2), (0, 0, -3), Z_TRIANGLE, 0, Q, 0),
            ((0, 0, 0), (0, 0, 1), Z_TRIANGLE, Q, Q, 0),
            ((Q, 0, 0), (0, 0, 1), Z_TRIANGLE, 0, Q, 0),
            ((Q//2, Q//2, 0), (0, 0, 1), Z_TRIANGLE, 0, Q, 0),
            ((1, 1, 0), (0, 0, 1), ((0, 0, 1), (1, 0, 1), (0, 1, 1)), 0, Q, 0),
        ]
        for i in range(count):
            if i < len(directed)*4:
                o, d, v, low, high, cull = directed[i % len(directed)]
                if i // len(directed) & 1:
                    v = (v[0], v[2], v[1])
                cull = (i // len(directed)) >> 1
            elif i % 3 == 0:
                o = tuple(self.rng.choice(endpoints) for _ in range(3))
                d = tuple(self.rng.choice(endpoints) for _ in range(3))
                v = tuple(tuple(self.rng.choice(endpoints) for _ in range(3))
                          for _ in range(3))
                low, high, cull = 0, (1 << 63)-1, i & 1
            else:
                z = self.rng.randrange(-Q, Q)
                v = ((-Q, -Q, z), (Q, -Q, z), (-Q, Q, z))
                o = (self.rng.randrange(-Q, Q+1), self.rng.randrange(-Q, Q+1),
                     z + self.rng.choice([-Q, -1, 0, 1, Q]))
                d = (0, 0, self.rng.choice([0, 1, -1, 3, -3, Q, -Q]))
                low, high, cull = self.rng.choice([0, 1, Q]), self.rng.choice([Q, Q+1, (1 << 63)-1]), i & 1
            result = triangle(o, d, v, low, high, cull)
            case = self.add(0x910, expected=lambda tag, result=result: [
                triangle_record(tag, result)], latency=16384, coverage="triangle")
            case.command = triangle_command(self.tag, o, d, v, low, high, cull)
        for index in (1, 3, 23, 30):
            case = self.add(0x910, expected=lambda tag: [
                record(0x50000010, tag, 1)], latency=16384, coverage="triangle-malformed")
            case.command = triangle_command(self.tag, (0, 0, 0), (0, 0, Q), Z_TRIANGLE)
            case.command[index] = 2 if index == 3 else 1
        for low, high in ((-1, Q), (Q+1, Q)):
            case = self.add(0x910, expected=lambda tag: [
                record(0x50000010, tag, 1)], latency=16384, coverage="triangle-invalid-range")
            case.command = triangle_command(self.tag, (0, 0, 0), (0, 0, Q),
                                            Z_TRIANGLE, low, high)
        for vertices in (Z_TRIANGLE, ((0, 0, 1), (1, 0, 1), (0, 1, 1))):
            for cull in (0, 1):
                for winding in (vertices, (vertices[0], vertices[2], vertices[1])):
                    result = triangle((0, 0, 0), (0, 0, 1), winding, Q, Q, cull)
                    case = self.add(0x910, expected=lambda tag, result=result: [
                        triangle_record(tag, result)], latency=16384,
                        coverage="triangle-unit-determinant-or-endpoint")
                    case.command = triangle_command(
                        self.tag, (0, 0, 0), (0, 0, 1), winding, Q, Q, cull)
        for low, high in ((Q-1, Q-1), (Q+1, Q+1)):
            result = triangle((16384, 16384, 0), (0, 0, 1), Z_TRIANGLE, low, high)
            case = self.add(0x910, expected=lambda tag, result=result: [
                triangle_record(tag, result)], latency=16384, coverage="triangle-endpoint-neighbor")
            case.command = triangle_command(
                self.tag, (16384, 16384, 0), (0, 0, 1), Z_TRIANGLE, low, high)

    def scenes(self, count=32):
        capacity = self.parameters["MAX_PRIMITIVES"]
        for scene in range(count):
            n = ([0, 1, min(2, capacity), capacity, min(3, capacity)][scene]
                 if scene < 5 else self.rng.randrange(min(5, capacity)+1))
            primitives = []
            for slot in range(n):
                if scene == 4 or scene % 7 == 0:
                    v = Z_TRIANGLE
                elif scene % 4 == 0:
                    v = tuple(tuple(self.rng.choice([-(1 << 31), -1, 0, (1 << 31)-1])
                                    for _ in range(3)) for _ in range(3))
                elif scene % 3 == 0:
                    p = tuple(self.rng.randrange(-Q, Q) for _ in range(3))
                    v = (p, p, p)
                else:
                    z = self.rng.randrange(-Q, Q)
                    v = ((-Q, -Q, z), (Q, -Q, z), (-Q, Q, z))
                primitives.append(Primitive(slot, self.rng.choice([0, 3, 9, MASK]), v))
            if scene & 1:
                for p in reversed(primitives):
                    self.write(p)
                nodes = lbvh(primitives)
                self.add(0x901, [n], latency=64+38*(8*n+16)+128*(2*n-1) if n else 64,
                         expected=lambda tag, nodes=nodes, n=n: [
                             *(node.response(tag) for node in nodes),
                             completion(tag, 0x901, n, [len(nodes), 0 if n else MASK])],
                         coverage="lbvh-scene")
            else:
                nodes = self.build(primitives)
            self.ray(nodes, (0, 0, -(1 << 31)), (0, 0, (1 << 31)-1),
                     tmax=(1 << 63)-1)
        ps = []
        for slot in range(min(31, capacity)):
            code = 0 if slot == 0 else 1 << (slot-1)
            quantized = [sum(((code >> (3*bit+axis)) & 1) << bit for bit in range(10))
                         for axis in range(3)]
            point = tuple((q << 22)-(1 << 31) for q in quantized)
            ps.append(Primitive(slot, slot, (point, point, point)))
        self.build(ps, "deep-radix-tree")
        odd = ((-(1 << 31), -3, -1), ((1 << 31)-1, -2, 0), (0, -2, 0))
        self.build([Primitive(0, MASK, odd)], "signed-odd-midpoint")

    def witnesses(self):
        nodes = self.build([Primitive(0, 9, Z_TRIANGLE)], "witness-build")
        for o, d in (((16384, 16384, 0), (0, 0, 3)),
                     ((16384, 16384, 2), (0, 0, -3))):
            case = self.ray(nodes, o, d, coverage="outward-witness")
            assert case.expected[0][3:12] == [1, 21845, 0, 16384, 16384, 9, 0, 1, 1]
        if self.parameters["MAX_PRIMITIVES"] >= 2:
            for identities in ((9, 3), (3, 3)):
                ps = [Primitive(i, identity, tuple((x, y, i+1) for x, y, _ in Z_TRIANGLE))
                      for i, identity in enumerate(identities)]
                nodes = self.build(ps, "equal-bin-build")
                case = self.ray(nodes, (16384, 16384, 0), (0, 0, 262144),
                                coverage="equal-bin-witness")
                assert case.expected[0][3:12] == [
                    1, 0, 0, 16384, 16384, 3, int(identities[0] != 3), 3, 2]
        for axes in permutations(range(3)):
            if axes == (0, 1, 2):
                continue
            rotated = tuple(tuple(v[a] for a in axes) for v in Z_TRIANGLE)
            nodes = self.build([Primitive(0, 9, rotated)], "axis-witness-build")
            for o, d in (((16384, 16384, 0), (0, 0, 3)),
                         ((16384, 16384, 2), (0, 0, -3))):
                case = self.ray(nodes, tuple(o[a] for a in axes), tuple(d[a] for a in axes),
                                coverage="axis-outward-witness")
                assert case.expected[0][3:12] == [
                    1, 21845, 0, 16384, 16384, 9, 0, 1, 1]

    def queries(self, count=128):
        capacity = self.parameters["MAX_PRIMITIVES"]
        ps = [Primitive(i, [9, 3, 3][i], tuple((x, y, i+1) for x, y, _ in Z_TRIANGLE))
              for i in range(min(3, capacity))]
        nodes = self.build(ps, "query-build")
        axes = tuple(permutations(range(3)))
        for index in range(count):
            if index % 16 == 0:
                axis = axes[(index // 16) % len(axes)]
                rotated = [Primitive(p.slot, p.identity, tuple(
                    tuple(v[a] for a in axis) for v in p.vertices)) for p in ps]
                nodes = self.build(rotated, "axis-query-build")
            sign = -1 if index & 1 else 1
            o = (self.rng.choice([0, 16384, Q//2, Q, Q+1]),
                 self.rng.choice([0, 16384, Q//2, Q, Q+1]),
                 self.rng.choice([-1, 0, 2, 3, 4]) if sign < 0 else -1)
            d = (0, 0, sign*self.rng.choice([0, 1, 3, Q, 262144, (1 << 31)-1]))
            o, d = tuple(o[a] for a in axis), tuple(d[a] for a in axis)
            self.ray(nodes, o, d, tmin=self.rng.choice([0, 1]),
                     tmax=(1 << 63)-1 if index % 7 == 0 else Q,
                     cull=(index >> 1) & 1)

    def state_errors(self):
        capacity = self.parameters["MAX_PRIMITIVES"]
        self.add(0x902, [0], status=2, kind=0x50000001, latency=4,
                 coverage="uninitialized-node")
        self.add(0x901, [1], status=2, latency=-1, coverage="missing-primitive")
        self.add(0x900, [capacity, 9], status=3, coverage="write-capacity")
        self.add(0x901, [capacity+1], status=3, coverage="build-capacity")
        nodes = self.build([Primitive(0, 9, Z_TRIANGLE)], "preservation-build")
        case = self.add(0x900, [0, 0], status=1, coverage="reserved-write-preservation")
        case.command[30] = 1
        self.add(0x901, [capacity+1], status=3, coverage="build-capacity-preservation")
        self.add(0x902, [0], latency=4, expected=lambda tag: [nodes[0].response(tag)],
                 coverage="rejected-command-preservation")
        self.add(0x902, [1], status=1, kind=0x50000001, latency=4,
                 coverage="node-range")
        self.write(Primitive(0, 9, Z_TRIANGLE))
        self.add(0x902, [0], status=2, kind=0x50000001, latency=4,
                 coverage="tree-invalidation")
        self.add(0x903, [0, 0, 0, 0, 0, 0, Q, *words64(0), *words64(Q)],
                 kind=0x50000010, status=2, latency=-1, coverage="query-unavailable")

    def frame(self, width, height, samples, history=None, reset=False, coverage="svgf-frame"):
        self.add(0x920, [int(reset)], metadata=(height << 16)|width,
                 count=width*height, coverage="frame-begin")
        for i, sample in enumerate(samples):
            self.add(0x921, sample.write(0, i % width, i // width)[3:13],
                     count=1, coverage="sample-write")
        values, variances, accepted, next_history = svgf(
            width, height, samples, None if reset else history)
        self.add(0x922, latency=64+25600*width*height,
                 expected=lambda tag: [
                     *(record(0x50000020, tag, payload=[
                         i % width, i // width, *values[i], *variances[i], accepted[i]])
                       for i in range(width*height)),
                     completion(tag, 0x922, width*height, [3, sum(accepted)])],
                 coverage=coverage)
        return next_history, values

    def abort(self, command, delay, phase, partial=None):
        self.cases.append(Case(command[:partial] if partial else command, [], delay,
                               "reset-"+phase, True))
        self.add(0x902, [0], status=2, kind=0x50000001, latency=4,
                 coverage="reset-tree-invalid")
        self.add(0x922, status=2, coverage="reset-frame-invalid")

    def resets(self):
        command = triangle_command(0, (16384, 16384, 0), (0, 0, 3), Z_TRIANGLE)
        self.abort(command, 0, "intake", partial=10)
        self.abort(command, 0, "dispatch")
        self.abort(command, 100, "arithmetic")
        self.abort(command, -1, "response")
        self.build([Primitive(0, 9, Z_TRIANGLE)], "reset-build")
        self.abort(packet(0, 0x903, [0, 16384, 16384, 0, 0, 0, 3,
                                   *words64(0), *words64(Q)]), 40, "memory")
        self.write(Primitive(0, 9, Z_TRIANGLE))
        self.abort(packet(0, 0x901, [1]), 300, "build")
        samples = [Sample(Q, 2*Q)]
        self.frame(1, 1, samples, reset=True, coverage="reset-history-prior")
        self.add(0x920, metadata=(1 << 16)|1, count=1)
        self.add(0x921, Sample(8*Q, 16*Q).write(0, 0, 0)[3:13], count=1)
        self.abort(packet(0, 0x922), 2000, "filtering")
        self.frame(1, 1, [Sample(3*Q, 6*Q)], coverage="reset-ghost-rejection")

    def frames(self, directed=8, randomized=4, full_image=False):
        maxw, maxh = self.parameters["SVGF_MAX_WIDTH"], self.parameters["SVGF_MAX_HEIGHT"]
        width, height = min(3, maxw), min(3, maxh)
        for sequence in range(directed):
            history = None
            self.add(0x923, coverage="history-clear")
            for frame in range(3):
                w, h = (1, height) if sequence == 0 else (width, 1) if sequence == 1 else (width, height)
                if sequence == 2 and frame == 2:
                    if (w, h) != (1, 1):
                        history = None
                    w, h = 1, 1
                samples = []
                for i in range(w*h):
                    side = i % w >= (w+1)//2
                    luma = [0, MASK >> 8, (i+frame)*12345, 4*Q if side else Q][sequence % 4]
                    if sequence in (3, 4):
                        luma = 4*Q if side else Q
                    elif sequence in (5, 6):
                        luma = (frame+1)*Q
                    normal = ((0, 32768, 0) if side and sequence == 3 else (0, 0, 32768))
                    depth = Q+4097 if (side and sequence == 4) or (frame == 2 and sequence == 5) else Q
                    if frame == 2 and sequence == 6:
                        normal = (0, 32768, 0)
                    motion = (1, 0) if sequence == 7 and frame else (0, 0)
                    samples.append(Sample(luma, (MASK >> 8)-luma, depth, normal, motion))
                history, values = self.frame(w, h, samples, history,
                                             reset=sequence == 7 and frame == 2,
                                             coverage="svgf-directed")
                if sequence in (3, 4):
                    assert all(abs(values[i][0]-samples[i].shadow) <= 1 and
                               abs(values[i][1]-samples[i].reflection) <= 1 for i in range(w*h))
        for sequence in range(randomized):
            self.add(0x923, coverage="history-clear")
            history = None
            for frame in range(3):
                samples = [Sample(self.rng.randrange(1 << 24), self.rng.randrange(1 << 24),
                                  self.rng.choice([Q, Q+4096, Q+4097]),
                                  self.rng.choice([(0, 0, 32768), (0, 32768, 0),
                                                   (23170, 23170, 0), (18919, 18919, 18919)]),
                                  self.rng.choice([(0, 0), (1, 0), (-1, 0), (0, 1), (32767, -32768)]))
                           for _ in range(width*height)]
                history, _ = self.frame(width, height, samples, history, coverage="svgf-random")
        if directed:
            self.add(0x923, coverage="history-clear")
            history = None
            noisy_error = filtered_error = [0, 0]
            noise_rng = random.Random(0x5A17)
            for frame in range(4):
                samples = [Sample(
                    Q+(-1 if (frame+i) & 1 else 1)*noise_rng.randrange(3*Q//8, 7*Q//16),
                    2*Q+(-1 if (frame+i) & 1 else 1)*noise_rng.randrange(3*Q//8, 7*Q//16))
                    for i in range(width*height)]
                history, values = self.frame(width, height, samples, history, coverage="svgf-noise")
                if frame == 3:
                    noisy_error = [sum((getattr(s, channel)-clean)**2 for s in samples)
                                   for channel, clean in (("shadow", Q), ("reflection", 2*Q))]
                    filtered_error = [sum((value[c]-clean)**2 for value in values)
                                      for c, clean in ((0, Q), (1, 2*Q))]
            assert all(10*f <= 9*n for f, n in zip(filtered_error, noisy_error))
            self.quality.append({"fixture": "seeded-constant-surface", "seed": self.seed,
                                 "noise_seed": 0x5A17,
                                 "noisy_squared_error": noisy_error,
                                 "filtered_squared_error": filtered_error,
                                 "threshold": "10*filtered <= 9*noisy"})
        if full_image:
            samples = [Sample(Q, 2*Q) for _ in range(maxw*maxh)]
            self.frame(maxw, maxh, samples, reset=True, coverage="svgf-full-image")
        for w, h in ((maxw, 1), (1, maxh)):
            samples = [Sample((i % 5)*Q, (4-i % 5)*Q, Q+(4097 if i >= w*h//2 else 0))
                       for i in range(w*h)]
            self.frame(w, h, samples, reset=True, coverage="svgf-axis-capacity")

    def frame_errors(self):
        self.add(0x921, [0, 0, Q, Q, Q, 0, 0, 32768], status=2,
                 coverage="sample-unavailable")
        self.add(0x920, metadata=0, status=1, coverage="frame-dimensions")
        self.add(0x920, metadata=(1 << 16)|(self.parameters["SVGF_MAX_WIDTH"]+1),
                 status=1, coverage="frame-dimensions")
        self.add(0x920, metadata=(1 << 16)|1, count=1)
        self.add(0x922, status=2, coverage="sample-initialization")
        invalid = [
            [1, 0, Q, Q, Q, 0, 0, 32768],
            [0, 0, 1 << 24, Q, Q, 0, 0, 32768],
            [0, 0, Q, Q, 1 << 31, 0, 0, 32768],
            [0, 0, Q, Q, Q, 0, 0, 32769],
            [0, 0, Q, Q, Q, 0, 0, 0],
            [0, 0, Q, Q, Q, 0, 0, 32768, 32768, 0],
        ]
        for sample in invalid:
            self.add(0x921, sample, status=1, coverage="sample-invalid")
        samples = [Sample(Q, 2*Q)]
        self.add(0x921, Sample(3*Q, 4*Q).write(0, 0, 0)[3:13], count=1,
                 coverage="sample-rewrite")
        self.add(0x921, samples[0].write(0, 0, 0)[3:13], count=1,
                 coverage="sample-rewrite")
        case = self.add(0x920, metadata=(1 << 16)|1, status=1,
                        coverage="invalid-begin-preservation")
        case.command[30] = 1
        values, variance, accepted, _ = svgf(1, 1, samples)
        self.add(0x922, latency=64+25600, expected=lambda tag: [
            record(0x50000020, tag, payload=[0, 0, *values[0], *variance[0], accepted[0]]),
            completion(tag, 0x922, 1, [3, 0])], coverage="invalid-begin-preservation")

    def write_fixture(self, path):
        with path.open("w") as output:
            for case in self.cases:
                output.write(f"{-len(case.command) if case.abort else len(case.command)} "
                             f"{len(case.expected)} {case.latency}\n")
                output.write(" ".join(f"{w:08x}" for w in case.command)+"\n")
                for response in case.expected:
                    output.write(" ".join(f"{w:08x}" for w in response)+"\n")


def morton_vectors(seed, count=4096):
    rng = random.Random(seed)
    coordinates = [(0, 0, 0), (1023, 1023, 1023)]
    coordinates += [tuple(1 << bit if a == axis else 0 for a in range(3))
                    for bit in range(10) for axis in range(3)]
    coordinates += list(permutations((0, 1, 1023)))
    coordinates += [tuple(rng.randrange(1024) for _ in range(3)) for _ in range(count)]
    return [(sum(x << (10*a) for a, x in enumerate(xyz)), morton(xyz))
            for xyz in coordinates]
