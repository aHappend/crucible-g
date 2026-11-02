"""Independent integer geometry, byte-memory, slab and alpha reference models.

These models derive public results from mathematical geometry and memory
transactions; they do not inspect DUT hierarchy or simulate RTL control states.
"""

from decimal import Decimal, localcontext, ROUND_HALF_UP

from oracle import MASK, Q, words64


def signed(value, bits=32):
    value &= (1 << bits)-1
    return value-(1 << bits) if value >> (bits-1) else value


def clamp(value, low, high):
    return min(high, max(low, value))


def transform(vertices, matrix, mode2d):
    result = []
    for vertex in vertices:
        vector = (*vertex[:2], 0, Q) if mode2d else vertex
        result.append(tuple(clamp(sum(matrix[4*r+c]*vector[c] for c in range(4)) >> 16,
                                  -(1 << 31), (1 << 31)-1) for r in range(4)))
    return result


def clip(vertices):
    distances = (lambda v: v[3]-1, lambda v: v[0]+v[3], lambda v: v[3]-v[0],
                 lambda v: v[1]+v[3], lambda v: v[3]-v[1],
                 lambda v: v[2], lambda v: v[3]-v[2])
    polygon = list(vertices)
    for plane, distance in enumerate(distances):
        output = []
        for i, b in enumerate(polygon):
            a = polygon[i-1]
            fa, fb = distance(a), distance(b)
            if (fa < 0) != (fb < 0):
                intersection = [signed(a[c]+((b[c]-a[c])*fa)//(fa-fb))
                                for c in range(len(a))]
                if plane == 0:
                    intersection[3] = 1
                elif plane in (1, 2):
                    intersection[0] = (-1 if plane == 1 else 1)*intersection[3]
                elif plane in (3, 4):
                    intersection[1] = (-1 if plane == 3 else 1)*intersection[3]
                else:
                    intersection[2] = 0 if plane == 5 else intersection[3]
                output.append(tuple(intersection))
            if fb >= 0:
                output.append(b)
        polygon = output
    return polygon


def project(vertex, width, height, depth24=False):
    x, y, z, w = vertex[:4]
    screen = (clamp((x+w)*width*256//(2*w), 0, width*256),
              clamp((w-y)*height*256//(2*w), 0, height*256))
    return (*screen, (1 << 40)//w,
            clamp(z*((1 << (24 if depth24 else 16))-1)//w,
                  0, (1 << (24 if depth24 else 16))-1), *vertex[4:])


def edge(a, b, p):
    return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])


def top_left(a, b):
    return b[1] < a[1] or (b[1] == a[1] and b[0] > a[0])


def samples(vertices, width, height, bounds=None):
    a, b, c = vertices
    area = edge(a, b, c)
    assert area > 0
    if bounds is None:
        bounds = (0, 0, width-1, height-1)
    for y in range(bounds[1], bounds[3]+1):
        for x in range(bounds[0], bounds[2]+1):
            p = (x*256+128, y*256+128)
            es = [edge(b, c, p), edge(c, a, p), edge(a, b, p)]
            pairs = ((b, c), (c, a), (a, b))
            if all(e > 0 or (e == 0 and top_left(*pair)) for e, pair in zip(es, pairs)):
                l0, l1 = es[0]*Q//area, es[1]*Q//area
                yield x, y, (l0, l1, Q-l0-l1)


class Raster:
    def __init__(self, tile_log2):
        self.tile = 1 << tile_log2
        self.configuration = None
        self.depth = {}

    def clear(self, tag, width, height, depth24):
        self.configuration = (width, height, depth24)
        self.depth = {(x, y): (1 << (24 if depth24 else 16))-1
                      for y in range(height) for x in range(width)}
        return [[1, tag, 0, *([0]*10)]]

    def draw(self, tag, width, height, opcode, matrix, vertices, attributes=None):
        generation = 1 if opcode in (0, 1) else 2
        size = 6 if generation == 1 else 13
        completion = [1, tag, 0, *([0]*(size-3))]
        if generation == 2 and self.configuration != (width, height, bool(opcode & 1)):
            completion[2] = 4
            return [completion]
        transformed = transform(vertices, matrix, bool(opcode & (1 if generation == 1 else 4)))
        augmented = [(*v, *(attributes[i] if attributes else ())) for i, v in enumerate(transformed)]
        polygon = clip(augmented)
        if len(polygon) < 3:
            completion[2] = 2
            return [completion]
        projected = [project(v, width, height, bool(opcode & 1)) for v in polygon]
        records = []
        counters = [0]*7
        for fan in range(len(projected)-2):
            vs = [projected[0], projected[fan+1], projected[fan+2]]
            area = edge(*vs)
            if area == 0:
                continue
            counters[1] += 1
            if area < 0:
                vs[1], vs[2] = vs[2], vs[1]
            if generation == 1:
                for x, y, weights in samples(vs, width, height):
                    records.append([0, tag, x | (y << 8) | (fan << 16), *weights])
                    counters[0] += 1
                continue
            xmin = min(v[0] for v in vs)//256
            ymin = min(v[1] for v in vs)//256
            xmax = min(width-1, max(v[0] for v in vs)//256)
            ymax = min(height-1, max(v[1] for v in vs)//256)
            for ty in range(ymin//self.tile*self.tile, ymax+1, self.tile):
                for tx in range(xmin//self.tile*self.tile, xmax+1, self.tile):
                    counters[2] += 1
                    bounds = (tx, ty, min(width-1, tx+self.tile-1), min(height-1, ty+self.tile-1))
                    maximum = max(self.depth[x, y] for y in range(ty, bounds[3]+1)
                                  for x in range(tx, bounds[2]+1))
                    if not opcode & 256 and min(v[3] for v in vs) >= maximum:
                        counters[3] += 1
                        continue
                    for x, y, weights in samples(vs, width, height, bounds):
                        z = sum(weight*v[3] for weight, v in zip(weights, vs))//Q
                        counters[4] += 1
                        if z >= self.depth[x, y]:
                            counters[6] += 1
                            continue
                        self.depth[x, y] = z
                        counters[5] += 1
                        counters[0] += 1
                        weighted = [weight*v[2] for weight, v in zip(weights, vs)]
                        denominator = sum(weighted)
                        attrs = [(sum(weight*v[4+c] for weight, v in zip(weighted, vs))//
                                  denominator) & MASK for c in range(6)]
                        records.append([0, tag, x | (y << 8) | (fan << 16), *weights, z, *attrs])
        completion[2] = 0 if counters[1] else 3
        if generation == 1:
            completion[3:5] = counters[:2]
        else:
            completion[3:10] = counters
        return [*records, completion]


def shader(attributes, texture, destination, program):
    vertex = [(clamp(signed(a), 0, Q)*255+32768)//Q for a in attributes]
    tex = [(texture >> (8*c)) & 255 for c in range(4)]
    dst = [(destination >> (8*c)) & 255 for c in range(4)]
    src = vertex if not program & 1 else [
        (v*t+127)//255 if program & 2 else t for v, t in zip(vertex, tex)]
    if not program & 4:
        return sum(v << (8*c) for c, v in enumerate(src))
    factors = [0, 255, src[3], 255-src[3], dst[3], 255-dst[3]]
    values = [min(255, (src[c]*factors[(program >> (9 if c == 3 else 3)) & 7]+
                       dst[c]*factors[(program >> (12 if c == 3 else 6)) & 7]+127)//255)
              for c in range(4)]
    return sum(v << (8*c) for c, v in enumerate(values))


class Texture:
    def __init__(self, width, height, base=0x1000, stride=64):
        self.width, self.height, self.base, self.stride = width, height, base, stride
        self.tags = {}

    def texel(self, x, y):
        return ((31*x+17*y+11) & 255) | (((13*x+29*y+23) & 255) << 8) | (
            ((7*x+3*y+41) & 255) << 16) | (192 << 24)

    def sample(self, u, v, error=False):
        u, v = clamp(signed(u), 0, (self.width-1)*Q), clamp(signed(v), 0, (self.height-1)*Q)
        x0, y0 = u//Q, v//Q
        points = ((x0, y0), (min(x0+1, self.width-1), y0),
                  (x0, min(y0+1, self.height-1)),
                  (min(x0+1, self.width-1), min(y0+1, self.height-1)))
        beats, hits, misses = [], 0, 0
        error_index = 0 if error is True else error if error is not False else None
        for x, y in points:
            line, tag = ((y >> 2) & 1, (x >> 2) & 1), (x >> 2, y >> 2)
            if self.tags.get(line) == tag:
                hits += 1
            else:
                misses += 1
                for j in range(16):
                    xx, yy = min((x//4)*4+j%4, self.width-1), min((y//4)*4+j//4, self.height-1)
                    fail = error_index is not None and len(beats) == error_index
                    beats.append((self.base+yy*self.stride+xx*4, self.texel(xx, yy), int(fail)))
                    if fail:
                        self.tags.clear()
                        return 0, hits, misses, beats, True
                self.tags[line] = tag
        fx, fy = u % Q, v % Q
        weights = ((Q-fx)*(Q-fy), fx*(Q-fy), (Q-fx)*fy, fx*fy)
        values = [sum(w*((self.texel(x, y) >> (8*c)) & 255)
                      for w, (x, y) in zip(weights, points)) for c in range(4)]
        rgba = sum(((value+(1 << 31)) >> 32) << (8*c) for c, value in enumerate(values))
        return rgba, hits, misses, beats, False


def slab(origin, direction, bounds, tmin, tmax):
    entry, exit_t = tmin, tmax
    for o, d, lo, hi in zip(origin, direction, bounds[:3], bounds[3:]):
        if d == 0:
            if not lo <= o <= hi:
                return None
        else:
            a, b = (lo-o)*Q, (hi-o)*Q
            if d < 0:
                a, b = b, a
            entry, exit_t = max(entry, -((-a)//d)), min(exit_t, b//d)
            if entry > exit_t:
                return None
    return entry


def bvh_query(nodes, root, origin, direction, tmin=0, tmax=Q, any_hit=False, depth=3):
    visited, stack, tested, maximum, best = set(), [], 0, 0, None
    status = 0
    if root == MASK:
        return [0, MASK, MASK, 0, 0, 0, 0], 0
    current = root
    while True:
        if current in visited:
            status = 4
            break
        if current not in nodes:
            status = 2
            break
        visited.add(current)
        leaf, left, right, identity, bounds = nodes[current]
        tested += 1
        candidate = slab(origin, direction, bounds, tmin, min(tmax, best[0]) if best else tmax)
        if candidate is not None:
            if leaf:
                choice = (candidate, identity, current)
                best = choice if best is None or choice < best else best
                if any_hit:
                    break
            else:
                if len(stack) == depth:
                    status = 3
                    break
                stack.append(right)
                maximum = max(maximum, len(stack))
                current = left
                continue
        if not stack:
            break
        current = stack.pop()
    if status or best is None:
        return [0, MASK, MASK, 0, 0, tested, maximum], status
    return [1, best[1], best[2], *words64(best[0]), tested, maximum], status


def alpha(x, y, mean, conic, opacity):
    dx, dy = x*4096+2048-mean[0], y*4096+2048-mean[1]
    a, b, c = conic
    quadratic = a*dx*dx+2*b*dx*dy+c*dy*dy
    if quadratic >= (1 << 45):
        return 0
    address = min(4096, (quadratic+(1 << 32)) >> 33)
    with localcontext() as context:
        context.prec = 60
        weight = int((Decimal(Q)*(-Decimal(address)/256).exp()).to_integral_value(
            rounding=ROUND_HALF_UP))
    return min(Q, (opacity*weight+32768)//Q)


def splats(width, height, scene, epsilon, background):
    order = sorted(scene, key=lambda i: (scene[i][0], i))
    records, evaluations, early = [], 0, 0
    for y in range(height):
        for x in range(width):
            transmittance, accum, tested = Q, [0, 0, 0], 0
            for i in order:
                if transmittance < epsilon:
                    break
                _, mean, conic, opacity, rgb = scene[i]
                weight = (transmittance*alpha(x, y, mean, conic, opacity)+32768)//Q
                accum = [s+weight*((rgb >> (8*c)) & 255) for c, s in enumerate(accum)]
                transmittance -= weight
                tested += 1
            rgba = (255 << 24) | sum(min(255, (s+transmittance*((background >> (8*c)) & 255)+
                                             32768)//Q) << (8*c) for c, s in enumerate(accum))
            records.append([x, y, rgba, transmittance, tested, len(scene)])
            evaluations += tested
            early += tested < len(scene)
    return records, evaluations, early
