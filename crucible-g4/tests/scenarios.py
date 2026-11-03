"""Requirement-derived public command workloads; no DUT hierarchy access."""

from dataclasses import dataclass, field
from itertools import product
import random

from model import (G4Oracle, Node, Splat, U32, SPLAT_RENDER, compose, frame,
                   node_command, ray_command, splat_command, record)

PARAMETERS = [(1, 1, 0, 1, 1, 1), (3, 5, 1, 3, 3, 2),
              (16, 16, 3, 64, 64, 16), (256, 256, 3, 64, 64, 16),
              (256, 256, 4, 256, 256, 64)]


@dataclass
class Transaction:
    command: list
    records: list
    bound: int
    gap: int = 0
    stall: int = 0
    coverage: tuple = ()
    dma: list = field(default_factory=list)


class Workload:
    def __init__(self, parameters):
        self.parameters = parameters
        self.oracle = G4Oracle(parameters)
        self.transactions = []
        self.tag = 0

    def add(self, command, coverage=(), legal_tree=False, gap=None, stall=None):
        self.tag += 1
        command = command[:]
        command[0] = self.tag
        records = self.oracle.command(command, legal_tree=legal_tree)
        n = command[3] if command[2] == SPLAT_RENDER else 0
        width, height = command[1] & 65535, command[1] >> 16
        bound = 32 * (8 * n + 16) + 4 * n + 32
        bound += width * height * (256 * n + 128) + 256
        if command[2] != SPLAT_RENDER:
            bound = 2048 * self.parameters[3] + 128
        choice = len(self.transactions) % 5
        lengths = (0, 1, 2, 7, 31)
        gap = lengths[choice] if gap is None else gap
        stall = lengths[(choice + 2) % 5] if stall is None else stall
        # Framing, parent replay, serialized record transfer and external gaps.
        bound += len(command) * (gap + 2) + sum(len(r) for r, _ in records) * (stall + 2) + 1024
        self.transactions.append(Transaction(command, records, bound, gap, stall, coverage))
        return records

    def node(self, slot, node, coverage=()):
        return self.add(node_command(slot, node, 0), coverage)

    def ray(self, root, origin=(0, 0, 0), direction=(65536, 0, 0),
            coverage=(), **options):
        legal = options.pop("legal_tree", False)
        return self.add(ray_command(root, origin, direction, 0, **options),
                        coverage, legal_tree=legal)

    def splat(self, slot, splat, coverage=()):
        return self.add(splat_command(slot, splat, 0), coverage)

    def render(self, n, width=1, height=1, epsilon=0, background=0, coverage=()):
        return self.add(frame(SPLAT_RENDER, 0, {3: n, 4: epsilon, 5: background},
                              width | height << 16), coverage)

    def legacy_clear(self, color=0x12345678):
        self.tag += 1
        command = frame(1026, self.tag, {3: color}, 0x10001)
        expected = record(3, self.tag)
        self.transactions.append(Transaction(command, [(expected, True)], 10000,
                                             1, 7, ("legacy.clear",)))


