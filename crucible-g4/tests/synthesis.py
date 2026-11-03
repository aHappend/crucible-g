"""Real memory-preserving Yosys synthesis and reachable hierarchy checks."""

from collections import Counter, defaultdict, deque
import json

from execution import dump
from scenarios import PARAMETERS

NAMES = ("MAX_WIDTH", "MAX_HEIGHT", "TILE_LOG2", "MAX_NODES", "MAX_SPLATS", "STACK_DEPTH")
REQUIRED = {
    "crucible_g4_top": {"compatibility": "crucible_g3_top", "bvh": "g4_bvh", "splat": "g4_splat"},
    "g4_bvh": {"slab": "g4_slab"},
    "g4_slab": {"divider": "g4_divider"},
    "g4_splat": {"sorter": "g4_radix_sort", "conic": "g4_conic", "compositor": "g4_compositor"},
    "g4_conic": {"exp_rom": "g4_exp_rom"},
}


def hdlname(name, module):
    return str(module.get("attributes", {}).get("hdlname", name)).split()[0].lstrip("\\")


def instances(module, modules):
    return {name.rsplit(".", 1)[-1]: (name, cell, hdlname(cell["type"], modules[cell["type"]]))
            for name, cell in module["cells"].items() if cell["type"] in modules}


def data_graph(module):
    graph = defaultdict(set)
    memory_reads, memory_writes = defaultdict(list), defaultdict(list)
    for cell in module["cells"].values():
        directions = cell["port_directions"]
        inputs = [bit for port, bits in cell["connections"].items()
                  if directions[port] == "input" and port.upper() not in
                  ("CLK", "CLOCK", "ARST", "SRST", "RST_N", "RST")
                  for bit in bits if isinstance(bit, int)]
        outputs = [bit for port, bits in cell["connections"].items()
                   if directions[port] == "output"
                   for bit in bits if isinstance(bit, int)]
        for bit in inputs:
            graph[bit].update(outputs)
        memory_id = cell.get("parameters", {}).get("MEMID")
        if memory_id is not None and cell["type"].startswith("$memrd"):
            memory_reads[memory_id].extend(cell["connections"]["DATA"])
        if memory_id is not None and cell["type"].startswith("$memwr"):
            memory_writes[memory_id].extend(
                bit for port in ("DATA", "ADDR", "EN")
                for bit in cell["connections"][port] if isinstance(bit, int))
    for memory_id, write_bits in memory_writes.items():
        for bit in write_bits:
            graph[bit].update(value for value in memory_reads[memory_id] if isinstance(value, int))
    return graph


def path_exists(module, source, target):
    graph = data_graph(module)
    targets, seen = set(target), set()
    queue = deque(bit for bit in source if isinstance(bit, int))
    while queue:
        bit = queue.popleft()
        if bit in targets:
            return True
        if bit in seen:
            continue
        seen.add(bit)
        queue.extend(graph[bit] - seen)
    return False


