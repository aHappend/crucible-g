#!/usr/bin/env python3
"""Portable L1 entry. --compact is partial reproduction, never full acceptance.

Requirement mapping: model.py defines exact independent integer/Fraction rules;
scenarios.py defines required matrix, public persistence, clipping and reset cases;
stream_tb.sv checks every output word/last and public handshake; leaf_tb.sv
checks arithmetic signs, endpoints and the exact pre/post-edge schedules.
This entry builds real simulators, isolated behavioral mutants, two complete-top
Yosys configurations and a clean-directory partial reproduction. Native physical
timing and board gates belong exclusively to the shared runtime.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from model import Q, Projected, attributes, signed, transform  # noqa: E402
from scenarios import (CELLS, SEEDS, Campaign, command, compact_campaign, directed,
                       matrix_campaign, triangle)  # noqa: E402

TOOLS = ("python3", "iverilog", "vvp", "verilator", "yosys", "g++", "make")
SELECTORS = ("rtl/*.sv", "design/SPEC.md", "design/ARCHITECTURE.md",
             "crucible_g1_reference/rtl/*.sv", "tests/*")


def utc():
    return datetime.now(timezone.utc).isoformat()


def identity():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]


def relative(path):
    return str(Path(path).relative_to(ROOT))


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sources():
    files = []
    for selector in SELECTORS:
        matched = sorted(p for p in ROOT.glob(selector) if p.is_file())
        if not matched:
            raise RuntimeError(f"EMPTY_SOURCE_SELECTOR: {selector}")
        files.extend(matched)
    return sorted(set(files))


class ToolFailure(RuntimeError):
    def __init__(self, record):
        self.record = record
        super().__init__(f"TOOL_FAILURE {record['argv']} exit={record['exit_code']} "
                         f"timeout={record['timed_out']}; stderr={record['stderr']}")


class Evidence:
    def __init__(self, args):
        parent = ROOT / "evidence"
        stem = "l1"
        if args.probe:
            parent = parent / "preparation"
            stem = "verifier-" + args.probe
        self.path = parent / (stem + "-" + identity())
        self.path.mkdir(parents=True, exist_ok=False)
        self.records = []
        self.coverage = []
        self.receipt = {
            "schema": 1, "kind": "advisory-preparation" if args.probe else "l1",
            "scope": args.probe or ("partial-compact" if args.compact else "full"),
            "acceptance_evidence": False if args.probe else "shared-runtime-admission-required",
            "argv": ["python3", "tests/verify.py", *sys.argv[1:]], "cwd": ".",
            "start_utc": utc(), "end_utc": None, "exit_code": None,
            "timeout_seconds": None, "timed_out": False,
            "source_sha256": {}, "commands": self.records, "coverage": self.coverage,
            "repair_of": args.repair_of,
        }
        snapshot = self.path / ("sources-" + uuid.uuid4().hex[:8])
        for source in sources():
            destination = snapshot / source.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            self.receipt["source_sha256"][relative(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
        self.receipt["source_snapshot"] = relative(snapshot)
        self.save()

    def save(self):
        dump(self.path / "receipt.json", self.receipt)

    def run(self, name, argv, cwd=ROOT, allow_failure=False, timeout=3600):
        prefix = f"{len(self.records):03d}-{name}"
        stdout, stderr = self.path / (prefix + ".stdout.txt"), self.path / (prefix + ".stderr.txt")
        record = {"argv": [str(x) for x in argv], "cwd": relative(cwd),
                  "start_utc": utc(), "timeout_seconds": timeout,
                  "stdout": relative(stdout), "stderr": relative(stderr)}
        start = time.monotonic()
        with stdout.open("wb") as out, stderr.open("wb") as err:
            try:
                child = subprocess.run(argv, cwd=cwd, stdout=out, stderr=err,
                                       timeout=timeout, check=False)
                record.update(exit_code=child.returncode, timed_out=False)
            except subprocess.TimeoutExpired:
                record.update(exit_code=None, timed_out=True)
        record.update(end_utc=utc(), duration_seconds=time.monotonic()-start)
        self.records.append(record)
        self.save()
        if (record["exit_code"] != 0 or record["timed_out"]) and not allow_failure:
            raise ToolFailure(record)
        return record, stdout.read_text(errors="replace"), stderr.read_text(errors="replace")

    def tools(self):
        missing = [tool for tool in TOOLS if shutil.which(tool) is None]
        if missing:
            raise RuntimeError("MISSING_TOOLS: " + ", ".join(missing) + "; installation is not permitted")
        self.receipt["tool_versions"] = {}
        for tool, option in (("python3", "--version"), ("iverilog", "-V"), ("vvp", "-V"),
                             ("verilator", "--version"), ("yosys", "-V"),
                             ("g++", "--version"), ("make", "--version")):
            record, out, err = self.run("version-"+tool.replace("+", "p"), [tool, option])
            self.receipt["tool_versions"][tool] = (out or err).splitlines()[0]
        self.save()


def rtl_paths(directory=None):
    return sorted(relative(p) for p in (directory or ROOT / "rtl").glob("*.sv"))


def compile_stream(evidence, cell, backend, directory=None, parent=False):
    key = uuid.uuid4().hex[:8]
    bench = "tests/stream_tb.sv"
    rtl = rtl_paths(directory)
    if parent:
        rtl = sorted(relative(p) for p in (ROOT / "crucible_g1_reference/rtl").glob("*.sv"))
    parameters = dict(MW=cell[0], MH=cell[1], TL=cell[2], PARENT=int(parent))
    if backend == "icarus":
        parameters["CYCLE_LIMIT"] = 500000
        binary = evidence.path / ("stream-" + key + ".vvp")
        argv = ["iverilog", "-g2012", "-Wall", "-s", "stream_tb", "-o", relative(binary)]
        argv += [f"-Pstream_tb.{k}={v}" for k, v in parameters.items()]
        evidence.run("compile-icarus", argv + rtl + [bench])
        return ["vvp", relative(binary)], None
    obj = evidence.path / ("compile-obj-" + key)
    binary = "sim"
    argv = ["verilator", "--binary", "--timing", "--assert", "-Wno-fatal",
            "--top-module", "stream_tb", "-j", "2", "--Mdir", relative(obj), "-o", binary]
    argv += [f"-G{k}={v}" for k, v in parameters.items()]
    evidence.run("compile-verilator", argv + rtl + [bench])
    return [relative(obj / binary)], obj


def clean_intermediates(obj):
    if obj is None:
        return
    # Keep generated C++, makefiles and the simulator. Only known compiler
    # intermediates, never whole evidence directories, are removed.
    for pattern in ("*.o", "*.a", "*.gch"):
        for path in obj.glob(pattern):
            path.unlink()


def execute_campaign(evidence, campaign, executable, name, thresholds=False):
    vectors = evidence.path / (name + "-" + uuid.uuid4().hex[:8] + ".txt")
    campaign.write(vectors)
    record, out, _ = evidence.run(name, executable + ["+vectors=" + relative(vectors)])
    expected_words = sum(len(c.result.transfers) for c in campaign.cases if c.result is not None)
    match = re.search(r"STREAM_OK commands=(\d+) compared_words=(\d+) stalls=(\d+)", out)
    if not match or int(match[1]) != len(campaign.cases) or int(match[2]) != expected_words:
        raise AssertionError(f"NO_COMPLETE_COMPARISON: {record['stdout']}")
    assert int(match[3]) > 0, "NO_OBSERVED_STALL"
    # Coverage is admitted to the ledger only after the actual simulator
    # compared every transfer and reported the exact expected totals.
    coverage = campaign.assert_thresholds() if thresholds else campaign.coverage()
    coverage.update(cell=list(campaign.cell), seed=campaign.seed, run=name,
                    compared_words=expected_words, observed_stall_cycles=int(match[3]),
                    receipt_command=len(evidence.records)-1, outcome="passed",
                    vectors=relative(vectors))
    evidence.coverage.append(coverage)
    evidence.save()
    return coverage


def pack(values, bits):
    return sum((v & ((1 << bits)-1)) << (i*bits) for i, v in enumerate(values))


def leaf_vectors(path, compact):
    rng = random.Random(2026)
    rows = []
    values = [(0, 1), (1, 1), (-1, 1), (1, -1), (-1, -1),
              (7, 3), (-7, 3), (7, -3), (-7, -3),
              (-(1<<95), 1), ((1<<95)-1, (1<<63)-1),
              (-(1<<95), -(1<<63)), ((1<<95)-1, -(1<<63)),
              (1, -(1<<63)), (-1, (1<<63)-1),
              ((1<<80)+1234567, (1<<48)+17)]
    values += [(rng.randrange(-(1<<94), 1<<94), rng.choice((-1, 1))*rng.randrange(1, 1<<63))
               for _ in range(8 if compact else 96)]
    for mode in (0, 1):
        for n, d in values:
            quotient, remainder = divmod(n, d)
            assert n == quotient*d+remainder and (not remainder or (remainder>0)==(d>0))
            rows.append((mode, n & ((1<<96)-1), d & ((1<<64)-1), 0,
                         quotient & ((1<<96)-1), remainder & ((1<<64)-1)))
    for index in range(8 if compact else 64):
        l0 = rng.randrange(Q+1)
        l1 = rng.randrange(Q-l0+1)
        lambdas = (l0,l1,Q-l0-l1)
        qs = (1,1<<40,(1<<40)-1) if index == 0 else tuple(rng.randrange(1,1<<40) for _ in range(3))
        attrs = [tuple(rng.randrange(-(1<<31), 1<<31) for _ in range(6)) for _ in range(3)]
        vertices = [Projected(0,0,q,0,a,1) for q,a in zip(qs,attrs)]
        expected = attributes(vertices,lambdas)
        rows.append((2,pack([a for v in attrs for a in v],32),pack(qs,41),
                     pack(lambdas,17),pack(expected,32),0))
    for coordinates in (
        ((0,0),(65536,0),(0,65536)), ((65536,65536),(0,0),(65536,0)),
        ((0,0),(0,0),(65536,65536)), ((255,128),(129,65535),(32768,17)),
    ):
        (ax,ay),(bx,by),(px,py)=coordinates
        result=(bx-ax)*(py-ay)-(by-ay)*(px-ax)
        rows.append((3,pack([pack(v,17) for v in coordinates],34),0,0,result&((1<<37)-1),0))
    for index in range(8 if compact else 64):
        a = tuple(rng.randrange(-(1<<31),1<<31) for _ in range(4))
        b = tuple(rng.randrange(-(1<<31),1<<31) for _ in range(4))
        result=max(-(1<<31),min((1<<31)-1,sum(x*y for x,y in zip(a,b))//Q))
        rows.append((4,pack(a,32),pack(b,32),0,result&0xffffffff,0))
    with path.open("w",encoding="ascii") as output:
        for mode,a,b,extra,expected,remainder in rows:
            output.write(f"{mode} {a:x} {b:x} {extra:x} {expected:x} {remainder:x}\n")
    return len(rows)


def leaves(evidence, compact=False, backend="icarus"):
    vectors = evidence.path / ("leaves-" + uuid.uuid4().hex[:8] + ".txt")
    count = leaf_vectors(vectors,compact)
    if backend == "icarus":
        binary=evidence.path / ("leaves-"+uuid.uuid4().hex[:8]+".vvp")
        evidence.run("leaf-compile",["iverilog","-g2012","-Wall","-s","leaf_tb",
                     "-o",relative(binary),*rtl_paths(),"tests/leaf_tb.sv"])
        executable=["vvp",relative(binary)]
        obj=None
    else:
        obj=evidence.path / ("compile-obj-"+uuid.uuid4().hex[:8])
        evidence.run("leaf-compile",["verilator","--binary","--timing","--assert","-Wno-fatal",
                     "--top-module","leaf_tb","-j","2","--Mdir",relative(obj),"-o","sim",
                     *rtl_paths(),"tests/leaf_tb.sv"])
        executable=[relative(obj/"sim")]
    try:
        record,out,_=evidence.run("leaf-behavior",executable+["+vectors="+relative(vectors)])
        match=re.search(r"LEAF_OK comparisons=(\d+) cycles=(\d+)",out)
        assert match and int(match[1])==count, f"MISSING_LEAF_COMPARISONS: {record['stdout']}"
        assert int(match[2])<=500000
        evidence.receipt.setdefault("arithmetic",[]).append({
            "backend":backend,"compared":count,"cycles":int(match[2]),
            "latencies":{"g2_divider":588,"g1_divider":98,"g2_interpolator":596,
                         "g1_edge":2,"g1_dot4":4},
            "command":len(evidence.records)-1,"outcome":"passed"})
        evidence.save()
        if backend=="icarus":
            record,out,err=evidence.run("zero-denominator",
                executable+["+zero_denominator=1"],allow_failure=True)
            assert record["exit_code"] not in (0,None) and not record["timed_out"]
            assert "g2_divider: zero denominator" in out+err, "MISSING_ZERO_DIVISION_ASSERTION"
            evidence.receipt["zero_denominator_assertion"]={
                "outcome":"explicitly-rejected","command":len(evidence.records)-1}
            evidence.save()
    finally:
        clean_intermediates(obj)


def compact(evidence, backend="verilator"):
    leaves(evidence,compact=True,backend="icarus")
    campaign=compact_campaign()
    executable,obj=compile_stream(evidence,campaign.cell,backend)
    try:
        execute_campaign(evidence,campaign,executable,"compact-stream")
    finally:
        clean_intermediates(obj)
    synthesis(evidence, compact_only=True)


def source_rules():
    for source in (ROOT/"rtl").glob("*.sv"):
        text=source.read_text()
        text=re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
        text=re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
        assert not re.search(r"[/%%]",text), f"COMBINATIONAL_OPERATOR: {relative(source)}"
    for source in sources():
        if source.suffix not in (".sv",".md",".py"):
            continue
        text=source.read_text()
        # These are host privacy/portability checks, not tests of runtime
        # metadata, device enumeration or native timing-gate receipts.
        for prefix in ("/"+"data/", "/"+"home/", "/"+"root/"):
            assert prefix not in text, f"PRIVATE_HOST_PATH: {relative(source)}"


def yosys_number(value):
    return int(value,2) if isinstance(value,str) else value


def synthesis(evidence, compact_only=False):
    for name,compact_top in ([("compact",True)] if compact_only else
                             [("default",False),("compact",True)]):
        netlist=evidence.path/(name+"-"+uuid.uuid4().hex[:8]+".json")
        script=evidence.path/(name+"-"+uuid.uuid4().hex[:8]+".ys")
        lines=["read_verilog -sv -DSYNTHESIS "+" ".join(rtl_paths())]
        if compact_top:
            lines += ["chparam -set MAX_WIDTH 1 -set MAX_HEIGHT 1 -set TILE_LOG2 3 crucible_g2_top"]
        lines += ["hierarchy -check -top crucible_g2_top",
                  "proc", "opt_expr", "opt_clean", "check -assert",
                  "memory -nomap", "opt_clean", "check -assert"]
        if compact_top:
            # Map only this explicitly compact elaboration. Avoid unrestricted
            # full synth/ABC/opt -full on the default depth RAM.
            # Yosys creates undefined read-mux leaves above the declared
            # 384-word array size. Normalize those generated don't-cares using
            # the standard synthesis pass, after check -assert has already
            # rejected any undriven source net before memory mapping.
            lines += ["memory_map", "opt_expr -undriven -mux_undef",
                      "opt_clean", "check -assert", "techmap", "opt_expr",
                      "opt_clean", "check -assert"]
        lines += ["stat", "write_json "+relative(netlist)]
        script.write_text("\n".join(lines)+"\n",encoding="ascii")
        record,_,_=evidence.run("yosys-"+name,["yosys","-Q","-s",relative(script)])
        modules=json.loads(netlist.read_text())["modules"]
        instances=[]
        state_bits=memory_bits=0

        def visit(module_name, path):
            nonlocal state_bits,memory_bits
            module=modules[module_name]
            assert not yosys_number(module.get("attributes",{}).get("blackbox",0))
            for cell_name,cell in module.get("cells",{}).items():
                kind=cell["type"]
                full=path+"."+cell_name
                assert "latch" not in kind.lower(), ("INFERRED_LATCH",full,kind)
                assert kind not in ("$div","$mod","$divfloor","$modfloor"), ("COMBINATIONAL_DIVMOD",full)
                if kind in modules:
                    instances.append(full)
                    visit(kind,full)
                elif kind.startswith(("$dff","$adff","$sdff")):
                    state_bits+=yosys_number(cell["parameters"]["WIDTH"])
                elif kind.startswith(("$_DFF","$_SDFF")):
                    state_bits+=1
                elif kind.startswith("$mem"):
                    memory_bits+=(yosys_number(cell["parameters"]["WIDTH"]) *
                                  yosys_number(cell["parameters"]["SIZE"]))
                connections=cell.get("connections",{})
                assert connections and any(connections.values()), ("DISCONNECTED_CELL",full)
                for port,direction in cell.get("port_directions",{}).items():
                    if direction=="input":
                        assert connections.get(port), ("EMPTY_INPUT_CONNECTION",full,port)
        visit("crucible_g2_top","top")
        for expected in ("top.legacy","top.engine","top.engine.setup","top.engine.raster",
                         "top.engine.zbuffer","top.engine.interpolator",
                         "top.engine.setup.transform","top.engine.setup.clipper","top.engine.setup.project"):
            assert expected in instances, ("MISSING_HIERARCHY",expected)
        assert len([p for p in instances if p.startswith("top.engine.interpolator.") and
                    p.endswith(".divider")])==6, "MISSING_ATTRIBUTE_DIVIDERS"
        assert state_bits>10000, ("VACUOUS_STATE",state_bits)
        if compact_top:
            assert memory_bits==0, ("UNMAPPED_MEMORY",memory_bits)
            assert state_bits>400000, ("MISSING_MAPPED_STORAGE",state_bits)
        else:
            assert memory_bits>=2041728, ("MISSING_MEMORY",memory_bits)
        evidence.receipt.setdefault("synthesis",[]).append({
            "configuration":name,"state_bits":state_bits,"memory_bits":memory_bits,
            "hierarchical_instances":len(instances),"zero_latches":True,"zero_divmod":True,
            "outcome":"passed","netlist":relative(netlist),
            "command":len(evidence.records)-1})
        evidence.save()


MUTATIONS=(
    ("less-to-lequal","g2_zbuffer.sv","new_depth<memory_q","new_depth<=memory_q","depth-comparison"),
    ("reversed-depth","g2_zbuffer.sv","new_depth<memory_q","new_depth>memory_q","depth-comparison"),
    ("suppressed-depth-write","g2_zbuffer.sv",
     "if (memory_write) depth_mem[address]<=memory_write_data;",
     "if (memory_write && state==CLEAR_WRITE) depth_mem[address]<=memory_write_data;","depth-persistence"),
    ("unjustified-rejection","g2_zbuffer.sv",
     "reject_result<=zmin>=next_maximum;","reject_result<=1'b1;","tile-rejection"),
    ("rejection-counter","g2_engine.sv",
     "tiles_rejected<=tiles_rejected+32'd1;","tiles_rejected<=tiles_rejected+32'd2;","counter"),
    ("affine-attributes","g2_interpolator.sv",
     "q[v]<=s_q[v*41 +:41];","q[v]<=41'd16777216;","perspective"),
    ("winding-identity","g2_engine.sv",
     "if (area<0) begin v1<=v2; v2<=v1; end",
     "if (area<0) begin v1<={v1[290:99],v2[98:75],v1[74:34],v2[33:0]}; "
     "v2<={v2[290:99],v1[98:75],v2[74:34],v1[33:0]}; end","winding-payload"),
)


def mutations(evidence):
    campaign=compact_campaign((7,5,1))
    vectors=evidence.path/("mutations-"+uuid.uuid4().hex[:8]+".txt")
    campaign.write(vectors)
    for name,filename,old,new,intention in MUTATIONS:
        directory=evidence.path/(name+"-"+uuid.uuid4().hex[:8])
        directory.mkdir()
        for source in (ROOT/"rtl").glob("*.sv"):
            shutil.copyfile(source,directory/source.name)
        target=directory/filename
        text=target.read_text()
        assert old in text, f"MUTATION_ANCHOR_MISSING {name}"
        target.write_text(text.replace(old,new),encoding="ascii")
        mutant_hash=hashlib.sha256(target.read_bytes()).hexdigest()
        executable,obj=compile_stream(evidence,campaign.cell,"verilator",directory)
        try:
            record,out,err=evidence.run("mutant-"+name,executable+["+vectors="+relative(vectors)],
                                        allow_failure=True)
            assert not record["timed_out"] and record["exit_code"] not in (0,None), ("MUTANT_SURVIVED",name)
            mismatch=re.search(r"WORD_MISMATCH command=(\d+) word=(\d+) got=([0-9a-fA-F]+)/([01]) "
                               r"expected=([0-9a-fA-F]+)/([01])",out+err)
            assert mismatch, ("NOT_BEHAVIORAL_REJECTION",name,record["stdout"],record["stderr"])
            command_index,index=int(mismatch[1]),int(mismatch[2])
            case=campaign.cases[command_index]
            # Require a category-specific public mismatch in the intended
            # command, not any unrelated crash or compile rejection.
            if name in ("less-to-lequal","suppressed-depth-write"):
                assert "equality-disabled" in case.name and index==0
            elif name in ("reversed-depth","unjustified-rejection"):
                assert "unequal-w" in case.name
            elif name=="rejection-counter":
                assert "early-reject" in case.name and index==6
            else:
                assert "unequal-w" in case.name and index%13>=7
            evidence.receipt.setdefault("mutations",[]).append({
                "name":name,"intended_defect":intention,"changed_file":filename,
                "mutant_sha256":mutant_hash,"outcome":"behaviorally-rejected",
                "case":case.name,"word":index,"command":len(evidence.records)-1,
                "source_copy":relative(directory)})
            evidence.save()
        finally:
            clean_intermediates(obj)


def illegal_parameters(evidence):
    for cell in ((0,1,0),(257,1,0),(1,0,0),(1,257,0),(1,1,-1),(1,1,5)):
        executable,_=compile_stream(evidence,cell,"icarus")
        record,out,err=evidence.run("illegal-parameters",executable,allow_failure=True)
        assert not record["timed_out"] and record["exit_code"] not in (0,None)
        assert "PARAMETER ERROR" in out+err, ("MISSING_PARAMETER_DIAGNOSTIC",cell)
        evidence.receipt.setdefault("illegal_parameters",[]).append({
            "cell":cell,"outcome":"explicitly-rejected","command":len(evidence.records)-1})
    evidence.save()


def legacy_regression(evidence):
    c=Campaign((7,5,1),89)
    c.add("legacy-3d",7,5,0)
    c.add("legacy-2d",7,5,1)
    c.add("legacy-invalid-mode",7,5,123)
    v,a=triangle(False)
    v[2]=(0,2*Q,Q//2,Q)
    c.add("legacy-clipped",7,5,0,vertices=v,attrs=a)
    for parent in (True,False):
        executable,obj=compile_stream(evidence,c.cell,"verilator",parent=parent)
        try:
            execute_campaign(evidence,c,executable,"immutable-parent" if parent else "g2-legacy")
        finally:
            clean_intermediates(obj)


def clean_reproduction(evidence):
    directory=evidence.path/("clean-"+uuid.uuid4().hex[:8])
    directory.mkdir()
    for source in sources():
        destination=directory/source.relative_to(ROOT)
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,destination)
    record,_,_=evidence.run("clean-directory",["python3","tests/verify.py","--compact"],cwd=directory)
    children=sorted((directory/"evidence").glob("l1-*/receipt.json"))
    assert len(children)==1 and json.loads(children[0].read_text())["exit_code"]==0
    evidence.receipt["clean_reproduction"]={
        "directory":relative(directory),"receipt":relative(children[0]),
        "command":len(evidence.records)-1,"outcome":"passed","scope":"partial-compact"}
    evidence.save()


def full(evidence):
    source_rules()
    leaves(evidence,compact=True,backend="icarus")
    leaves(evidence,compact=False,backend="verilator")
    smoke=compact_campaign()
    executable,_=compile_stream(evidence,smoke.cell,"icarus")
    execute_campaign(evidence,smoke,executable,"icarus-smoke")
    smoke=compact_campaign((7,5,1))
    executable,_=compile_stream(evidence,smoke.cell,"icarus")
    execute_campaign(evidence,smoke,executable,"icarus-perspective-smoke")
    matrix=[]
    for cell in CELLS:
        executable,obj=compile_stream(evidence,cell,"verilator")
        try:
            for seed in SEEDS:
                campaign=matrix_campaign(cell,seed)
                if seed==17:
                    directed(campaign)
                coverage=execute_campaign(evidence,campaign,executable,
                    "matrix-"+"-".join(map(str,cell))+f"-seed{seed}",thresholds=True)
                matrix.append(coverage)
        finally:
            clean_intermediates(obj)
    assert len(matrix)==21
    assert sum(c["audits"] for c in matrix)>=128
    assert sum(c["nonaffine"] for c in matrix)>0
    assert all(sum(c["crossings"][i] for c in matrix)>0 for i in range(7))
    illegal_parameters(evidence)
    legacy_regression(evidence)
    mutations(evidence)
    synthesis(evidence)
    clean_reproduction(evidence)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compact",action="store_true",help="partial clean-directory reproduction only")
    parser.add_argument("--probe",choices=("smoke","matrix","synthesis","mutations"),
                        help="bounded advisory preparation, not admitted L1")
    parser.add_argument("--repair-of",action="append",default=[],help="project-relative earlier failed receipt")
    parser.add_argument("--cell",nargs=3,type=int,metavar=("WIDTH","HEIGHT","TILE_LOG2"),
                        help="one preparation matrix cell only; never filters admitted full L1")
    parser.add_argument("--seed",type=int,default=17,help="preparation matrix seed only")
    args=parser.parse_args()
    if args.cell and args.probe!="matrix":
        parser.error("--cell is legal only with --probe matrix")
    evidence=Evidence(args)
    print("L1 receipt: "+relative(evidence.path/"receipt.json"),flush=True)
    exit_code=1
    try:
        evidence.tools()
        if args.probe=="smoke":
            leaves(evidence,compact=True)
            campaign=compact_campaign()
            executable,_=compile_stream(evidence,campaign.cell,"icarus")
            execute_campaign(evidence,campaign,executable,"probe-compact")
        elif args.probe=="matrix":
            cell=tuple(args.cell) if args.cell else (7,5,1)
            if cell not in CELLS:
                raise ValueError("Preparation cell must be in the admitted matrix")
            c=matrix_campaign(cell,args.seed)
            directed(c)
            executable,obj=compile_stream(evidence,cell,"verilator")
            try:
                execute_campaign(evidence,c,executable,"probe-matrix",thresholds=True)
            finally:
                clean_intermediates(obj)
        elif args.probe=="synthesis":
            synthesis(evidence)
        elif args.probe=="mutations":
            mutations(evidence)
        elif args.compact:
            source_rules()
            compact(evidence)
        else:
            full(evidence)
        current_hashes={relative(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources()}
        assert current_hashes==evidence.receipt["source_sha256"], "SOURCE_CHANGED_DURING_EXECUTION"
        evidence.receipt["outcome"]="passed"
        exit_code=0
    except (AssertionError,RuntimeError,OSError,ValueError) as error:
        evidence.receipt["outcome"]="failed"
        evidence.receipt["error"]=str(error)
        print(f"L1 FAILED: {error}",file=sys.stderr)
    finally:
        evidence.receipt.update(end_utc=utc(),exit_code=exit_code)
        evidence.save()
    return exit_code


if __name__=="__main__":
    sys.exit(main())
