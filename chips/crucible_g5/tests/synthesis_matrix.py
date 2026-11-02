"""Complete memory-preserving L1 elaboration/coarse-synthesis matrix."""

import gzip
import hashlib
import json
from pathlib import Path

from scenarios import CELLS, PARAMETERS


NEW_TOPS = ("g5_morton", "g5_lbvh", "g5_ray_triangle", "g5_ray_query", "g5_svgf",
            "g5_divider", "g5_signed_divider", "g5_sqrt", "g5_mul", "g5_limb_alu",
            "g5_slab", "g5_svgf_channel", "g5_svgf_surface")


def check(run, reproduction=False):
    matrix = [("integrated-"+cell, "crucible_g5_top", dict(zip(PARAMETERS, values)),
               cell != "default") for cell, values in CELLS.items()]
    matrix += [(top+"-default", top, {}, False) for top in NEW_TOPS]
    for cell in ("singleton", "nonpower", "maximum"):
        parameters = dict(zip(PARAMETERS, CELLS[cell]))
        matrix += [(top+"-"+cell, top, {"MAX_PRIMITIVES": parameters["MAX_PRIMITIVES"]}, False)
                   for top in ("g5_lbvh", "g5_ray_query")]
        matrix.append(("g5_svgf-"+cell, "g5_svgf", {
            "MAX_WIDTH": parameters["SVGF_MAX_WIDTH"],
            "MAX_HEIGHT": parameters["SVGF_MAX_HEIGHT"]}, False))
    if reproduction:
        matrix = [("clean-singleton", "crucible_g5_top",
                   dict(zip(PARAMETERS, CELLS["singleton"])), True)]
    results = []
    run.receipt["synthesis"] = results
    for name, top, parameters, structural in matrix:
        argv = ["python3", "tests/synthesis.py", "--output-root", str(run.directory),
                "--top", top, "--defer"]
        if structural:
            argv.append("--structural-only")
        for key, value in parameters.items():
            argv.extend(["--parameter", f"{key}={value}"])
        out, err, _ = run.execute(argv, name, timeout=1200)
        notices = [json.loads(line) for line in out.read_text().splitlines()
                   if line.startswith('{"receipt":')]
        assert len(notices) == 1 and notices[0]["exit_code"] == 0
        path = Path(notices[0]["receipt"])
        result = json.loads(path.read_text())
        assert result["exit_code"] == 0 and result["tool_exit_code"] == 0
        assert result["settled"] and not result["timed_out"] and result["source_unchanged"]
        assert result["source_sha256"] == run.receipt["source_sha256"]
        with gzip.open(result["compressed_netlist"], "rb") as netlist:
            digest, size = hashlib.sha256(), 0
            while chunk := netlist.read(1 << 20):
                digest.update(chunk)
                size += len(chunk)
        assert digest.hexdigest() == result["netlist_sha256"] and size == result["netlist_bytes"]
        results.append({"case": name, "top": top, "parameters": parameters,
                        "stage": result["synthesis_stage"], "receipt": str(path),
                        "retained_memory_bits": result["retained_memory_bits"],
                        "cell_counts": result["cell_counts"],
                        "netlist_sha256": result["netlist_sha256"], "netlist_bytes": size,
                        "stdout": str(out), "stderr": str(err)})
    return results