def inspect_netlist(path, check_connections=True):
    modules = json.loads(path.read_text())["modules"]
    top = modules["crucible_g4_top"]
    reached, hierarchy, types = set(), {}, Counter()

    def visit(name):
        if name in reached:
            return
        reached.add(name)
        module = modules[name]
        attributes = module.get("attributes", {})
        assert not int(attributes.get("blackbox", "0"), 2), f"blackbox {name}"
        logical = hdlname(name, module)
        children = instances(module, modules)
        if logical in REQUIRED:
            for instance, expected in REQUIRED[logical].items():
                assert instance in children and children[instance][2] == expected, (logical, instance, expected)
            hierarchy[logical] = {instance: child[2] for instance, child in children.items()}
        for cell in module["cells"].values():
            kind = cell["type"]
            types[kind] += 1
            assert "latch" not in kind.lower(), f"latch {name}: {kind}"
            assert kind not in ("$div", "$mod", "$divfloor", "$modfloor"), f"division {name}: {kind}"
            if kind in modules:
                visit(kind)
            else:
                assert kind.startswith("$"), f"unresolved cell {name}: {kind}"
        if logical in ("g4_bvh", "g4_slab", "g4_divider", "g4_splat",
                       "g4_radix_sort", "g4_conic", "g4_compositor"):
            sequential = sum(cell["type"].lower().startswith(("$dff", "$adff", "$sdff"))
                             for cell in module["cells"].values())
            assert sequential >= 2, f"no substantive registered state: {logical}"

    visit("crucible_g4_top")
    assert all(name in hierarchy for name in REQUIRED), "missing required reachable module"
    if not check_connections:
        return {"hierarchy": hierarchy, "reachable_modules": len(reached),
                "cell_types": dict(types), "latch_cells": 0, "division_cells": 0}
    by_name = {hdlname(name, modules[name]): modules[name] for name in reached}
    children = instances(top, modules)
    for engine in ("bvh", "splat"):
        cell = children[engine][1]
        assert path_exists(top, top["ports"]["s_data"]["bits"], cell["connections"]["s_command"]), engine
        assert path_exists(top, cell["connections"]["m_record"], top["ports"]["m_data"]["bits"]), engine
    bvh = by_name["g4_bvh"]
    slab_cell = instances(bvh, modules)["slab"][1]
    assert path_exists(bvh, slab_cell["connections"]["m_t_enter"], bvh["ports"]["m_record"]["bits"])
    slab_module = by_name["g4_slab"]
    divider = instances(slab_module, modules)["divider"][1]
    assert path_exists(slab_module, divider["connections"]["m_ceil"], slab_module["ports"]["m_t_enter"]["bits"])
    splat = by_name["g4_splat"]
    children = instances(splat, modules)
    assert path_exists(splat, children["sorter"][1]["connections"]["m_index"],
                       children["conic"][1]["connections"]["s_mean"]), "sort index does not reach conic input"
    assert path_exists(splat, children["conic"][1]["connections"]["m_alpha"],
                       children["compositor"][1]["connections"]["s_alpha"])
    assert path_exists(splat, children["compositor"][1]["connections"]["m_rgba"],
                       splat["ports"]["m_record"]["bits"])
    assert any(kind.startswith("$mem") for kind in types), "no actual synthesized memories"
    return {"hierarchy": hierarchy, "reachable_modules": len(reached),
            "cell_types": dict(types), "latch_cells": 0, "division_cells": 0,
            "connected_engines": ["bvh/slab/divider", "splat/sorter/conic/ROM/compositor"]}


def synthesis(run, configurations=None):
    run.versions(("python3", "yosys"))
    run.execute(["yosys", "-Q", "-T", "-p", "help synth"], "synth-help")
    sources = [run.relative(path) for path in sorted((run.root / "rtl").glob("*.sv"))]
    for index, parameters in enumerate(configurations or
                                        (PARAMETERS[3], PARAMETERS[0], PARAMETERS[1], PARAMETERS[4])):
        netlist = run.folder / f"synthesis-{index}.json"
        elaborated = run.folder / f"elaborated-{index}.json"
        script = run.folder / f"synthesis-{index}.ys"
        settings = " ".join(f"-set {name} {value}" for name, value in zip(NAMES, parameters))
        script.write_text(
            "read_verilog -sv " + " ".join(sources) + "\n"
            f"chparam {settings} crucible_g4_top\n"
            "hierarchy -check -top crucible_g4_top\n"
            "proc\n"
            f"write_json {run.relative(elaborated)}\n"
            "synth -top crucible_g4_top -run coarse:fine\n"
            "check -assert -noinit\n"
            "stat\n"
            f"write_json {run.relative(netlist)}\n")
        run.execute(["yosys", "-s", run.relative(script)], f"synthesis-{index}")
        connected = inspect_netlist(elaborated)
        result = inspect_netlist(netlist, check_connections=False)
        result["preoptimization_connections"] = connected["connected_engines"]
        result["parameters"] = dict(zip(NAMES, parameters))
        dump(run.folder / f"synthesis-{index}.structure.json", result)
        run.receipt["comparisons"][f"synthesis-{index}"] = result
        run.save()
