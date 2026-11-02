"""Independent unbounded-integer models of the admitted CRUCIBLE-G5 ABI."""

from dataclasses import dataclass
from math import isqrt

Q = 65536
MASK = (1 << 32) - 1
SENTINEL = MASK


def signed(value, width=32):
    value &= (1 << width) - 1
    return value - (1 << width) if value >> (width - 1) else value


def words64(value):
    return [value & MASK, (value >> 32) & MASK]


def packet(tag, opcode, payload=(), metadata=0):
    result = [tag, metadata, opcode, *payload]
    if len(result) > 31:
        raise ValueError("G5 payload exceeds 31 words")
    return [x & MASK for x in result] + [0] * (31 - len(result))


def record(kind, tag, status=0, payload=()):
    result = [kind, tag, status, *payload]
    if len(result) > 16:
        raise ValueError("record exceeds 16 words")
    return [x & MASK for x in result] + [0] * (16 - len(result))


def completion(tag, opcode, count=0, extra=()):
    return record(0x50000000, tag, payload=[opcode, count, *extra])


def morton(xyz):
    return sum(((xyz[axis] >> bit) & 1) << (3 * bit + axis)
               for bit in range(10) for axis in range(3))


@dataclass(frozen=True)
class Primitive:
    slot: int
    identity: int
    vertices: tuple

    @property
    def bounds(self):
        return (tuple(min(v[a] for v in self.vertices) for a in range(3)),
                tuple(max(v[a] for v in self.vertices) for a in range(3)))

    @property
    def code(self):
        lo, hi = self.bounds
        midpoints = [(lo[a] + hi[a]) // 2 for a in range(3)]
        return morton([((m & MASK) ^ (1 << 31)) >> 22 for m in midpoints])

    def write(self, tag):
        return packet(tag, 0x900, [self.slot, self.identity,
                                  *(c for v in self.vertices for c in v)])


@dataclass(frozen=True)
class Node:
    index: int
    parent: int
    left: int
    right: int
    primitive: object
    bounds: tuple

    def response(self, tag):
        p = self.primitive
        return record(0x50000001, tag, payload=[
            self.index, int(p is not None), self.left, self.right,
            p.identity if p else SENTINEL, p.slot if p else SENTINEL,
            p.code if p else 0, *self.bounds[0], *self.bounds[1]])


def lbvh(primitives):
    ordered = sorted(primitives, key=lambda p: (p.code, p.slot))
    nodes = []

    def construct(items, parent):
        index = len(nodes)
        nodes.append(None)
        if len(items) == 1:
            p = items[0]
            nodes[index] = Node(index, parent, SENTINEL, SENTINEL, p, p.bounds)
        else:
            keys = [(p.code << 8) | p.slot for p in items]
            bit = (keys[0] ^ keys[-1]).bit_length() - 1
            split = next(i for i, key in enumerate(keys) if key & (1 << bit))
            left = construct(items[:split], index)
            right = construct(items[split:], index)
            boxes = [nodes[left].bounds, nodes[right].bounds]
            bounds = (tuple(min(b[0][a] for b in boxes) for a in range(3)),
                      tuple(max(b[1][a] for b in boxes) for a in range(3)))
            nodes[index] = Node(index, parent, left, right, None, bounds)
        return index

    if ordered:
        construct(ordered, SENTINEL)
    assert len(nodes) == max(0, 2 * len(primitives) - 1)
    leaves = [n.primitive.slot for n in nodes if n.primitive is not None]
    assert sorted(leaves) == sorted(p.slot for p in primitives)
    return nodes


def subtract(a, b):
    return tuple(x - y for x, y in zip(a, b))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def triangle(origin, direction, vertices, t_min, t_max, cull=False):
    if not 0 <= t_min <= t_max < (1 << 63):
        return 1, 0, 0, 0, 0
    v0, v1, v2 = vertices
    e1, e2, tv = subtract(v1, v0), subtract(v2, v0), subtract(origin, v0)
    p = cross(direction, e2)
    det = dot(e1, p)
    if det == 0 or (cull and det <= 0):
        return 0, 0, 0, 0, 0
    q = cross(tv, e1)
    un, vn, tn = dot(tv, p), dot(direction, q), dot(e2, q)
    if det < 0:
        det, un, vn, tn = -det, -un, -vn, -tn
    if (un < 0 or vn < 0 or un + vn > det or
            not t_min * det <= tn * Q <= t_max * det):
        return 0, 0, 0, 0, 0
    return 0, 1, tn * Q // det, un * Q // det, vn * Q // det


def triangle_command(tag, origin, direction, vertices, t_min=0, t_max=Q, cull=0):
    return packet(tag, 0x910, [cull, *origin, *direction,
                              *(c for v in vertices for c in v),
                              *words64(t_min), *words64(t_max)])


def triangle_record(tag, result):
    status, hit, t, u, v = result
    return record(0x50000010, tag, status, [hit, *words64(t), u, v])


def slab(origin, direction, bounds, t_min, t_max):
    entry, exit_t = t_min, t_max
    for o, d, lo, hi in zip(origin, direction, *bounds):
        if not d:
            if o < lo or o > hi:
                return False
        else:
            a, b = ((lo - o) * Q, (hi - o) * Q) if d > 0 else (
                (hi - o) * Q, (lo - o) * Q)
            entry = max(entry, a // d)
            exit_t = min(exit_t, -((-b) // d))
    return entry <= exit_t


def query(nodes, origin, direction, t_min=0, t_max=Q, cull=False):
    best = None
    tested, invoked = 0, 0

    def visit(index):
        nonlocal best, tested, invoked
        node = nodes[index]
        tested += 1
        upper = best[0] if best else t_max
        if not slab(origin, direction, node.bounds, t_min, upper):
            return
        if node.primitive is None:
            visit(node.left)
            visit(node.right)
        else:
            invoked += 1
            p = node.primitive
            _, hit, t, u, v = triangle(origin, direction, p.vertices,
                                       t_min, t_max, cull)
            if hit:
                candidate = (t, p.identity, p.slot, u, v)
                if best is None or candidate[:3] < best[:3]:
                    best = candidate

    if nodes:
        visit(0)
    exhaustive = []
    for node in nodes:
        if node.primitive:
            p = node.primitive
            _, hit, t, u, v = triangle(origin, direction, p.vertices,
                                       t_min, t_max, cull)
            if hit:
                exhaustive.append((t, p.identity, p.slot, u, v))
    assert best == (min(exhaustive, key=lambda c: c[:3]) if exhaustive else None)
    if best is None:
        return [0, 0, 0, 0, 0, SENTINEL, SENTINEL, tested, invoked]
    t, identity, slot, u, v = best
    return [1, *words64(t), u, v, identity, slot, tested, invoked]


def normal_dot(a, b):
    return max(0, min(Q, dot(a, b) // (1 << 14)))


@dataclass(frozen=True)
class Sample:
    shadow: int
    reflection: int
    depth: int = Q
    normal: tuple = (0, 0, 32768)
    motion: tuple = (0, 0)

    def write(self, tag, x, y):
        return packet(tag, 0x921, [x, y, self.shadow, self.reflection,
                                  self.depth, *self.normal, *self.motion])


def svgf(width, height, samples, history=None):
    """History consists of temporal moments and original guides, not filtered pixels."""
    assert len(samples) == width * height
    temporal, variances, accepted, next_history = [], [], [], []
    for index, sample in enumerate(samples):
        x, y = index % width, index // width
        px, py = x + sample.motion[0], y + sample.motion[1]
        prior = history[py * width + px] if (
            history is not None and 0 <= px < width and 0 <= py < height) else None
        use_history = bool(prior and abs(sample.depth - prior[2].depth) <= 4096
                           and normal_dot(sample.normal, prior[2].normal) >= 58982)
        means, seconds, variance = [], [], []
        for channel, luma in enumerate((sample.shadow, sample.reflection)):
            second = luma * luma // Q
            mean = luma
            if use_history:
                mean = (7 * prior[0][channel] + luma + 4) // 8
                second = (7 * prior[1][channel] + second + 4) // 8
            means.append(mean)
            seconds.append(second)
            variance.append(max(0, second - mean * mean // Q))
        temporal.append(means)
        variances.append(variance)
        accepted.append(int(use_history))
        next_history.append((means, seconds, sample))
    kernel = (1, 4, 6, 4, 1)
    for step in (1, 2, 4):
        output, output_variance = [], []
        for index, center in enumerate(samples):
            x, y = index % width, index // width
            channels, channel_variances = [], []
            for channel in (0, 1):
                sigma = isqrt(variances[index][channel] << 16)
                b = (max(256, 4 * sigma + 256) - 1).bit_length()
                sum_w = sum_l = sum_v = 0
                for ky in range(5):
                    for kx in range(5):
                        qx, qy = x + (kx - 2) * step, y + (ky - 2) * step
                        if not (0 <= qx < width and 0 <= qy < height):
                            continue
                        qi = qy * width + qx
                        tap = samples[qi]
                        d = normal_dot(center.normal, tap.normal)
                        depth_difference = abs(center.depth - tap.depth)
                        if qi != index and (d < 32768 or depth_difference > 4096):
                            continue
                        wn = Q if qi == index else d
                        if qi != index:
                            for _ in range(3):
                                wn = wn * wn // Q
                        wz = Q >> min(16, depth_difference >> 12)
                        wl = Q >> min(16, abs(temporal[index][channel] -
                                             temporal[qi][channel]) >> b)
                        w = ((wn * wz // Q) * wl // Q) * kernel[kx] * kernel[ky]
                        sum_w += w
                        sum_l += w * temporal[qi][channel]
                        sum_v += w * w * variances[qi][channel]
                assert sum_w > 0
                channels.append((sum_l + sum_w // 2) // sum_w)
                channel_variances.append((sum_v + sum_w * sum_w // 2) //
                                         (sum_w * sum_w))
            output.append(channels)
            output_variance.append(channel_variances)
        temporal, variances = output, output_variance
    return temporal, variances, accepted, next_history
