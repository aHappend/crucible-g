#!/usr/bin/env python3
"""Portable L1 checks. Native timing and hardware gates are runtime-owned."""

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import random
import shutil
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import Evidence, sha
from model import bilinear, pack, shader
from scenarios import (integrated, dma_scenario, smoke, cache_scenario,
                       mutation_scenario, prerequisites, directed_state)

ROOT = Path(__file__).resolve().parents[1]


def leaf_vectors(path, seed, count):
    rng = random.Random(seed)
    vectors = []
    for i in range(count):
        texels = [rng.getrandbits(32) for _ in range(4)]
        fx, fy = rng.randrange(65536), rng.randrange(65536)
        vertex = [rng.randrange(-65536, 131073) for _ in range(4)]
        texture, destination = rng.getrandbits(32), rng.getrandbits(32)
        factors = [rng.randrange(6) for _ in range(4)]
        program = rng.randrange(8) | sum(f << s for f, s in zip(factors, (3, 6, 9, 12)))
        if i < 72:
            a, b = divmod(i % 36, 6)
            vertex = [17000, 43000, 61000, 37000]
            destination = pack([71, 139, 211, 91], 8)
            texture = pack([231, 53, 117, 173], 8)
            program = 7 | (a << (3 if i < 36 else 9)) | (
                b << (6 if i < 36 else 12)) | (
                (1 << 9) if i < 36 else (1 << 3))
        elif i < 100:
            vertex = [(-1, 0, 32768, 65536, 65537, -2**31, 2**31-1)[(i+j) % 7]
                      for j in range(4)]
            program = (i & 7) | (1 << 3) | (1 << 6) | (1 << 9) | (1 << 12)
            fx, fy = ((0, 1, 32768, 65535)[i % 4],
                      (0, 1, 32768, 65535)[i//4 % 4])
        if i == 99:
            vertex, texture, destination = [65536]*4, 0, 0xffffffff
            program = 4 | (1 << 3) | (1 << 6) | (1 << 9) | (1 << 12)
        if i == 96:
            texels, fx, fy = [0x42c19e37, 0xa57b801d, 0x192f4ee3, 0xd32651af], 0, 0
        elif i == 97:
            texels, fx, fy = [0, 0, 0, 0x01010101], 32768, 32768
        elif i == 98:
            texels, fx, fy = [0, 0x01010101, 0, 0x01010101], 32768, 0
        values = [pack(texels, 32), fx, fy, pack(vertex, 32), texture, destination,
                  program, bilinear(texels, fx, fy),
                  shader(vertex, texture, destination, program)]
        vectors.append(" ".join(f"{v:x}" for v in values)+f" {2+i%5}")
    path.write_text("\n".join(vectors)+"\n")
    return count


def compile_sim(evidence, top, bench, sources, name, verilator=False, parameters=()):
    suffix = hashlib.sha256(name.encode()).hexdigest()[:8]
    work = evidence.path / f"{name}-{suffix}"
    work.mkdir()
    if verilator:
        obj = work / ("compile-obj-"+suffix)
        executable = obj / ("V"+top)
        try:
            evidence.run(["verilator", "--binary", "--timing", "-Wno-fatal",
                          "--top-module", top, "-j", "2", "--Mdir",
                          evidence.relative(obj), *parameters,
                          *[evidence.relative(x) for x in sources],
                          evidence.relative(bench)], name+"-compile")
        except Exception:
            if obj.is_dir():
                shutil.rmtree(obj)
            raise
    else:
        executable = work / "simulation.vvp"
        evidence.run(["iverilog", "-g2012", "-Wall", "-s", top, "-o",
                      evidence.relative(executable), *parameters,
                      *[evidence.relative(x) for x in sources],
                      evidence.relative(bench)], name+"-compile")
    return executable


def leaves(evidence, compact=False):
    sources = [ROOT / "rtl/g3_bilinear.sv", ROOT / "rtl/g3_shader_pipeline.sv"]
    runs = []
    executable = compile_sim(evidence, "leaf_tb", ROOT / "tests/leaf_tb.sv",
                             sources, "leaf-icarus")
    vectors = evidence.path / "leaf-smoke.txt"
    leaf_vectors(vectors, 17, 100)
    out, _, _ = evidence.run(["vvp", evidence.relative(executable),
                             "+vectors="+evidence.relative(vectors)], "leaf-icarus-run")
    assert "SUMMARY leaf compared=100" in out, out
    runs.append({"simulator": "icarus", "seed": 17, "compared": 100})
    if not compact:
        executable = compile_sim(evidence, "leaf_tb", ROOT / "tests/leaf_tb.sv",
                                 sources, "leaf-verilator", True)
        try:
            for seed in (17, 89, 233):
                vectors = evidence.path / f"leaf-{seed}.txt"
                leaf_vectors(vectors, seed, 356)
                out, _, _ = evidence.run([evidence.relative(executable),
                                         "+vectors="+evidence.relative(vectors)],
                                        f"leaf-verilator-{seed}")
                assert "SUMMARY leaf compared=356" in out, out
                runs.append({"simulator": "verilator", "seed": seed, "compared": 356,
                             "fully_random_filter_samples": 256, "fully_random_shader_vectors": 256,
                             "rgb_factor_cartesian": 36, "alpha_factor_cartesian": 36})
        finally:
            if executable.parent.is_dir():
                shutil.rmtree(executable.parent)
    return runs


def top_probe(evidence, compact=True):
    config = (13, 11, 3)
    path = evidence.path / "integrated.txt"
    ledger = integrated(path, config, compact=compact)
    executable = compile_sim(evidence, "top_tb", ROOT / "tests/top_tb.sv",
                             sorted((ROOT / "rtl").glob("*.sv")), "top-verilator", True)
    try:
        out = run_top(evidence, executable, path, ledger, "top-verilator-run")
        assert f"SUMMARY top transactions={len(ledger)} " in out, out
    finally:
        if executable.parent.is_dir():
            shutil.rmtree(executable.parent)
    return ledger


def run_top(evidence, executable, path, ledger, name, icarus=False, expect=0):
    coverage = evidence.path / (name+".coverage.txt")
    argv = (["vvp"] if icarus else []) + [
        evidence.relative(executable), "+scenario="+evidence.relative(path),
        "+coverage="+evidence.relative(coverage)]
    out, err, code = evidence.run(argv, name, expect=expect)
    if code != 0:
        return out+err, code
    lines = coverage.read_text().splitlines()
    assert len(lines) == len(ledger), (len(lines), len(ledger))
    for line, row in zip(lines, ledger):
        values = line.split()
        observed = [int(x, 16 if i < 2 else 10) for i, x in enumerate(values)]
        required = [row["tag"], row["opcode"], row["accepted_beats_required"],
                    row["output_words_required"], row["texture_reads"], row["dma_requests"]]
        assert observed[:6] == required and observed[6] >= 3, (observed, required)
        row["observed_accepted_beats"] = observed[2]
        row["observed_output_words"] = observed[3]
        row["observed_texture_reads"] = observed[4]
        row["observed_dma_requests"] = observed[5]
        row["observed_terminal_stalls"] = observed[6]
        row["observed_cycles"] = observed[7]
        row["observed_header_stalls"] = observed[8]
        row["observed_attribute_stalls"] = observed[9]
        row["complete_independent_response_compared"] = True
        assert observed[8] > 0 and (row["accepted_beats_required"] != 49 or observed[9] > 0)
    return out


def dma_checks(evidence, configs=None):
    runs = []
    configs = configs or ((1, 1, 0), (13, 11, 0), (13, 11, 3),
                          (19, 17, 4), (256, 256, 3))
    for w, h, log in configs:
        name = f"dma-{w}-{h}-{log}"
        executable = compile_sim(evidence, "dma_tb", ROOT / "tests/dma_tb.sv",
                                 [ROOT / "rtl/g3_framebuffer_dma.sv"], name, True,
                                 [f"-GW={w}", f"-GH={h}", f"-GL={log}"])
        dimensions = ((1, 17), (19, 1)) if (w, h) == (19, 17) else ((w, h),)
        try:
            for width, height in dimensions:
                path = evidence.path / f"{name}-{width}-{height}.txt"
                row = dma_scenario(path, width, height, log)
                out, _, _ = evidence.run([evidence.relative(executable),
                                         "+scenario="+evidence.relative(path)],
                                        f"{name}-{width}-{height}-run")
                assert "SUMMARY dma transactions=" in out, out
                runs.append(dict(configuration=[w, h, log], **row))
        finally:
            if executable.parent.is_dir():
                shutil.rmtree(executable.parent)
    return runs


def parameters(evidence):
    runs = []
    sources = sorted((ROOT / "rtl").glob("*.sv"))
    cases = [(w, h, log) for w, h in ((1, 1), (13, 11), (19, 17))
             for log in range(5)]
    illegal = ((0, 11, 3), (257, 11, 3), (13, 0, 3), (13, 257, 3),
               (13, 11, -1), (13, 11, 5))
    for i, config in enumerate(cases+list(illegal)):
        w, h, log = config
        executable = compile_sim(evidence, "parameter_tb", ROOT / "tests/parameter_tb.sv",
                                 sources, f"parameter-{i}", parameters=[
                                     f"-Pparameter_tb.W={w}", f"-Pparameter_tb.H={h}",
                                     f"-Pparameter_tb.L={log}"])
        out, err, code = evidence.run(["vvp", evidence.relative(executable)],
                                     f"parameter-{i}-run", expect=None)
        if config in illegal:
            assert code != 0 and "PARAMETER ERROR" in out+err, (config, code, out, err)
        else:
            assert code == 0 and "SUMMARY legal parameters" in out, (config, code, out, err)
        runs.append({"configuration": config, "expected_rejection": config in illegal,
                     "exit_code": code})
    return runs


def synthesize(evidence, config, name, root=ROOT):
    w, h, log = config
    script = evidence.path / (name+".ys")
    netlist = evidence.path / (name+".json")
    sources = " ".join(evidence.relative(x) for x in sorted((root / "rtl").glob("*.sv")))
    script.write_text(
        f"read_verilog -sv {sources}\n"
        f"chparam -set MAX_WIDTH {w} -set MAX_HEIGHT {h} -set TILE_LOG2 {log} crucible_g3_top\n"
        "hierarchy -check -top crucible_g3_top\n"
        "proc\nopt_expr\nopt_clean\ncheck -noinit -assert\n"
        "memory -nomap\nopt_clean\ncheck -noinit -assert\nstat\n"
        f"write_json {evidence.relative(netlist)}\n")
    out, err, _ = evidence.run(["yosys", "-Q", "-T", "-s", evidence.relative(script)], name)
    graph = json.loads(netlist.read_text())
    modules = graph["modules"]
    top = modules["crucible_g3_top"]
    instances, primitives = {}, {}

    def visit(module_name, path):
        module = modules[module_name]
        assert not int(str(module.get("attributes", {}).get("blackbox", "0")), 2), module_name
        local = []
        for cell_name, cell in module.get("cells", {}).items():
            kind = cell["type"]
            cell_path = path+"."+cell_name if path else cell_name
            assert not any(token in kind.lower() for token in ("dlatch", "$div", "$mod", "$divfloor", "$modfloor")), (cell_path, kind)
            if kind in modules:
                children = visit(kind, cell_path)
                hdlname = str(modules[kind].get("attributes", {}).get("hdlname", kind))
                instances[cell_path] = {"module": hdlname.lstrip("\\").split()[0],
                                        "primitive_cells": len(children)}
                local.extend(children)
            else:
                assert kind.startswith("$"), ("unresolved cell", cell_path, kind)
                primitives[kind] = primitives.get(kind, 0)+1
                local.append((cell_path, kind, cell))
        return local

    cells = visit("crucible_g3_top", "")
    required = {"compatibility": "crucible_g2_top", "compatibility.legacy": "crucible_g1_top",
                "compatibility.engine": "g2_engine", "texture_cache": "g3_texture_cache",
                "texture_cache.filter": "g3_bilinear", "shader": "g3_shader_pipeline",
                "framebuffer_dma": "g3_framebuffer_dma"}
    for path, kind in required.items():
        assert path in instances and instances[path]["module"] == kind, (path, instances.get(path))
        subtree = [(p, t, c) for p, t, c in cells if p.startswith(path+".")]
        state_bits = sum(len(c["connections"].get("Q", [])) for _, t, c in subtree
                         if "dff" in t.lower())
        assert state_bits >= 32, (path, state_bits)
        instances[path]["state_bits"] = state_bits
    for cell_name, prefix in (("texture_cache", "tex_"), ("framebuffer_dma", "dma_")):
        for port_name, port in top["ports"].items():
            if port_name.startswith(prefix):
                assert top["cells"][cell_name]["connections"][port_name] == port["bits"]
    memory_bits = 0
    for _, kind, cell in cells:
        if kind == "$mem_v2":
            params = cell["parameters"]
            memory_bits += int(params["WIDTH"], 2)*int(params["SIZE"], 2)
    assert memory_bits >= 512, memory_bits
    result = {"configuration": config, "instances": instances, "primitive_counts": primitives,
              "memory_bits": memory_bits, "latch_cells": 0, "division_modulo_cells": 0,
              "structural_assertions": "Yosys check -noinit -assert",
              "raw_stdout": evidence.relative(evidence.path / (name+".stdout.txt"))}
    (evidence.path / (name+"-summary.json")).write_text(json.dumps(result, indent=2)+"\n")
    return result


def synthesis_checks(evidence):
    evidence.versions(("python3", "yosys"))
    return [synthesize(evidence, config, f"synthesis-{config[0]}-{config[1]}-{config[2]}")
            for config in ((13, 11, 3), (1, 1, 0))]


def compact_smoke(evidence):
    path = evidence.path / "smoke.txt"
    ledger = smoke(path)
    executable = compile_sim(evidence, "top_tb", ROOT / "tests/top_tb.sv",
                             sorted((ROOT / "rtl").glob("*.sv")), "smoke-icarus",
                             parameters=["-Ptop_tb.W=1", "-Ptop_tb.H=1", "-Ptop_tb.L=0",
                                         "-Ptop_tb.CYCLE_LIMIT=400000"])
    out = run_top(evidence, executable, path, ledger, "smoke-icarus-run", icarus=True)
    assert f"SUMMARY top transactions={len(ledger)} " in out, out
    assert sum(row["observed_cycles"] for row in ledger) < 500000
    return ledger


def resets(evidence):
    executable = compile_sim(evidence, "reset_tb", ROOT / "tests/reset_tb.sv",
                             sorted((ROOT / "rtl").glob("*.sv")), "reset-icarus")
    out, _, _ = evidence.run(["vvp", evidence.relative(executable)], "reset-icarus-run")
    assert "SUMMARY reset input=1 output=1 refill=1 export=1" in out, out
    return {"input": 1, "output": 1, "refill": 1, "export": 1}


def cache_checks(evidence):
    path = evidence.path / "cache.txt"
    ledger = cache_scenario(path)
    executable = compile_sim(evidence, "top_tb", ROOT / "tests/top_tb.sv",
                             sorted((ROOT / "rtl").glob("*.sv")), "cache-verilator", True)
    try:
        run_top(evidence, executable, path, ledger, "cache-verilator-run")
        atomic_path = evidence.path / "state-directed.txt"
        atomic_ledger = directed_state(atomic_path)
        run_top(evidence, executable, atomic_path, atomic_ledger, "state-directed-run")
    finally:
        if executable.parent.is_dir():
            shutil.rmtree(executable.parent)
    return {"cache": ledger, "state": atomic_ledger}


MUTANTS = (
    ("bilinear", "g3_bilinear.sv", "{8'd0,total[31]}", "{8'd0,1'b0}", "BILINEAR_MISMATCH"),
    ("cache", "g3_texture_cache.sv", "tags[line_index*12 +:12]==block_tag",
     "1'b1", "RECORD_MISMATCH"),
    ("shader", "g3_shader_pipeline.sv", "8'd255-source_alpha",
     "8'd254-source_alpha", "SHADER_MISMATCH"),
    ("depth", "g2_zbuffer.sv", "new_depth<memory_q",
     "new_depth<=memory_q", "RECORD_MISMATCH"),
    ("perspective", "g2_interpolator.sv", "weight[v]<=lambda[v]*q[v];",
     "weight[v]<={lambda[v],24'd0};", "RECORD_MISMATCH"),
    ("dma", "g3_framebuffer_dma.sv", "row_address+{21'd0,x,2'd0}",
     "row_address+{21'd0,x,2'd0}+32'd4", "DMA_NUMERICAL_MISMATCH"),
)


def defect_checks(evidence, selected=None):
    evidence.versions(("python3", "verilator", "make", "g++"))
    results = []
    for kind, file_name, original, changed, token in MUTANTS:
        if selected and kind not in selected:
            continue
        mutation_hash = hashlib.sha256((kind+changed).encode()).hexdigest()[:12]
        mutant_root = evidence.path / f"mutant-{kind}-{mutation_hash}"
        shutil.copytree(ROOT / "rtl", mutant_root / "rtl")
        file = mutant_root / "rtl" / file_name
        before = file.read_text()
        required_occurrences = 2 if kind == "depth" else 1
        assert before.count(original) == required_occurrences, (kind, before.count(original))
        after = before.replace(original, changed)
        file.write_text(after)
        diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                           fromfile="rtl/"+file_name, tofile="mutant/rtl/"+file_name))
        (mutant_root / "mutation.diff").write_text(diff)
        record = {"kind": kind, "file": "rtl/"+file_name,
                  "original_sha256": hashlib.sha256(before.encode()).hexdigest(),
                  "mutated_sha256": sha(file), "diff": evidence.relative(mutant_root / "mutation.diff"),
                  "expected_mismatch": token}
        if kind in ("bilinear", "shader"):
            top, bench = "leaf_tb", ROOT / "tests/leaf_tb.sv"
            files = ("g3_bilinear.sv", "g3_shader_pipeline.sv")
            params = []
            scenario = evidence.path / f"mutant-{kind}-vectors.txt"
            leaf_vectors(scenario, 17, 356)
            extra = ["+vectors="+evidence.relative(scenario)]
        elif kind == "dma":
            top, bench, files = "dma_tb", ROOT / "tests/dma_tb.sv", ("g3_framebuffer_dma.sv",)
            params = ["-GW=13", "-GH=11", "-GL=3"]
            scenario = evidence.path / "mutant-dma-scenario.txt"
            dma_scenario(scenario, 13, 11, 3)
            extra = ["+scenario="+evidence.relative(scenario)]
        else:
            top, bench, files = "top_tb", ROOT / "tests/top_tb.sv", tuple(
                file.name for file in sorted((ROOT / "rtl").glob("*.sv")))
            config = (13, 11, 3) if kind == "cache" else (3, 3, 0)
            params = [f"-G{key}={value}" for key, value in zip(("W", "H", "L"), config)]
            scenario = evidence.path / f"mutant-{kind}-scenario.txt"
            mutation_scenario(scenario, kind)
            extra = ["+scenario="+evidence.relative(scenario)]
        for mutated in (False, True):
            name = f"defect-{kind}-{'mutated' if mutated else 'original'}"
            root = mutant_root if mutated else ROOT
            executable = compile_sim(evidence, top, bench,
                                     [root / "rtl" / file for file in files],
                                     name, True, params)
            run_args = list(extra)
            if top == "top_tb":
                run_args.append("+coverage="+evidence.relative(evidence.path / (name+".coverage.txt")))
            try:
                out, err, code = evidence.run([evidence.relative(executable), *run_args],
                                             name+"-run", expect=None)
                if mutated:
                    assert code != 0 and token in out+err, (
                        f"mutant {kind} survived or failed without intended numerical mismatch", code, out, err)
                else:
                    assert code == 0 and "SUMMARY" in out, ("original failed", kind, code, out, err)
                record["mutated" if mutated else "original"] = {
                    "exit_code": code, "stdout": evidence.relative(evidence.path / (name+"-run.stdout.txt")),
                    "specific_behavioral_mismatch": mutated and token in out+err}
            finally:
                if executable.parent.is_dir():
                    shutil.rmtree(executable.parent)
        results.append(record)
    if not selected:
        assert len(results) == 6 and all(row["mutated"]["specific_behavioral_mismatch"] for row in results)
    return results


