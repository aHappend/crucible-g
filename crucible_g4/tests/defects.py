"""Twelve isolated executing faulty variants; clean production RTL is immutable."""

import shutil
import uuid

from execution import compile_top, dump, hashes, simulate_top
from leaves import compile_leaves, leaf_vectors, simulate_leaves
from scenarios import PARAMETERS, directed

MUTATIONS = (
    ("signed_slab_rounding", "g4_slab.sv",
     "if (d>0) axis_entry<=quotient_ceil;",
     "if (d>0) axis_entry<=quotient_floor;", "top"),
    ("parallel_axis", "g4_slab.sv",
     "if (o<lo || o>hi) hit<=0;", "if (o<=lo || o>=hi) hit<=0;", "top"),
    ("right_child_push", "g4_bvh.sv",
     "stack[occupancy]<=node_q[64 +:9];", "stack[occupancy]<=9'd0;", "top"),
    ("closest_tie", "g4_bvh.sv",
     "node_q[96 +:32]<primitive_id", "node_q[96 +:32]>primitive_id", "top"),
    ("radix_stability", "g4_radix_sort.sv",
     "wire [8:0] scatter_address=read_q[bit_index] ? position_one : position_zero;",
     "wire [8:0] scatter_address=bit_index==31 ? "
     "(read_q[bit_index] ? count+zeros-9'd1-position_one : zeros-9'd1-position_zero) : "
     "(read_q[bit_index] ? position_one : position_zero);", "top"),
    ("off_diagonal_conic", "g4_conic.sv",
     "low_b<=abs_b*xy[24:0]; high_b<=b*xy_high;",
     "low_b<=0; high_b<=0;", "top"),
    ("exponential_index", "g4_conic.sv",
     "else address<=rounded_nq[45:33];",
     "else address<=rounded_nq[45:33]+13'd1;", "top"),
    ("transmittance_conservation", "g4_compositor.sv",
     "next_t<=transmittance-weight;", "next_t<=transmittance-weight+17'd1;", "top"),
    ("termination_equality", "g4_compositor.sv",
     "transmittance<epsilon", "transmittance<=epsilon", "top"),
    ("stalled_payload", "crucible_g4_top.sv",
     "OUTPUT_RECORD: if (m_ready) begin", "OUTPUT_RECORD: if (1'b1) begin", "top"),
    ("parent_bilinear_rounding", "g3_bilinear.sv",
     "{1'b0,total[39:32]}+{8'd0,total[31]}", "{1'b0,total[39:32]}", "leaves"),
    ("parent_blend_factor", "g3_shader_pipeline.sv",
     "2: factor=source_alpha;", "2: factor=8'd255-source_alpha;", "leaves"),
)


def defects(run):
    run.versions(("python3", "verilator"))
    production = hashes(run.root)
    workload = directed(PARAMETERS[1], compact=True)
    vectors = leaf_vectors(compact=True)
    control = compile_top(run, PARAMETERS[1], "verilator", stem="clean-top")
    simulate_top(run, control, workload, "clean-top-run")
    control = compile_leaves(run, "verilator", stem="clean-leaves")
    simulate_leaves(run, control, vectors, "clean-leaves-run")
    rows = []
    for mutation in MUTATIONS:
        name = mutation[0]
        execute_mutation(run, mutation, workload, vectors)
        rows.append({"mutation": name, "elaborated": True, "functional_mismatch": True,
                     "stdout": run.relative(run.folder / f"{name}-run.stdout.txt"),
                     "stderr": run.relative(run.folder / f"{name}-run.stderr.txt")})
        run.receipt["comparisons"]["isolated_mutations"] = rows[:]
        run.save()
    assert len(rows) == 12
    assert hashes(run.root) == production, "production sources changed during defect suite"


def execute_mutation(run, mutation, workload=None, vectors=None):
    name, filename, original, replacement, fixture = mutation
    source = run.folder / f"fault-{name}-{uuid.uuid4().hex[:8]}"
    shutil.copytree(run.root / "rtl", source)
    target = source / filename
    text = target.read_text()
    assert text.count(original) == 1, f"mutation anchor is not unique: {name}"
    target.write_text(text.replace(original, replacement, 1))
    dump(run.folder / f"{name}.mutation.json",
         {"name": name, "source_copy": run.relative(source), "file": filename,
          "original": original, "replacement": replacement})
    if fixture == "top":
        executable = compile_top(run, PARAMETERS[1], "verilator", rtl=source, stem=name)
        simulate_top(run, executable, workload or directed(PARAMETERS[1], compact=True),
                     f"{name}-run", expect_mismatch=True)
    else:
        executable = compile_leaves(run, "verilator", rtl=source, stem=name)
        simulate_leaves(run, executable, vectors or leaf_vectors(compact=True),
                        f"{name}-run", expect_mismatch=True)
