"""Requirement-driven transactions and independent expected public effects."""

import json
import random

from model import (Q, OPCODES, PARENT_DRAWS, G3_DRAWS, IDENTITY, Renderer,
                   command, state_command, tile_coordinates)


class Scenario:
    def __init__(self, path, config):
        self.path, self.config = path, config
        self.model = Renderer(*config)
        self.rows, self.ledger = [], []
        self.tag = 0x81000000

    def add(self, words, label, **errors):
        self.tag += 1
        words = list(words)
        words[0] = self.tag
        assert len(words) == OPCODES.get(words[2], 31)
        records, reads, writes = self.model.execute(words, **errors)
        assert records and records[-1][0] in (1, 3)
        flattened = [(word & 0xffffffff, int(ri == len(records)-1 and wi == len(record)-1))
                     for ri, record in enumerate(records)
                     for wi, word in enumerate(record)]
        row = [f"{len(words)} {len(flattened)} {len(reads)} {len(writes)}"]
        row += [f"{word:08x}" for word in words]
        row += [f"{word:08x} {last}" for word, last in flattened]
        row += [f"{address:08x} {data:08x} {error}" for address, data, error in reads]
        row += [f"{address:08x} {data:08x} {strobe:x} {last} {error}"
                for address, data, strobe, last, error in writes]
        self.rows.extend(row)
        self.ledger.append({"label": label, "tag": self.tag, "opcode": words[2],
                            "accepted_beats_required": len(words), "records_required": len(records),
                            "output_words_required": len(flattened), "status": records[-1][2],
                            "pixels": records[-1][3], "texture_reads": len(reads),
                            "dma_requests": len(writes),
                            "independent_geometry_events": self.model.events})
        return records

    def save(self):
        self.path.write_text("\n".join(self.rows)+"\n")
        self.path.with_suffix(".json").write_text(json.dumps(
            {"configuration": self.config, "transactions": self.ledger}, indent=2)+"\n")