def behavior_checks(evidence):
    evidence.versions(("python3", "iverilog", "vvp", "verilator", "make", "g++"))
    results = {"leaf": leaves(evidence), "smoke": compact_smoke(evidence),
               "reset": resets(evidence), "parameters": parameters(evidence),
               "cache": cache_checks(evidence), "framebuffer": dma_checks(evidence),
               "integrated": []}
    for config in ((1, 1, 0), (13, 11, 0), (13, 11, 3), (19, 17, 4), (256, 256, 3)):
        w, h, log = config
        name = f"behavior-{w}-{h}-{log}"
        executable = compile_sim(evidence, "top_tb", ROOT / "tests/top_tb.sv",
                                 sorted((ROOT / "rtl").glob("*.sv")), name, True,
                                 [f"-GW={w}", f"-GH={h}", f"-GL={log}"])
        try:
            path = evidence.path / (name+"-prerequisites.txt")
            ledger = prerequisites(path, config)
            run_top(evidence, executable, path, ledger, name+"-prerequisites-run")
            results["integrated"].append({"configuration": config,
                                           "case": "prerequisites", "transactions": ledger})
            for seed in (17, 89, 233):
                path = evidence.path / f"{name}-{seed}.txt"
                ledger = integrated(path, config, seed, compact=False)
                run_top(evidence, executable, path, ledger, f"{name}-{seed}-run")
                legacy = [r for r in ledger if r["label"].startswith(f"seed-{seed}-legacy-")]
                g3 = [r for r in ledger if r["label"].startswith(f"seed-{seed}-g3-")]
                opcodes = {r["opcode"] for r in ledger if r["label"].startswith("opcode-")}
                from model import OPCODES
                assert len(legacy) >= 48 and len(g3) >= 48 and opcodes == set(OPCODES)
                for index, row in enumerate(ledger):
                    if row["label"].startswith(("opcode-", "invalid-opcode-")):
                        assert ledger[index+1]["label"] == "immediate-valid-following-command"
                        assert ledger[index+1]["tag"] != row["tag"]
                assert all(r["observed_accepted_beats"] == 49 for r in g3)
                assert all(next(r for r in ledger if r["label"] == f"opcode-{m}")["pixels"] > 0
                           for m in (770, 771))
                results["integrated"].append({"configuration": config, "seed": seed,
                                               "legacy_draws": len(legacy), "g3_draws": len(g3),
                                               "legal_opcodes": len(opcodes), "transactions": ledger})
                print(f"PROGRESS behavior configuration={config} seed={seed} compared", flush=True)
        finally:
            if executable.parent.is_dir():
                shutil.rmtree(executable.parent)
    return results


