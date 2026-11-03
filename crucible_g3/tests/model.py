"""Independent integer reference functions for the frozen CRUCIBLE-G3 contract."""

Q = 65536
PARENT_DRAWS = (2, 3, 6, 7, 258, 259, 262, 263)
G3_DRAWS = tuple(x | 512 for x in PARENT_DRAWS)
OPCODES = {0: 31, 1: 31, 4: 31, 5: 31,
           **{x: 49 for x in PARENT_DRAWS + G3_DRAWS},
           **{x: 31 for x in range(1024, 1028)}}
assert len(OPCODES) == 24


def signed(n, bits=32):
    n &= (1 << bits) - 1
    return n - (1 << bits) if n >> (bits - 1) else n


def pack(values, bits):
    return sum((x & ((1 << bits) - 1)) << (i * bits)
               for i, x in enumerate(values))


def channels(word):
    return [(word >> (8 * i)) & 255 for i in range(4)]


def bilinear(texels, fx, fy):
    weights = ((Q-fx)*(Q-fy), fx*(Q-fy), (Q-fx)*fy, fx*fy)
    return pack([(sum(channels(t)[c]*w for t, w in zip(texels, weights))
                  + (1 << 31)) >> 32 for c in range(4)], 8)


def shader(vertex, texture, destination, program):
    vertex = [(min(Q, max(0, signed(a)))*255 + 32768)//Q for a in vertex]
    tex, dst = channels(texture), channels(destination)
    src = vertex if not program & 1 else (
        [(a*b+127)//255 for a, b in zip(vertex, tex)] if program & 2 else tex)
    if not program & 4:
        return pack(src, 8)
    factors = (0, 255, src[3], 255-src[3], dst[3], 255-dst[3])
    out = []
    for c in range(4):
        shift = 9 if c == 3 else 3
        sf = factors[(program >> shift) & 7]
        df = factors[(program >> (shift+3)) & 7]
        out.append(min(255, (src[c]*sf+dst[c]*df+127)//255))
    return pack(out, 8)


def texture_word(x, y, salt=0):
    return pack(((17*x+37*y+salt) & 255, (61*x+7*y+salt*3) & 255,
                 (11*x+103*y+salt*5) & 255, (29*x+43*y+salt*7) & 255), 8)


class Cache:
    """Block address oracle; stores tags, not DUT scheduling or RAM indices."""

    def __init__(self, width, height, base=0x1000, stride=None, salt=0):
        self.width, self.height, self.base = width, height, base
        self.stride = stride if stride is not None else width*4+12
        self.salt = salt
        self.tags = {}

    def sample(self, u, v, fail_at=None):
        u = min((self.width-1)*Q, max(0, signed(u)))
        v = min((self.height-1)*Q, max(0, signed(v)))
        x, y = u//Q, v//Q
        coords = ((x, y), (min(x+1, self.width-1), y),
                  (x, min(y+1, self.height-1)),
                  (min(x+1, self.width-1), min(y+1, self.height-1)))
        reads, texels, hits, misses = [], [], 0, 0
        for x, y in coords:
            block = (x//4, y//4)
            line = (block[0] & 1, block[1] & 1)
            if self.tags.get(line) == block:
                hits += 1
            else:
                misses += 1
                for dy in range(4):
                    for dx in range(4):
                        rx = min(block[0]*4+dx, self.width-1)
                        ry = min(block[1]*4+dy, self.height-1)
                        error = fail_at == len(reads)
                        reads.append((self.base+ry*self.stride+rx*4,
                                      texture_word(rx, ry, self.salt), int(error)))
                        if error:
                            self.tags.clear()
                            return 0, True, reads, hits, misses
                self.tags[line] = block
            texels.append(texture_word(x, y, self.salt))
        return bilinear(texels, u % Q, v % Q), False, reads, hits, misses


def tile_coordinates(width, height, log2):
    size = 1 << log2
    for ty in range(0, height, size):
        for tx in range(0, width, size):
            for y in range(ty, min(ty+size, height)):
                for x in range(tx, min(tx+size, width)):
                    yield x, y


def transform(vertices, matrix, mode2d):
    out = []
    for vertex in vertices:
        vec = list(vertex[:4])
        if mode2d:
            vec[2:4] = [0, Q]
        out.append([min(2**31-1, max(-2**31,
                    sum(signed(matrix[4*r+c])*signed(vec[c]) for c in range(4))
                    // Q)) for r in range(4)] + list(vertex[4:]))
    return out


def clip(vertices, intersections=None):
    planes = (lambda v: v[3]-1, lambda v: v[0]+v[3],
              lambda v: v[3]-v[0], lambda v: v[1]+v[3],
              lambda v: v[3]-v[1], lambda v: v[2],
              lambda v: v[3]-v[2])
    polygon = vertices
    for plane, distance in enumerate(planes):
        result = []
        if not polygon:
            break
        a = polygon[-1]
        fa = distance(a)
        for b in polygon:
            fb = distance(b)
            if (fa >= 0) != (fb >= 0):
                if intersections is not None:
                    intersections[plane] += 1
                p = [signed(av + signed((bv-av)*fa//(fa-fb), 33))
                     for av, bv in zip(a, b)]
                if plane == 0:
                    p[3] = 1
                elif plane in (1, 2):
                    p[0] = signed(-p[3] if plane == 1 else p[3])
                elif plane in (3, 4):
                    p[1] = signed(-p[3] if plane == 3 else p[3])
                else:
                    p[2] = 0 if plane == 5 else p[3]
                result.append(p)
            if fb >= 0:
                result.append(b)
            a, fa = b, fb
        polygon = result
    return polygon


def project(v, width, height, depth24):
    x, y, z, w = v[:4]
    limit = (1 << (24 if depth24 else 16))-1
    return [min(width*256, max(0, (x+w)*width*256//(2*w))),
            min(height*256, max(0, (w-y)*height*256//(2*w))),
            min(limit, max(0, z*limit//w)), (1 << 40)//w] + v[4:]


def edge(a, b, p):
    return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])


def top_left(a, b):
    dx, dy = b[0]-a[0], b[1]-a[1]
    return dy < 0 or (dy == 0 and dx > 0)


IDENTITY = [Q if r == c else 0 for r in range(4) for c in range(4)]


def command(tag, opcode, width=1, height=1, vertices=None, attributes=None,
            matrix=None):
    vertices = vertices or [(-Q, -Q, Q//4, Q), (Q, -Q, Q//4, Q),
                            (-Q, Q, Q//4, Q)]
    words = [tag, width | height << 16, opcode] + list(matrix or IDENTITY)
    words += [v for vertex in vertices for v in vertex]
    if OPCODES.get(opcode, 31) == 49:
        attributes = attributes or [(Q//2, Q//2, Q, Q//3, Q//2, Q)]*3
        words += [a for vertex in attributes for a in vertex]
    return [x & 0xffffffff for x in words]


def state_command(tag, opcode, width=0, height=0, word3=0, word4=0):
    return [tag, width | height << 16, opcode, word3, word4] + [0]*26


class Renderer:
    """Transaction-level geometry, Z, color and DMA reference."""

    def __init__(self, max_width, max_height, tile_log2):
        self.max_width, self.max_height, self.tile_log2 = max_width, max_height, tile_log2
        self.depth_config = None
        self.color_config = None
        self.program = None
        self.cache = None
        self.depth, self.color = {}, {}
        self.events = {}

    def execute(self, words, texture_fail_at=None, dma_fail_at=None):
        tag, dims, opcode = words[:3]
        self.events = {}
        width, height = dims & 65535, dims >> 16
        g3 = opcode in G3_DRAWS or opcode in range(1024, 1028)
        n = 16 if g3 else 13 if opcode in PARENT_DRAWS+(4, 5) else 6
        terminal = [3 if g3 else 1, tag] + [0]*(n-2)
        records, reads, writes = [], [], []

        def finish(status):
            terminal[2] = status
            return records+[terminal], reads, writes

        viewport_ok = 1 <= width <= self.max_width and 1 <= height <= self.max_height
        if opcode not in OPCODES:
            return finish(1)
        if opcode in range(1024, 1028):
            if opcode == 1025:
                p = words[3]
                if dims or any(words[4:]) or p >> 15 or any(
                        (p >> shift) & 7 > 5 for shift in (3, 6, 9, 12)):
                    return finish(1)
                self.program = p
            elif opcode == 1026:
                if not viewport_ok or any(words[4:]):
                    return finish(1)
                self.color_config = (width, height)
                self.color = {(x, y): words[3] for y in range(height) for x in range(width)}
            else:
                base, stride = words[3:5]
                dim_ok = (1 <= width <= 256 and 1 <= height <= 256
                          if opcode == 1024 else viewport_ok)
                if (not dim_ok or base % 4 or stride % 4 or stride < 4*width or
                        base+(height-1)*stride+4*width-1 > 0xffffffff or any(words[5:])):
                    return finish(1)
                if opcode == 1024:
                    self.cache = Cache(width, height, base, stride)
                else:
                    if self.color_config != (width, height):
                        return finish(4)
                    for x, y in tile_coordinates(width, height, self.tile_log2):
                        error = len(writes) == dma_fail_at
                        writes.append((base+y*stride+4*x, self.color[x, y], 15,
                                       int(x == width-1 and y == height-1), int(error)))
                        if error:
                            return finish(5)
                        terminal[12] += 1
            return finish(0)
        if not viewport_ok:
            return finish(1)
        if opcode in (4, 5):
            limit = (1 << (24 if opcode == 5 else 16))-1
            self.depth_config = (width, height, opcode == 5)
            self.depth = {(x, y): limit for y in range(height) for x in range(width)}
            return finish(0)
        legacy = opcode in (0, 1)
        if g3 and (self.color_config != (width, height) or self.program is None or
                   self.program & 1 and self.cache is None):
            return finish(4)
        if not legacy and self.depth_config != (width, height, bool(opcode & 1)):
            return finish(4)
        vertices = [[signed(x) for x in words[19+i*4:23+i*4]] +
                    ([] if legacy else [signed(x) for x in words[31+i*6:37+i*6]])
                    for i in range(3)]
        self.events["clip_intersections"] = [0]*7
        vertices = clip(transform(vertices, words[3:19],
                                  bool(opcode == 1 if legacy else opcode & 4)),
                        self.events["clip_intersections"])
        if len(vertices) < 3:
            return finish(2)
        projected = [project(v, width, height, bool(opcode & 1)) for v in vertices]
        failed_texture = False
        for fan in range(len(projected)-2):
            a, b, c = projected[0], projected[fan+1], projected[fan+2]
            area = edge(a, b, c)
            if not area:
                continue
            terminal[4] += 1
            if area < 0:
                b, c, area = c, b, -area
            minx, miny = min(v[0] for v in (a, b, c))//256, min(v[1] for v in (a, b, c))//256
            maxx = min(width-1, max(v[0] for v in (a, b, c))//256)
            maxy = min(height-1, max(v[1] for v in (a, b, c))//256)
            if legacy:
                tiles = [(minx, miny, maxx+1, maxy+1)]
            else:
                size = 1 << self.tile_log2
                tiles = [(tx, ty, min(tx+size, width), min(ty+size, height))
                         for ty in range(miny//size*size, maxy//size*size+1, size)
                         for tx in range(minx//size*size, maxx//size*size+1, size)]
            for tx, ty, ex, ey in tiles:
                if not legacy:
                    terminal[5] += 1
                    if not opcode & 256 and min(v[2] for v in (a, b, c)) >= max(
                            self.depth[x, y] for y in range(ty, ey) for x in range(tx, ex)):
                        terminal[6] += 1
                        continue
                for y in range(max(miny, ty), min(maxy+1, ey)):
                    for x in range(max(minx, tx), min(maxx+1, ex)):
                        p = (x*256+128, y*256+128)
                        es = (edge(b, c, p), edge(c, a, p), edge(a, b, p))
                        if not all(e > 0 or e == 0 and top_left(v0, v1)
                                   for e, v0, v1 in zip(es, (b, c, a), (c, a, b))):
                            continue
                        ls = [es[0]*Q//area, es[1]*Q//area]
                        ls.append(Q-sum(ls))
                        packed_xy = x | y << 8 | fan << 16
                        if legacy:
                            records.append([0, tag, packed_xy]+ls)
                            terminal[3] += 1
                            continue
                        terminal[7] += 1
                        depth = sum(l*v[2] for l, v in zip(ls, (a, b, c)))//Q
                        if depth >= self.depth[x, y]:
                            terminal[9] += 1
                            continue
                        self.depth[x, y] = depth
                        terminal[8] += 1
                        weights = [l*v[3] for l, v in zip(ls, (a, b, c))]
                        attrs = [signed(sum(w*v[4+i] for w, v in zip(weights, (a, b, c)))
                                        // sum(weights)) for i in range(6)]
                        rec = [0, tag, packed_xy]+ls+[depth]+attrs
                        if g3:
                            if failed_texture:
                                continue
                            tex = 0
                            if self.program & 1:
                                tex, err, requests, hits, misses = self.cache.sample(
                                    attrs[0], attrs[1], None if texture_fail_at is None
                                    else texture_fail_at-len(reads))
                                reads.extend(requests)
                                terminal[10] += hits
                                terminal[11] += misses
                                if err:
                                    failed_texture = True
                                    continue
                            src = shader(attrs[2:], tex, self.color[x, y], self.program & ~4)
                            final = shader(attrs[2:], tex, self.color[x, y], self.program)
                            self.color[x, y] = final
                            rec = [2]+rec[1:]+[tex, src, final]
                        records.append(rec)
                        terminal[3] += 1
        return finish(5 if failed_texture else 0 if terminal[4] else 3)
