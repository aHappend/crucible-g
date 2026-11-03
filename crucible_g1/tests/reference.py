"""Arbitrary-precision specification model; no RTL state or intermediates."""

from dataclasses import dataclass, field

Q = 65536
IDENTITY = tuple(Q if r == c else 0 for r in range(4) for c in range(4))


@dataclass(frozen=True)
class Command:
    tag: int
    width: int
    height: int
    mode: int
    matrix: tuple
    vertices: tuple
    seed: int | None = None

    def words(self):
        return [x & 0xFFFFFFFF for x in (
            self.tag, self.width | self.height << 16, self.mode,
            *self.matrix, *(c for v in self.vertices for c in v)
        )]


@dataclass
class Result:
    records: list = field(default_factory=list)
    transformed: list = field(default_factory=list)
    planes: list = field(default_factory=list)
    projected: list = field(default_factory=list)
    fans: list = field(default_factory=list)
    pixels: set = field(default_factory=set)
    saturation: set = field(default_factory=set)
    negative_remainders: int = 0
    fractional: int = 0
    ties: set = field(default_factory=set)
    cycle_bound: int = 1000

    def words(self):
        return [w for record in self.records for w in record]


def distance(v, plane):
    x, y, z, w = v
    return (w - 1, x + w, w - x, y + w, w - y, z, w - z)[plane]


def edge(a, b, p):
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def top_left(a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    return dy < 0 or (dy == 0 and dx > 0)


def edge_kind(a, b):
    return "vertical" if a[0] == b[0] else "horizontal" if a[1] == b[1] else "diagonal"


def model(command):
    c, out = command, Result()
    if c.mode not in (0, 1) or not (1 <= c.width <= 256 and 1 <= c.height <= 256):
        out.records.append([1, c.tag, 1, 0, 0, 0])
        return out
    for vertex in c.vertices:
        v = vertex if c.mode == 0 else (*vertex[:2], 0, Q)
        transformed = []
        for row in range(4):
            total = sum(c.matrix[4 * row + k] * v[k] for k in range(4))
            scaled = total // Q
            if total < 0 and total % Q:
                out.negative_remainders += 1
            if scaled < -(1 << 31):
                out.saturation.add("negative")
            if scaled > (1 << 31) - 1:
                out.saturation.add("positive")
            transformed.append(max(-(1 << 31), min((1 << 31) - 1, scaled)))
        out.transformed.append(tuple(transformed))
    polygon = out.transformed[:]
    for plane in range(7):
        previous, polygon = polygon, []
        distances = [distance(v, plane) for v in previous]
        crossings = 0
        if previous:
            a = previous[-1]
            for b in previous:
                fa, fb = distance(a, plane), distance(b, plane)
                if (fa >= 0) != (fb >= 0):
                    crossings += 1
                    intersection = []
                    for ac, bc in zip(a, b):
                        n, d = (bc - ac) * fa, fa - fb
                        if n * d < 0 and n % d:
                            out.negative_remainders += 1
                        intersection.append(ac + n // d)
                    if plane == 0:
                        intersection[3] = 1
                    elif plane in (1, 2):
                        intersection[0] = (-1 if plane == 1 else 1) * intersection[3]
                    elif plane in (3, 4):
                        intersection[1] = (-1 if plane == 3 else 1) * intersection[3]
                    else:
                        intersection[2] = 0 if plane == 5 else intersection[3]
                    polygon.append(tuple(intersection))
                if fb >= 0:
                    polygon.append(b)
                a = b
        assert len(polygon) <= 384
        out.planes.append({
            "input": len(previous), "output": len(polygon),
            "crossings": crossings,
            "partial": bool(distances) and min(distances) < 0 <= max(distances),
            "fully_outside": bool(distances) and max(distances) < 0,
        })
        out.cycle_bound += len(previous) * 12 + crossings * 4 * 112 + 20
    if len(polygon) < 3:
        out.records.append([1, c.tag, 2, 0, 0, 0])
        return out
    for x, y, z, w in polygon:
        assert w >= 1
        out.projected.append((
            max(0, min(c.width * 256, (x + w) * c.width * 256 // (2 * w))),
            max(0, min(c.height * 256, (w - y) * c.height * 256 // (2 * w))),
        ))
    out.cycle_bound += len(polygon) * 240
    for fan_index in range(len(polygon) - 2):
        a, b, d = (out.projected[0], out.projected[fan_index + 1],
                   out.projected[fan_index + 2])
        area = edge(a, b, d)
        if area == 0:
            continue
        if area < 0:
            b, d, area = d, b, -area
        fan = (a, b, d)
        out.fans.append((fan_index, fan))
        lo_x, hi_x = min(v[0] for v in fan) // 256, min(
            c.width - 1, max(v[0] for v in fan) // 256)
        lo_y, hi_y = min(v[1] for v in fan) // 256, min(
            c.height - 1, max(v[1] for v in fan) // 256)
        out.cycle_bound += max(0, hi_x - lo_x + 1) * max(0, hi_y - lo_y + 1) * 260 + 100
        # Deliberately enumerate the whole viewport, not the RTL bounding box.
        for y in range(c.height):
            for x in range(c.width):
                p = (256 * x + 128, 256 * y + 128)
                edges = ((b, d), (d, a), (a, b))
                values = [edge(u, v, p) for u, v in edges]
                if min(values) >= 0:
                    for (u, v), e in zip(edges, values):
                        if e == 0:
                            out.ties.add(edge_kind(u, v))
                if not all(e > 0 or (e == 0 and top_left(u, v))
                           for e, (u, v) in zip(values, edges)):
                    continue
                l0, l1 = values[0] * Q // area, values[1] * Q // area
                weights = (l0, l1, Q - l0 - l1)
                assert sum(weights) == Q and all(0 <= w <= Q for w in weights)
                out.fractional += int(any(w not in (0, Q) for w in weights))
                out.records.append([0, c.tag, fan_index << 16 | y << 8 | x, *weights])
                out.pixels.add((x, y))
    pixels = len(out.records)
    out.records.append([1, c.tag, 0 if out.fans else 3, pixels, len(out.fans), 0])
    out.cycle_bound += len(out.records) * 6 * 100
    return out
