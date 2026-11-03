"""Independent integer/rational CRUCIBLE-G4 public-packet reference.

The models do not read RTL, simulator results, or parent verification scripts.
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP, localcontext
from fractions import Fraction
from functools import lru_cache

U32 = (1 << 32) - 1
BVH_WRITE, RAY_QUERY, SPLAT_WRITE, SPLAT_RENDER = 0x800, 0x801, 0x810, 0x811
ACK, RAY_RESULT, SPLAT_PIXEL, SPLAT_DONE = range(0x40000000, 0x40000004)


def signed(value, bits):
    value &= (1 << bits) - 1
    return value - (1 << bits) if value >> (bits - 1) else value


def words64(value):
    return [value & U32, (value >> 32) & U32]


def pack_rgb(channels):
    return sum(channel << (8 * index) for index, channel in enumerate(channels))


def rgb(value):
    return tuple((value >> (8 * index)) & 255 for index in range(3))


def record(kind, tag, status=0, fields=()):
    result = [kind, tag & U32, status, *fields]
    assert len(result) <= 16
    return result + [0] * (16 - len(result))


def frame(opcode, tag, fields=None, dimensions=0):
    result = [0] * 31
    result[:3] = [tag & U32, dimensions, opcode]
    for index, value in (fields or {}).items():
        result[index] = value & U32
    return result


@dataclass(frozen=True)
class Node:
    bounds: tuple
    leaf: bool = True
    primitive: int = 0
    left: int = 0
    right: int = 0


def node_command(slot, node, tag):
    fields = {3: slot, 4: int(node.leaf), 5: node.left,
              6: node.right, 7: node.primitive}
    fields.update(enumerate(node.bounds, 8))
    return frame(BVH_WRITE, tag, fields)


def ray_command(root, origin, direction, tag, t_min=0, t_max=(1 << 63) - 1,
                any_hit=False):
    fields = {3: root, 4: int(any_hit)}
    fields.update(enumerate(origin, 5))
    fields.update(enumerate(direction, 8))
    fields.update(enumerate(words64(t_min) + words64(t_max), 11))
    return frame(RAY_QUERY, tag, fields)


def slab(bounds, origin, direction, t_min, t_max):
    """Intersect rational intervals, then intersect their integer lattice."""
    low, high = Fraction(t_min), Fraction(t_max)
    for axis, (o, d) in enumerate(zip(origin, direction)):
        lo, hi = bounds[axis], bounds[axis + 3]
        if not d:
            if not lo <= o <= hi:
                return None
            continue
        endpoints = (Fraction((lo - o) * 65536, d),
                     Fraction((hi - o) * 65536, d))
        low, high = max(low, min(endpoints)), min(high, max(endpoints))
    enter = -((-low.numerator) // low.denominator)
    leave = high.numerator // high.denominator
    return (enter, leave) if enter <= leave else None


def exhaustive_closest(nodes, root, origin, direction, t_min, t_max):
    """Independent leaf enumeration, without stack pruning or DFS selection."""
    if root == U32:
        return None
    leaves = []

    def collect(index):
        node = nodes[index]
        if node.leaf:
            interval = slab(node.bounds, origin, direction, t_min, t_max)
            if interval:
                leaves.append((interval[0], node.primitive, index))
        else:
            collect(node.left)
            collect(node.right)

    collect(root)
    return min(leaves) if leaves else None


def traverse(nodes, root, origin, direction, t_min, t_max, any_hit, depth):
    """Recursive left-first tree walk; pending-right depth is diagnostic state."""
    tested, maximum, status, best = 0, 0, 0, None
    visited = set()

    def visit(index, pending):
        nonlocal tested, maximum, status, best
        if status or (any_hit and best is not None):
            return
        if index in visited:
            status = 4
            return
        if index not in nodes:
            status = 2
            return
        visited.add(index)
        tested += 1
        node = nodes[index]
        interval = slab(node.bounds, origin, direction, t_min,
                        min(t_max, best[0]) if best else t_max)
        if interval is None:
            return
        if node.leaf:
            candidate = (interval[0], node.primitive, index)
            best = candidate if best is None else min(best, candidate)
            return
        if pending == depth:
            status = 3
            return
        maximum = max(maximum, pending + 1)
        visit(node.left, pending + 1)
        visit(node.right, pending)

    if root != U32:
        visit(root, 0)
    return status, None if status else best, tested, maximum


@lru_cache(maxsize=1)
def exp_table():
    with localcontext() as context:
        context.prec = 90
        return tuple(int((Decimal(65536) * (-Decimal(k) / 256).exp())
                         .to_integral_value(rounding=ROUND_HALF_UP))
                     for k in range(4097))


def gaussian_weight(nq):
    assert nq >= 0, "positive definite quadratic must be nonnegative"
    if nq >= 16 * (1 << 41):
        return 0
    k = min(4096, (nq + (1 << 32)) // (1 << 33))
    return exp_table()[k]


def gaussian_alpha(pixel, mean, conic, opacity):
    dx, dy = (pixel[index] * 4096 + 2048 - mean[index] for index in range(2))
    a, b, c = conic
    nq = a * dx * dx + 2 * b * dx * dy + c * dy * dy
    return min(65536, (opacity * gaussian_weight(nq) + 32768) // 65536)


@dataclass(frozen=True)
class Splat:
    key: int
    mean: tuple
    conic: tuple
    opacity: int
    color: int


def splat_command(slot, splat, tag):
    values = [slot, splat.key, *splat.mean, *splat.conic, splat.opacity, splat.color]
    return frame(SPLAT_WRITE, tag, dict(enumerate(values, 3)))


def compose(pixel, splats, epsilon, background):
    transmittance, colors, evaluated = 65536, [0, 0, 0], 0
    for splat in sorted(splats, key=lambda item: item.key):
        if transmittance < epsilon:
            break
        alpha = gaussian_alpha(pixel, splat.mean, splat.conic, splat.opacity)
        weight = (transmittance * alpha + 32768) // 65536
        colors = [total + weight * channel
                  for total, channel in zip(colors, rgb(splat.color))]
        transmittance -= weight
        evaluated += 1
    output = [min(255, (total + transmittance * channel + 32768) // 65536)
              for total, channel in zip(colors, rgb(background))]
    return pack_rgb(output) | 0xFF000000, transmittance, evaluated


def sign_extended24(value):
    return signed(value, 32) == signed(value, 24)


class G4Oracle:
    def __init__(self, parameters):
        self.width, self.height, _, self.max_nodes, self.max_splats, self.depth = parameters
        self.nodes, self.splats = {}, {}

    def reset(self):
        self.nodes.clear()
        self.splats.clear()

    def command(self, command, legal_tree=False):
        assert len(command) == 31
        tag, dimensions, opcode = command[:3]
        slot = command[3]
        if opcode == BVH_WRITE:
            bounds = tuple(signed(value, 32) for value in command[8:14])
            leaf = command[4] == 1
            valid = (not dimensions and command[4] in (0, 1)
                     and slot < self.max_nodes and not any(command[14:])
                     and all(bounds[k] <= bounds[k + 3] for k in range(3)))
            valid &= ((command[5] == command[6] == 0) if leaf else
                      (command[7] == 0 and command[5] < self.max_nodes
                       and command[6] < self.max_nodes))
            if valid:
                self.nodes[slot] = Node(bounds, leaf, command[7], command[5], command[6])
            return [(record(ACK, tag, 0 if valid else 1, (opcode, slot)), True)]
        if opcode == RAY_QUERY:
            t_min = signed(command[11] | command[12] << 32, 64)
            t_max = signed(command[13] | command[14] << 32, 64)
            valid = (not dimensions and command[4] in (0, 1)
                     and (slot < self.max_nodes or slot == U32)
                     and 0 <= t_min <= t_max and not any(command[15:]))
            origin = tuple(signed(value, 32) for value in command[5:8])
            direction = tuple(signed(value, 32) for value in command[8:11])
            result = (traverse(self.nodes, slot, origin, direction, t_min, t_max,
                               command[4], self.depth) if valid else (1, None, 0, 0))
            status, hit, tested, maximum = result
            if legal_tree and not command[4] and valid:
                assert status == 0
                assert hit == exhaustive_closest(self.nodes, slot, origin, direction,
                                                 t_min, t_max)
            fields = [int(hit is not None), hit[1] if hit else U32,
                      hit[2] if hit else U32, *words64(hit[0] if hit else 0),
                      tested, maximum]
            return [(record(RAY_RESULT, tag, status, fields), True)]
        if opcode == SPLAT_WRITE:
            mean = tuple(signed(value, 24) for value in command[5:7])
            conic = tuple(signed(value, 24) for value in command[7:10])
            a, b, c = conic
            valid = (not dimensions and slot < self.max_splats
                     and all(sign_extended24(value) for value in command[5:10])
                     and a > 0 and c > 0 and a * c > b * b
                     and command[10] <= 65536 and command[11] < (1 << 24)
                     and not any(command[12:]))
            if valid:
                self.splats[slot] = Splat(command[4], mean, conic,
                                          command[10], command[11])
            return [(record(ACK, tag, 0 if valid else 1, (opcode, slot)), True)]
        if opcode == SPLAT_RENDER:
            width, height = dimensions & 65535, dimensions >> 16
            n, epsilon, background = command[3:6]
            valid = (0 < width <= self.width and 0 < height <= self.height
                     and n <= self.max_splats and epsilon <= 65536
                     and background < (1 << 24) and not any(command[6:]))
            status = 1 if not valid else 2 if any(k not in self.splats for k in range(n)) else 0
            if status:
                return [(record(SPLAT_DONE, tag, status, (0, n, 0, 0)), True)]
            splats = [self.splats[index] for index in range(n)]
            results, evaluations, early = [], 0, 0
            for y in range(height):
                for x in range(width):
                    rgba, transmittance, evaluated = compose((x, y), splats, epsilon, background)
                    results.append((record(SPLAT_PIXEL, tag, fields=(
                        x, y, rgba, transmittance, evaluated, n)), False))
                    evaluations += evaluated
                    early += evaluated < n
            results.append((record(SPLAT_DONE, tag, fields=(
                width * height, n, evaluations, early)), True))
            return results
        raise ValueError(f"not a G4 command: {opcode:#x}")


def bilinear(texels, fx, fy):
    weights = ((65536 - fx) * (65536 - fy), fx * (65536 - fy),
               (65536 - fx) * fy, fx * fy)
    channels = [sum(((texel >> (8 * channel)) & 255) * weight
                    for texel, weight in zip(texels, weights))
                for channel in range(4)]
    return sum(((total + (1 << 31)) // (1 << 32)) << (8 * channel)
               for channel, total in enumerate(channels))


def shader(vertex, texture, destination, program):
    vertex8 = [min(65536, max(0, value)) * 255 + 32768 for value in vertex]
    source = [value // 65536 for value in vertex8]
    if program & 1:
        texture8 = [(texture >> (8 * k)) & 255 for k in range(4)]
        source = ([(a * b + 127) // 255 for a, b in zip(source, texture8)]
                  if program & 2 else texture8)
    dst = [(destination >> (8 * k)) & 255 for k in range(4)]
    if program & 4:
        factors = [0, 255, source[3], 255 - source[3], dst[3], 255 - dst[3]]
        result = []
        for k in range(4):
            sf = (program >> (9 if k == 3 else 3)) & 7
            df = (program >> (12 if k == 3 else 6)) & 7
            result.append(min(255, (source[k] * factors[sf] + dst[k] * factors[df] + 127) // 255))
        source = result
    return sum(channel << (8 * k) for k, channel in enumerate(source))