def scenario_audit(evidence):
    rows = []
    for config in ((1, 1, 0), (13, 11, 0), (13, 11, 3), (19, 17, 4), (256, 256, 3)):
        name = "-".join(map(str, config))
        for seed in (17, 89, 233):
            ledger = integrated(evidence.path / f"audit-{name}-{seed}.txt", config, seed)
            rows.append({"configuration": config, "seed": seed, "generated_transactions": len(ledger)})
        prerequisites(evidence.path / f"prerequisites-{name}.txt", config)
    directed_state(evidence.path / "audit-directed-state.txt")
    cache_scenario(evidence.path / "audit-cache.txt")
    return {"generation_only_not_rtl_coverage": rows}


def portable_checks(evidence, child=False):
    evidence.versions(("python3", "iverilog", "vvp", "yosys"))
    if child:
        assert not (ROOT / "crucible_g2_reference").exists()
        assert not any((ROOT / name).exists() for name in (".vulcan", ".git", ".tooling", "VULCAN"))
        return {"smoke": compact_smoke(evidence), "leaf": leaves(evidence, compact=True),
                "structure": synthesize(evidence, (1, 1, 0), "portable-structure")}
    portable = evidence.path / "portable-root-6f9a2c71"
    portable.mkdir()
    copied = {}
    for pattern in ("rtl/*.sv", "design/*.md", "tests/*"):
        for source in sorted(ROOT.glob(pattern)):
            if not source.is_file():
                continue
            relative = source.relative_to(ROOT)
            destination = portable / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            assert sha(source) == sha(destination)
            copied[str(relative)] = sha(destination)
    out, _, _ = evidence.run(["python3", "tests/verify.py", "--suite", "reproduce",
                             "--portable-child"], "portable-child", cwd=portable)
    summary = json.loads(out.strip().splitlines()[-1])
    assert summary["status"] == "passed", summary
    receipt = portable / summary["receipt"]
    child_record = json.loads(receipt.read_text())
    assert child_record["status"] == "passed"
    assert child_record["source_sha256"] == copied
    return {"copied_source_sha256": copied, "child_receipt": evidence.relative(receipt),
            "child_receipt_sha256": sha(receipt), "independent_comparisons_and_tools": child_record["runs"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("behavior", "defects", "synthesis", "reproduce"),
                        required=True)
    parser.add_argument("--probe", choices=("leaves", "integration", "geometry", "dma", "parameters",
                                          "structure", "smoke", "reset", "cache", "mutants", "audit",
                                          "perspective"))
    parser.add_argument("--repair-of")
    parser.add_argument("--portable-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    evidence = Evidence(ROOT, args.probe or args.suite, ["python3", "tests/verify.py"]+sys.argv[1:],
                        preparation=bool(args.probe), repair_of=args.repair_of)
    try:
        if not __debug__:
            raise RuntimeError("Verifier assertions require Python without optimization.")
        if args.probe:
            evidence.versions(("python3", "iverilog", "vvp", "verilator", "make", "g++", "yosys"))
            runs = (defect_checks(evidence, selected=("perspective",))
                    if args.probe == "perspective" else
                    scenario_audit(evidence) if args.probe == "audit" else
                    defect_checks(evidence, selected=("cache", "depth", "perspective"))
                    if args.probe == "mutants" else
                    synthesize(evidence, (1, 1, 0), "structure-singleton")
                    if args.probe == "structure" else
                    top_probe(evidence, compact=False) if args.probe == "geometry" else
                    {"leaves": leaves, "integration": top_probe,
                     "dma": dma_checks, "parameters": parameters, "smoke": compact_smoke,
                     "reset": resets, "cache": cache_checks}[args.probe](evidence))
        elif args.suite == "synthesis":
            runs = synthesis_checks(evidence)
        elif args.suite == "defects":
            runs = defect_checks(evidence)
        elif args.suite == "behavior":
            runs = behavior_checks(evidence)
        elif args.suite == "reproduce":
            runs = portable_checks(evidence, child=args.portable_child)
        else:
            raise AssertionError("unreachable suite")
        evidence.finish("passed", runs=runs)
        print(json.dumps({"status": "passed", "receipt": evidence.relative(evidence.path / "receipt.json")}))
        return 0
    except Exception as exc:
        evidence.finish("failed", error=str(exc))
        print(json.dumps({"status": "failed", "error": str(exc),
                          "receipt": evidence.relative(evidence.path / "receipt.json")}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