def directed(parameters, compact=False):
    w = Workload(parameters)
    w.legacy_clear()
    w.ray(U32, coverage=("ray.empty",))
    w.ray(0, coverage=("ray.uninitialized",))
    w.render(1, coverage=("splat.uninitialized",))
    bounds = (-65536, -65536, -65536, 65536, 65536, 65536)
    w.node(0, Node(bounds, primitive=U32), ("ray.root_leaf",))
    signs = list(product((-1, 0, 1), repeat=3))
    if compact:
        signs = [(-1, 1, 0), (0, 0, 0), (1, -1, 1)]
    for sign in signs:
        w.ray(0, direction=tuple(k * 65537 for k in sign),
              coverage=(f"ray.direction.{sign}",), legal_tree=True)
    for origin in [(0, 65536, 0), (0, 65537, 0), (65536, 65536, 65536),
                   (-65536, -65536, -65536)]:
        w.ray(0, origin, coverage=("ray.parallel_boundary",))
    for bound in [(0, 0, 0, 0, 0, 0),
                  (1, -3, -1, 9, 7, 2),
                  (-(1 << 31), -(1 << 31), -(1 << 31),
                   (1 << 31) - 1, (1 << 31) - 1, (1 << 31) - 1)]:
        w.node(0, Node(bound, primitive=17))
        for origin, direction in [((0, 0, 0), (3, -7, 0)),
                                  (((1 << 31) - 1, 0, 0), (-(1 << 31), 1, 0))]:
            w.ray(0, origin, direction, coverage=("ray.extremes_fractional",))
    w.node(0, Node(bounds, primitive=23))
    for minimum, maximum in [(0, 0), (65536, 65536), (65537, 65537)]:
        w.ray(0, t_min=minimum, t_max=maximum, coverage=("ray.closed_t",))
    rejected = node_command(0, Node(bounds, primitive=99), 0)
    rejected[14] = 1
    w.add(rejected, ("ray.write_rejected",))
    w.ray(0, coverage=("ray.write_preserved",))
    bad_ray = ray_command(0, (0, 0, 0), (1, 0, 0), 0)
    bad_ray[4] = 2
    w.add(bad_ray, ("ray.reserved_error",))
    if parameters[3] >= 3:
        w.node(0, Node(bounds, False, left=1, right=2))
        w.node(1, Node(bounds, primitive=U32))
        w.node(2, Node(bounds, primitive=1))
        w.ray(0, any_hit=True, coverage=("ray.any_vs_closest",))
        w.ray(0, coverage=("ray.tie_primitive", "ray.push_pop"), legal_tree=True)
        w.node(1, Node(bounds, primitive=1))
        w.ray(0, coverage=("ray.tie_slot",), legal_tree=True)
        w.node(1, Node((2 * 65536, -65536, -65536, 3 * 65536, 65536, 65536),
                       primitive=1))
        w.ray(0, direction=(-65536, 0, 0), coverage=("ray.right_only",))
        w.node(0, Node(bounds, False, left=1, right=1))
        w.node(1, Node(bounds, primitive=1))
        w.ray(0, coverage=("ray.repeated_child",))
        w.node(0, Node(bounds, False, left=0, right=1))
        w.ray(0, coverage=("ray.cycle",))
    first = Splat(0x80000000, (1536, 2560), (65536, 32768, 196608), 40000, 0x1234EF)
    w.splat(0, first, ("splat.anisotropic_positive_b",))
    w.render(0, background=0x804020, coverage=("splat.empty",))
    w.render(1, background=0x804020, coverage=("splat.background",))
    for epsilon in (0, 1, 65536):
        w.render(1, epsilon=epsilon, coverage=(f"splat.epsilon.{epsilon}",))
    for splat in [Splat(0, (2048, 2048), (1, 0, 1), 0, 0xFFFFFF),
                  Splat(U32, (2048, 2048), (8388607, -8388606, 8388607), 65536, 0xFF),
                  Splat(1, (-8388608, 8388607), (8388607, 0, 8388607), 65536, 0xABCDEF),
                  Splat(1, (-1024, 3073), (196608, -32768, 65536), 32000, 0xABCDEF)]:
        w.splat(0, splat)
        w.render(1, coverage=("splat.signed_extremes",))
    bad = splat_command(0, first, 0)
    for index, value in [(5, 0x01000000), (7, 0), (8, 196608), (10, 65537),
                         (11, 0xFF123456), (12, 1)]:
        command = bad[:]
        command[index] = value
        w.add(command, ("splat.write_rejected",))
        w.render(1, coverage=("splat.write_preserved",))
    if parameters[4] >= 3:
        equal = [Splat(0, (2048, 2048), (65536, 32768, 131072), 32768, color)
                 for color in (0xFF, 0xFF00, 0xFF0000)]
        normal = compose((0, 0), equal, 0, 0)
        reverse = compose((0, 0), list(reversed(equal)), 0, 0)
        assert normal[0] != reverse[0], "equal-key scene must expose instability"
        for slot, splat in enumerate(equal):
            w.splat(slot, splat)
        w.render(3, coverage=("splat.equal_key_observable",))
        opaque = Splat(0, (2048, 2048), (1, 0, 2), 65536, 0x123456)
        w.splat(0, opaque)
        stopped = w.render(3, epsilon=1, coverage=("splat.termination_observable",))
        unstopped = w.render(3, epsilon=0, coverage=("splat.zero_disables_termination",))
        assert stopped[0][0][5] == unstopped[0][0][5]
        assert stopped[0][0][7] != unstopped[0][0][7]
        w.splat(0, Splat(0, (2048, 2048), (1, 0, 2), 32768, 0x123456))
        w.render(3, epsilon=32768, coverage=("splat.epsilon_equality",))
        w.render(3, epsilon=32769, coverage=("splat.epsilon_below",))
    if not compact:
        capacity = parameters[4]
        for pattern in ("reverse", "sorted", "equal", "high_bits"):
            for slot in range(capacity):
                key = {"reverse": capacity - slot, "sorted": slot,
                       "equal": 0xDEADBEEF, "high_bits": ((slot * 0x87654321) & U32)}[pattern]
                w.splat(slot, Splat(key, (2048 + slot, 2048 - slot),
                                    (65536, -8192, 131072), 257,
                                    (slot * 0x123456) & 0xFFFFFF))
            w.render(capacity, coverage=(f"splat.capacity.{pattern}",))
    if parameters == PARAMETERS[-1] and not compact:
        w.node(255, Node(bounds, primitive=0x87654321))
        w.ray(255, coverage=("ray.slot255",))
        for levels in (64, 65):
            for k in range(levels):
                w.node(k, Node(bounds, False, left=k + 1, right=levels + 1 + k))
                w.node(levels + 1 + k, Node(bounds, primitive=k))
            w.node(levels, Node(bounds, primitive=U32))
            w.ray(0, coverage=("ray.stack_boundary" if levels == 64 else "ray.stack_overflow",),
                  legal_tree=levels == 64)
        w.render(0, 256, 256, background=0x102030, coverage=("splat.full_frame",))
    return w


