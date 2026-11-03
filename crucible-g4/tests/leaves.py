"""Public-pin arithmetic vectors, including fixed-stage latency expectations."""

from decimal import Decimal, localcontext
from itertools import product
import random
import re
import shutil
import uuid

from model import bilinear, exp_table, gaussian_alpha, gaussian_weight, shader, slab


def pack(values, widths):
    offset, packed = 0, 0
    for value, width in zip(values, widths):
        packed |= (value & ((1 << width) - 1)) << offset
        offset += width
    return packed


def leaf_vectors(compact=False):
    vectors = []
    rng = random.Random(93)
    divisions = [(1, 3), (-1, 3), (1, -3), (-1, -3), (0, 0), (3, 0),
                 (-(1 << 63), -1), (-(1 << 63), 1), ((1 << 63) - 1, 1),
                 (-(1 << 63), (1 << 63) - 1), ((1 << 63) - 1, -(1 << 63))]
    divisions += [(rng.randint(-(1 << 63), (1 << 63) - 1),
                   rng.randint(-(1 << 63), (1 << 63) - 1))
                  for _ in range(16 if compact else 256)]
    for numerator, denominator in divisions:
        error = denominator == 0 or (numerator == -(1 << 63) and denominator == -1)
        result = 0 if error else pack((numerator // denominator,
                                      -((-numerator) // denominator),
                                      abs(numerator) % abs(denominator)), (64, 64, 64))
        result |= int(error) << 192
        vectors.append((0, pack((numerator, denominator), (64, 64)), result, 68, 68))
    bounds = (-65536, -65536, -65536, 65536, 65536, 65536)
    for sign in product((-1, 0, 1), repeat=3):
        origin = (0, 65536 if sign[1] == 0 else 0, 0)
        direction = tuple(k * 65537 for k in sign)
        interval = slab(bounds, origin, direction, 0, (1 << 63) - 1)
        payload = pack((*origin, *direction, *bounds, 0, (1 << 63) - 1),
                       (32,) * 12 + (64, 64))
        expected = pack((int(interval is not None), *(interval or (0, 0))), (1, 64, 64))
        vectors.append((1, payload, expected, 0, 1024))
    table = exp_table()
    addresses = (0, 1, 255, 256, 4095, 4096, 4097, 8191) if compact else range(8192)
    for address in addresses:
        vectors.append((5, address, table[address] if address <= 4096 else 0, 1, 1))
    # Check the specified approximation bound independently over every rounding
    # boundary, its integer neighbors, the exponent cutoff and extreme support.
    nqs = [0, 1, (16 << 41) - 1, 16 << 41, (16 << 41) + 1, (1 << 75) - 1]
    for k in range(4096):
        boundary = (k << 33) + (1 << 32)
        nqs.extend((boundary - 1, boundary, boundary + 1))
    with localcontext() as context:
        context.prec = 90
        for nq in nqs:
            exact = Decimal(65536) * (-Decimal(nq) / (1 << 41)).exp()
            assert abs(Decimal(gaussian_weight(nq)) - exact) <= Decimal(129)
    conics = [((0, 0), (1536, 2560), (65536, 32768, 196608), 40000),
              ((0, 0), (-1024, 3073), (196608, -32768, 65536), 65536),
              ((255, 255), (-8388608, 8388607), (8388607, -8388606, 8388607), 65536),
              ((0, 0), (2048, 2048), (1, 0, 2), 0),
              ((0, 0), (2048, 2048), (1, 0, 2), 65536)]
    for _ in range(16 if compact else 512):
        a, c = rng.randint(1, 8388607), rng.randint(1, 8388607)
        b = rng.randint(-min(a, c) + 1, min(a, c) - 1)
        conics.append(((rng.randrange(256), rng.randrange(256)),
                       (rng.randint(-8388608, 8388607), rng.randint(-8388608, 8388607)),
                       (a, b, c), rng.randrange(65537)))
    # dx=32768,dy=0 gives exact half-index and cutoff boundaries by varying a.
    conics += [((8, 0), (2048, 2048), (a, 0, 1), 65536)
               for a in (1, 3, 5, 32767, 32768, 32769)]
    for pixel, mean, conic, opacity in conics:
        payload = pack((pixel[0] | pixel[1] << 8, *mean, *conic, opacity),
                       (16, 24, 24, 24, 24, 24, 17))
        vectors.append((2, payload, gaussian_alpha(pixel, mean, conic, opacity), 11, 11))
    texel_sets = [(0, 1, 0, 1), (0xFFFFFFFF, 0, 0, 0xFFFFFFFF),
                  (0x01020304, 0xFEFDFCFB, 0x10203040, 0x55667788)]
    for texels in texel_sets:
        for fx, fy in product((0, 1, 32768, 65535), repeat=2):
            payload = pack((*texels, fx, fy), (32, 32, 32, 32, 16, 16))
            vectors.append((3, payload, bilinear(texels, fx, fy), 5, 5))
    for _ in range(8 if compact else 256):
        texels = tuple(rng.getrandbits(32) for _ in range(4))
        fx, fy = rng.randrange(65536), rng.randrange(65536)
        vectors.append((3, pack((*texels, fx, fy), (32,) * 4 + (16, 16)),
                        bilinear(texels, fx, fy), 5, 5))
    for sf, df in product(range(6), repeat=2):
        for source_mode in (0, 1, 3):
            program = source_mode | 4 | sf << 3 | df << 6 | df << 9 | sf << 12
            vertex = (-7, 32768, 131072, 16448)
            texture, destination = 0x7F123456, 0xC0123456
            payload = pack((*vertex, texture, destination, program), (32,) * 6 + (15,))
            vectors.append((4, payload, shader(vertex, texture, destination, program), 6, 6))
    for epsilon, alphas in [(0, (65536, 0, 65536)), (1, (65536,)),
                            (32768, (32768, 32768)), (32769, (32768,)),
                            (65536, (1,)), (0, (257, 32767, 65535, 0))]:
        background = 0x123456
        vectors.append((6, background | epsilon << 24, 0, 0, 1))
        transmittance, colors = 65536, [0, 0, 0]
        for alpha in alphas:
            assert transmittance >= epsilon
            color = 0x654321
            weight = (transmittance * alpha + 32768) // 65536
            transmittance -= weight
            colors = [total + weight * ((color >> (8 * k)) & 255) for k, total in enumerate(colors)]
            vectors.append((7, alpha | color << 17, int(transmittance < epsilon), 4, 4))
        channels = [min(255, (total + transmittance * ((background >> (8 * k)) & 255) + 32768) // 65536)
                    for k, total in enumerate(colors)]
        rgba = 0xFF000000 | sum(channel << (8 * k) for k, channel in enumerate(channels))
        vectors.append((8, 0, rgba | transmittance << 32, 4, 4))
    return vectors


def compile_leaves(run, simulator, rtl=None, stem="leaves"):
    source_root = rtl or run.root / "rtl"
    sources = [run.relative(source_root / name) for name in
               ("g4_divider.sv", "g4_slab.sv", "g4_conic.sv", "g4_exp_rom.sv",
                "g4_compositor.sv", "g3_bilinear.sv", "g3_shader_pipeline.sv")]
    tb = run.relative(run.root / "tests/leaf_tb.sv")
    if simulator == "iverilog":
        binary = run.folder / f"{stem}.vvp"
        run.execute(["iverilog", "-g2012", "-Wall", "-s", "leaf_tb", "-o",
                     run.relative(binary), tb, *sources], f"{stem}-compile")
        return ["vvp", run.relative(binary)]
    obj = run.folder / f"{stem}-obj-{uuid.uuid4().hex[:8]}"
    binary = run.folder / f"{stem}.bin"
    run.execute(["verilator", "--binary", "--timing", "--top-module", "leaf_tb",
                 "-Wno-fatal", "-j", "2", "--Mdir", run.relative(obj),
                 "-o", f"../{binary.name}", tb, *sources], f"{stem}-compile")
    shutil.rmtree(obj)
    return [run.relative(binary)]


def simulate_leaves(run, executable, vectors, stem="leaves", expect_mismatch=False):
    path = run.folder / f"{stem}.vectors.txt"
    with path.open("w") as stream:
        stream.write(f"{len(vectors)}\n")
        for kind, payload, expected, latency, bound in vectors:
            stream.write(f"{kind} {payload:0128x} {expected:064x} {latency} {bound}\n")
    out, err, code = run.execute([*executable, f"+vectors={run.relative(path)}"],
                                 stem, expect_exit=None)
    if expect_mismatch:
        assert code != 0 and "NUMERICAL_MISMATCH" in out + err, "mutation did not produce a numerical mismatch"
        return
    if code:
        raise RuntimeError(f"{stem}: leaf simulation exited {code}; see {run.relative(run.folder / (stem + '.stdout.txt'))}")
    rows = re.findall(r"^LEAF_SUMMARY COMPARISONS (\d+) FIXED_LATENCIES (\d+)$", out, re.M)
    assert len(rows) == 1 and int(rows[0][0]) == len(vectors) and int(rows[0][1]) > 0
    counts = {str(kind): sum(vector[0] == kind for vector in vectors) for kind in range(9)}
    run.receipt["comparisons"][stem] = {"cases": len(vectors), "fixed_latencies": int(rows[0][1]),
                                       "by_leaf_kind": counts}
    run.save()
