"""Independent integer/Fraction transaction model of the admitted graphics rules."""

from dataclasses import dataclass, field
from fractions import Fraction

Q = 65536
IDENTITY = tuple(Q if i // 4 == i % 4 else 0 for i in range(16))
DRAW_MODES = {2, 3, 6, 7, 258, 259, 262, 263}


def signed(value, bits=32):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def word(value):
    return value & 0xFFFFFFFF


def transform(vertex, matrix, two_d):
    vector = (vertex[0], vertex[1], 0, Q) if two_d else vertex[:4]
    return tuple(
        max(-(1 << 31), min((1 << 31) - 1,
                           sum(matrix[4 * r + c] * vector[c] for c in range(4)) // Q))
        for r in range(4)
    ) + tuple(vertex[4:])


def distance(v, plane):
    x, y, z, w = v[:4]
    return (w - 1, x + w, w - x, y + w, w - y, z, w - z)[plane]


def clip(vertices):
    polygon = list(vertices)
    crossings = [0] * 7
    for plane in range(7):
        output = []
        if polygon:
            a = polygon[-1]
            for b in polygon:
                fa, fb = distance(a, plane), distance(b, plane)
                if (fa >= 0) != (fb >= 0):
                    c = [signed(av + (bv - av) * fa // (fa - fb))
                         for av, bv in zip(a, b)]
                    if plane == 0:
                        c[3] = 1
                    elif plane in (1, 2):
                        c[0] = signed(-c[3] if plane == 1 else c[3])
                    elif plane in (3, 4):
                        c[1] = signed(-c[3] if plane == 3 else c[3])
                    elif plane == 5:
                        c[2] = 0
                    else:
                        c[2] = c[3]
                    output.append(tuple(c))
                    crossings[plane] += 1
                if fb >= 0:
                    output.append(b)
                a = b
        polygon = output
        assert len(polygon) <= 384
    return polygon, crossings


@dataclass(frozen=True)
class Projected:
    x: int
    y: int
    q: int
    depth: int
    attributes: tuple
    w: int


def project(v, width, height, precision):
    x, y, z, w = v[:4]
    assert w >= 1
    maximum = (1 << precision) - 1
    return Projected(
        max(0, min(width * 256, (x + w) * width * 256 // (2 * w))),
        max(0, min(height * 256, (w - y) * height * 256 // (2 * w))),
        (1 << 40) // w, max(0, min(maximum, z * maximum // w)),
        tuple(v[4:]), w,
    )


def edge(a, b, point):
    return (b.x - a.x) * (point[1] - a.y) - (b.y - a.y) * (point[0] - a.x)


def top_left(a, b):
    return b.y < a.y or (b.y == a.y and b.x > a.x)


def samples(vertices, region):
    a, b, c = vertices
    area = edge(a, b, (c.x, c.y))
    assert area > 0
    for y in range(region[1], region[3] + 1):
        for x in range(region[0], region[2] + 1):
            point = (256 * x + 128, 256 * y + 128)
            edges = (edge(b, c, point), edge(c, a, point), edge(a, b, point))
            if all(e > 0 or (e == 0 and top_left(u, v))
                   for e, (u, v) in zip(edges, ((b, c), (c, a), (a, b)))):
                l0, l1 = (edges[i] * Q // area for i in (0, 1))
                yield x, y, (l0, l1, Q - l0 - l1)


def attributes(vertices, lambdas):
    weights = [v.q * l for v, l in zip(vertices, lambdas)]
    denominator = sum(weights)
    assert 0 < denominator < 1 << 63
    result = tuple(sum(w * v.attributes[a] for w, v in zip(weights, vertices))
                   // denominator for a in range(6))
    assert all(-(1 << 31) <= a < (1 << 31) for a in result)
    return result


def precision_audit(vertices, lambdas, result):
    if len({v.w for v in vertices}) == 1:
        return None
    if not all(Q // 4 <= v.w <= 4 * Q and
               all(-8 * Q <= a <= 8 * Q for a in v.attributes) for v in vertices):
        return None
    weights = [Fraction(l, v.w) for l, v in zip(lambdas, vertices)]
    exact = [sum(w * v.attributes[a] for w, v in zip(weights, vertices)) / sum(weights)
             for a in range(6)]
    errors = [abs(Fraction(value) - ideal) for value, ideal in zip(result, exact)]
    assert all(e <= 2 for e in errors), ("precision audit", errors)
    affine = [sum(l * v.attributes[a] for l, v in zip(lambdas, vertices)) // Q
              for a in range(6)]
    return {"max_error": str(max(errors)),
            "nonaffine": any(abs(a - r) > 256 for a, r in zip(affine, result))}


@dataclass
class Result:
    records: list
    counts: dict = field(default_factory=dict)
    audits: list = field(default_factory=list)
    crossings: list = field(default_factory=lambda: [0] * 7)
    coordinates: set = field(default_factory=set)
    status: int = 0
    windings: list = field(default_factory=lambda: [0, 0])

    @property
    def transfers(self):
        return [(word(w), int(ri == len(self.records) - 1 and wi == len(record) - 1))
                for ri, record in enumerate(self.records) for wi, w in enumerate(record)]


class Model:
    def __init__(self, maximum_width, maximum_height, tile_log2):
        self.limits = maximum_width, maximum_height
        self.tile = 1 << tile_log2
        self.reset()

    def reset(self):
        self.configuration = None
        self.depth = {}

    def command(self, words):
        tag, dimensions, mode = words[:3]
        width, height = dimensions & 65535, dimensions >> 16
        draw, clear = mode in DRAW_MODES, mode in (4, 5)
        g2 = draw or clear
        assert len(words) == (49 if draw else 31)
        result = Result([])
        counts = dict(emitted=0, fans=0, tiles=0, rejected=0, tested=0, passed=0, failed=0)
        result.counts = counts

        def finish(status):
            result.status = status
            result.records.append(
                [1, tag, status, counts["emitted"], counts["fans"],
                 counts["tiles"], counts["rejected"], counts["tested"],
                 counts["passed"], counts["failed"], 0, 0, 0] if g2 else
                [1, tag, status, counts["emitted"], counts["fans"], 0])
            return result

        if not (1 <= width <= self.limits[0] and 1 <= height <= self.limits[1]):
            return finish(1)
        if mode not in DRAW_MODES | {0, 1, 4, 5}:
            return finish(1)
        precision = 24 if mode & 1 else 16
        configuration = width, height, precision
        if clear:
            self.depth = {(x, y): (1 << precision) - 1
                          for y in range(height) for x in range(width)}
            self.configuration = configuration
            return finish(0)
        if draw and self.configuration != configuration:
            return finish(4)
        matrix = tuple(signed(x) for x in words[3:19])
        vertices = []
        for i in range(3):
            vertex = tuple(signed(w) for w in words[19 + 4*i:23 + 4*i])
            attrs = tuple(signed(w) for w in words[31 + 6*i:37 + 6*i]) if draw else ()
            vertices.append(transform(vertex + attrs, matrix, mode == 1 or
                                      (draw and mode & 255 in (6, 7))))
        polygon, result.crossings = clip(vertices)
        projected = [project(v, width, height, precision) for v in polygon]
        if len(projected) < 3:
            return finish(2)
        for fan in range(len(projected) - 2):
            triangle = [projected[0], projected[fan + 1], projected[fan + 2]]
            area = edge(*triangle[:2], (triangle[2].x, triangle[2].y))
            if area == 0:
                continue
            result.windings[int(area < 0)] += 1
            counts["fans"] += 1
            if area < 0:
                triangle[1], triangle[2] = triangle[2], triangle[1]
            x0, y0 = min(v.x for v in triangle) // 256, min(v.y for v in triangle) // 256
            x1 = min(width - 1, max(v.x for v in triangle) // 256)
            y1 = min(height - 1, max(v.y for v in triangle) // 256)
            if x0 > x1 or y0 > y1:
                continue
            regions = [(x0, y0, x1, y1)]
            if draw:
                regions = []
                for ty in range(y0 // self.tile * self.tile, y1 + 1, self.tile):
                    for tx in range(x0 // self.tile * self.tile, x1 + 1, self.tile):
                        counts["tiles"] += 1
                        tile_max = max(self.depth[x, y]
                                       for y in range(ty, min(height, ty + self.tile))
                                       for x in range(tx, min(width, tx + self.tile)))
                        if not mode & 256 and min(v.depth for v in triangle) >= tile_max:
                            counts["rejected"] += 1
                            continue
                        regions.append((max(x0, tx), max(y0, ty),
                                        min(x1, tx + self.tile - 1),
                                        min(y1, ty + self.tile - 1)))
            for region in regions:
                for x, y, lambdas in samples(triangle, region):
                    record = [0, tag, x | y << 8 | fan << 16, *lambdas]
                    if draw:
                        depth = sum(l * v.depth for l, v in zip(lambdas, triangle)) // Q
                        counts["tested"] += 1
                        if depth >= self.depth[x, y]:
                            counts["failed"] += 1
                            continue
                        counts["passed"] += 1
                        self.depth[x, y] = depth
                        interpolated = attributes(triangle, lambdas)
                        audit = precision_audit(triangle, lambdas, interpolated)
                        if audit is not None:
                            result.audits.append(audit)
                        record += [depth, *interpolated]
                    result.records.append(record)
                    result.coordinates.add((x, y))
                    counts["emitted"] += 1
        assert counts["tested"] == counts["passed"] + counts["failed"]
        return finish(0 if counts["fans"] else 3)