def generated_tree(rng, capacity):
    leaf_count = rng.randint(2, min(12, (capacity + 1) // 2))
    slots = list(range(capacity))
    rng.shuffle(slots)
    nodes, cursor = {}, 0

    def build(leaves):
        nonlocal cursor
        slot = slots[cursor]
        cursor += 1
        if leaves == 1:
            lo = tuple(rng.randint(-4 * 65536, 4 * 65536) for _ in range(3))
            hi = tuple(value + rng.randint(0, 3 * 65536) for value in lo)
            nodes[slot] = Node(lo + hi, primitive=rng.getrandbits(32))
        else:
            nleft = rng.randint(1, leaves - 1)
            left, right = build(nleft), build(leaves - nleft)
            a, b = nodes[left].bounds, nodes[right].bounds
            bounds = tuple(min(a[k], b[k]) for k in range(3))
            bounds += tuple(max(a[k + 3], b[k + 3]) for k in range(3))
            nodes[slot] = Node(bounds, False, left=left, right=right)
        return slot

    root = build(leaf_count)
    return root, nodes


def seeded(parameters, seed):
    w = Workload(parameters)
    rng = random.Random(seed)
    for tree in range(12):
        root, nodes = generated_tree(rng, parameters[3])
        for slot, node in nodes.items():
            w.node(slot, node)
        for query in range(22):
            origin = tuple(rng.randint(-6 * 65536, 6 * 65536) for _ in range(3))
            direction = tuple(rng.choice((0, rng.randint(-131072, 131072))) for _ in range(3))
            w.ray(root, origin, direction, any_hit=query % 7 == 0,
                  t_min=rng.choice((0, 1, 32768)), t_max=rng.choice((65536, 655360, (1 << 63) - 1)),
                  legal_tree=True, coverage=(f"seed.{seed}.tree.{tree}", f"seed.{seed}.ray"))
    for scene in range(16):
        count = (0, 1, 3, parameters[4])[scene % 4]
        for slot in range(count):
            a, c = rng.randint(1, 262144), rng.randint(1, 262144)
            b = rng.randint(-min(a, c) + 1, min(a, c) - 1)
            w.splat(slot, Splat(rng.choice((0, 1, 0x80000000, rng.getrandbits(32))),
                                (rng.randint(-4096, 16384), rng.randint(-4096, 16384)),
                                (a, b, c), rng.choice((0, 65536, rng.randint(1, 65535))),
                                rng.getrandbits(24)))
        w.render(count, rng.randint(1, 3), rng.randint(1, 3),
                 rng.choice((0, 1, 65536)), rng.getrandbits(24),
                 (f"seed.{seed}.scene",))
    return w
