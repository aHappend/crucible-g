#!/usr/bin/env python3
"""Portable L1: exact public-pin comparison, mutation, synthesis, reproduction.

Requirement gates live in workload.coverage; protocol/primitive gates are
executable assertions below. Native timing and physical-board gates are separate.
L1 results report only portable checks; the shared runtime records native gate
outcomes independently. A portable pass does not establish delivery acceptance.
Synthetic native-diagnostic regressions check evidence parsing without accessing
Quartus, a fit database or a board; they do not execute any native gate.
The native-coverage probe also executes the old and repaired output-allocation
snippets in a disposable tree, retaining the expected collision and two fresh
runs. This does not apply or confirm the effective shared-runtime contract.

Behavior jobs retain the original command order and overlap the preceding
command at each partition boundary. Only primary membership contributes to
functional coverage. Per-job public transfers prove every adjacent command's
earliest-legal handshake, including boundaries. Scheduling estimates include
reset recovery, input gaps and output stalls; actual Icarus cycles and elapsed
execution must independently satisfy <=500,000 cycles and <60 seconds.
"""

import argparse
import hashlib
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
import sys
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reference import Q, edge, model  # noqa: E402
from native_contract import (  # noqa: E402
    coverage_marker_self_test, execution_contract_self_test,
)
from native_prerequisites import (  # noqa: E402
    coverage_report_self_test, diagnostic_self_test, report_parser_self_test,
    timing_observation_self_test,
)
from stream_compare import (  # noqa: E402
    TransferChecker, bridge_commands, self_test as transfer_self_test,
)
from workload import coverage, workload  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("rtl/*.sv", "design/SPEC.md", "design/ARCHITECTURE.md", "tests/*.py")
TIMEOUT = 3600
ICARUS_CYCLE_LIMIT = 500000
ICARUS_SECONDS_LIMIT = 60
STREAM_BATCH_BUDGET = 450000


class VerificationFailure(RuntimeError):
    pass


def allocation_repair_regression(execution):
    """Exercise namespace reuse in a disposable product tree, not runtime state."""
    root = execution.output / "allocation-fixture"
    historical = root / "evidence/native-contract-discovery-0291"
    historical.mkdir(parents=True, exist_ok=False)
    sentinel = historical / "receipt.json"
    original_bytes = b'{"fixture": "historical receipt; preserve unchanged"}\n'
    sentinel.write_bytes(original_bytes)
    prefix = "import pathlib, uuid\nroot = pathlib.Path.cwd()\n"
    old = (
        prefix + "out = root / 'evidence/native-contract-discovery-0291'\n"
        "out.mkdir(parents=True, exist_ok=False)\n")
    repaired = (
        prefix + "out = root / 'evidence/native-contract-discovery-0291' / "
        "('run-' + uuid.uuid4().hex)\n"
        "out.mkdir(parents=True, exist_ok=False)\n"
        "print(out.relative_to(root).as_posix())\n")
    row = execution.run(
        "allocation-original-collision", ["python3", "-c", old], cwd=root)
    require(row["exit_code"] == 1 and not row["timed_out"],
            "Original occupied allocation did not fail as expected")
    error = (execution.root / row["stderr"]).read_text()
    require("FileExistsError" in error,
            "Original allocation failed for a reason other than the occupied namespace")
    paths = []
    for index in range(2):
        row = execution.checked(
            f"allocation-repaired-{index}", ["python3", "-c", repaired], cwd=root)
        name = (execution.root / row["stdout"]).read_text().strip()
        require(re.fullmatch(
            r"evidence/native-contract-discovery-0291/run-[0-9a-f]{32}", name)
                is not None, "Repaired allocation emitted an unexpected output path")
        require((root / name).is_dir(), "Repaired allocation did not create its directory")
        paths.append(name)
    require(len(set(paths)) == 2, "Repaired invocations reused an output directory")
    require(sentinel.read_bytes() == original_bytes,
            "Allocation regression changed the historical fixture receipt")
    require({path.name for path in historical.iterdir()}
            == {"receipt.json", *(Path(name).name for name in paths)},
            "Allocation regression created unexpected historical-namespace contents")
    write_json(execution.output / "allocation-repair-regression.json", {
        "kind": "isolated_allocation_execution_regression",
        "acceptance_evidence": False, "native_gate_executed": False,
        "runtime_state_modified": False,
        "scope": "Known allocation snippets only; not effective contract application",
        "original_rejection": "FileExistsError", "fresh_directories": paths,
        "historical_fixture_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "historical_fixture_preserved": True,
    })


def require(condition, message):
    if not condition:
        raise VerificationFailure(message)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def inventory(root):
    paths = []
    for selector in SOURCES:
        matched = sorted(root.glob(selector))
        require(bool(matched), f"Source selector has no inputs: {selector}")
        paths.extend(matched)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}


