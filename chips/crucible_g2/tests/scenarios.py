"""Requirement-directed public command streams; no DUT implementation imports."""

import random
from itertools import permutations
from dataclasses import dataclass

from model import DRAW_MODES, IDENTITY, Model, Q, word

CELLS = ((1, 1, 0), (1, 1, 3), (7, 5, 1), (9, 9, 2),
         (16, 16, 3), (17, 9, 4), (256, 256, 3))
SEEDS = (17, 89, 2026)
DEFAULT_ATTRIBUTES = (
    (-3 * Q - 123, Q // 7, Q, -Q, 7 * Q, -8 * Q),
    (5 * Q + 321, -Q // 3, 3 * Q, 2 * Q, -6 * Q, 4 * Q),
    (Q // 11, 6 * Q, -2 * Q, 7 * Q, Q // 9, 3 * Q),
)


def triangle(unequal=True, reverse=False, far=False):
    ws = (19001, 90001, 251111) if unequal else (Q, Q, Q)
    xy = ((-1, -1), (1, -1), (0, 1))
    vertices = [(x * w, y * w, w if far else w // 3, w)
                for (x, y), w in zip(xy, ws)]
    attrs = list(DEFAULT_ATTRIBUTES)
    if reverse:
        vertices[1], vertices[2] = vertices[2], vertices[1]
        attrs[1], attrs[2] = attrs[2], attrs[1]
    return vertices, attrs


def command(tag, width, height, mode, vertices=None, attrs=None, matrix=IDENTITY):
    if vertices is None:
        vertices, default = triangle(False)
        if attrs is None:
            attrs = default
    if attrs is None:
        attrs = DEFAULT_ATTRIBUTES
    words = [tag, width | height << 16, mode, *matrix,
             *(x for vertex in vertices for x in vertex)]
    if mode in DRAW_MODES:
        words += [a for vertex in attrs for a in vertex]
    return [word(x) for x in words]


@dataclass
class Case:
    name: str
    words: list
    result: object
    operation: int = 0
    delay: int = 11
    wait: int = 0


class Campaign:
    def __init__(self, cell, seed):
        self.cell, self.seed = cell, seed
        self.model = Model(*cell)
        self.cases = []
        self.replays = []
        self.scene_replays = []
        self.rng = random.Random(seed)
        self.tag = 0

    def add(self, name, width, height, mode, **kwargs):
        self.tag += 1
        words = command(self.tag, width, height, mode, **kwargs)
        result = self.model.command(words)
        self.cases.append(Case(name, words, result))
        return result

    def clear(self, width, height, precision):
        return self.add("clear", width, height, 5 if precision == 24 else 4)

    def aborted(self, name, words, operation, wait=0):
        self.cases.append(Case(name, words, None, operation, 7, wait))
        self.model.reset()

    def write(self, path):
        total_cycles = 0
        with path.open("w", encoding="ascii") as output:
            for index, case in enumerate(self.cases):
                transfers = [] if case.result is None else case.result.transfers
                # Bound every possible clip vertex/component division and
                # traversal separately; output stalls have a fixed fairness
                # pattern in stream_tb, so at most 4 cycles/word are reserved.
                width = case.words[1] & 65535 if len(case.words) > 1 else 1
                height = case.words[1] >> 16 if len(case.words) > 1 else 1
                counts = case.result.counts if case.result else {}
                bound = (7 * 384 * (10 * 610 + 32) + 384 * 4 * 610 +
                         counts.get("tested", 0) * (2 * 610 + 620) +
                         counts.get("tiles", 0) * (2 * (1 << (2*self.cell[2])) + 64) +
                         min(width, self.cell[0]) * min(height, self.cell[1]) * 16 +
                         len(transfers) * 4 + 4096)
                if case.result is not None:
                    # Most commands have a much smaller proven bound from the
                    # independent polygon's actual crossing and sample counts.
                    crossings = sum(case.result.crossings)
                    bound = (4096 + crossings * 10 * 610 + 384 * 4 * 610 +
                             counts.get("tested", 0) * 1900 +
                             counts.get("tiles", 0) *
                             (2 * (1 << (2*self.cell[2])) + 64) +
                             min(width, self.cell[0]) * min(height, self.cell[1]) * 16 +
                             len(transfers) * 4)
                total_cycles += bound
                output.write(f"{case.operation} {len(case.words)} {len(transfers)} "
                             f"{case.wait or case.delay} {bound} "
                             f"{self.seed + index + 1}\n")
                for w in case.words:
                    output.write(f"{w:08x}\n")
                for w, last in transfers:
                    output.write(f"{w:08x} {last}\n")
        return total_cycles

    def coverage(self):
        results = [(c, c.result) for c in self.cases if c.result is not None]
        draws = [(c, r) for c, r in results if c.words[2] in DRAW_MODES]
        counts = {key: sum(r.counts[key] for _, r in draws)
                  for key in ("tested", "passed", "failed", "tiles", "rejected")}
        counts.update(draws=len(draws), commands=len(self.cases),
                      six_attribute_outputs=counts["passed"],
                      surviving_tiles=counts["tiles"] - counts["rejected"],
                      disabled_failures=sum(r.counts["failed"] for c, r in draws
                                            if c.words[2] & 256),
                      audits=sum(len(r.audits) for _, r in draws),
                      nonaffine=sum(a["nonaffine"] for _, r in draws for a in r.audits))
        counts["precisions"] = {}
        for precision in (16, 24):
            subset = [r for c, r in draws if bool(c.words[2] & 1) == (precision == 24)]
            counts["precisions"][str(precision)] = {
                "draws": len(subset), "passed": sum(r.counts["passed"] for r in subset),
                "failed": sum(r.counts["failed"] for r in subset),
            }
        counts["modes"] = sorted({c.words[2] & 255 for c, _ in draws})
        counts["crossings"] = [sum(r.crossings[i] for _, r in results) for i in range(7)]
        counts["windings"] = [sum(r.windings[i] for _, r in draws) for i in range(2)]
        counts["coordinates"] = sorted({p for _, r in results for p in r.coordinates})
        counts["directed_cases"] = [c.name for c, _ in results]
        return counts

    def assert_thresholds(self):
        c = self.coverage()
        singleton = self.cell[0] == self.cell[1] == 1
        assert c["draws"] >= 32
        assert c["tested"] >= (16 if singleton else 128)
        assert c["six_attribute_outputs"] >= (16 if singleton else 64)
        assert c["rejected"] >= 2 and c["surviving_tiles"] >= 2
        assert c["disabled_failures"] >= 2
        assert c["modes"] == [2, 3, 6, 7]
        assert all(c["windings"]), "MISSING_COMPARED_WINDING"
        for p in c["precisions"].values():
            assert p["draws"] >= 16 and p["passed"] > 0 and p["failed"] > 0
        for enabled, disabled in self.replays:
            a, b = [self.cases[i].result for i in (enabled, disabled)]
            # Tags differ; compare every payload field, not just coordinates.
            identity = lambda r: sorted(tuple(record[:1] + record[2:])
                                        for record in r.records[:-1])
            assert identity(a) == identity(b)
            assert a.counts["rejected"] > 0
            assert a.counts["tested"] < b.counts["tested"]
        for enabled, disabled in self.scene_replays:
            identity = lambda indices: [
                tuple(record[:1] + record[2:])
                for i in indices for record in self.cases[i].result.records[:-1]]
            assert sorted(identity(enabled)) == sorted(identity(disabled))
            assert identity(enabled), "EMPTY_EARLY_Z_PASSING_REPLAY"
            ec = [self.cases[i].result.counts for i in enabled]
            dc = [self.cases[i].result.counts for i in disabled]
            assert sum(x["rejected"] for x in ec) > 0
            assert sum(x["tested"] for x in ec) < sum(x["tested"] for x in dc)
            assert all(x["rejected"] == 0 for x in dc)
        return c


def matrix_campaign(cell, seed):
    c = Campaign(cell, seed)
    w, h = min(cell[0], 7), min(cell[1], 5)
    for precision in (16, 24):
        for group in range(8):
            c.clear(w, h, precision)
            mode = (3 if precision == 24 else 2) + (4 if group % 2 else 0)
            vertices, attrs = triangle(group % 2 == 0, bool(group & 2))
            attrs = [tuple(a + c.rng.randint(-31, 31) for a in v) for v in attrs]
            c.add(f"matrix-{precision}-{group}-pass", w, h, mode,
                  vertices=vertices, attrs=attrs)
            c.add(f"matrix-{precision}-{group}-equal-disabled", w, h, mode | 256,
                  vertices=vertices, attrs=attrs)
        # A far-plane triangle has zmin=max: guaranteed rejection even for
        # tiles with uncovered pixels. Replay from a separate identical clear.
        vertices, attrs = triangle(False, far=True)
        c.clear(w, h, precision)
        enabled = len(c.cases)
        c.add("early-far-enabled", w, h, 3 if precision == 24 else 2,
              vertices=vertices, attrs=attrs)
        c.clear(w, h, precision)
        disabled = len(c.cases)
        c.add("early-far-disabled", w, h, (3 if precision == 24 else 2) | 256,
              vertices=vertices, attrs=attrs)
        c.replays.append((enabled, disabled))
        # A truly occluded viewport, not merely far-plane clear equality.
        square = [(-Q,-Q,Q//4,Q),(Q,-Q,Q//4,Q),(Q,Q,Q//4,Q),(-Q,Q,Q//4,Q)]
        scenes = []
        for disable in (0,256):
            c.clear(w,h,precision)
            indices=[]
            for vertices in (square[:3], [square[0],square[2],square[3]],
                             [(x,y,3*Q//4,vw) for x,y,_,vw in square[:3]]):
                indices.append(len(c.cases))
                c.add("occluded-replay",w,h,(3 if precision==24 else 2)|disable,
                      vertices=vertices)
            scenes.append(indices)
        c.scene_replays.append(tuple(scenes))
        # Strictly nearer/equal/farther permutations, followed by public
        # persistence probes through both invalid and legacy commands.
        c.clear(w, h, precision)
        for depth in (Q//2, Q//4, 3*Q//4, Q//4, 0):
            v, a = triangle(False)
            v = [(x, y, depth, vw) for x, y, _, vw in v]
            c.add("depth-permutation", w, h, (3 if precision == 24 else 2) | 256,
                  vertices=v, attrs=a)
        c.add("legacy-persistence", w, h, 0)
        c.add("invalid-mode-preserves-depth", w, h, 0x1234)
        c.add("invalid-size-priority", 0, h, 3 if precision == 24 else 2)
        c.add("mismatch-preserves-depth", w, h, 2 if precision == 24 else 3)
        v, a = triangle(False)
        v = [(x, y, 0, vw) for x, y, _, vw in v]
        r = c.add("public-depth-preservation", w, h,
                  (3 if precision == 24 else 2) | 256, vertices=v, attrs=a)
        assert r.counts["failed"] > 0 and r.counts["passed"] == 0
    return c


def directed(c):
    w, h = min(c.cell[0], 7), min(c.cell[1], 5)
    c.clear(w, h, 24)
    base, a = triangle(False)
    crossing_vertices = (
        (0, 0, 0, -Q), (-2*Q, 0, Q//2, Q), (2*Q, 0, Q//2, Q),
        (0, -2*Q, Q//2, Q), (0, 2*Q, Q//2, Q),
        (0, 0, -Q, Q), (0, 0, 2*Q, Q),
    )
    for plane, outside in enumerate(crossing_vertices):
        c.clear(w, h, 24)
        v = list(base)
        v[2] = outside
        r = c.add(f"clip-plane-{plane}-attributes", w, h, 259, vertices=v, attrs=a)
        assert r.crossings[plane] > 0
    for name, vertices in (
        ("near-zero-positive-w", [(x, y, 0, 1) for x, y in ((-1, -1), (1, -1), (0, 1))]),
        ("fully-clipped", [(x, y, -Q, vw) for x, y, _, vw in base]),
        ("degenerate", [base[0]] * 3),
    ):
        c.clear(w, h, 16)
        c.add(name, w, h, 258, vertices=vertices)
    c.clear(w, h, 16)
    endpoints = [(-(1<<31), (1<<31)-1, -1, 0, 1, -65537),
                 ((1<<31)-1, -(1<<31), 65537, -2, 3, 0), (0, 1, -2, 3, -4, 5)]
    c.add("signed32-attribute-endpoints", w, h, 258, attrs=endpoints)
    extreme = tuple(((1<<31)-1 if i%3 else -(1<<31)) for i in range(16))
    c.add("extreme-matrix", w, h, 258, matrix=extreme)
    c.add("legacy-3d", w, h, 0)
    c.add("legacy-2d", w, h, 1)
    # Exact shared diagonal of a viewport rectangle. Disabled early-Z and
    # z=0 ensure a repeated covered pixel would fail in the second triangle.
    c.clear(w, h, 16)
    square = [(-Q, -Q, 0, Q), (Q, -Q, 0, Q), (Q, Q, 0, Q), (-Q, Q, 0, Q)]
    r0 = c.add("shared-edge-first", w, h, 258, vertices=square[:3])
    r1 = c.add("shared-edge-second", w, h, 258,
               vertices=[square[0], square[2], square[3]])
    assert not r0.coordinates & r1.coordinates
    assert len(r0.coordinates | r1.coordinates) == w*h
    assert r0.counts["failed"] == r1.counts["failed"] == 0
    # Closely spaced depths collapse in D16 but differ in D24.
    for precision in (16, 24):
        c.clear(w, h, precision)
        mode = (3 if precision == 24 else 2) | 256
        pair=[]
        for z in (32769, 32768):
            v = [(x, y, z, 65537) for x, y, _, _ in base]
            pair.append(c.add(f"precision-pair-{precision}-{z}", w, h, mode, vertices=v))
        assert pair[0].counts["passed"]>0
        if precision==16:
            assert pair[1].counts["failed"]>0 and pair[1].counts["passed"]==0
        else:
            assert pair[1].counts["passed"]>0 and pair[1].counts["failed"]==0
    # Invalid commands must not commit a new configuration.
    c.add("invalid-clear-dimension", 0, h, 4)
    c.add("invalid-clear-upper-mode", w, h, 260)
    c.add("invalid-legacy-dimension", c.cell[0]+1, h, 0)
    if c.cell[0] >= 2:
        c.add("dimension-mismatch", w-1, h, 259)
    v=[(x,y,32768,65537) for x,y,_,_ in base]
    r=c.add("invalid-clear-public-preservation",w,h,259,vertices=v)
    assert r.counts["failed"]>0 and r.counts["passed"]==0
    for order in permutations((Q//4,Q//2,3*Q//4)):
        c.clear(w,h,24)
        for depth in (*order, min(order)):
            v=[(x,y,depth,vw) for x,y,_,vw in base]
            c.add("nearest-farthest-equal-permutation",w,h,259,vertices=v)
    if c.cell[0] == 256 and c.cell[1] == 256:
        c.clear(256, 256, 24)
        # A 2x2 corner footprint exercises 255 and endpoint256 cheaply.
        v = [(65024, -65536, 0, Q), (65536, -65536, 0, Q),
             (65536, -65024, 0, Q)]
        r = c.add("viewport-255-and-256", 256, 256, 259, vertices=v)
        assert (255, 255) in r.coordinates
        c.add("legacy-corner-255", 256, 256, 0, vertices=v)
    # Public reset epochs: reception, arithmetic, clear, stalled output.
    words = command(0xAB01, w, h, 2)
    c.aborted("reset-receive", words[:11], 1, 5)
    c.add("reset-invalidated-configuration", w, h, 2)
    c.clear(w, h, 16)
    c.aborted("reset-compute", words, 1, 200)
    c.add("reset-after-compute", w, h, 2)
    c.aborted("reset-clear", command(0xAB02, w, h, 4), 1, 3)
    c.add("reset-after-clear", w, h, 2)
    c.aborted("reset-stalled-output", command(0xAB03, w, h, 4), 2)
    c.add("reset-after-stall", w, h, 2)
    c.clear(w, h, 24)
    c.add("reset-recovery-draw", w, h, 259)


def compact_campaign(cell=(1, 1, 3), seed=17):
    c = Campaign(cell, seed)
    w,h = cell[:2]
    c.add("legacy-compact", w, h, 0)
    for p in (16,24):
        c.clear(w,h,p)
        vertices,attrs=triangle(True)
        c.add("compact-unequal-w", w,h,3 if p==24 else 2,vertices=vertices,attrs=attrs)
        c.add("compact-equality-disabled", w,h,259 if p==24 else 258,
              vertices=vertices,attrs=attrs)
        c.clear(w,h,p)
        v,a=triangle(False,far=True)
        c.add("compact-early-reject",w,h,3 if p==24 else 2,vertices=v,attrs=a)
    return c
