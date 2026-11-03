"""Stimuli and measured requirement gates, independently derived from the spec."""

import itertools
import random
from collections import Counter, defaultdict

from reference import Command, IDENTITY, Q, edge, edge_kind, model


def workload():
    commands = []

    def add(vertices, width=8, height=8, mode=0, matrix=IDENTITY, seed=None):
        commands.append(Command(len(commands) + 1, width, height, mode,
                                tuple(matrix), tuple(tuple(v) for v in vertices), seed))

    def v(x, y, z=Q // 2, w=Q):
        return x, y, z, w

    # The first commands form a small, independently useful reproduction set.
    add([v(-Q, -Q), v(Q, -Q), v(-Q, Q)])
    add([v(Q, Q), v(-Q, Q), v(Q, -Q)])
    add([v(-2 * Q, -Q // 2), v(Q // 2, -Q // 2), v(0, Q)])
    add([v(-Q, -Q, -123, 0), v(Q, -Q, 99, -Q), v(-Q, Q, 2, 1)], mode=1)
    add([v(-Q, -Q), v(Q, -Q), v(-Q, Q)], width=3, height=5)
    small_count = len(commands)
    grid = [v(x * Q, y * Q) for x in (-1, 0, 1) for y in (-1, 0, 1)]
    for triangle in itertools.product(grid, repeat=3):
        add(triangle, 2, 2)
    for seed in (17, 89, 271):
        rng = random.Random(seed)
        for _ in range(100):
            matrix = list(IDENTITY)
            matrix[0] = rng.randint(Q // 2, 3 * Q // 2)
            matrix[5] = rng.randint(Q // 2, 3 * Q // 2)
            matrix[1] = rng.randint(-Q // 4, Q // 4)
            matrix[3] = rng.randint(-Q // 4, Q // 4)
            matrix[7] = rng.randint(-Q // 4, Q // 4)
            matrix[12] = rng.randint(-Q // 16, Q // 16)
            vertices = [v(rng.randint(-Q, Q), rng.randint(-Q, Q),
                          rng.randint(0, Q), rng.randint(Q // 2, 3 * Q // 2))
                        for _ in range(3)]
            add(vertices, mode=rng.randrange(2), matrix=matrix, seed=seed)
    inside = [v(-Q // 2, -Q // 2), v(Q // 2, -Q // 2), v(0, Q // 2)]
    outside = [
        v(0, 0, -Q // 2, -Q), v(-2 * Q, 0), v(2 * Q, 0),
        v(0, -2 * Q), v(0, 2 * Q), v(0, 0, -Q), v(0, 0, 2 * Q),
    ]
    for p, bad in enumerate(outside):
        for shift in (0, 701):
            tri = [bad, inside[1], inside[2]]
            tri[1] = (tri[1][0] + shift, *tri[1][1:])
            add(tri)
        # Translate a small triangle wholly outside just this plane.
        tri = []
        for x, y, z, w in inside:
            if p == 0:
                w = -Q
            elif p in (1, 2):
                x = (-3 if p == 1 else 3) * Q + x
            elif p in (3, 4):
                y = (-3 if p == 3 else 3) * Q + y
            elif p == 5:
                z = -Q
            else:
                z = 2 * Q
            tri.append((x, y, z, w))
        add(tri)
    add([v(-3 * Q, -2 * Q, -Q), v(2 * Q, 0, Q), v(0, 2 * Q)])
    for w in (-1, 0, 1):
        add([v(0, 0, 0, w), *inside[1:]])
    for tri in itertools.permutations(inside):
        add(tri)
    for _ in range(7):
        add([inside[0]] * 3)
        add([v(-Q, -Q), v(0, 0), v(Q, Q)])
        add([v(Q // 4, Q // 4, Q // 4, Q // 2),
             v(Q // 2, Q // 2, Q // 2, Q),
             v(Q, Q, Q, 2 * Q)])
    for sign in (-1, 1):
        matrix = list(IDENTITY)
        matrix[0] = matrix[3] = sign * ((1 << 31) - 1)
        add([v(Q, -Q), v(2 * Q, Q), v(3 * Q, 0)], matrix=matrix)
    matrix = list(IDENTITY)
    matrix[0], matrix[1], matrix[3] = 65537, -17, -1
    add([v(-Q + 1, -Q), v(Q - 3, -Q), v(0, Q)], matrix=matrix)
    dense = (65537, -17, 4097, 3, -2048, 50000, 1024, -4000,
             1234, -4321, 32768, 20000, 333, -777, 1000, 65536)
    for mode in (0, 1):
        add([v(-Q, -Q // 2, 12345, Q // 2),
             v(Q, -Q // 3, -23456, 2 * Q), v(0, Q, Q, Q)],
            mode=mode, matrix=dense)
    low, high = -(1 << 31), (1 << 31) - 1
    for axis in range(4):
        extreme = [list(vertex) for vertex in inside]
        extreme[0][axis], extreme[1][axis], extreme[2][axis] = low, high, -1
        add(extreme)
    for w, h in ((1, 1), (3, 5), (16, 16), (32, 24)):
        add([v(-Q, -Q), v(Q, -Q), v(-Q, Q)], w, h)
    # Small footprints at both extreme corners preserve the 65536 endpoint.
    add([v(Q - 1024, Q - 1024), v(Q, Q - 1024), v(Q, Q)], 256, 256)
    add([v(-Q, -Q), v(-Q + 1024, -Q), v(-Q, -Q + 1024)], 256, 256)
    for _ in range(12):
        add(inside)
        add([v(-Q // 3, -Q // 2), v(3 * Q // 4, -Q // 2), v(0, 3 * Q // 4)])
    # Exact half-pixel shared edges, each with opposite-side third vertices.
    for kind in ("horizontal", "vertical", "diagonal"):
        for i in range(6):
            if kind == "horizontal":
                a, b, c, d = (1, 9 + 2 * i), (27, 9 + 2 * i), (15, 1), (15, 31)
            elif kind == "vertical":
                a, b, c, d = (9 + 2 * i, 1), (9 + 2 * i, 27), (1, 15), (31, 15)
            else:
                a, b, c, d = (2, 2), (26, 26), (2, 24 - i), (24 - i, 2)
            # Coordinates above are half-pixel units in a 16x16 viewport.
            def sp(p):
                return v(p[0] * 4096 - Q, Q - p[1] * 4096)
            add([sp(a), sp(b), sp(c)], 16, 16)
            add([sp(b), sp(a), sp(d)], 16, 16)
    for w, h, mode in ((0, 1, 0), (257, 1, 0), (1, 0, 0),
                       (1, 257, 0), (1, 1, 2), (65535, 65535, 0)):
        add(inside, w, h, mode)
    return commands, small_count


def coverage(commands, results, observed_pixels):
    bins = Counter()
    partial, outside = [0] * 7, [0] * 7
    dimensions, modes, signs, wsigns, boundaries = set(), set(), set(), set(), set()
    shared = defaultdict(list)
    permutations = defaultdict(set)
    seeded, nonempty, nonidentity = Counter(), Counter(), Counter()
    overlap_candidates = defaultdict(list)
    degenerate_kinds = Counter()
    endpoints = set()
    for c, r in zip(commands, results):
        assert observed_pixels[c.tag] == len(r.records) - 1
        pixels = observed_pixels[c.tag]
        bins["commands"] += 1
        bins["pixels"] += pixels
        bins["fractional"] += r.fractional
        bins["negative_remainders"] += r.negative_remainders
        bins["multiple_fans"] += int(len(r.fans) > 1)
        signs.update(r.saturation)
        modes.add(c.mode)
        dimensions.add((c.width, c.height))
        wsigns.update("negative" if v[3] < 0 else "zero" if v[3] == 0
                     else "tiny" if v[3] == 1 else "positive" for v in c.vertices)
        if c.seed is not None:
            seeded[c.seed] += 1
            nonempty[c.seed] += int(pixels > 0)
            nonidentity[c.seed] += int(c.matrix != IDENTITY)
        for p, info in enumerate(r.planes):
            partial[p] += int(info["partial"] and len(r.projected) >= 3)
            outside[p] += int(info["fully_outside"] and r.records[-1][2] == 2)
        bins["mixed_planes"] += int(sum(p["partial"] for p in r.planes) >= 2)
        if r.records[-1][2] == 3:
            bins["degenerates"] += 1
            if len(set(c.vertices)) == 1:
                degenerate_kinds["identical"] += 1
            elif edge(c.vertices[0][:2], c.vertices[1][:2], c.vertices[2][:2]) == 0:
                degenerate_kinds["collinear"] += 1
            if len(set(r.projected)) == 1 and len(set(c.vertices)) > 1:
                degenerate_kinds["projective"] += 1
        permutations[tuple(sorted(c.vertices))].add(c.vertices)
        for x, y in r.pixels:
            if x == 0:
                boundaries.add("left")
            if x == c.width - 1:
                boundaries.add("right")
            if y == 0:
                boundaries.add("top")
            if y == c.height - 1:
                boundaries.add("bottom")
        if c.width == c.height == 256:
            endpoints.update(coordinate for point in r.projected for coordinate in point
                             if coordinate in (0, 65536))
        if len(r.fans) == 1:
            _, fan = r.fans[0]
            for a, b in zip(fan, fan[1:] + fan[:1]):
                shared[(c.width, c.height, tuple(sorted((a, b))))].append((c.tag, a, b))
        overlap_candidates[(c.width, c.height)].append((c.tag, r.pixels))
    pairs, tie_kinds = set(), set()
    for (width, height, segment), entries in shared.items():
        a, b = segment
        ties = any(edge(a, b, (256 * x + 128, 256 * y + 128)) == 0
                   and min(a[0], b[0]) <= 256 * x + 128 <= max(a[0], b[0])
                   and min(a[1], b[1]) <= 256 * y + 128 <= max(a[1], b[1])
                   for y in range(height) for x in range(width))
        if not ties:
            continue
        for first, second in itertools.combinations(entries, 2):
            if first[1:] == second[1:][::-1] and first[0] != second[0]:
                pairs.add(tuple(sorted((first[0], second[0]))))
                tie_kinds.add(edge_kind(a, b))
    overlaps = set()
    for entries in overlap_candidates.values():
        for (ta, pa), (tb, pb) in itertools.combinations(entries, 2):
            if pa & pb:
                overlaps.add((ta, tb))
    exhaustive = [(c.vertices, c.width, c.height, c.mode, c.matrix)
                  for c in commands if c.width == c.height == 2 and c.matrix == IDENTITY
                  and c.mode == 0]
    grid = [(x * Q, y * Q, Q // 2, Q) for x in (-1, 0, 1) for y in (-1, 0, 1)]
    expected_grid = set(itertools.product(grid, repeat=3))
    bins["exhaustive"] = len({v for v, *_ in exhaustive} & expected_grid)
    bins["shared_pairs"], bins["overlap_pairs"] = len(pairs), len(overlaps)
    requirements = {
        "exhaustive_729": bins["exhaustive"] == 729,
        "pixels_2000": bins["pixels"] >= 2000,
        "seeded_100_each": all(seeded[s] >= 100 for s in (17, 89, 271)),
        "nonempty_20_each": all(nonempty[s] >= 20 for s in (17, 89, 271)),
        "nonidentity_each": all(nonidentity[s] > 0 for s in (17, 89, 271)),
        "partial_twice_each_plane": min(partial) >= 2,
        "fully_clipped_each_plane": min(outside) >= 1,
        "both_modes": {0, 1} <= modes,
        "mixed_planes": bins["mixed_planes"] > 0,
        "input_w": {"negative", "zero", "tiny"} <= wsigns,
        "all_winding_permutations": any(len(v) == 6 for v in permutations.values()),
        "degenerates_20": bins["degenerates"] >= 20,
        "degenerate_categories": all(degenerate_kinds[k] > 0
                                     for k in ("identical", "collinear", "projective")),
        "saturation_signs": signs == {"negative", "positive"},
        "negative_floor_remainders": bins["negative_remainders"] > 0,
        "viewport_boundaries": len(boundaries) == 4,
        "dimensions": {(1, 1), (3, 5), (16, 16), (32, 24), (256, 256)} <= dimensions,
        "endpoint_65536": {0, 65536} <= endpoints,
        "overlap_pairs_12": len(overlaps) >= 12,
        "shared_pairs_16": len(pairs) >= 16,
        "all_tie_directions": tie_kinds == {"horizontal", "vertical", "diagonal"},
        "fractional_weights": bins["fractional"] > 0,
        "multiple_fans": bins["multiple_fans"] > 0,
    }
    return {
        "requirements": requirements, "counts": dict(bins),
        "partial_per_plane": partial, "fully_clipped_per_plane": outside,
        "seed_commands": dict(seeded), "seed_nonempty": dict(nonempty),
        "seed_nonidentity": dict(nonidentity), "degenerate_categories": dict(degenerate_kinds),
        "shared_tie_directions": sorted(tie_kinds),
    }