class Execution:
    def __init__(self, root, output, repair_of=None):
        self.root, self.output = root, output
        self.commands = []
        self.receipt = {
            "kind": "independent-l1", "acceptance_evidence": False,
            "argv": ["python3", *sys.argv], "cwd": ".", "start": time.time(),
            "source_sha256": inventory(root), "commands": self.commands,
            "tool_versions": {}, "timeout_s": None, "child_timeout_s": TIMEOUT,
            "repair_of": repair_of,
        }
        self.save()

    def save(self):
        write_json(self.output / "receipt.json", self.receipt)

    def run(self, name, argv, cwd=None, timeout=TIMEOUT):
        require(not any(c["name"] == name for c in self.commands),
                f"Refusing to overwrite command evidence: {name}")
        directory = self.output / name
        directory.mkdir()
        cwd = cwd or self.root
        row = {
            "name": name, "argv": [str(a) for a in argv],
            "cwd": cwd.relative_to(self.root).as_posix(),
            "start": time.time(), "timeout_s": timeout, "timed_out": False,
            "exit_code": None,
            "stdout": (directory / "stdout.log").relative_to(self.root).as_posix(),
            "stderr": (directory / "stderr.log").relative_to(self.root).as_posix(),
        }
        self.commands.append(row)
        self.save()
        with (directory / "stdout.log").open("wb") as stdout, (
                directory / "stderr.log").open("wb") as stderr:
            started = time.monotonic()
            try:
                result = subprocess.run(row["argv"], cwd=cwd, stdout=stdout,
                                        stderr=stderr, timeout=timeout, check=False)
                row["exit_code"] = result.returncode
            except subprocess.TimeoutExpired:
                row["timed_out"] = True
            except OSError as error:
                row["error"] = f"{type(error).__name__}: {error}"
                raise
            finally:
                row["duration_s"] = time.monotonic() - started
                row["end"] = time.time()
                self.save()
        return row

    def checked(self, name, argv, **kwargs):
        row = self.run(name, argv, **kwargs)
        require(row["exit_code"] == 0 and not row["timed_out"],
                f"Tool failure: {name}; see {row['stdout']} and {row['stderr']}")
        return row

    def rel(self, path):
        return path.relative_to(self.root).as_posix()

    def verify_retention(self):
        """Bind readable raw logs and source snapshots before reporting success."""
        retained = {}
        for row in self.commands:
            require("exit_code" in row and "end" in row and row["end"] >= row["start"],
                    f"Incomplete command receipt: {row['name']}")
            require(row["exit_code"] is not None or row["timed_out"],
                    f"Command has no execution outcome: {row['name']}")
            for stream in ("stdout", "stderr"):
                path = self.root / row[stream]
                data = path.read_bytes()
                retained[row[stream]] = {
                    "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
        for name, expected in self.receipt["source_sha256"].items():
            path = self.output / "source" / name
            data = path.read_bytes()
            require(hashlib.sha256(data).hexdigest() == expected,
                    f"Retained source snapshot mismatch: {name}")
            retained[self.rel(path)] = {
                "bytes": len(data), "sha256": expected}
        self.receipt["retained_files"] = retained
        self.save()
        require(json.loads((self.output / "receipt.json").read_text()) == self.receipt,
                "Saved execution receipt is unreadable or differs from recorded execution")

    def complete(self, result):
        self.verify_retention()
        write_json(self.output / "result.json", result)
        require(json.loads((self.output / "result.json").read_text()) == result,
                "Saved verification result differs from the computed result")
        self.receipt["exit_code"] = 0
        return 0


def icarus_tier(execution, directory, row, cycles):
    measured = {
        "command": row["name"], "actual_cycles": cycles,
        "duration_s": row["duration_s"],
        "cycle_limit_inclusive": ICARUS_CYCLE_LIMIT,
        "seconds_limit_exclusive": ICARUS_SECONDS_LIMIT,
        "within_tier": (0 < cycles <= ICARUS_CYCLE_LIMIT
                        and row["duration_s"] < ICARUS_SECONDS_LIMIT),
    }
    write_json(directory / "tier.json", measured)
    require(measured["within_tier"],
            f"Icarus tier violation: {row['name']}: {cycles} actual cycles, "
            f"{row['duration_s']:.6f}s; see {execution.rel(directory / 'tier.json')}")


def stream_cycle_estimate(result):
    # The reference budgets 100 idle cycles per output word. For packing only,
    # use 32 per word for the nonzero 32-bit LFSR's short random stall bursts.
    # Directed 70-cycle stalls are separate below. This is not a timing proof
    # or a replacement for the unchanged per-command functional watchdog.
    return result.cycle_bound - len(result.words()) * (100 - 32) + 31


def stream_job_estimate(results, reset_tests):
    # At most one input gap per word, six 70-cycle directed stalls, startup
    # and final idle checks. Reset tests add three fully compared recoveries,
    # a prefix, an arithmetic abort, and an output-stalled abort of command 0.
    estimate = sum(stream_cycle_estimate(r) for r in results) + 6 * 70 + 256
    if reset_tests:
        estimate += 4 * stream_cycle_estimate(results[0]) + 13 + 31 + 20 + 70 + 16
    return estimate


def stream_batches(results, budget=STREAM_BATCH_BUDGET):
    require(bool(results), "Cannot partition an empty workload")
    batches = []
    start = 0
    while start < len(results):
        first = max(0, start - 1)
        stop = start + 1
        reset_tests = start == 0
        require(stream_job_estimate(results[first:stop], reset_tests) <= budget,
                f"Command/boundary {first}..{start} cannot fit compact Icarus budget")
        while stop < len(results) and stream_job_estimate(
                results[first:stop + 1], reset_tests) <= budget:
            stop += 1
        batches.append({
            "first": first, "primary_start": start, "stop": stop,
            "reset_tests": reset_tests,
            "estimated_cycles": stream_job_estimate(results[first:stop], reset_tests),
        })
        start = stop
    require([i for b in batches for i in range(b["primary_start"], b["stop"])]
            == list(range(len(results))), "Partition lost or duplicated primary commands")
    require({i for b in batches for i in range(b["first"], b["stop"] - 1)}
            == set(range(len(results) - 1)), "Partition lost an adjacent-command witness")
    return batches


def tiering_sensitivity(execution):
    fixtures = execution.output / "tiering-fixtures"
    fixtures.mkdir()
    cases = (
        ("at-cycle-limit", ICARUS_CYCLE_LIMIT, 1.0, True),
        ("over-cycle-limit", ICARUS_CYCLE_LIMIT + 1, 1.0, False),
        ("below-time-limit", 1, ICARUS_SECONDS_LIMIT - 0.001, True),
        ("at-time-limit", 1, ICARUS_SECONDS_LIMIT, False),
        ("zero-cycles", 0, 1.0, False),
    )
    ledger = []
    for name, cycles, duration, expected in cases:
        directory = fixtures / name
        directory.mkdir()
        try:
            icarus_tier(execution, directory,
                        {"name": name, "duration_s": duration}, cycles)
        except VerificationFailure:
            accepted = False
        else:
            accepted = True
        require(accepted == expected, f"Tier-limit checker sensitivity failed: {name}")
        ledger.append({"fixture": name, "cycles": cycles, "duration_s": duration,
                       "accepted": accepted, "expected": expected})
    write_json(fixtures / "sensitivity.json", {
        "kind": "synthetic_tier_limit_sensitivity", "simulation_executed": False,
        "cases": ledger,
    })


STREAM_TB = r"""
`timescale 1ns/1ps
module tb;
  reg clk=0;
  always #5 clk=~clk;
  reg rst_n, s_valid=0, m_ready=0;
  reg [31:0] s_data=0;
  wire s_ready,m_valid,m_last;
  wire [31:0] m_data;
  crucible_g1_top dut(.*);
  reg [31:0] inputs[0:@INPUT_MAX@], expected[0:@EXPECT_MAX@];
  integer lengths[0:@COMMAND_MAX@];
  reg [63:0] bounds[0:@COMMAND_MAX@];
  integer trace, summary;
  integer command_index=0, phase=0, offset=0, base=0, accepted=0;
  integer stall_left[0:5], stalls[0:5], position=0;
  integer gap_count=0, random_stalls=0, resets[0:2];
  integer comparisons=0, completion_count=0, cycle_count=0;
  integer actual_cycles=0;
  always @(posedge clk) actual_cycles=actual_cycles+1;
  integer last_completion_cycle=-100, back_to_back=0;
  integer cmd_cycles=0, first_after_reset=1;
  integer first_input[0:@COMMAND_MAX@], completion_cycle[0:@COMMAND_MAX@];
  integer command_trace;
  reg [31:0] lfsr=32'h1a2b3c4d;
  reg old_sr,old_mv,old_ml;
  reg [31:0] old_md;
  reg took_input,took_output,completed;
  reg in_command=0;
  integer i,j,k,n;

  task automatic fail(input [255:0] why);
    begin
      $display("CHECKER_REJECT %0s command=%0d phase=%0d offset=%0d cycle=%0d actual_cycles=%0d",
                why,command_index,phase,offset,cycle_count,actual_cycles);
      $fatal(1,"public protocol/numerical mismatch");
    end
  endtask
  task automatic pins;
    begin
      if ((^{s_ready,m_valid,m_data,m_last}) === 1'bx) fail("UNKNOWN_PUBLIC");
      if (!rst_n) begin
        if ({s_ready,m_valid,m_data,m_last} !== 35'd0) fail("RESET_OUTPUT");
      end else begin
        if (!m_valid && {m_data,m_last} !== 33'd0) fail("INVALID_OUTPUT");
        if (m_last && !m_valid) fail("LAST_WITHOUT_VALID");
      end
    end
  endtask
  // Both clock polarities, including the first Active-region posedge at t=5.
  always @(posedge clk or negedge clk) if ($time>0) pins();

  task automatic tick(input reg sv,input reg [31:0] sd,input reg mr);
    begin
      @(negedge clk);
      old_sr=s_ready;
      s_valid=sv; s_data=sd; m_ready=mr;
      #1;
      pins();
      if (s_ready !== old_sr) fail("COMBINATIONAL_READY");
      @(posedge clk);
      pins();
      cycle_count=cycle_count+1;
      cmd_cycles=cmd_cycles+1;
      lfsr={lfsr[30:0],lfsr[31]^lfsr[21]^lfsr[1]^lfsr[0]};
      old_sr=s_ready; old_mv=m_valid; old_md=m_data; old_ml=m_last;
      took_input=s_valid && s_ready;
      took_output=m_valid && m_ready;
      completed=0;
      if (first_after_reset && s_ready !== 1'b0) fail("EARLY_RESET_READY");
      if (rst_n) first_after_reset=0;
      if (in_command && accepted==31 && s_ready) fail("READY_WHILE_BUSY");
      if (m_valid && (!in_command || accepted!=31)) fail("EARLY_OUTPUT");
      if (took_input) begin
        if (!in_command || accepted>=31) fail("UNEXPECTED_INPUT");
        if (phase==0 && accepted==0) first_input[command_index]=cycle_count;
        if (accepted==0 && cycle_count==last_completion_cycle+1)
          back_to_back=back_to_back+1;
        accepted=accepted+1;
      end
      if (took_output) begin
        if (offset>=lengths[command_index]) fail("EXTRA_OUTPUT");
        if (m_data !== expected[base+offset]) begin
          $display("EXPECTED %08x OBSERVED %08x",expected[base+offset],m_data);
          fail("WORD_MISMATCH");
        end
        if (m_last !== (offset==lengths[command_index]-1)) fail("LAST_MISMATCH");
        $fdisplay(trace,"%0d %0d %0d %0d %08x %0d",
                  phase,command_index,offset,cycle_count,m_data,m_last);
        comparisons=comparisons+1;
        offset=offset+1;
        if (position==5) position=0; else position=position+1;
        if (m_last) begin
          if (phase==0) completion_cycle[command_index]=cycle_count;
          completed=1; completion_count=completion_count+1;
          last_completion_cycle=cycle_count;
          in_command=0;
        end
      end
      #1;
      pins();
      if (old_mv && !mr &&
          {m_valid,m_data,m_last} !== {old_mv,old_md,old_ml}) fail("STALL_CHANGED");
      if (took_input && accepted==31 && s_ready !== 1'b0) fail("WORD30_READY");
      if (completed && {m_valid,m_data,m_last} !== 34'd0) fail("COMPLETION_CLEAR");
      if (rst_n && first_after_reset==0 && accepted==0 && !in_command &&
          s_ready !== 1'b1) fail("RESET_RELEASE_READY");
      if (cmd_cycles>bounds[command_index]) fail("FINITE_CYCLE_BOUND");
    end
  endtask

  task automatic reset_now;
    begin
      @(negedge clk);
      #1;
      rst_n=0; s_valid=0; m_ready=0; s_data=0;
      #1; pins();
      // A pulse wholly between rising edges proves asynchronous cancellation.
      #1;
      rst_n=1;
      accepted=0; offset=0; position=0; in_command=0;
      cmd_cycles=0; first_after_reset=1;
      @(posedge clk);
      pins();
      if(s_ready !== 1'b0) fail("EARLY_RESET_READY");
      cycle_count=cycle_count+1;
      #1; pins();
      if(s_ready !== 1'b1) fail("RESET_RELEASE_READY");
      first_after_reset=0;
    end
  endtask

  task automatic begin_command(input integer ci,input integer cb,input integer ph);
    begin
      command_index=ci; base=cb; phase=ph;
      accepted=0; offset=0; position=0; in_command=1; cmd_cycles=0;
    end
  endtask
  task automatic send_words(input integer ci,input integer count,input reg gaps);
    integer wi;
    begin
      for(wi=0;wi<count;wi=wi+1) begin
        if(gaps && wi>0 && lfsr[1:0]==0) begin
          tick(0,0,0); gap_count=gap_count+1;
        end
        tick(1,inputs[ci*31+wi],0);
        while(!took_input) tick(1,inputs[ci*31+wi],0);
      end
    end
  endtask
  task automatic drain(input reg stress);
    reg ready_value;
    begin
      while(in_command) begin
        ready_value=1;
        if(stress && m_valid && stall_left[position]>0) begin
          ready_value=0;
          stall_left[position]=stall_left[position]-1;
          stalls[position]=stalls[position]+1;
        end else if(stress && m_valid && lfsr[3:0]==0) begin
          ready_value=0; random_stalls=random_stalls+1;
        end
        tick(0,0,ready_value);
      end
    end
  endtask
  task automatic recover(input integer ph);
    begin
      begin_command(0,0,ph);
      send_words(0,31,0);
      drain(0);
    end
  endtask
  initial begin
    // An actual X -> 0 assertion at time zero, not a delayed 1 -> 0 workaround.
    rst_n=0;
    $readmemh("@INPUT_FILE@",inputs);
    $readmemh("@EXPECT_FILE@",expected);
    $readmemh("@LENGTH_FILE@",lengths);
    $readmemh("@BOUND_FILE@",bounds);
    trace=$fopen("@TRACE_FILE@","w");
    command_trace=$fopen("@COMMAND_TRACE_FILE@","w");
    for(i=0;i<@COMMAND_COUNT@;i=i+1) begin
      first_input[i]=-1; completion_cycle[i]=-1;
    end
    for(i=0;i<6;i=i+1) begin stall_left[i]=70; stalls[i]=0; end
    for(i=0;i<3;i=i+1) resets[i]=0;
    #1; pins();
    reset_now();
    if (@RESET_TESTS@) begin
    // Reset while a real prefix is outstanding.
    begin_command(0,0,-1); send_words(0,13,0);
    if(accepted!=13) fail("PARTIAL_RESET_PRECONDITION");
    resets[0]=1; reset_now(); recover(-1);
    // The serialized transform cannot finish in these twenty edges.
    begin_command(0,0,-2); send_words(0,31,0);
    repeat(20) tick(0,0,0);
    if(accepted!=31 || m_valid) fail("ARITH_RESET_PRECONDITION");
    resets[1]=1; reset_now(); recover(-2);
    // A valid public output is held for 70 full edges before reset.
    begin_command(0,0,-3); send_words(0,31,0);
    while(!m_valid) tick(0,0,0);
    repeat(70) tick(0,0,0);
    if(!m_valid || offset!=0) fail("STALL_RESET_PRECONDITION");
    resets[2]=1; reset_now(); recover(-3);
    end
    base=0;
    for(n=0;n<@COMMAND_COUNT@;n=n+1) begin
      begin_command(n,base,0);
      send_words(n,31,1);
      drain(1);
      if(first_input[n]<0 || completion_cycle[n]<=first_input[n])
        fail("MISSING_COMMAND_BOUNDARY");
      if(n>0 && first_input[n]!=completion_cycle[n-1]+1)
        fail("COMMAND_BOUNDARY_NOT_EARLIEST");
      $fdisplay(command_trace,"%0d %0d %0d",n,first_input[n],completion_cycle[n]);
      base=base+lengths[n];
    end
    // No extra output after completion, including a held-valid extra record.
    repeat(128) tick(0,0,1);
    for(i=0;i<6;i=i+1) if(stalls[i]<64) fail("MISSING_STALL_COVERAGE");
    if(gap_count==0 || (@RESET_TESTS@ && random_stalls==0)) fail("MISSING_GAP_COVERAGE");
    if(back_to_back<@COMMAND_COUNT@-1) fail("MISSING_BACK_TO_BACK");
    summary=$fopen("@SUMMARY_FILE@","w");
    $fdisplay(summary,"{\"comparisons\":%0d,\"completions\":%0d,\"cycles\":%0d,\"actual_cycles\":%0d,\"input_gaps\":%0d,\"random_stalls\":%0d,\"back_to_back\":%0d,\"reset_recoveries\":%0d,\"stalls\":[%0d,%0d,%0d,%0d,%0d,%0d]}",
      comparisons,completion_count,cycle_count,actual_cycles,gap_count,random_stalls,
      back_to_back,resets[0]+resets[1]+resets[2],
      stalls[0],stalls[1],stalls[2],stalls[3],stalls[4],stalls[5]);
    $fclose(summary); $fclose(trace); $fclose(command_trace);
    $display("CHECKER_COMPLETE %0d",comparisons);
    $finish;
  end
endmodule
"""


def simulate(execution, name, commands, results, rtl=None, mutation=False,
             reset_tests=True):
    directory = execution.output / name
    directory.mkdir()
    inputs = [word for command in commands for word in command.words()]
    expected = [word for result in results for word in result.words()]
    for filename, values in (
            ("input.hex", inputs), ("expected.hex", expected),
            ("length.hex", [len(r.words()) for r in results]),
            ("bound.hex", [max(r.cycle_bound * 2, 20000) for r in results])):
        (directory / filename).write_text("".join(f"{v:x}\n" for v in values))
    write_json(directory / "stimulus.json", [
        {"tag": c.tag, "width": c.width, "height": c.height, "mode": c.mode,
         "matrix": c.matrix, "vertices": c.vertices, "seed": c.seed}
        for c in commands])
    substitutions = {
        "INPUT_MAX": len(inputs) - 1, "EXPECT_MAX": len(expected) - 1,
        "COMMAND_MAX": len(commands) - 1, "COMMAND_COUNT": len(commands),
        "INPUT_FILE": execution.rel(directory / "input.hex"),
        "EXPECT_FILE": execution.rel(directory / "expected.hex"),
        "LENGTH_FILE": execution.rel(directory / "length.hex"),
        "BOUND_FILE": execution.rel(directory / "bound.hex"),
        "TRACE_FILE": execution.rel(directory / "observed.txt"),
        "COMMAND_TRACE_FILE": execution.rel(directory / "commands.txt"),
        "SUMMARY_FILE": execution.rel(directory / "protocol.json"),
        "RESET_TESTS": int(reset_tests),
    }
    tb = STREAM_TB
    for key, value in substitutions.items():
        tb = tb.replace(f"@{key}@", str(value))
    require("@" not in re.sub(r"@\(", "", tb), "Unexpanded testbench template")
    (directory / "tb.sv").write_text(tb)
    sources = sorted((rtl or execution.root / "rtl").glob("*.sv"))
    execution.checked(name + "-compile", [
        "iverilog", "-g2012", "-Wall", "-s", "tb",
        "-o", execution.rel(directory / "simulation"),
        execution.rel(directory / "tb.sv"), *(execution.rel(p) for p in sources)])
    row = execution.run(name + "-simulate", ["vvp", execution.rel(directory / "simulation")])
    stdout = (execution.root / row["stdout"]).read_text()
    if mutation:
        valid_rejection = (row["exit_code"] not in (0, None) and not row["timed_out"]
                           and "CHECKER_REJECT" in stdout
                           and "FINITE_CYCLE_BOUND" not in stdout)
        rejection_cycles = re.findall(r"CHECKER_REJECT .* actual_cycles=(\d+)", stdout)
        if rejection_cycles:
            icarus_tier(execution, directory, row, int(rejection_cycles[-1]))
        write_json(directory / "rejection.json", {
            "rejected_numerically_or_procedurally": valid_rejection,
            "exit_code": row["exit_code"], "timed_out": row["timed_out"],
            "reason": [line for line in stdout.splitlines()
                       if "CHECKER_REJECT" in line or "EXPECTED " in line],
        })
        require(valid_rejection and len(rejection_cycles) == 1,
                f"Mutation not sensitized: {name}; {row['stdout']}")
        return None
    require(row["exit_code"] == 0 and not row["timed_out"],
            f"Simulation/checker failure: {name}; {row['stdout']}")
    require("CHECKER_COMPLETE " in stdout, f"Missing checker completion: {name}")
    protocol = json.loads((directory / "protocol.json").read_text())
    icarus_tier(execution, directory, row, protocol["actual_cycles"])
    recoveries = 3 if reset_tests else 0
    require(protocol["completions"] == len(commands) + recoveries,
            "Completion conservation failed")
    require(min(protocol["stalls"]) >= 64 and protocol["reset_recoveries"] == recoveries,
            "Missing protocol coverage")
    require(protocol["back_to_back"] >= len(commands) - 1,
            "No observed earliest-legal input after completion")
    expected_transfers = {}
    for phase in ((-1, -2, -3) if reset_tests else ()):
        expected_transfers[(phase, 0)] = results[0].words()
    for i, result in enumerate(results):
        expected_transfers[(0, i)] = result.words()
    observed = {key: [] for key in expected_transfers}
    completion_transfers = {}
    transfer_checker = TransferChecker(commands, results)
    last_cycle = -1
    for line in (directory / "observed.txt").read_text().splitlines():
        ph, ci, offset, cycle, word, last = line.split()
        key = int(ph), int(ci)
        offset, cycle, word, last = int(offset), int(cycle), int(word, 16), int(last)
        require(key in observed, f"Unexpected output epoch: {key}")
        require(offset == len(observed[key]) and cycle > last_cycle,
                "Transfer offset/order failure")
        require(offset < len(expected_transfers[key]), "Extra transferred word")
        require(word == expected_transfers[key][offset], "Independent trace mismatch")
        require(last == int(offset == len(expected_transfers[key]) - 1),
                "Independent last mismatch")
        observed[key].append(word)
        if last:
            completion_transfers[key] = cycle
        if key[0] == 0:
            transfer_checker.accept(word, last)
        last_cycle = cycle
    require(observed == expected_transfers, "Missing/extra trace transfers")
    transfer_summary = transfer_checker.finish()
    require(protocol["comparisons"] == sum(map(len, observed.values())),
            "Protocol/trace comparison count mismatch")
    command_cycles = []
    for line in (directory / "commands.txt").read_text().splitlines():
        ci, first, final = map(int, line.split())
        require(ci == len(command_cycles) and 0 < first < final,
                "Missing/unordered command cycle witness")
        require(not command_cycles or first == command_cycles[-1]["completion_cycle"] + 1,
                "Adjacent commands did not transfer at the earliest legal edge")
        require(completion_transfers[(0, ci)] == final,
                "Command cycle witness differs from the compared completion transfer")
        command_cycles.append({
            "command_index": ci, "tag": commands[ci].tag,
            "first_input_cycle": first, "completion_cycle": final,
        })
    require(len(command_cycles) == len(commands), "Missing command cycle witnesses")
    pixels = {}
    for i, (c, result) in enumerate(zip(commands, results)):
        words = observed[(0, i)]
        records = [words[j:j + 6] for j in range(0, len(words), 6)]
        require(records[-1][0] == 1 and records[-1][1] == c.tag, "Malformed completion")
        for record in records[:-1]:
            require(record[0] == 0 and record[1] == c.tag, "Malformed pixel")
            require(all(0 <= w <= Q for w in record[3:]) and sum(record[3:]) == Q,
                    "Barycentric invariant")
        pixels[c.tag] = len(records) - 1
    write_json(directory / "comparison.json", {
        "exact_words": sum(map(len, observed.values())),
        "commands": len(commands), "reset_recoveries": recoveries,
        "pixel_records": sum(pixels.values()), "per_tag_pixels": pixels,
        "all_words_ordered_exact": True,
        "transport_independent_comparison": transfer_summary,
        "command_cycles": command_cycles,
    })
    return pixels


def simulate_batched(execution, name, commands, results, budget=STREAM_BATCH_BUDGET):
    """Compare every original command once for coverage; retain boundary replays."""
    directory = execution.output / name
    directory.mkdir()
    plan = stream_batches(results, budget)
    ledger = {
        "packing_budget_cycles": budget, "estimates_are_not_acceptance": True,
        "cycle_limit_inclusive": ICARUS_CYCLE_LIMIT,
        "seconds_limit_exclusive": ICARUS_SECONDS_LIMIT,
        "coverage_policy": "primary commands only; boundary/reset replays excluded",
        "batches": [],
    }
    for index, batch in enumerate(plan):
        members = [
            {"local_index": i - batch["first"], "original_index": i,
             "tag": commands[i].tag, "seed": commands[i].seed,
             "coverage_primary": i >= batch["primary_start"]}
            for i in range(batch["first"], batch["stop"])
        ]
        ledger["batches"].append({
            **batch, "job": f"{name}-batch-{index:03d}", "members": members,
            "status": "pending",
        })
    write_json(directory / "batches.json", ledger)
    pixels, completed, witnesses = {}, [], {}
    replay_pixels = replay_words = reset_words = all_words = 0
    total_cycles = total_duration = total_gaps = total_random_stalls = 0
    for batch in ledger["batches"]:
        first, stop = batch["first"], batch["stop"]
        job = batch["job"]
        simulate(execution, job, commands[first:stop], results[first:stop],
                 reset_tests=batch["reset_tests"])
        output = execution.output / job
        comparison = json.loads((output / "comparison.json").read_text())
        protocol = json.loads((output / "protocol.json").read_text())
        tier = json.loads((output / "tier.json").read_text())
        observed_commands = comparison["transport_independent_comparison"]["completed_commands"]
        cycles = comparison["command_cycles"]
        for member, observed, timing in zip(batch["members"], observed_commands, cycles):
            require(member["tag"] == observed["tag"] == timing["tag"],
                    "Batch membership/compared tag mismatch")
            original = member["original_index"]
            if member["coverage_primary"]:
                require(original == len(completed) and member["tag"] not in pixels,
                        "Primary comparison missing, duplicated or out of order")
                pixels[member["tag"]] = observed["pixel_records"]
                completed.append({**observed, "command_index": original,
                                  "job": job, "local_index": member["local_index"]})
            else:
                previous = completed[original]
                require(all(previous[key] == observed[key] for key in
                            ("tag", "input_words_sha256", "compared_transfers_sha256",
                             "exact_words", "pixel_records", "status", "nondegenerate_fans")),
                        "Boundary replay differs from the original compared command")
                replay_pixels += observed["pixel_records"]
                replay_words += observed["exact_words"]
        for local in range(1, len(cycles)):
            original = first + local
            require(cycles[local]["first_input_cycle"]
                    == cycles[local - 1]["completion_cycle"] + 1,
                    "Missing earliest-legal boundary transfer")
            witnesses[original] = {
                "previous_index": original - 1, "next_index": original,
                "previous_tag": commands[original - 1].tag,
                "next_tag": commands[original].tag, "job": job,
                "completion_cycle": cycles[local - 1]["completion_cycle"],
                "next_input_cycle": cycles[local]["first_input_cycle"],
                "partition_boundary": (original == batch["primary_start"]
                                       and batch["primary_start"] > 0),
            }
        all_words += comparison["exact_words"]
        reset_words += (comparison["exact_words"]
                        - comparison["transport_independent_comparison"]["exact_words"])
        total_cycles += protocol["actual_cycles"]
        total_duration += tier["duration_s"]
        total_gaps += protocol["input_gaps"]
        total_random_stalls += protocol["random_stalls"]
        batch.update({
            "status": "passed", "actual_cycles": protocol["actual_cycles"],
            "duration_s": tier["duration_s"],
            "protocol": execution.rel(output / "protocol.json"),
            "comparison": execution.rel(output / "comparison.json"),
            "tier": execution.rel(output / "tier.json"),
            "source_snapshot": execution.rel(execution.output / "source"),
        })
        write_json(directory / "batches.json", ledger)
    require(len(completed) == len(commands) and set(pixels) == {c.tag for c in commands},
            "Aggregate lost/duplicated original commands")
    require(set(witnesses) == set(range(1, len(commands))),
            "Missing adjacent-command evidence across partitions")
    require(sum(b["reset_tests"] for b in plan) == 1 and total_random_stalls > 0,
            "Missing reset/random backpressure coverage")
    primary_words = sum(row["exact_words"] for row in completed)
    require(all_words == primary_words + replay_words + reset_words,
            "Aggregate transfer conservation failed")
    write_json(directory / "comparison.json", {
        "commands": len(completed), "pixel_records": sum(pixels.values()),
        "exact_words": primary_words, "per_tag_pixels": pixels,
        "all_words_ordered_exact": True, "completed_commands": completed,
        "excluded_boundary_replay_words": replay_words,
        "excluded_boundary_replay_pixels": replay_pixels,
        "excluded_reset_recovery_words": reset_words,
        "all_compared_words_including_replays": all_words,
        "adjacent_command_witnesses": [witnesses[i] for i in sorted(witnesses)],
        "reset_recoveries": 3, "input_gaps": total_gaps,
        "random_stalls": total_random_stalls, "total_actual_cycles": total_cycles,
        "total_simulation_duration_s": total_duration,
    })
    return pixels


def packed(values, width):
    return sum((v & ((1 << width) - 1)) << (width * i) for i, v in enumerate(values))


def literal(width, value):
    return f"{width}'h{value & ((1 << width) - 1):x}"


def primitives(execution):
    """Exercise verbatim primitive pins, exact edge latency and holding."""
    rng = random.Random(20261026)
    dot_cases = [
        ((-(1 << 31),) * 4, (-(1 << 31),) * 4),
        (((1 << 31) - 1,) * 4, (-(1 << 31),) * 4),
        ((-1, 0, 0, 0), (1, 0, 0, 0)),
        ((1 << 30, 1 << 30, -(1 << 30), -(1 << 30)), (Q,) * 4),
    ]
    dot_cases += [(tuple(rng.randint(-(1 << 31), (1 << 31) - 1) for _ in range(4)),
                   tuple(rng.randint(-(1 << 31), (1 << 31) - 1) for _ in range(4)))
                  for _ in range(48)]
    div_cases = [(n, d) for n in (-7, 0, 7, -(1 << 95), (1 << 95) - 1)
                 for d in (1, -1, 3, -3, -(1 << 63), (1 << 63) - 1)
                 if not (n == -(1 << 95) and d == -1)]
    div_cases += [(rng.randint(-(1 << 94), (1 << 94) - 1),
                   rng.choice((-1, 1)) * rng.randint(1, (1 << 63) - 1))
                  for _ in range(48)]
    edge_cases = [((0, 0), (65536, 0), (0, 65536)),
                  ((65536, 65536), (0, 65536), (65536, 0)),
                  ((0, 0), (0, 0), (128, 128))]
    edge_cases += [tuple((rng.randrange(65537), rng.randrange(65537)) for _ in range(3))
                   for _ in range(48)]
    definitions = [
        ("dot4", 4,
         "reg [127:0] s_a=0,s_b=0; wire signed [31:0] m_result;",
         "g1_dot4 dut(.*);", "{m_result}", 32,
         [(f"s_a={literal(128, packed(a,32))}; s_b={literal(128, packed(b,32))};",
           literal(32, max(-(1 << 31), min((1 << 31) - 1,
                          sum(x * y for x, y in zip(a, b)) // Q))))
          for a, b in dot_cases]),
        ("divider", 98,
         "reg signed [95:0] s_numerator=0; reg signed [63:0] s_denominator=1;"
         "wire signed [95:0] m_quotient; wire signed [63:0] m_remainder;",
         "g1_divider dut(.*);", "{m_quotient,m_remainder}", 160,
         [(f"s_numerator={literal(96,n)}; s_denominator={literal(64,d)};",
           literal(160, ((n // d) & ((1 << 96) - 1)) << 64
                   | ((n % d) & ((1 << 64) - 1)))) for n, d in div_cases]),
        ("edge", 2,
         "reg [33:0] s_a=0,s_b=0,s_p=0; wire signed [36:0] m_edge;",
         "g1_edge dut(.*);", "{m_edge}", 37,
         [(f"s_a={literal(34,packed(a,17))}; s_b={literal(34,packed(b,17))};"
           f"s_p={literal(34,packed(p,17))};", literal(37, edge(a, b, p)))
          for a, b, p in edge_cases]),
    ]
    ledger = []
    for name, latency, declarations, instance, data, width, cases in definitions:
        directory = execution.output / ("unit-" + name)
        directory.mkdir()
        body = []
        for index, (assignments, expected) in enumerate(cases):
            body.append(f"""
      @(negedge clk); {assignments} s_valid=1;
      if(s_ready !== 1'b1) $fatal(1,"UNIT_NOT_READY");
      @(posedge clk); #1;
      if(m_valid !== 1'b0) $fatal(1,"UNIT_EARLY_RESULT");
      @(negedge clk); s_valid=0;
      for(k=1;k<={latency};k=k+1) begin
        @(posedge clk); #1;
        if(m_valid !== (k=={latency})) $fatal(1,"UNIT_LATENCY case {index}");
      end
      if({data} !== {expected}) $fatal(1,"UNIT_NUMERICAL case {index}");
      repeat(70) begin
        @(posedge clk); #1;
        if(m_valid !== 1'b1 || {data} !== {expected})
          $fatal(1,"UNIT_HOLD case {index}");
        if(s_ready !== 1'b0) $fatal(1,"UNIT_BUSY_READY");
      end
      @(negedge clk); m_ready=1;
      @(posedge clk); #1;
      if(m_valid !== 1'b0 || s_ready !== 1'b1) $fatal(1,"UNIT_RETIRE");
      @(negedge clk); m_ready=0;
""")
        tb = f"""
`timescale 1ns/1ps
module tb;
  reg clk=0,rst_n,s_valid=0,m_ready=0;
  wire s_ready,m_valid;
  {declarations}
  {instance}
  integer k,actual_cycles=0;
  always @(posedge clk) actual_cycles=actual_cycles+1;
  always #5 clk=~clk;
  always @(posedge clk or negedge clk) if($time>0) begin
    if((^{{s_ready,m_valid}})===1'bx) $fatal(1,"UNIT_XZ");
    if(!rst_n && {{s_ready,m_valid}} !== 2'b00) $fatal(1,"UNIT_RESET");
  end
  initial begin
    rst_n=0;
    #1;
    if({{s_ready,m_valid}} !== 2'b00) $fatal(1,"UNIT_TIME0_RESET");
    repeat(3) @(negedge clk);
    #2; rst_n=1;
    {''.join(body)}
    $display("UNIT_COMPLETE {len(cases)} {latency} cycles=%0d",actual_cycles);
    $finish;
  end
endmodule
"""
        (directory / "tb.sv").write_text(tb)
        execution.checked("unit-" + name + "-compile", [
            "iverilog", "-g2012", "-Wall", "-s", "tb", "-o",
            execution.rel(directory / "simulation"), execution.rel(directory / "tb.sv"),
            execution.rel(execution.root / "rtl" / ("g1_" + name + ".sv"))])
        row = execution.checked("unit-" + name + "-simulate",
                                ["vvp", execution.rel(directory / "simulation")])
        require(f"UNIT_COMPLETE {len(cases)} {latency}" in
                (execution.root / row["stdout"]).read_text(),
                f"Missing primitive comparisons: {name}")
        actual = re.findall(r"UNIT_COMPLETE \d+ \d+ cycles=(\d+)",
                            (execution.root / row["stdout"]).read_text())
        require(len(actual) == 1, f"Missing actual primitive cycle count: {name}")
        icarus_tier(execution, directory, row, int(actual[0]))
        ledger.append({"primitive": name, "compared_cases": len(cases),
                       "required_latency_cycles": latency, "hold_cycles_each": 70,
                       "receipt_command": row["name"]})
    write_json(execution.output / "primitives.json", ledger)


def synthesis(execution, name="synthesis"):
    directory = execution.output / name
    directory.mkdir()
    sources = sorted((execution.root / "rtl").glob("*.sv"))
    for source in sources:
        text = re.sub(r"/\*.*?\*/|//[^\n]*", "", source.read_text(), flags=re.S)
        require("/" not in text and "%" not in text,
                f"Forbidden division/modulo operator in {source.name}")
    script = (
        "read_verilog -sv " + " ".join(execution.rel(p) for p in sources) + "\n"
        "hierarchy -check -top crucible_g1_top\n"
        "proc\ncheck -assert\n"
        f"write_json {execution.rel(directory / 'lowered.json')}\n"
        "synth -top crucible_g1_top -noabc\n"
        "check -assert\n"
        f"write_json {execution.rel(directory / 'netlist.json')}\nstat\n")
    (directory / "synthesis.ys").write_text(script)
    row = execution.checked(name + "-yosys",
                            ["yosys", "-s", execution.rel(directory / "synthesis.ys")])
    warnings = [line for line in (execution.root / row["stdout"]).read_text().splitlines()
                if line.startswith("Warning:")]
    required = {"crucible_g1_top", "g1_transform", "g1_clipper", "g1_project",
                "g1_raster", "g1_dot4", "g1_divider", "g1_edge"}
    ledger = {}
    for filename in ("lowered.json", "netlist.json"):
        netlist = json.loads((directory / filename).read_text())
        modules = netlist["modules"]
        require(required <= set(modules), f"Required hierarchy lost: {filename}")
        states = {}
        for module_name, module in modules.items():
            attrs = module.get("attributes", {})
            require(not int(attrs.get("blackbox", "0"), 2), f"Black box: {module_name}")
            cells = module.get("cells", {})
            cell_types = [cell["type"] for cell in cells.values()]
            require(not any("latch" in t.lower() or t.lower() in
                            ("$div", "$mod", "$divfloor", "$modfloor")
                            for t in cell_types), f"Forbidden cell in {module_name}")
            state_count = sum("dff" in t.lower() for t in cell_types)
            if module_name in required:
                require(state_count > 0, f"No sequential state: {module_name}")
            states[module_name] = {"sequential_cells": state_count, "cells": len(cells)}
            for cell in cells.values():
                require(cell["type"] in modules or cell["type"].startswith("$"),
                        f"Unresolved primitive/black box: {cell['type']}")
                if cell["type"] in required:
                    connections = cell.get("connections", {})
                    directions = cell.get("port_directions", {})
                    require(all(connections.get(p) for p, direction in directions.items()
                                if direction == "input"),
                            f"Unconnected required child input: {module_name}")
                    require(any(connections.get(p) for p, direction in directions.items()
                                if direction == "output"),
                            f"Disconnected required child result: {module_name}")
            # check -assert checks connectivity; also reject constant/unconnected
            # public valid, ready and data outputs after optimization.
            if module_name == "crucible_g1_top":
                for port in ("s_ready", "m_valid", "m_data", "m_last"):
                    bits = module["ports"][port]["bits"]
                    require(any(isinstance(bit, int) for bit in bits),
                            f"Constant public output: {port}")
        # Verify the literal required child instance relationships.
        children = {
            "crucible_g1_top": {"g1_transform": 1, "g1_clipper": 1,
                                "g1_project": 1, "g1_raster": 1},
            "g1_transform": {"g1_dot4": 1},
            "g1_clipper": {"g1_divider": 1}, "g1_project": {"g1_divider": 1},
            "g1_raster": {"g1_divider": 1, "g1_edge": 3},
        }
        for parent, expected in children.items():
            actual = [c["type"] for c in modules[parent]["cells"].values()]
            require(all(actual.count(child) == count for child, count in expected.items()),
                    f"Hierarchy instance mismatch: {parent}")
        ledger[filename] = states
    write_json(directory / "structure.json", {
        "zero_latches": True, "zero_div_mod": True, "no_blackboxes": True,
        "hierarchy_and_state": ledger, "timing_acceptance": False,
        "warnings": warnings,
    })


def mutations(execution, commands, results):
    edits = [
        ("top-left", "g1_raster.sv", "top_left=(dy<0)", "top_left=(dy>0)"),
        ("normalization", "g1_raster.sv", "18'd65536-{1'b0,lambda0}",
         "18'd65535-{1'b0,lambda0}"),
        ("transform-signedness", "g1_dot4.sv", "total >>> 16", "total >> 16"),
        ("clip-plane", "g1_clipper.sv", "3'd1: distance=x+w;", "3'd1: distance=x-w;"),
        ("output-order", "crucible_g1_top.sv",
         "record_index<=record_index+3'd1;", "record_index<=record_index+3'd2;"),
    ]
    ledger = []
    for name, filename, old, new in edits:
        directory = execution.output / ("mutant-" + name)
        directory.mkdir()
        rtl = directory / "rtl"
        shutil.copytree(execution.root / "rtl", rtl)
        path = rtl / filename
        original = path.read_text()
        require(original.count(old) == 1, f"Mutation anchor not unique: {name}")
        path.write_text(original.replace(old, new))
        write_json(directory / "edit.json", {
            "file": "rtl/" + filename, "before": old, "after": new,
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in sorted(rtl.glob("*.sv"))},
            "oracle_changed": False,
        })
        simulate(execution, "sensitivity-" + name, commands, results, rtl, mutation=True)
        ledger.append({"mutation": name, "rejected": True,
                       "edit": execution.rel(directory / "edit.json"),
                       "rejection": execution.rel(
                           execution.output / ("sensitivity-" + name) / "rejection.json")})
    write_json(execution.output / "mutations.json", ledger)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-child", action="store_true",
                        help="Internal bounded clean-tree reproduction; no recursion")
    parser.add_argument("--probe", action="store_true",
                        help="Advisory bounded preparation, not full L1 acceptance")
    parser.add_argument("--probe-stage", choices=("stream", "structure", "sensitivity", "stimulus",
                                                 "transfer-checker", "native-coverage", "tiering"),
                        default="stream", help="Select a bounded preparation diagnostic")
    parser.add_argument("--repair-of", help="Project-relative earlier preparation receipt")
    args = parser.parse_args()
    relative = ("evidence/preparation/independent-probe-" if args.probe
                else "evidence/l1/run-") + uuid.uuid4().hex
    output = ROOT / relative
    output.mkdir(parents=True, exist_ok=False)
    print(relative + "/result.json", flush=True)
    execution = Execution(ROOT, output, args.repair_of)
    try:
        for tool in ("python3", "iverilog", "vvp", "yosys"):
            require(shutil.which(tool) is not None, f"Missing prerequisite executable: {tool}")
        for tool, argv in (("python3", ["python3", "--version"]),
                           ("iverilog", ["iverilog", "-V"]), ("vvp", ["vvp", "-V"]),
                           ("yosys", ["yosys", "-V"])):
            row = execution.checked("version-" + tool, argv)
            execution.receipt["tool_versions"][tool] = {
                "stdout": row["stdout"], "stderr": row["stderr"]}
        execution.save()
        # Keep an exact passing-baseline source snapshot, not only a mutable path.
        for path in execution.receipt["source_sha256"]:
            target = output / "source" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, target)
        tiering_sensitivity(execution)
        write_json(output / "transfer-checker-sensitivity.json", transfer_self_test())
        write_json(output / "coverage-marker-sensitivity.json", coverage_marker_self_test())
        write_json(output / "execution-contract-sensitivity.json", execution_contract_self_test())
        allocation_repair_regression(execution)
        write_json(output / "diagnostic-sensitivity.json", diagnostic_self_test())
        write_json(output / "timing-observation-sensitivity.json",
                   timing_observation_self_test())
        write_json(output / "report-parser-sensitivity.json",
                   report_parser_self_test(output / "report-parser-fixtures"))
        write_json(output / "coverage-report-sensitivity.json",
                   coverage_report_self_test(output / "coverage-report-fixtures"))
        if args.probe and args.probe_stage == "native-coverage":
            return execution.complete({
                "status": "preparation_passed", "full_l1": False,
                "stage": "native-coverage", "native_gate_executed": False})
        if args.probe and args.probe_stage == "transfer-checker":
            return execution.complete({
                "status": "preparation_passed", "full_l1": False,
                "stage": "transfer-checker", "physical_board_runs": 0})
        commands, subset_count = workload()
        subset = commands[:subset_count]
        if (args.probe and args.probe_stage not in ("stimulus", "tiering")) or args.clean_child:
            commands = subset
        results = [model(c) for c in commands]
        write_json(output / "reference.json", [
            {"tag": c.tag, "records": r.records, "transformed": r.transformed,
             "planes": r.planes, "projected": r.projected, "fans": r.fans,
             "cycle_bound": r.cycle_bound}
            for c, r in zip(commands, results)])
        if args.probe and args.probe_stage == "stimulus":
            prediction = coverage(commands, results, {
                c.tag: len(r.records) - 1 for c, r in zip(commands, results)})
            write_json(output / "reference-prediction.json", {
                "hardware_comparisons": 0, "acceptance_evidence": False,
                "reference_only_stimulus_prediction": prediction})
            require(all(prediction["requirements"].values()),
                    "Stimulus/reference prediction cannot meet frozen thresholds: " +
                    ", ".join(k for k, v in prediction["requirements"].items() if not v))
            return execution.complete({
                "status": "stimulus_reference_prepared", "full_l1": False,
                "hardware_comparisons": 0})
        if args.probe and args.probe_stage == "structure":
            synthesis(execution)
            result = {"status": "preparation_passed", "full_l1": False,
                      "stage": "structure"}
            return execution.complete(result)
        if args.probe and args.probe_stage == "tiering":
            planned = stream_batches(results)
            write_json(output / "full-workload-partition-prediction.json", {
                "kind": "scheduling_prediction_not_hardware_coverage",
                "commands": len(commands), "batches": planned,
                "hardware_comparisons": 0,
            })
            # Force a real partition just beyond the unchanged clean subset.
            budget = stream_job_estimate(results[:subset_count], True)
            probe_commands = commands[:subset_count + 2]
            pixels = simulate_batched(execution, "tiering", probe_commands,
                                      results[:subset_count + 2], budget)
            batches = json.loads((output / "tiering/batches.json").read_text())["batches"]
            require(len(batches) >= 2, "Tiering probe did not exercise a boundary replay")
            return execution.complete({
                "status": "preparation_passed", "full_l1": False,
                "stage": "tiering", "compared_commands": len(probe_commands),
                "pixels": sum(pixels.values()), "batches": len(batches)})
        if args.probe and args.probe_stage == "sensitivity":
            simulate(execution, "sensitivity-baseline", commands, results)
            mutations(execution, commands, results)
            result = {"status": "preparation_passed", "full_l1": False,
                      "stage": "sensitivity"}
            return execution.complete(result)
        bridge = bridge_commands()
        simulate(execution, "bridge-workload", bridge, [model(c) for c in bridge])
        primitives(execution)
        pixels = simulate_batched(execution, "behavior", commands, results)
        if args.probe:
            result = {"status": "preparation_passed", "full_l1": False,
                      "compared_commands": len(commands), "pixels": sum(pixels.values())}
        elif args.clean_child:
            require({0, 1} <= {c.mode for c in commands} and
                    any(len(r.fans) > 1 for r in results), "Clean subset coverage missing")
            require(bool(results[0].ties | results[1].ties), "Clean shared-edge tie missing")
            synthesis(execution)
            result = {"status": "clean_subset_passed", "full_l1": False,
                      "compared_commands": len(commands), "pixels": sum(pixels.values())}
        else:
            measured = coverage(commands, results, pixels)
            write_json(output / "coverage.json", measured)
            require(all(measured["requirements"].values()),
                    "Unclosed functional coverage: " + ", ".join(
                        key for key, value in measured["requirements"].items() if not value))
            subset_results = results[:subset_count]
            # An unmutated baseline precedes every unchanged-checker campaign.
            simulate(execution, "sensitivity-baseline", subset, subset_results)
            mutations(execution, subset, subset_results)
            synthesis(execution)
            clean = output / "clean"
            clean.mkdir()
            for path in inventory(ROOT):
                target = clean / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / path, target)
            execution.checked("clean-reproduction",
                              ["python3", "tests/verify.py", "--clean-child"], cwd=clean)
            clean_results = list(clean.glob("evidence/l1/run-*/result.json"))
            require(len(clean_results) == 1 and
                    json.loads(clean_results[0].read_text())["status"] == "clean_subset_passed",
                    "Clean reproduction missing actual numerical/synthesis result")
            require(inventory(ROOT) == execution.receipt["source_sha256"],
                    "Product sources changed during verification")
            result = {"status": "portable_l1_passed", "full_l1": True,
                      "coverage": "coverage.json"}
        return execution.complete(result)
    except (RuntimeError, OSError, ValueError, KeyError, AssertionError) as error:
        execution.receipt["exit_code"] = 1
        write_json(output / "result.json", {
            "status": "failed", "error_type": type(error).__name__, "reason": str(error)})
        print(f"FAIL: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        execution.receipt["end"] = time.time()
        execution.save()


if __name__ == "__main__":
    sys.exit(main())