def integrated(path, config, seed=17, compact=False):
    scenario = Scenario(path, config)
    w, h = min(config[0], 5 if compact else 13), min(config[1], 5 if compact else 11)
    rng = random.Random(seed)
    shader_program = 0

    def add(words, label, **errors):
        return scenario.add(words, label, **errors)

    def follow():
        add(command(0, 0, w, h, [(2*Q, 0, Q//4, Q)]*3),
            "immediate-valid-following-command")

    def color():
        add(state_command(0, 1026, w, h, 0x7143a7d1), "color-clear")

    def depth(mode):
        add(command(0, 5 if mode & 1 else 4, w, h), "depth-clear")

    def shader(p):
        nonlocal shader_program
        shader_program = p
        add(state_command(0, 1025, word3=p), "shader-configuration")

    color()
    shader(0)
    add(state_command(0, 1024, 13, 11, 0x1000, 64), "texture-configuration")
    vertices = [(-Q, -Q, Q//4, Q), (Q, -Q, Q//4, Q), (0, Q, Q//4, Q)]
    attrs = [(-Q//3, Q//4, 11000, 23000, Q+100, 44000),
             (4*Q, 3*Q, Q, -100, 17000, Q),
             (8*Q, 7*Q, 47000, 52000, 13000, 21000)]
    for opcode in OPCODES:
        if opcode in PARENT_DRAWS + G3_DRAWS:
            depth(opcode)
        if opcode in (1024, 1025, 1026, 1027):
            words = state_command(0, opcode, *(
                (13, 11, 0x1000, 64) if opcode == 1024 else
                (0, 0, shader_program, 0) if opcode == 1025 else
                (w, h, 0x7143a7d1, 0) if opcode == 1026 else
                (w, h, 0x4000, 4*w+12)))
        else:
            words = command(0, opcode, w, h, vertices, attrs)
        add(words, f"opcode-{opcode}")
        follow()
    for opcode in (0x300, 0x301):
        add(command(0, opcode, w, h), f"invalid-opcode-{opcode}")
        follow()
    for opcode in (1024, 1026, 1027):
        for dims in ((0, h), (w, 0), (257, h), (w, 257)):
            words = state_command(0, opcode, *dims, 0x1000, 2048)
            add(words, f"invalid-dimensions-{opcode}-{dims}")
            follow()
    for opcode in (1024, 1027):
        for base, stride in ((0x1001, 4*w+12), (0x1000, 4*w+13),
                             (0x1000, 4*w-4), (0xfffffff0, 0xfffffff0)):
            add(state_command(0, opcode, w, h, base, stride), f"invalid-address-{opcode}")
            follow()
    for opcode in range(1024, 1028):
        words = state_command(0, opcode, 0 if opcode == 1025 else w,
                              0 if opcode == 1025 else h, 0, 4*w)
        words[30] = 1
        add(words, f"reserved-word-{opcode}")
        follow()
    for shift in (3, 6, 9, 12):
        for factor in (6, 7):
            add(state_command(0, 1025, word3=factor << shift), f"invalid-factor-{shift}-{factor}")
            follow()
    add(state_command(0, 1025, word3=1 << 15), "invalid-shader-reserved-bit")
    follow()
    legacy_modes = (0, 1) + PARENT_DRAWS
    for i in range(6 if compact else 48):
        opcode = legacy_modes[i % len(legacy_modes)]
        if opcode not in (0, 1):
            depth(opcode)
        varied = [list(v) for v in vertices]
        if i % 4 == 1:
            varied[1], varied[2] = varied[2], varied[1]
        if i % 8 == 2:
            varied[0][0] = -2*Q
        if i % 8 == 3:
            varied[1][1] = -2*Q
        if i % 8 == 4:
            varied[2][3] = 2*Q
        matrix = list(IDENTITY)
        matrix[0] = rng.randrange(40000, 65537)
        matrix[5] = rng.randrange(40000, 65537)
        matrix[3] = rng.randrange(-6000, 6001)
        signed_attrs = [[rng.randrange(-2*Q, 3*Q) for _ in range(6)] for _ in range(3)]
        add(command(0, opcode, w, h, varied, signed_attrs, matrix), f"seed-{seed}-legacy-{i}")
    for i in range(6 if compact else 48):
        opcode = G3_DRAWS[i % len(G3_DRAWS)]
        depth(opcode)
        p = (0, 1, 3, 4 | 1 << 3 | 3 << 6 | 1 << 9 | 3 << 12,
             5 | 2 << 3 | 3 << 6 | 1 << 9 | 1 << 12,
             7 | 4 << 3 | 5 << 6 | 2 << 9 | 3 << 12)[i % 6]
        shader(p)
        varied = [list(v) for v in vertices]
        if i % 3 == 1:
            varied[2][3] = 2*Q
        matrix = list(IDENTITY)
        matrix[3] = rng.randrange(-3000, 3001)
        add(command(0, opcode, w, h, varied, attrs, matrix), f"seed-{seed}-g3-{i}")
    add(state_command(0, 1027, w, h, 0x8000, 4*w+16), "final-framebuffer-export")
    add(state_command(0, 1027, w, h, 0x8000, 4*w+16), "repeat-framebuffer-export")
    if not compact:
        for plane in range(7):
            varied = [list(v) for v in vertices]
            component, value = ((3, -Q), (0, -2*Q), (0, 2*Q),
                                (1, -2*Q), (1, 2*Q), (2, -Q), (2, 2*Q))[plane]
            varied[0][component] = value
            if plane == 0:
                varied[0] = [0, 0, 0, 0]
            depth(770)
            shader(0)
            add(command(0, 770, w, h, varied, attrs), f"clipping-plane-{plane}")
            assert scenario.ledger[-1]["independent_geometry_events"]["clip_intersections"][plane] > 0
        depth(770)
        for label, z in (("depth-pass", Q//2), ("depth-equal", Q//2),
                         ("depth-fail", 3*Q//4), ("depth-nearer", Q//8)):
            varied = [(x, y, z, vw) for x, y, _, vw in vertices]
            records = add(command(0, 770, w, h, varied, attrs), label)
            assert records[-1][8 if label in ("depth-pass", "depth-nearer") else 9] > 0
        shared = ([(-Q, -Q, Q//4, Q), (Q, -Q, Q//4, Q), (-Q, Q, Q//4, Q)],
                  [(Q, -Q, Q//4, Q), (Q, Q, Q//4, Q), (-Q, Q, Q//4, Q)])
        sets = []
        for i, triangle in enumerate(shared):
            depth(770)
            records = add(command(0, 770, w, h, triangle, attrs), f"shared-edge-{i}")
            sets.append({rec[2] & 65535 for rec in records[:-1]})
        assert not sets[0] & sets[1]
        assert len(sets[0] | sets[1]) == w*h
        depth(770)
        add(command(0, 770, w, h, [vertices[0]]*3, attrs), "degenerate")
        shader(1)
        add(state_command(0, 1024, 13, 11, 0x1000, 64), "invalidate-before-error")
        depth(770)
        add(command(0, 770, w, h, vertices, attrs), "texture-response-error", texture_fail_at=3)
        add(state_command(0, 1024, 13, 11, 0x1000, 64), "texture-error-recovery-config")
        depth(770)
        add(command(0, 770, w, h, vertices, attrs), "texture-error-recovery-draw")
        add(state_command(0, 1027, w, h, 0x8000, 4*w+16), "dma-response-error", dma_fail_at=0)
        add(state_command(0, 1027, w, h, 0x8000, 4*w+16), "dma-error-recovery")
    scenario.save()
    return scenario.ledger


def prerequisites(path, config):
    scenario = Scenario(path, config)
    w, h = min(config[0], 3), min(config[1], 3)
    vertices = [(-Q, -Q, Q//4, Q), (Q, -Q, Q//4, Q), (0, Q, Q//4, Q)]
    scenario.add(command(0, 4, w, h), "prerequisite-depth-init")
    for mode in G3_DRAWS:
        records = scenario.add(command(0, mode, w, h, vertices), f"missing-color-shader-{mode}")
        assert len(records) == 1 and records[0][2] == 4
        scenario.add(state_command(0, 1025), "immediate-valid-following-command")
    scenario.add(state_command(0, 1026, w, h, 0x7f315599), "prerequisite-color")
    scenario.add(command(0, 770, w, h, vertices), "rejected-draws-preserved-depth")
    assert scenario.ledger[-1]["pixels"] > 0
    scenario.add(command(0, 4, w, h), "prerequisite-depth-reinit")
    scenario.add(state_command(0, 1025, word3=1), "enable-unconfigured-texture")
    records = scenario.add(command(0, 770, w, h, vertices), "missing-texture")
    assert len(records) == 1 and records[0][2] == 4
    scenario.add(state_command(0, 1025), "immediate-valid-following-command")
    scenario.add(command(0, 770, w, h, vertices), "texture-rejection-preserved-depth")
    assert scenario.ledger[-1]["pixels"] > 0
    if w > 1:
        scenario.add(state_command(0, 1026, w-1, h, 0x713579bd), "mismatch-color")
        records = scenario.add(command(0, 770, w, h, vertices), "mismatched-color")
        assert records[-1][2] == 4 and len(records) == 1
        scenario.add(command(0, 0, w, h, [(2*Q, 0, Q//4, Q)]*3),
                     "immediate-valid-following-command")
    scenario.save()
    return scenario.ledger


def smoke(path):
    scenario = Scenario(path, (1, 1, 0))
    for words, label in (
            (state_command(0, 1026, 1, 1, 0x71234567), "smoke-color"),
            (state_command(0, 1025), "smoke-shader"),
            (command(0, 4), "smoke-depth"),
            (command(0, 0), "smoke-legacy"),
            (command(0, 770), "smoke-g3"),
            (state_command(0, 1027, 1, 1, 0x1000, 4), "smoke-dma"),
            (state_command(0, 1024, 1, 1, 0x2000, 4), "smoke-texture-config"),
            (state_command(0, 1025, word3=1), "smoke-texture-shader"),
            (command(0, 4), "smoke-texture-depth"),
            (command(0, 770), "smoke-textured-g3"),
            (state_command(0, 1027, 1, 1, 0x1000, 4), "smoke-textured-dma")):
        scenario.add(words, label)
    scenario.save()
    return scenario.ledger


def cache_scenario(path, config=(13, 11, 3)):
    scenario = Scenario(path, config)
    w, h = min(config[0], 3), min(config[1], 3)
    vertices = [(-Q, -Q, Q//4, Q), (Q, -Q, Q//4, Q), (0, Q, Q//4, Q)]
    scenario.add(state_command(0, 1026, w, h, 0x7143a7d1), "cache-color")
    scenario.add(state_command(0, 1025, word3=1), "cache-shader")
    for tw, th in ((13, 11), (1, 1), (1, 17), (19, 1)):
        scenario.add(state_command(0, 1024, tw, th, 0x1000, 4*tw+12), f"cache-config-{tw}-{th}")
        samples = [(Q//2, Q//2)]*9+[(3*Q+Q//2, 3*Q+Q//2),
                  (8*Q+Q//2, Q//2), (Q//2, Q//2), (-Q, -Q),
                  (100*Q, 100*Q), ((tw-1)*Q-Q//2, (th-1)*Q-Q//2)]
        for i, (u, v) in enumerate(samples):
            scenario.add(command(0, 4, w, h), "cache-depth")
            attrs = [(u, v, 21000, 43000, 17000, 39000)]*3
            records = scenario.add(command(0, 770, w, h, vertices, attrs),
                                   f"cache-{tw}-{th}-sample-{i}")
            assert records[-1][3] > 0
            if 1 <= i <= 8:
                assert scenario.ledger[-1]["texture_reads"] == 0
            if i == 9 and (tw, th) == (13, 11):
                assert records[-1][11] >= 3 and scenario.ledger[-1]["texture_reads"] >= 48
        scenario.add(command(0, 4, w, h), "cache-depth")
        scenario.add(command(0, 770, w, h, vertices, [(0, 0, Q, Q, Q, Q)]*3),
                     "prime-identical-reconfiguration")
        scenario.add(state_command(0, 1024, tw, th, 0x1000, 4*tw+12),
                     "identical-reconfiguration")
        scenario.add(command(0, 4, w, h), "cache-depth")
        scenario.add(command(0, 770, w, h, vertices, [(0, 0, Q, Q, Q, Q)]*3),
                     "reconfiguration-cold-refill")
        assert scenario.ledger[-1]["texture_reads"] == 16
    scenario.save()
    return scenario.ledger


def directed_state(path, config=(13, 11, 3)):
    scenario = Scenario(path, config)
    w, h = min(config[0], 3), min(config[1], 3)
    program = 7 | 2 << 3 | 3 << 6 | 4 << 9 | 5 << 12
    vertices = [(-Q, -Q, Q//4, Q), (Q, -Q, Q//4, Q), (0, Q, Q//4, Q)]
    attrs = [(3*Q+Q//2, 3*Q+Q//2, 17000, 43000, 61000, 37000)]*3
    malformed = []
    for mode in (1024, 1026, 1027):
        for dw, dh in ((0, h), (w, 0), (257, h), (w, 257)):
            malformed.append(state_command(0, mode, dw, dh, 0x1000, 64))
    for mode in (1024, 1027):
        for base, stride in ((0x1001, 64), (0x1000, 65), (0x1000, 4*w-4),
                             (0xfffffff0, 0xfffffff0)):
            malformed.append(state_command(0, mode, w, h, base, stride))
    for mode in range(1024, 1028):
        words = state_command(0, mode, 0 if mode == 1025 else w,
                              0 if mode == 1025 else h, program if mode == 1025 else 0, 64)
        words[30] = 1
        malformed.append(words)
    for shift in (3, 6, 9, 12):
        for factor in (6, 7):
            malformed.append(state_command(0, 1025, word3=factor << shift))
    malformed.append(state_command(0, 1025, word3=1 << 15))
    malformed.append(state_command(0, 1025, 1, 1, program))
    for i, words in enumerate(malformed):
        scenario.add(state_command(0, 1026, w, h, 0x7143a7d1), "atomic-color-prime")
        scenario.add(state_command(0, 1025, word3=program), "atomic-shader-prime")
        scenario.add(state_command(0, 1024, 13, 11, 0x1000, 64), "atomic-texture-prime")
        scenario.add(command(0, 4, w, h), "atomic-depth-prime")
        records = scenario.add(words, f"atomic-invalid-{i}")
        assert records[-1][2] == 1
        scenario.add(state_command(0, 1027, w, h, 0x8000, 4*w+12),
                     "immediate-valid-following-command")
        records = scenario.add(command(0, 770, w, h, vertices, attrs),
                               "atomic-configurations-preserved")
        assert records[-1][3] > 0
        scenario.add(state_command(0, 1027, w, h, 0x8000, 4*w+12), "atomic-post-shader-color")
    scenario.add(state_command(0, 1026, 1, 1, 0x7143a7d1), "early-z-color")
    scenario.add(state_command(0, 1025), "early-z-shader")
    scenario.add(command(0, 4), "early-z-depth")
    scenario.add(command(0, 514, 1, 1, vertices, attrs), "early-z-pass")
    records = scenario.add(command(0, 514, 1, 1, vertices, attrs), "early-z-equal-tile-reject")
    assert records[-1][6] == 1 and records[-1][7] == 0
    records = scenario.add(command(0, 770, 1, 1, vertices, attrs), "early-z-disabled-equal-fragment-fail")
    assert records[-1][6] == 0 and records[-1][9] == 1
    scenario.add(state_command(0, 1025, word3=1), "error-shader")
    scenario.add(state_command(0, 1024, 13, 11, 0x1000, 64), "error-cache-prime")
    for i, u in enumerate((0, 4*Q, 0)):
        scenario.add(command(0, 4), "error-depth")
        attrs = [(u, 0, Q, Q//2, Q//3, 39000)]*3
        records = scenario.add(command(0, 770, 1, 1, vertices, attrs),
                               ("error-populate-old-line", "error-in-different-line",
                                "error-invalidated-all-lines-recovery")[i],
                               **({"texture_fail_at": 3} if i == 1 else {}))
        if i == 1:
            assert records[-1][2] == 5 and records[-1][3] == 0 and len(records) == 1
        else:
            assert records[-1][2] == 0 and records[-1][3] == 1
            assert scenario.ledger[-1]["texture_reads"] == 16
    scenario.save()
    return scenario.ledger


def mutation_scenario(path, kind):
    if kind == "cache":
        return cache_scenario(path)
    scenario = Scenario(path, (3, 3, 0))
    vertices = [(-Q, -Q, Q//4, Q), (Q, -Q, Q//4, Q), (0, Q, Q//2, 2*Q)]
    attrs = [(-Q//3, 0, 21000, 43000, 17000, 39000),
             (4*Q, 7*Q, 17000, -23000, 51000, Q),
             (9*Q, Q, 43000, 31000, -17000, 0)]
    scenario.add(command(0, 4, 3, 3), "mutant-depth-init")
    for i in range(2):
        scenario.add(command(0, 258, 3, 3, vertices, attrs), f"mutant-{kind}-{i}")
    assert scenario.ledger[1]["pixels"] > 0 and scenario.ledger[2]["pixels"] == 0
    scenario.save()
    return scenario.ledger


def dma_scenario(path, width, height, log2):
    rows = [f"0\n{width} {height} 7139a5d7"]
    color = {(x, y): 0x7139a5d7 for y in range(height) for x in range(width)}
    for i, (x, y) in enumerate(dict.fromkeys(((0, 0), (width-1, 0),
                                             (0, height-1), (width-1, height-1),
                                             (width//2, height//2)))):
        rows.append(f"2\n{x} {y} {color[x, y]:08x}")
        value = (0x8f4b1703 + i*0x1020304) & 0xffffffff
        rows.append(f"1\n{x} {y} {value:08x}")
        color[x, y] = value
        rows.append(f"2\n{x} {y} {value:08x}")
    base, stride = 0x10000, width*4+28
    order = list(tile_coordinates(width, height, log2))
    for fail in (None, None, min(2, len(order)-1), None):
        requests = order if fail is None else order[:fail+1]
        rows.append(f"3\n{base:08x} {stride:08x} {len(requests)} "
                    f"{len(order) if fail is None else fail} {int(fail is not None)}")
        for i, (x, y) in enumerate(requests):
            rows.append(f"{base+y*stride+x*4:08x} {color[x, y]:08x} "
                        f"{int(i==len(order)-1)} {int(i==fail)}")
    path.write_text("\n".join(rows)+"\n")
    return {"dimensions": [width, height], "compared_framebuffer_bytes_per_full_export": width*height*4,
            "full_exports": 3, "error_exports": 1, "corner_read_before_after_writes": True}
