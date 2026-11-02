"""Source-bound Yosys coarse synthesis with retained memories and zero-latch assertions."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from preparation import inventory


def synthesize(directory, top, parameters, defer=False, repair_of=None,
               source_directory="rtl", structural_only=False):
    directory.mkdir()
    script_path = directory / "synthesis.ys"
    netlist_path = directory / "netlist.json"
    if source_directory not in ("rtl", "crucible_g4_reference/rtl"):
        raise ValueError("unsupported synthesis source directory")
    sources = sorted(str(p) for p in Path(source_directory).glob("*.sv"))
    if not sources:
        raise ValueError("empty synthesis source directory")
    lines = ["read_verilog -sv " + ("-defer " if defer else "") + " ".join(sources)]
    if parameters:
        lines.append("chparam " + " ".join("-set " + key + " " + str(value)
                                         for key, value in parameters.items()) + " " + top)
    lines.extend([
        "hierarchy -check -top " + top,
        "proc",
        "opt_expr",
        "opt_clean",
        "check -assert",
        "memory -nomap",
        "opt_clean",
    ])
    if not structural_only:
        lines.append("synth -top " + top + " -run coarse:coarse")
    lines.extend([
        "check -assert",
        "select -assert-none t:$dlatch t:$adlatch t:$dlatchsr t:$div t:$mod",
        "stat",
        "write_json " + str(netlist_path),
    ])
    script_path.write_text("\n".join(lines) + "\n")
    argv = ["yosys", "-s", str(script_path)]
    receipt = {"argv": argv, "cwd": ".", "top": top, "parameters": parameters,
               "source_sha256": inventory(Path.cwd()), "start_time": time.time(),
               "timeout_s": 1200, "stdout": str(directory / "stdout.txt"),
               "stderr": str(directory / "stderr.txt"), "repair_of": repair_of,
               "deferred_elaboration": defer, "source_directory": source_directory,
               "selected_source_sha256": {
                   source: hashlib.sha256(Path(source).read_bytes()).hexdigest()
                   for source in sources}}
    receipt["synthesis_stage"] = "structure" if structural_only else "coarse"
    try:
        with (directory / "version.stdout.txt").open("w") as out, (
                directory / "version.stderr.txt").open("w") as err:
            version = subprocess.run(["yosys", "-V"], stdout=out, stderr=err,
                                     timeout=60, check=False)
        receipt["tool_version"] = (directory / "version.stdout.txt").read_text().strip()
        receipt["version_argv"] = ["yosys", "-V"]
        if version.returncode:
            raise RuntimeError(f"Yosys version exit {version.returncode}")
        with (directory / "stdout.txt").open("w") as stdout, (
                directory / "stderr.txt").open("w") as stderr:
            child = subprocess.run(argv, stdout=stdout, stderr=stderr, timeout=1200, check=False)
        receipt.update(tool_exit_code=child.returncode, timed_out=False, settled=True)
        if child.returncode:
            raise RuntimeError(f"Yosys exit {child.returncode}")
        netlist_bytes = netlist_path.read_bytes()
        netlist = json.loads(netlist_bytes)
        modules = netlist["modules"]
        assert top in modules, "top absent from retained netlist"
        prohibited = {"$dlatch", "$adlatch", "$dlatchsr", "$div", "$mod"}
        counts = {}
        memory_bits = 0
        for name, module in modules.items():
            assert int(module.get("attributes", {}).get("blackbox", "0"), 2) == 0, (
                "functional blackbox: " + name)
            for cell in module["cells"].values():
                cell_type = cell["type"]
                assert cell_type not in prohibited, "prohibited cell: " + cell_type
                assert not cell_type.startswith("$") or cell_type not in {"$divfloor", "$modfloor"}
                counts[cell_type] = counts.get(cell_type, 0) + 1
                if cell_type == "$mem_v2":
                    p = cell["parameters"]
                    memory_bits += int(p["WIDTH"], 2) * int(p["SIZE"], 2)
        assert sum(count for kind, count in counts.items() if (
            "dff" in kind or kind == "$mem_v2")) > 0, "no retained state"
        for port in ("s_ready", "m_valid"):
            bits = modules[top]["ports"].get(port, {}).get("bits", [])
            assert bits and any(isinstance(bit, int) for bit in bits), (
                "constant or missing handshake: " + port)
        data_ports = [port for port in modules[top]["ports"] if port.startswith("m_") and
                      port not in ("m_valid", "m_ready", "m_terminal")]
        assert any(any(isinstance(bit, int) for bit in modules[top]["ports"][port]["bits"])
                   for port in data_ports), "all functional outputs constant"
        if top == "crucible_g5_top":
            top_cells = modules[top]["cells"]
            for child in ("compatibility", "builder", "triangle", "ray_query", "denoiser"):
                matches = [cell for name, cell in top_cells.items()
                           if name.split(".")[-1] == child]
                assert len(matches) == 1, "literal integrated child absent: " + child
                assert matches[0]["type"] in modules, "unresolved child: " + child
                assert modules[matches[0]["type"]]["cells"], "empty child: " + child
                child_module = modules[matches[0]["type"]]
                assert any("dff" in cell["type"] or cell["type"] == "$mem_v2"
                           for cell in child_module["cells"].values()), (
                    "integrated child has no retained control state: " + child)
                assert any(any(isinstance(bit, int) for bit in connection)
                           for connection in matches[0]["connections"].values()), (
                    "integrated child has no signal connectivity: " + child)
        compressed_path = directory / "netlist.json.gz"
        with gzip.open(compressed_path, "wb") as compressed:
            compressed.write(netlist_bytes)
        with gzip.open(compressed_path, "rb") as compressed:
            restored = compressed.read()
        assert restored == netlist_bytes, "lossy netlist retention"
        receipt.update(netlist_sha256=hashlib.sha256(restored).hexdigest(),
                       netlist_bytes=len(restored), compressed_netlist=str(compressed_path),
                       cell_counts=counts, retained_memory_bits=memory_bits, exit_code=0)
        netlist_path.unlink()
    except subprocess.TimeoutExpired:
        receipt.update(timed_out=True, settled=True, exit_code=1, error="Yosys timeout")
    except (AssertionError, OSError, RuntimeError, ValueError, KeyError) as error:
        receipt.update(exit_code=1, error=str(error))
    finally:
        receipt["end_time"] = time.time()
        receipt["source_unchanged"] = receipt["source_sha256"] == inventory(Path.cwd())
        (directory / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="evidence/preparation")
    parser.add_argument("--top", default="crucible_g5_top")
    parser.add_argument("--parameter", action="append", default=[])
    parser.add_argument("--defer", action="store_true")
    parser.add_argument("--repair-of")
    parser.add_argument("--source-directory", choices=["rtl", "crucible_g4_reference/rtl"],
                        default="rtl")
    parser.add_argument("--structural-only", action="store_true")
    args = parser.parse_args()
    output = Path(args.output_root)
    output.mkdir(parents=True, exist_ok=True)
    parameters = {key: int(value) for key, value in (
        entry.split("=", 1) for entry in args.parameter)}
    directory = output / ("synthesis-" + args.top + "-" + uuid.uuid4().hex)
    result = synthesize(directory, args.top, parameters, args.defer, args.repair_of,
                        args.source_directory, args.structural_only)
    print(json.dumps({"receipt": str(directory / "receipt.json"),
                      "exit_code": result["exit_code"]}), flush=True)
    sys.exit(result["exit_code"])
