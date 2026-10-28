#!/usr/bin/env python3
"""Read-only native prerequisite discovery; never a timing or board pass.

After append-only admission, run from the project root:
python3 tests/native_prerequisites.py --fit-dir <existing-fit> --revision top

The fit path is project-relative. TimeQuest opens a disposable copy, never the
original fit. No map, fit, assembly, programming or graphics test is launched.
The optional --bridge-dir overrides VULCAN_BRIDGE_DIR or the supported bridge
client's default ~/netsys17_bridge. Remote operations only enumerate tool files
and read narrowly named graphics transport/manifests. Missing documentation is
an unresolved interface, not proof of unavailable hardware.

Quartus 17.1 coverage uses report_ucp and check_timing; it does not expose
get_unconstrained_paths. Reported unconstrained I/O is retained separately from
clock coverage and must not be relabeled as constrained external timing.
Successful query execution is distinct from complete timing coverage: nonzero
coverage counts and mismatched fitted sources are explicit discovery issues.
Summary parsing rejects duplicate sections and missing I/O-delay checks; its
synthetic corruption controls execute before native discovery.
Every Quartus 17.1 summary check is required, including clock and multicycle
exception consistency; omitted checks are missing evidence, not zero issues.
Query validation inspects both raw streams: success markers cannot override
TimeQuest errors, failed queries or missing-asynchronous-reset warnings.
Query lifecycle markers must occur once in Tcl execution order, followed by
the final zero-failure marker; unordered success tokens are not execution proof.
The unique post-fit netlist marker must precede all query lifecycle markers.
Missing local FPGA configuration or image inventory is also an explicit issue,
not a successful source/image binding. This read-only inventory cannot prove
which image is loaded, even when local files are present.
Bridge prerequisites are inventoried together before snapshots are copied, so
an absent client cannot hide an independently absent heartbeat.
Bridge discovery requires a completed, nonempty inventory, not merely exit zero.
Its completion marker establishes discovery only, never graphics transport.
Clock period and both setup/hold slacks are checked separately from query
success. Meeting those numerical limits never overrides incomplete coverage.
The queried project must name the exact required device and top-level entity.
These assignments are prerequisites, not proof of fitted or loaded-image identity.
timing-readiness.json separates successful query execution, numerical limits and
coverage completeness; positive slack cannot turn missing coverage into readiness.
Readiness independently requires every coverage summary row, even when supplied
with an already parsed zero-count dictionary. Each row must contain the exact
number of nonnegative integer counts; empty rows are not zero-issue evidence.
The retained tool banner must identify TimeQuest 17.1 before querying the fit;
successful queries from another Quartus release do not meet the native contract.
Timing readiness is retained even when a missing fit or rejected tool version
prevents querying; an unexecuted query is explicitly unresolved, not a pass.
Unconstrained I/O detail tables are reconciled with both summary columns.
Their endpoint lists diagnose integration work; they never generate delays or
false-path exceptions, including for the asynchronous reset input.
Readiness also requires successful endpoint-detail reconciliation; a failed
detail parser cannot be hidden by otherwise complete zero-count summaries.
Zero-count endpoint reports still require unique ordered Setup/Hold analyses;
an empty or truncated report is not evidence that no endpoints need constraints.
Fitted-source associations also bind the product hash captured at discovery
start; matching a subsequently changed product does not match that receipt.
Unconstrained path rows are counted independently of endpoint tables, with
bounded destination samples per port. Reset destinations remain visible;
their names alone do not justify false-path exceptions.
"""

import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("rtl/*.sv", "design/SPEC.md", "design/ARCHITECTURE.md", "tests/*.py")
TIMEOUT = 3600
UNCONSTRAINED_PROPERTIES = (
    "Illegal Clocks", "Unconstrained Clocks", "Unconstrained Input Ports",
    "Unconstrained Input Port Paths", "Unconstrained Output Ports",
    "Unconstrained Output Port Paths",
)
TIMING_CHECKS = (
    "no_clock", "multiple_clock", "pos_neg_clock_domain", "generated_clock",
    "virtual_clock", "no_input_delay", "no_output_delay", "partial_input_delay",
    "partial_output_delay", "io_min_max_delay_consistency", "reference_pin",
    "generated_io_delay", "latency_override", "partial_multicycle",
    "multicycle_consistency", "loops", "latches", "pll_cross_check",
    "uncertainty", "partial_min_max_delay", "clock_assignments_on_output_ports",
    "input_delay_assigned_to_clock",
)

# These are file-discovery commands, not a graphics transport implementation.
REMOTE_DISCOVERY = r"""
$ErrorActionPreference = 'Stop'
$base = Join-Path $env:USERPROFILE 'Catapult\BoardTestPackages'
if (-not (Test-Path -LiteralPath $base)) {
    throw "Supported board-tools package root is not readable: $base"
}
$packages = @(Get-ChildItem -LiteralPath $base -Directory | Sort-Object Name)
if ($packages.Count -gt 32) { throw 'Package discovery exceeds bounded limit 32' }
foreach ($package in $packages) {
    $tools = Join-Path $package.FullName 'retail-amd64\Tools'
    if (-not (Test-Path -LiteralPath $tools)) { continue }
    Write-Output ("TOOLS_DIRECTORY:" + $tools)
    $files = @(Get-ChildItem -LiteralPath $tools -File | Sort-Object Name)
    if ($files.Count -gt 2048) { throw 'Tools inventory exceeds bounded limit 2048' }
    foreach ($file in $files) {
        Write-Output ("TOOL_FILE:{0}|{1}|{2:o}" -f
            $file.Name, $file.Length, $file.LastWriteTimeUtc)
        if ($file.Name -match '(?i)(crucible|graphics.?stream|stream.?transport)' -and
            $file.Extension -match '^\.(json|txt|md|ps1|py)$') {
            if ($file.Length -gt 65536) {
                Write-Output ("UNREAD_LARGE_INTERFACE_FILE:" + $file.FullName)
            } else {
                Write-Output ("INTERFACE_FILE_BEGIN:" + $file.FullName)
                Write-Output ("SHA256:" + (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash)
                Get-Content -LiteralPath $file.FullName -Raw
                Write-Output ("INTERFACE_FILE_END:" + $file.FullName)
            }
        }
    }
}
Write-Output 'READ_ONLY_DISCOVERY_COMPLETE'
"""


def digest(path):
    with path.open("rb") as stream:
        value = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
        return value.hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    if json.loads(path.read_text()) != value:
        raise RuntimeError("Receipt read-back mismatch: " + str(path))


def relative(path):
    return path.relative_to(ROOT).as_posix()


def project_path(value):
    path = Path(value)
    if path.is_absolute():
        raise ValueError("Use a project-relative fit path")
    resolved = (ROOT / path).resolve(strict=True)
    resolved.relative_to(ROOT)
    return resolved


def quartus_version(text):
    """Require the admitted TimeQuest release, retaining its full build banner."""
    lines = text.splitlines()
    versions = [line for line in lines if line.startswith("Version ")]
    if (lines.count("Quartus Prime TimeQuest Timing Analyzer") != 1
            or len(versions) != 1
            or re.fullmatch(r"Version 17\.1(?:\.[0-9]+)? Build [0-9]+ .+",
                            versions[0]) is None):
        raise RuntimeError("Expected an unambiguous Quartus TimeQuest 17.1 build banner")
    return {"release": "17.1", "build_banner": versions[0],
            "acceptance_evidence": False}


class Discovery:
    def __init__(self, output, argv):
        self.output = output
        self.receipt = {
            "schema": 1, "kind": "native-prerequisites",
            "acceptance_evidence": False, "native_gate_pass_claimed": False,
            "argv": argv, "cwd": ".", "start": time.time(), "end": None,
            "exit_code": None, "timed_out": False, "status": "running",
            "timeout_s": None, "child_timeout_s": TIMEOUT,
            "python_version": sys.version, "commands": [], "operations": [],
            "source_sha256": {}, "tool_versions": {}, "issues": [],
        }
        self.persist()

    def persist(self):
        save(self.output / "receipt.json", self.receipt)

    def issue(self, message):
        self.receipt["issues"].append(message)
        self.persist()

    def operation(self, name, function):
        row = {"operation": name, "start": time.time(), "status": "running"}
        self.receipt["operations"].append(row)
        self.persist()
        try:
            row["result"] = function()
            row["status"] = "completed"
            return row["result"]
        except (OSError, ValueError, RuntimeError) as error:
            row["status"] = "failed"
            row["error"] = f"{type(error).__name__}: {error}"
            self.issue(name + ": " + row["error"])
            return None
        finally:
            row["end"] = time.time()
            self.persist()

    def capture(self, name, argv, cwd=ROOT, timeout=TIMEOUT):
        directory = self.output / name
        directory.mkdir(exist_ok=False)
        row = {
            "name": name, "argv": [str(word) for word in argv],
            "cwd": relative(cwd), "start": time.time(), "end": None,
            "timeout_s": timeout, "timed_out": False, "exit_code": None,
            "stdout": relative(directory / "stdout.log"),
            "stderr": relative(directory / "stderr.log"),
        }
        self.receipt["commands"].append(row)
        self.persist()
        try:
            with (ROOT / row["stdout"]).open("xb") as stdout, (
                    ROOT / row["stderr"]).open("xb") as stderr:
                result = subprocess.run(row["argv"], cwd=cwd, stdout=stdout,
                                        stderr=stderr, timeout=timeout, check=False)
                row["exit_code"] = result.returncode
        except subprocess.TimeoutExpired as error:
            row["timed_out"] = True
            self.receipt["timed_out"] = True
            row["error"] = str(error)
        except OSError as error:
            row["error"] = f"{type(error).__name__}: {error}"
        finally:
            row["end"] = time.time()
            row["streams"] = {
                key: {"sha256": digest(ROOT / row[key]),
                      "bytes": (ROOT / row[key]).stat().st_size}
                for key in ("stdout", "stderr")
            }
            self.persist()
        if row["exit_code"] != 0 or row["timed_out"]:
            self.issue(name + ": command failed; inspect " + row["stderr"])
        return row

    def inventory(self):
        for selector in SOURCES:
            paths = sorted(ROOT.glob(selector))
            if not paths:
                raise RuntimeError("No declared source matches " + selector)
            for path in paths:
                self.receipt["source_sha256"][relative(path)] = digest(path)
        self.persist()
        return dict(self.receipt["source_sha256"])


def sta_tcl(revision):
    if re.fullmatch(r"[A-Za-z0-9_-]+", revision) is None:
        raise ValueError("Revision must be a simple Quartus identifier")
    return r"""
package require ::quartus::project
package require ::quartus::sta
set failed 0
proc query {name script} {
    global failed
    puts "QUERY_BEGIN:$name"
    if {[catch {uplevel 1 $script} result options]} {
        puts stderr "QUERY_FAILED:${name}:$result"
        puts stderr [dict get $options -errorinfo]
        set failed 1
    } else {
        puts "QUERY_SUCCEEDED:$name"
    }
}
project_open -revision @REVISION@ @REVISION@
create_timing_netlist
puts "NETLIST_MODE:post_fit"
read_sdc
update_timing_netlist
query clocks {
    puts "PROJECT_DEVICE:[get_global_assignment -name DEVICE]"
    puts "PROJECT_TOP:[get_global_assignment -name TOP_LEVEL_ENTITY]"
    set clocks [get_clocks *]
    if {[get_collection_size $clocks] == 0} { error "No synchronous clocks" }
    foreach_in_collection clk $clocks {
        puts "CLOCK:[get_clock_info -name $clk]:[get_clock_info -period $clk]"
    }
    report_clocks -file clocks.rpt
}
query synchronous_paths {
    set registers [get_registers *]
    puts "REGISTER_COUNT:[get_collection_size $registers]"
    if {[get_collection_size $registers] == 0} { error "Empty register scope" }
    set paths [get_timing_paths -setup -npaths 1]
    if {[get_collection_size $paths] == 0} { error "No synchronous setup paths" }
    foreach_in_collection path $paths {
        puts "SETUP_SLACK:[get_path_info $path -slack]"
        puts "SETUP_FROM_CLOCK:[get_clock_info -name [get_path_info $path -from_clock]]"
        puts "SETUP_TO_CLOCK:[get_clock_info -name [get_path_info $path -to_clock]]"
    }
    set hold_paths [get_timing_paths -hold -npaths 1]
    if {[get_collection_size $hold_paths] == 0} { error "No synchronous hold paths" }
    foreach_in_collection path $hold_paths {
        puts "HOLD_SLACK:[get_path_info $path -slack]"
        puts "HOLD_FROM_CLOCK:[get_clock_info -name [get_path_info $path -from_clock]]"
        puts "HOLD_TO_CLOCK:[get_clock_info -name [get_path_info $path -to_clock]]"
    }
    report_timing -setup -npaths 20 -file setup.rpt
    report_timing -hold -npaths 20 -file hold.rpt
}
query unconstrained_report {
    report_ucp -file unconstrained.rpt
}
query timing_coverage {
    check_timing -file timing_checks.rpt
}
delete_timing_netlist
project_close
puts "DISCOVERY_QUERY_FAILURES:$failed"
exit $failed
""".replace("@REVISION@", revision)


def report_summary(path, heading, columns, required):
    """Reject missing, duplicated or malformed native summary evidence."""
    tables = [
        [field.strip() for field in line.split(";")[1:-1]]
        for line in path.read_text().splitlines() if line.startswith(";")
    ]
    if tables.count([heading]) != 1:
        raise RuntimeError("Missing or duplicate summary in " + path.name)
    rows = {}
    in_summary = False
    header_seen = False
    for fields in tables:
        if fields == [heading]:
            in_summary = True
            continue
        if not in_summary:
            continue
        if len(fields) == 1:
            break
        if fields == columns:
            if header_seen or rows:
                raise RuntimeError("Duplicate summary header in " + path.name)
            header_seen = True
            continue
        if not header_seen or len(fields) != len(columns):
            raise RuntimeError("Malformed summary row in " + path.name)
        name, *counts = fields
        if (not name or name in rows
                or not all(re.fullmatch(r"[0-9]+", count) for count in counts)):
            raise RuntimeError("Invalid summary counts in " + path.name)
        rows[name] = [int(count) for count in counts]
    missing = set(required) - rows.keys()
    if not header_seen or missing:
        raise RuntimeError("Missing summary evidence in " + path.name + ": "
                           + ", ".join(sorted(missing)))
    return rows


def coverage_reports(fit):
    unconstrained = report_summary(
        fit / "unconstrained.rpt", "Unconstrained Paths Summary",
        ["Property", "Setup", "Hold"],
        UNCONSTRAINED_PROPERTIES)
    checks = report_summary(
        fit / "timing_checks.rpt", "Summary",
        ["Check", "Number of Issues Found"],
        TIMING_CHECKS)
    return {
        "unconstrained_summary_setup_hold": unconstrained,
        "timing_check_issue_counts": checks,
        "scope": "Native report summaries, not a counted unconstrained-path collection",
        "external_io_timing_constrained": not any(
            any(counts) for name, counts in unconstrained.items()
            if "Port" in name),
        "acceptance_evidence": False,
    }


def unconstrained_port_details(path, summary):
    """Retain actual endpoint names without inventing external timing budgets."""
    tables = {"Setup": {"input": [], "output": []},
              "Hold": {"input": [], "output": []}}
    sections = set()
    analyses = []
    analysis = None
    active = None
    header_seen = False
    with path.open() as stream:
        for line in stream:
            if not line.startswith(";"):
                continue
            fields = [field.strip() for field in line.split(";")[1:-1]]
            if len(fields) == 1:
                if active is not None and not header_seen:
                    raise RuntimeError("Missing unconstrained port detail header")
                active = None
                header_seen = False
                if fields[0] in ("Setup Analysis", "Hold Analysis"):
                    analysis = fields[0].split()[0]
                    analyses.append(analysis)
                    if analyses != ["Setup", "Hold"][:len(analyses)]:
                        raise RuntimeError("Duplicate or unordered endpoint analyses")
                elif analysis is not None and fields[0] in (
                        "Unconstrained Input Ports", "Unconstrained Output Ports"):
                    active = "input" if "Input" in fields[0] else "output"
                    key = (analysis, active)
                    if key in sections:
                        raise RuntimeError("Duplicate unconstrained port detail section")
                    sections.add(key)
                else:
                    analysis = None if fields[0].endswith(" Analysis") else analysis
                continue
            if active is None:
                continue
            expected_header = [active.capitalize() + " Port", "Comment"]
            if not header_seen:
                if fields != expected_header:
                    raise RuntimeError("Missing unconstrained port detail header")
                header_seen = True
                continue
            if len(fields) != 2 or not all(fields):
                raise RuntimeError("Malformed unconstrained port detail row")
            rows = tables[analysis][active]
            if any(row["port"] == fields[0] for row in rows):
                raise RuntimeError("Duplicate unconstrained port: " + fields[0])
            rows.append({"port": fields[0], "comment": fields[1]})
    if active is not None and not header_seen:
        raise RuntimeError("Missing unconstrained port detail header")
    if analyses != ["Setup", "Hold"]:
        raise RuntimeError("Missing endpoint Setup/Hold analysis")
    for column, analysis in enumerate(("Setup", "Hold")):
        for direction in ("input", "output"):
            property_name = "Unconstrained " + direction.capitalize() + " Ports"
            expected = summary[property_name][column]
            actual = len(tables[analysis][direction])
            if actual != expected:
                raise RuntimeError(
                    f"{analysis} {direction} port details disagree with summary: "
                    f"expected={expected} observed={actual}")
    return {
        "ports": tables, "acceptance_evidence": False,
        "constraints_generated": False,
        "scope": "Observed unconstrained endpoints only; integration must supply "
                 "justified min/max I/O timing and reset treatment, not blanket exceptions",
    }


def unconstrained_path_details(path, summary, ports):
    """Reconcile path counts while retaining bounded per-port diagnostics."""
    tables = {analysis: {direction: {} for direction in ("input", "output")}
              for analysis in ("Setup", "Hold")}
    known_ports = {
        analysis: {direction: {row["port"] for row in ports["ports"][analysis][direction]}
                   for direction in ("input", "output")}
        for analysis in ("Setup", "Hold")}
    analyses = []
    sections = set()
    analysis = None
    active = None
    header_seen = False
    with path.open() as stream:
        for line in stream:
            if not line.startswith(";"):
                continue
            fields = [field.strip() for field in line.split(";")[1:-1]]
            if len(fields) == 1:
                if active is not None and not header_seen:
                    raise RuntimeError("Missing unconstrained path detail header")
                active = None
                header_seen = False
                if fields[0] in ("Setup Analysis", "Hold Analysis"):
                    analysis = fields[0].split()[0]
                    analyses.append(analysis)
                    if analyses != ["Setup", "Hold"][:len(analyses)]:
                        raise RuntimeError("Duplicate or unordered path analyses")
                elif analysis is not None and fields[0] in (
                        "Unconstrained Input Port Paths", "Unconstrained Output Port Paths"):
                    active = "input" if "Input" in fields[0] else "output"
                    if (analysis, active) in sections:
                        raise RuntimeError("Duplicate unconstrained path detail section")
                    sections.add((analysis, active))
                elif fields[0].endswith(" Analysis"):
                    analysis = None
                continue
            if active is None:
                continue
            expected_header = (["From", "To", "To Clocks"] if active == "input"
                               else ["From", "To", "From Clocks"])
            if not header_seen:
                if fields != expected_header:
                    raise RuntimeError("Missing unconstrained path detail header")
                header_seen = True
                continue
            if len(fields) != 3 or not all(fields[:2]):
                raise RuntimeError("Malformed unconstrained path detail row")
            port, endpoint = ((fields[0], fields[1]) if active == "input"
                              else (fields[1], fields[0]))
            if port not in known_ports[analysis][active]:
                raise RuntimeError("Path references unreported unconstrained port: " + port)
            opposite = "output" if active == "input" else "input"
            if not fields[2] and endpoint not in known_ports[analysis][opposite]:
                raise RuntimeError("Unclocked path does not connect reported input/output ports")
            entry = tables[analysis][active].setdefault(
                port, {"count": 0, "endpoint_samples": []})
            entry["count"] += 1
            if len(entry["endpoint_samples"]) < 4:
                entry["endpoint_samples"].append(
                    {"endpoint": endpoint, "clocks": fields[2]})
    if active is not None and not header_seen:
        raise RuntimeError("Missing unconstrained path detail header")
    if analyses != ["Setup", "Hold"]:
        raise RuntimeError("Missing path Setup/Hold analysis")
    for column, analysis in enumerate(("Setup", "Hold")):
        for direction in ("input", "output"):
            expected = summary["Unconstrained " + direction.capitalize()
                               + " Port Paths"][column]
            actual = sum(row["count"] for row in tables[analysis][direction].values())
            if actual != expected:
                raise RuntimeError(
                    f"{analysis} {direction} path details disagree with summary: "
                    f"expected={expected} observed={actual}")
    return {
        "paths_by_port": tables, "acceptance_evidence": False,
        "constraints_generated": False,
        "scope": "Reported path counts and up to four endpoints per port only; "
                 "reset names do not prove asynchronous-only fanout or justify exceptions",
    }


def path_detail_self_test(directory):
    directory.mkdir(exist_ok=False)
    control = "".join(
        f"; {analysis} Analysis ;\n"
        "; Unconstrained Input Ports ;\n; Input Port ; Comment ;\n"
        "; rst_n ; No input delay found ;\n"
        "; Unconstrained Output Ports ;\n; Output Port ; Comment ;\n"
        "; m_valid ; No output delay found ;\n"
        "; Unconstrained Input Port Paths ;\n; From ; To ; To Clocks ;\n"
        "; rst_n ; ram|reg0 ; clk_main ;\n"
        "; Unconstrained Output Port Paths ;\n; From ; To ; From Clocks ;\n"
        "; record_valid ; m_valid ; clk_main ;\n"
        for analysis in ("Setup", "Hold"))
    summary = {name: [1, 1] for name in (
        "Unconstrained Input Ports", "Unconstrained Output Ports",
        "Unconstrained Input Port Paths", "Unconstrained Output Port Paths")}
    path = directory / "control.rpt"
    path.write_text(control)
    ports = unconstrained_port_details(path, summary)
    observed = unconstrained_path_details(path, summary, ports)
    if observed["paths_by_port"]["Setup"]["input"]["rst_n"] != {
            "count": 1, "endpoint_samples": [
                {"endpoint": "ram|reg0", "clocks": "clk_main"}]}:
        raise RuntimeError("Reset path destination diagnosis was lost")
    rejected = {}
    for name, text in {
        "missing_path": control.replace("; rst_n ; ram|reg0 ; clk_main ;\n", "", 1),
        "extra_path": control.replace("; rst_n ; ram|reg0 ; clk_main ;\n",
                                      "; rst_n ; ram|reg0 ; clk_main ;\n" * 2, 1),
        "unknown_port": control.replace("rst_n ; ram", "other ; ram", 1),
        "wrong_header": control.replace("To Clocks", "From Clocks", 1),
        "empty_clock": control.replace("ram|reg0 ; clk_main", "ram|reg0 ;", 1),
        "missing_hold": control[:control.index("; Hold Analysis ;")],
        "duplicate_section": control + control,
    }.items():
        path = directory / (name + ".rpt")
        path.write_text(text)
        try:
            unconstrained_path_details(path, summary, ports)
        except RuntimeError as error:
            rejected[name] = str(error)
        else:
            raise RuntimeError("Fail-open unconstrained path details: " + name)
    zero_path = directory / "zero.rpt"
    zero_path.write_text("; Setup Analysis ;\n; Hold Analysis ;\n")
    zero_summary = {name: [0, 0] for name in summary}
    zero = unconstrained_path_details(
        zero_path, zero_summary, unconstrained_port_details(zero_path, zero_summary))
    combinational = directory / "port-to-port.rpt"
    combinational.write_text(control.replace(
        "; rst_n ; ram|reg0 ; clk_main ;", "; rst_n ; m_valid ; ;").replace(
        "; record_valid ; m_valid ; clk_main ;", "; rst_n ; m_valid ; ;"))
    port_to_port = unconstrained_path_details(combinational, summary, ports)
    many_path = directory / "many.rpt"
    many_path.write_text(control.replace("; rst_n ; ram|reg0 ; clk_main ;\n", "".join(
        f"; rst_n ; ram|reg{index} ; clk_main ;\n" for index in range(8))))
    many = unconstrained_path_details(
        many_path, {**summary, "Unconstrained Input Port Paths": [8, 8]}, ports)
    for analysis in ("Setup", "Hold"):
        row = many["paths_by_port"][analysis]["input"]["rst_n"]
        if row["count"] != 8 or len(row["endpoint_samples"]) != 4:
            raise RuntimeError("Path diagnostic sampling changed its full path count")
    return {"control": observed, "zero_control": zero, "bounded_samples": many,
            "unclocked_port_to_port_control": port_to_port,
            "rejections": rejected,
            "acceptance_evidence": False, "native_gate_executed": False}


def port_detail_self_test(directory):
    """Synthetic detail corruption must not conceal reported missing timing."""
    directory.mkdir(exist_ok=False)
    control = "".join(
        f"; {analysis} Analysis ;\n"
        "; Unconstrained Input Ports ;\n; Input Port ; Comment ;\n"
        "; m_ready ; No input delay found ;\n"
        "; Unconstrained Output Ports ;\n; Output Port ; Comment ;\n"
        "; m_valid ; No output delay found ;\n"
        for analysis in ("Setup", "Hold"))
    summary = {"Unconstrained Input Ports": [1, 1],
               "Unconstrained Output Ports": [1, 1]}
    path = directory / "control.rpt"
    path.write_text(control)
    observed = unconstrained_port_details(path, summary)
    for analysis in ("Setup", "Hold"):
        if (observed["ports"][analysis]["input"][0]["port"] != "m_ready"
                or observed["ports"][analysis]["output"][0]["port"] != "m_valid"):
            raise RuntimeError("Unconstrained endpoint detail control was lost")
    rejected = {}
    for name, text in {
        "missing_hold": control[:control.index("; Hold Analysis ;")],
        "missing_port": control.replace("; m_ready ; No input delay found ;\n", "", 1),
        "duplicate_port": control.replace(
            "; m_valid ; No output delay found ;\n",
            "; m_valid ; No output delay found ;\n" * 2, 1),
        "duplicate_section": control + control,
        "missing_header": control.replace("; Input Port ; Comment ;\n", "", 1),
        "empty_comment": control.replace("No input delay found", "", 1),
        "extra_column": control.replace("No input delay found ;",
                                        "No input delay found ; extra ;", 1),
    }.items():
        path = directory / (name + ".rpt")
        path.write_text(text)
        try:
            unconstrained_port_details(path, summary)
        except RuntimeError as error:
            rejected[name] = str(error)
        else:
            raise RuntimeError("Fail-open unconstrained port details: " + name)
    empty = directory / "zero.rpt"
    empty.write_text("; Setup Analysis ;\n; Hold Analysis ;\n")
    zero = unconstrained_port_details(
        empty, {name: [0, 0] for name in summary})
    zero_rejected = {}
    for name, text in {
        "empty": "",
        "missing_hold": "; Setup Analysis ;\n",
        "duplicate_setup": "; Setup Analysis ;\n" * 2 + "; Hold Analysis ;\n",
        "reversed": "; Hold Analysis ;\n; Setup Analysis ;\n",
        "missing_header": (
            "; Setup Analysis ;\n; Unconstrained Input Ports ;\n; Hold Analysis ;\n"),
        "truncated_header": (
            "; Setup Analysis ;\n; Hold Analysis ;\n; Unconstrained Output Ports ;\n"),
    }.items():
        path = directory / ("zero-" + name + ".rpt")
        path.write_text(text)
        try:
            unconstrained_port_details(path, {key: [0, 0] for key in summary})
        except RuntimeError as error:
            zero_rejected[name] = str(error)
        else:
            raise RuntimeError("Fail-open zero-count endpoint analyses: " + name)
    return {"kind": "synthetic_unconstrained_port_detail_sensitivity",
            "acceptance_evidence": False, "native_gate_executed": False,
            "control": observed, "zero_summary": zero, "rejections": rejected,
            "zero_count_rejections": zero_rejected}


def coverage_schema_issues(coverage):
    """Validate parsed evidence before treating count rows as zero issues."""
    issues = []
    for key, required, width in (
            ("unconstrained_summary_setup_hold", UNCONSTRAINED_PROPERTIES, 2),
            ("timing_check_issue_counts", TIMING_CHECKS, 1)):
        rows = coverage.get(key)
        if not isinstance(rows, dict):
            issues.append("Missing coverage summary: " + key)
            continue
        for name in required:
            if name not in rows:
                issues.append("Missing coverage summary row: " + name)
        for name, counts in rows.items():
            if (not isinstance(counts, list) or len(counts) != width
                    or any(type(count) is not int or count < 0 for count in counts)):
                issues.append("Malformed coverage counts: " + key + "/" + str(name))
    return issues


def coverage_issues(coverage):
    malformed = coverage_schema_issues(coverage)
    if malformed:
        return malformed
    issues = []
    for name, counts in coverage["unconstrained_summary_setup_hold"].items():
        if any(counts):
            issues.append(f"{name}: setup={counts[0]}, hold={counts[1]}")
    for name, counts in coverage["timing_check_issue_counts"].items():
        if any(counts):
            issues.append(f"check_timing {name}: issues={counts[0]}")
    return issues


def timing_readiness(diagnostics, observations, coverage, *,
                     endpoint_details_reconciled=False):
    """Consolidate discovery prerequisites without issuing native acceptance."""
    complete = coverage is not None and not coverage_schema_issues(coverage)
    requirements = {
        "query_execution_complete": (
            diagnostics is not None and diagnostics["query_execution_complete"]),
        "numerical_limits_met": (
            observations is not None and observations["numerical_limits_met"]),
        "coverage_reports_complete": complete,
        "coverage_has_zero_issues": (
            complete and not coverage_issues(coverage)),
        "endpoint_details_reconciled": endpoint_details_reconciled is True,
    }
    return {
        "requirements": requirements,
        "unresolved": [name for name, met in requirements.items() if not met],
        "query_prerequisites_met": all(requirements.values()),
        "coverage_issues": coverage_issues(coverage) if coverage is not None else None,
        "acceptance_evidence": False,
        "native_gate_pass_claimed": False,
        "scope": "Query prerequisites only; source identity, integration constraints "
                 "and independent native acceptance remain separate",
    }


def timing_observations(text):
    """Parse measured query values, not success tokens or runtime summaries."""
    lines = text.splitlines()

    def single(prefix):
        values = [line[len(prefix):] for line in lines if line.startswith(prefix)]
        if len(values) != 1 or not values[0]:
            raise RuntimeError("Expected exactly one nonempty " + prefix + " observation")
        return values[0]

    def number(value):
        if re.fullmatch(r"[+-]?[0-9]+(?:\.[0-9]+)?", value) is None:
            raise RuntimeError("Malformed native timing number: " + value)
        return Decimal(value)

    device = single("PROJECT_DEVICE:")
    top = single("PROJECT_TOP:")
    if device != "10AX115N2F45E1SG":
        raise RuntimeError("Unexpected project device: " + device)
    if top != "crucible_g1_top":
        raise RuntimeError("Unexpected project top-level entity: " + top)
    clock = single("CLOCK:").split(":")
    if len(clock) != 2 or not clock[0].strip():
        raise RuntimeError("Expected a single named timing clock")
    period = number(clock[1])
    registers = single("REGISTER_COUNT:")
    if re.fullmatch(r"[0-9]+", registers) is None or int(registers) == 0:
        raise RuntimeError("Expected a positive fitted register count")
    slacks = {}
    for kind in ("SETUP", "HOLD"):
        slacks[kind] = number(single(kind + "_SLACK:"))
        for endpoint in ("FROM", "TO"):
            if single(kind + "_" + endpoint + "_CLOCK:") != clock[0]:
                raise RuntimeError("Unexpected " + kind + " path endpoint clock")
    issues = []
    if not Decimal(0) < period <= Decimal(10):
        issues.append("Clock period outside required (0, 10.0] ns: " + str(period))
    for kind, slack in slacks.items():
        if slack < 0:
            issues.append(kind + " slack is negative: " + str(slack) + " ns")
    return {
        "project_device": device, "project_top": top,
        "project_identity_scope": "Queried project assignments, not loaded-image authentication",
        "clock": clock[0], "clock_period_ns": str(period),
        "register_count": int(registers),
        "setup_slack_ns": str(slacks["SETUP"]),
        "hold_slack_ns": str(slacks["HOLD"]),
        "numerical_limits_met": not issues, "issues": issues,
        "acceptance_evidence": False,
        "scope": "Observed worst setup/hold path; complete constraints still required",
    }


def timing_observation_self_test():
    """Missing or corrupt measurements cannot be replaced by success markers."""
    control = (
        "PROJECT_DEVICE:10AX115N2F45E1SG\n"
        "PROJECT_TOP:crucible_g1_top\n"
        "CLOCK:clk:10.000\nREGISTER_COUNT:123\n"
        "SETUP_SLACK:0.280\nSETUP_FROM_CLOCK:clk\nSETUP_TO_CLOCK:clk\n"
        "HOLD_SLACK:0.039\nHOLD_FROM_CLOCK:clk\nHOLD_TO_CLOCK:clk\n"
    )
    result = timing_observations(control)
    if (not result["numerical_limits_met"] or result["register_count"] != 123
            or result["project_device"] != "10AX115N2F45E1SG"
            or result["project_top"] != "crucible_g1_top"):
        raise RuntimeError("Timing observations rejected their synthetic control")
    rejected = {}
    for name, text in {
        "markers_only": "QUERY_SUCCEEDED:synchronous_paths\n",
        "missing_device": control.replace("PROJECT_DEVICE:10AX115N2F45E1SG\n", ""),
        "wrong_device": control.replace("10AX115N2F45E1SG", "10AX115N2F45E2SG"),
        "duplicate_device": control + "PROJECT_DEVICE:10AX115N2F45E1SG\n",
        "empty_device": control.replace("PROJECT_DEVICE:10AX115N2F45E1SG",
                                        "PROJECT_DEVICE:"),
        "missing_top": control.replace("PROJECT_TOP:crucible_g1_top\n", ""),
        "wrong_top": control.replace("crucible_g1_top", "unrelated_top"),
        "duplicate_top": control + "PROJECT_TOP:crucible_g1_top\n",
        "empty_top": control.replace("PROJECT_TOP:crucible_g1_top", "PROJECT_TOP:"),
        "missing_hold": control.replace("HOLD_SLACK:0.039\n", ""),
        "duplicate_setup": control + "SETUP_SLACK:0.280\n",
        "unknown_slack": control.replace("0.280", "X"),
        "nonfinite_slack": control.replace("0.280", "NaN"),
        "infinite_period": control.replace("10.000", "Infinity"),
        "empty_clock": control.replace("CLOCK:clk:10.000", "CLOCK:"),
        "extra_clock": control + "CLOCK:other:10.000\n",
        "empty_clock_name": control.replace("CLOCK:clk:10.000", "CLOCK::10.000"),
        "wrong_endpoint": control.replace("HOLD_TO_CLOCK:clk", "HOLD_TO_CLOCK:other"),
        "missing_endpoint": control.replace("SETUP_FROM_CLOCK:clk\n", ""),
        "zero_registers": control.replace("REGISTER_COUNT:123", "REGISTER_COUNT:0"),
        "fractional_registers": control.replace("REGISTER_COUNT:123", "REGISTER_COUNT:1.5"),
    }.items():
        try:
            timing_observations(text)
        except RuntimeError as error:
            rejected[name] = str(error)
        else:
            raise RuntimeError("Fail-open timing observation parser: " + name)
    limits = {}
    for name, text in {
        "slow_clock": control.replace("10.000", "10.001"),
        "zero_period": control.replace("10.000", "0"),
        "negative_period": control.replace("10.000", "-10"),
        "negative_setup": control.replace("0.280", "-0.001"),
        "negative_hold": control.replace("0.039", "-0.001"),
    }.items():
        observed = timing_observations(text)
        if observed["numerical_limits_met"] or not observed["issues"]:
            raise RuntimeError("Fail-open timing numerical limit: " + name)
        limits[name] = observed["issues"]
    boundary = timing_observations(control.replace("0.280", "0").replace("0.039", "0"))
    if not boundary["numerical_limits_met"]:
        raise RuntimeError("Zero slack must meet the frozen timing limit")
    renamed = timing_observations(control.replace("clk", "clk_main"))
    if not renamed["numerical_limits_met"] or renamed["clock"] != "clk_main":
        raise RuntimeError("SDC clock labels need not match the top-level port name")
    return {
        "kind": "synthetic_timing_observation_sensitivity",
        "acceptance_evidence": False, "native_gate_executed": False,
        "control": result, "malformed_rejections": rejected,
        "numerical_limit_rejections": limits, "zero_slack_boundary": boundary,
        "renamed_sdc_clock": renamed,
    }


def report_parser_self_test(directory):
    """Retain synthetic report corruptions, not native timing evidence."""
    directory.mkdir(exist_ok=False)
    heading = "; Summary ;\n"
    header = "; Check ; Number of Issues Found ;\n"
    body = "; no_clock ; 0 ;\n; no_input_delay ; 0 ;\n"
    following = "; Details ;\n; Port ; Reason ;\n; s_valid ; detail ;\n"
    control = heading + header + body + following
    columns = ["Check", "Number of Issues Found"]
    required = ("no_clock", "no_input_delay")
    path = directory / "control.rpt"
    path.write_text(control)
    if report_summary(path, "Summary", columns, required) != {
            "no_clock": [0], "no_input_delay": [0]}:
        raise RuntimeError("Report parser rejected its synthetic control")
    variants = {
        "missing_summary": control.replace(heading, ""),
        "duplicate_adjacent_summary": heading + control,
        "duplicate_later_summary": control + heading + header + body,
        "missing_header": control.replace(header, ""),
        "duplicate_header": control.replace(header, header + header),
        "missing_required_row": control.replace("; no_input_delay ; 0 ;\n", ""),
        "duplicate_row": control.replace(body, body + "; no_clock ; 0 ;\n"),
        "empty_property": control.replace("no_clock", ""),
        "negative_count": control.replace("; no_clock ; 0 ;", "; no_clock ; -1 ;"),
        "fractional_count": control.replace("; no_clock ; 0 ;", "; no_clock ; 0.0 ;"),
        "unknown_count": control.replace("; no_clock ; 0 ;", "; no_clock ; X ;"),
        "missing_count": control.replace("; no_clock ; 0 ;", "; no_clock ; ;"),
        "extra_column": control.replace("; no_clock ; 0 ;", "; no_clock ; 0 ; 0 ;"),
    }
    rejections = {}
    for name, text in variants.items():
        path = directory / (name + ".rpt")
        path.write_text(text)
        try:
            report_summary(path, "Summary", columns, required)
        except RuntimeError as error:
            rejections[name] = str(error)
        else:
            raise RuntimeError("Fail-open synthetic report parser: " + name)
    return {
        "kind": "synthetic_report_parser_sensitivity",
        "acceptance_evidence": False, "native_gate_executed": False,
        "control": {"no_clock": [0], "no_input_delay": [0]},
        "rejections": rejections,
    }


def coverage_report_self_test(directory):
    """Exercise complete native-summary schemas with synthetic reports."""
    directory.mkdir(exist_ok=False)
    reports = {
        "unconstrained.rpt": (
            "; Unconstrained Paths Summary ;\n; Property ; Setup ; Hold ;\n",
            {name: f"; {name} ; 0 ; 0 ;\n"
             for name in UNCONSTRAINED_PROPERTIES}),
        "timing_checks.rpt": (
            "; Summary ;\n; Check ; Number of Issues Found ;\n",
            {name: f"; {name} ; 0 ;\n" for name in TIMING_CHECKS}),
    }

    def fixture(name, changed_file=None, omitted=None, nonzero=False):
        destination = directory / name
        destination.mkdir(exist_ok=False)
        for filename, (header, rows) in reports.items():
            contents = header + "".join(
                (row.replace("; 0 ;", "; 1 ;")
                 if nonzero and filename == changed_file and key == omitted
                 else row)
                for key, row in rows.items()
                if nonzero or filename != changed_file or key != omitted)
            (destination / filename).write_text(contents)
        return destination

    control = coverage_reports(fixture("complete"))
    if coverage_issues(control) or not control["external_io_timing_constrained"]:
        raise RuntimeError("Coverage reports rejected their complete zero-count control")
    rejections = {}
    nonzero_issues = {}
    for filename, (_, rows) in reports.items():
        for index, name in enumerate(rows):
            key = filename + ":" + name
            missing = fixture(f"missing-{filename}-{index}", filename, name)
            try:
                coverage_reports(missing)
            except RuntimeError as error:
                rejections[key] = str(error)
            else:
                raise RuntimeError("Fail-open missing native summary check: " + key)
            observed = coverage_reports(fixture(
                f"nonzero-{filename}-{index}", filename, name, nonzero=True))
            issues = coverage_issues(observed)
            if len(issues) != 1 or name not in issues[0]:
                raise RuntimeError("Nonzero native summary check was lost: " + key)
            nonzero_issues[key] = issues
    return {
        "kind": "synthetic_complete_coverage_summary_sensitivity",
        "acceptance_evidence": False, "native_gate_executed": False,
        "control": control, "missing_check_rejections": rejections,
        "nonzero_check_issues": nonzero_issues,
        "port_detail_sensitivity": port_detail_self_test(directory / "port-details"),
        "path_detail_sensitivity": path_detail_self_test(directory / "path-details"),
    }


def query_diagnostics(row, text, stderr=""):
    required = ("clocks", "synchronous_paths",
                "unconstrained_report", "timing_coverage")
    lines = text.splitlines()
    successes = {
        name: (lines.count("QUERY_BEGIN:" + name) == 1
               and lines.count("QUERY_SUCCEEDED:" + name) == 1
               and lines.index("QUERY_BEGIN:" + name)
                   < lines.index("QUERY_SUCCEEDED:" + name)
               and not any(line.startswith("QUERY_FAILED:" + name + ":")
                           for line in lines))
        for name in required
    }
    expected_markers = [
        marker + name for name in required
        for marker in ("QUERY_BEGIN:", "QUERY_SUCCEEDED:")
    ] + ["DISCOVERY_QUERY_FAILURES:0"]
    observed_markers = [
        line for line in lines
        if line.lstrip().startswith(("QUERY_", "DISCOVERY_QUERY_FAILURES:"))
    ]
    ordered = observed_markers == expected_markers
    netlist_markers = [
        line for line in lines if line.lstrip().startswith("NETLIST_MODE:")
    ]
    post_fit = (
        netlist_markers == ["NETLIST_MODE:post_fit"]
        and "QUERY_BEGIN:clocks" in lines
        and lines.index("NETLIST_MODE:post_fit") < lines.index("QUERY_BEGIN:clocks")
    )
    rejected_diagnostics = [
        {"stream": stream, "line": line}
        for stream, content in (("stdout", text), ("stderr", stderr))
        for line in content.splitlines()
        if (line.lstrip().startswith("QUERY_FAILED:")
            or re.match(r"\s*Error(?:\s|\(|:|$)", line, re.IGNORECASE)
            or re.match(r"\s*Warning\s*\(10268\)", line, re.IGNORECASE))
    ]
    complete = (row["exit_code"] == 0 and not row["timed_out"]
                and all(successes.values())
                and ordered
                and post_fit
                and not rejected_diagnostics
                and lines.count("DISCOVERY_QUERY_FAILURES:0") == 1
                and sum(line.startswith("DISCOVERY_QUERY_FAILURES:")
                        for line in lines) == 1)
    return {
        "successful_queries": successes,
        "query_lifecycle_ordered": ordered,
        "post_fit_netlist_identified": post_fit,
        "observed_query_markers": observed_markers,
        "tool_exit_code": row["exit_code"],
        "timed_out": row["timed_out"],
        "rejected_diagnostics": rejected_diagnostics,
        "query_execution_complete": complete,
        "acceptance_evidence": False,
        "scope": "Existing post-fit database; query success is not timing acceptance",
    }


def source_association_issues(association, product_names):
    issues = []
    for name in sorted(set(association) | set(product_names)):
        row = association.get(name)
        if row is None:
            issues.append("Product RTL absent from fitted source inventory: " + name)
        elif (row["product_sha256"] is None
              or row["staged_sha256"] != row["product_sha256"]):
            issues.append("Fitted RTL does not match product source: " + name)
        if row is not None and (
                row.get("inventoried_product_sha256") is None
                or row["product_sha256"] != row["inventoried_product_sha256"]):
            issues.append("Product RTL does not match initial source inventory: " + name)
    return issues


def local_binding_issues(binding):
    """Local inventory completeness only; never authenticate a loaded image."""
    issues = []
    if not binding["exists"]:
        issues.append("Missing project FPGA configuration: fpga/board_hil.json")
    if not any(Path(image["path"]).suffix in (".sof", ".rbf", ".rpd")
               for image in binding["images"]):
        issues.append("No project-local FPGA image; image/source binding unresolved")
    for image in binding["images"]:
        if image["bytes"] == 0:
            issues.append("Empty FPGA image or manifest: " + image["path"])
    return issues


def bridge_discovery_diagnostics(row, stdout, stderr):
    """Validate read-only inventory execution without claiming board access."""
    lines = stdout.splitlines()
    completion = "READ_ONLY_DISCOVERY_COMPLETE"
    directories = [line.partition(":")[2] for line in lines
                   if line.startswith("TOOLS_DIRECTORY:")]
    files = [line.partition(":")[2] for line in lines
             if line.startswith("TOOL_FILE:")]
    issues = []
    if row["exit_code"] != 0 or row["timed_out"]:
        issues.append("Bridge discovery command did not complete successfully")
    if lines.count(completion) != 1:
        issues.append("Expected exactly one bridge discovery completion marker")
    elif any(line.strip() for line in lines[lines.index(completion) + 1:]):
        issues.append("Unexpected output after bridge discovery completion")
    if not directories or any(not name.strip() for name in directories):
        issues.append("Missing nonempty board-tools directory inventory")
    if not files or any(not name.strip() for name in files):
        issues.append("Missing nonempty board-tools file inventory")
    if stderr.strip():
        issues.append("Bridge discovery emitted stderr; inspect retained raw stream")
    return {
        "discovery_execution_complete": not issues,
        "issues": issues, "tool_directories": directories,
        "tool_file_count": len(files), "acceptance_evidence": False,
        "graphics_transport_verified": False, "loaded_image_verified": False,
        "physical_board_runs": 0,
    }


def diagnostic_self_test():
    banner = ("Quartus Prime TimeQuest Timing Analyzer\n"
              "Version 17.1.0 Build 590 10/25/2017 SJ Standard Edition\n")
    version_control = quartus_version(banner)
    version_rejections = {}
    for name, text in {
        "missing": "",
        "wrong_release": banner.replace("17.1.0", "18.1.0"),
        "minor_prefix": banner.replace("17.1.0", "17.10.0"),
        "missing_build": banner.replace("Build 590 ", ""),
        "wrong_tool": banner.replace("TimeQuest Timing Analyzer", "Assembler"),
        "duplicate_version": banner + banner.splitlines()[1] + "\n",
        "conflicting_versions": banner + "Version 18.1.0 Build 625 Standard Edition\n",
    }.items():
        try:
            quartus_version(text)
        except RuntimeError as error:
            version_rejections[name] = str(error)
        else:
            raise RuntimeError("Fail-open native tool version fixture: " + name)
    """Synthetic fail-closed controls, never native execution evidence."""
    row = {"exit_code": 0, "timed_out": False}
    lines = [line for name in ("clocks", "synchronous_paths",
                              "unconstrained_report", "timing_coverage")
             for line in ("QUERY_BEGIN:" + name, "QUERY_SUCCEEDED:" + name)]
    text = "\n".join([
        "NETLIST_MODE:post_fit", *lines, "DISCOVERY_QUERY_FAILURES:0",
    ]) + "\n"
    if not query_diagnostics(row, text)["query_execution_complete"]:
        raise RuntimeError("Query diagnostic rejected its complete synthetic control")
    variants = {
        "nonzero_exit": ({**row, "exit_code": 1}, text),
        "timeout_with_markers": ({**row, "timed_out": True}, text),
        "missing_begin": (row, text.replace("QUERY_BEGIN:clocks\n", "")),
        "missing_success": (row, text.replace("QUERY_SUCCEEDED:clocks\n", "")),
        "duplicate_success": (row, text + "QUERY_SUCCEEDED:clocks\n"),
        "contradictory_failure": (row, text + "QUERY_FAILED:clocks:failure\n"),
        "missing_final_marker": (row, text.replace("DISCOVERY_QUERY_FAILURES:0\n", "")),
        "duplicate_final_marker": (row, text + "DISCOVERY_QUERY_FAILURES:0\n"),
        "conflicting_final_marker": (row, text + "DISCOVERY_QUERY_FAILURES:1\n"),
        "success_before_begin": (row, text.replace(
            "QUERY_BEGIN:clocks\nQUERY_SUCCEEDED:clocks\n",
            "QUERY_SUCCEEDED:clocks\nQUERY_BEGIN:clocks\n")),
        "interleaved_queries": (row, text.replace(
            "QUERY_SUCCEEDED:clocks\nQUERY_BEGIN:synchronous_paths\n",
            "QUERY_BEGIN:synchronous_paths\nQUERY_SUCCEEDED:clocks\n")),
        "reordered_queries": (row, "\n".join(
            [*lines[2:4], *lines[:2], *lines[4:], "DISCOVERY_QUERY_FAILURES:0"]) + "\n"),
        "early_final_marker": (row, "DISCOVERY_QUERY_FAILURES:0\n"
                               + "\n".join(lines) + "\n"),
        "unknown_query": (row, text.replace(
            "DISCOVERY_QUERY_FAILURES:0",
            "QUERY_BEGIN:other\nQUERY_SUCCEEDED:other\nDISCOVERY_QUERY_FAILURES:0")),
        "duplicate_begin": (row, text.replace(
            "QUERY_BEGIN:clocks\n", "QUERY_BEGIN:clocks\n" * 2)),
        "missing_netlist_mode": (row, text.replace("NETLIST_MODE:post_fit\n", "")),
        "pre_fit_netlist": (row, text.replace("post_fit", "pre_fit")),
        "duplicate_netlist_mode": (row, "NETLIST_MODE:post_fit\n" + text),
        "conflicting_netlist_mode": (row, "NETLIST_MODE:pre_fit\n" + text),
        "late_netlist_mode": (row, text.replace("NETLIST_MODE:post_fit\n", "")
                              + "NETLIST_MODE:post_fit\n"),
    }
    for name, (status, transcript) in variants.items():
        if query_diagnostics(status, transcript)["query_execution_complete"]:
            raise RuntimeError("Fail-open synthetic query diagnostic: " + name)
    stream_variants = {
        "stderr_query_failure": ("", "QUERY_FAILED:clocks:failure\n"),
        "unrecognized_query_failure": ("QUERY_FAILED:other:failure\n", ""),
        "stdout_quartus_error": ("Error (272006): no timing netlist\n", ""),
        "stderr_quartus_error": ("", "Error (272006): no timing netlist\n"),
        "stderr_tcl_error": ("", "error: query failed\n"),
        "stdout_reset_warning": ("Warning (10268): reset not asynchronous\n", ""),
        "stderr_reset_warning": ("", "Warning (10268): reset not asynchronous\n"),
    }
    for name, (extra_stdout, stderr) in stream_variants.items():
        diagnostics = query_diagnostics(row, text + extra_stdout, stderr)
        if (diagnostics["query_execution_complete"]
                or not diagnostics["rejected_diagnostics"]):
            raise RuntimeError("Fail-open synthetic tool-stream diagnostic: " + name)
    if not query_diagnostics(
            row, text, "Warning (292006): ignored license server\n"
    )["query_execution_complete"]:
        raise RuntimeError("Unrelated warning changed query-execution classification")
    control = {"g1.sv": {"staged_sha256": "a", "product_sha256": "a",
                         "inventoried_product_sha256": "a"}}
    if source_association_issues(control, ["g1.sv"]):
        raise RuntimeError("Source association rejected its matching control")
    associations = {
        "changed_product": ({"g1.sv": {
            "staged_sha256": "a", "product_sha256": "b",
            "inventoried_product_sha256": "a"}}, ["g1.sv"]),
        "missing_product": ({"g1.sv": {
            "staged_sha256": "a", "product_sha256": None,
            "inventoried_product_sha256": "a"}}, []),
        "missing_fitted_source": (control, ["g1.sv", "new.sv"]),
        "changed_after_inventory": ({"g1.sv": {
            "staged_sha256": "b", "product_sha256": "b",
            "inventoried_product_sha256": "a"}}, ["g1.sv"]),
        "missing_initial_inventory": ({"g1.sv": {
            "staged_sha256": "a", "product_sha256": "a"}}, ["g1.sv"]),
        "null_initial_inventory": ({"g1.sv": {
            "staged_sha256": "a", "product_sha256": "a",
            "inventoried_product_sha256": None}}, ["g1.sv"]),
    }
    for name, (association, product_names) in associations.items():
        if not source_association_issues(association, product_names):
            raise RuntimeError("Fail-open synthetic source association: " + name)
    coverage = {
        "unconstrained_summary_setup_hold": {
            name: [0, 0] for name in UNCONSTRAINED_PROPERTIES},
        "timing_check_issue_counts": {name: [0] for name in TIMING_CHECKS},
    }
    if coverage_issues(coverage):
        raise RuntimeError("Coverage diagnostic rejected its zero-count control")
    coverage["unconstrained_summary_setup_hold"]["Unconstrained Input Port Paths"] = [
        106367, 106367]
    coverage["timing_check_issue_counts"]["no_clock"] = [1]
    issues = coverage_issues(coverage)
    if len(issues) != 2 or "106367" not in issues[0] or "no_clock" not in issues[1]:
        raise RuntimeError("Coverage diagnostic lost nonzero counts")
    coverage["unconstrained_summary_setup_hold"]["Unconstrained Output Port Paths"] = [
        309, 309]
    query = {"query_execution_complete": True}
    measured = {"numerical_limits_met": True}
    readiness = {
        "positive_slack_incomplete_coverage": timing_readiness(query, measured, coverage),
        "missing_reports": timing_readiness(query, measured, None),
        "missing_measurements": timing_readiness(query, None, coverage),
        "failed_query": timing_readiness(
            {"query_execution_complete": False}, measured, coverage),
    }
    for name, result in readiness.items():
        if result["query_prerequisites_met"] or not result["unresolved"]:
            raise RuntimeError("Fail-open timing prerequisite consolidation: " + name)
    if readiness["positive_slack_incomplete_coverage"]["requirements"] != {
            "query_execution_complete": True, "numerical_limits_met": True,
            "coverage_reports_complete": True, "coverage_has_zero_issues": False,
            "endpoint_details_reconciled": False}:
        raise RuntimeError("Positive slack concealed incomplete timing coverage")
    clear_coverage = {
        "unconstrained_summary_setup_hold": {
            name: [0, 0] for name in UNCONSTRAINED_PROPERTIES},
        "timing_check_issue_counts": {name: [0] for name in TIMING_CHECKS},
    }
    incomplete_readiness = {}
    for key, rows in clear_coverage.items():
        for omitted in rows:
            incomplete = {name: dict(values)
                          for name, values in clear_coverage.items()}
            del incomplete[key][omitted]
            result = timing_readiness(query, measured, incomplete)
            if (result["query_prerequisites_met"]
                    or result["requirements"]["coverage_reports_complete"]
                    or result["requirements"]["coverage_has_zero_issues"]):
                raise RuntimeError("Missing summary row concealed by zero counts: " + omitted)
            incomplete_readiness[omitted] = result
    empty_readiness = timing_readiness(query, measured, {
        "unconstrained_summary_setup_hold": {}, "timing_check_issue_counts": {},
    })
    if empty_readiness["query_prerequisites_met"]:
        raise RuntimeError("Empty summary dictionaries accepted as complete coverage")
    incomplete_readiness["empty_summaries"] = empty_readiness
    malformed_readiness = {}
    for key, rows in clear_coverage.items():
        for name, counts in rows.items():
            for defect, malformed in {
                "empty": [], "short_or_extra": [0] if len(counts) == 2 else [0, 0],
                "negative": [-1] * len(counts), "boolean": [False] * len(counts),
                "string": ["0"] * len(counts), "float": [0.0] * len(counts),
                "scalar": 0,
            }.items():
                corrupt = {table: dict(values)
                           for table, values in clear_coverage.items()}
                corrupt[key][name] = malformed
                result = timing_readiness(query, measured, corrupt)
                if (result["query_prerequisites_met"]
                        or result["requirements"]["coverage_reports_complete"]
                        or result["requirements"]["coverage_has_zero_issues"]
                        or not result["coverage_issues"]):
                    raise RuntimeError("Malformed summary counts accepted: " + name)
                malformed_readiness[key + "/" + name + "/" + defect] = result
    for key in clear_coverage:
        for malformed in (None, [], 0):
            corrupt = {**clear_coverage, key: malformed}
            result = timing_readiness(query, measured, corrupt)
            if result["query_prerequisites_met"] or not result["coverage_issues"]:
                raise RuntimeError("Malformed coverage summary accepted: " + key)
    detail_readiness = {}
    for name, reconciled in (("missing_details", False), ("failed_details", None),
                             ("nonboolean_details", 1)):
        result = timing_readiness(
            query, measured, clear_coverage,
            endpoint_details_reconciled=reconciled)
        if (result["query_prerequisites_met"]
                or result["unresolved"] != ["endpoint_details_reconciled"]):
            raise RuntimeError("Failed endpoint reconciliation concealed: " + name)
        detail_readiness[name] = result
    control_readiness = timing_readiness(
        query, measured, clear_coverage, endpoint_details_reconciled=True)
    if (not control_readiness["query_prerequisites_met"]
            or control_readiness["native_gate_pass_claimed"]
            or control_readiness["acceptance_evidence"]):
        raise RuntimeError("Query prerequisites were confused with native acceptance")
    unexecuted_readiness = timing_readiness(None, None, None)
    if (unexecuted_readiness["query_prerequisites_met"]
            or any(unexecuted_readiness["requirements"].values())
            or len(unexecuted_readiness["unresolved"]) != 5):
        raise RuntimeError("An unexecuted query concealed missing timing prerequisites")
    missing_query = timing_readiness(
        None, measured, clear_coverage, endpoint_details_reconciled=True)
    if missing_query["unresolved"] != ["query_execution_complete"]:
        raise RuntimeError("Zero coverage counts concealed an unexecuted query")
    binding = {
        "exists": True,
        "images": [{"path": "fpga/example.sof", "bytes": 1}],
    }
    if local_binding_issues(binding):
        raise RuntimeError("Local inventory rejected its populated synthetic control")
    bindings = {
        "missing_configuration": {**binding, "exists": False},
        "missing_image": {**binding, "images": []},
        "manifest_without_image": {**binding, "images": [
            {"path": "fpga/example-manifest.json", "bytes": 1}]},
        "empty_image": {**binding, "images": [
            {"path": "fpga/example.sof", "bytes": 0}]},
    }
    for name, value in bindings.items():
        if not local_binding_issues(value):
            raise RuntimeError("Fail-open synthetic local image inventory: " + name)
    inventory = ("TOOLS_DIRECTORY:synthetic-tools\nTOOL_FILE:example.exe|1|date\n"
                 "READ_ONLY_DISCOVERY_COMPLETE\n")
    if not bridge_discovery_diagnostics(row, inventory, "")[
            "discovery_execution_complete"]:
        raise RuntimeError("Bridge diagnostic rejected its synthetic inventory")
    bridge_variants = {
        "empty_exit_zero": (row, "", ""),
        "marker_only": (row, "READ_ONLY_DISCOVERY_COMPLETE\n", ""),
        "missing_marker": (row, inventory.replace("READ_ONLY_DISCOVERY_COMPLETE\n", ""), ""),
        "duplicate_marker": (row, inventory + "READ_ONLY_DISCOVERY_COMPLETE\n", ""),
        "trailing_failure": (row, inventory + "remote execution failed\n", ""),
        "empty_directory": (row, inventory.replace("synthetic-tools", ""), ""),
        "empty_files": (row, inventory.replace("TOOL_FILE:example.exe|1|date\n", ""), ""),
        "stderr_failure": (row, inventory, "Remote command failed\n"),
        "nonzero_exit": ({**row, "exit_code": 1}, inventory, ""),
        "timeout": ({**row, "timed_out": True}, inventory, ""),
    }
    for name, (status, stdout, stderr) in bridge_variants.items():
        if bridge_discovery_diagnostics(status, stdout, stderr)[
                "discovery_execution_complete"]:
            raise RuntimeError("Fail-open synthetic bridge discovery: " + name)
    return {
        "kind": "synthetic_native_prerequisite_diagnostic_sensitivity",
        "acceptance_evidence": False, "native_gate_executed": False,
        "quartus_version_control": version_control,
        "quartus_version_rejections": version_rejections,
        "query_rejections": sorted(variants),
        "tool_stream_rejections": sorted(stream_variants),
        "source_association_rejections": sorted(associations),
        "nonzero_coverage_issues": issues,
        "timing_readiness_controls": {
            "clear_query_prerequisites": control_readiness,
            "unexecuted_query": unexecuted_readiness,
            "measurements_without_query": missing_query, **readiness},
        "incomplete_summary_rejections": incomplete_readiness,
        "malformed_count_rejections": malformed_readiness,
        "endpoint_reconciliation_rejections": detail_readiness,
        "local_binding_rejections": sorted(bindings),
        "bridge_discovery_rejections": sorted(bridge_variants),
    }


def copy_fit(discovery, fit, revision):
    """Only copy the existing fitted database; all tool writes stay in evidence."""
    destination = discovery.output / "fit"
    destination.mkdir()
    records = {}
    for name in (revision + ".qpf", revision + ".qsf", "timing.sdc",
                 "db", "incremental_db", "rtl_staged"):
        source = fit / name
        if not source.exists():
            if name == "incremental_db":
                continue
            raise RuntimeError("Missing existing-fit prerequisite: " + relative(source))
        paths = sorted(source.rglob("*")) if source.is_dir() else [source]
        for path in paths:
            if path.is_symlink():
                raise RuntimeError("Refusing fit symlink: " + relative(path))
            if path.is_file():
                target = destination / path.relative_to(fit)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                records[relative(path)] = {
                    "sha256": digest(path), "copy": relative(target),
                    "copy_sha256": digest(target),
                }
        save(discovery.output / "fit-inputs.json", records)
    save(discovery.output / "fit-inputs.json", records)
    # The retained native fit uses absolute staged-RTL assignments. Relocate
    # only the disposable QSF; never read the original product via those paths.
    qsf = destination / (revision + ".qsf")
    text = qsf.read_text()
    def relocate(match):
        name = Path(match.group(1).strip().strip('"')).name
        target = destination / "rtl_staged" / name
        if not target.is_file():
            raise RuntimeError("Missing staged RTL assignment: " + name)
        return "set_global_assignment -name SYSTEMVERILOG_FILE rtl_staged/" + name
    qsf.write_text(re.sub(
        r"(?m)^set_global_assignment -name SYSTEMVERILOG_FILE (.+)$", relocate, text))
    association = {}
    for path in sorted((destination / "rtl_staged").glob("*.sv")):
        product = ROOT / "rtl" / path.name
        association[path.name] = {
            "staged_sha256": digest(path),
            "product_sha256": digest(product) if product.is_file() else None,
            "inventoried_product_sha256": discovery.receipt["source_sha256"].get(
                "rtl/" + path.name),
        }
    save(discovery.output / "fit-source-association.json", association)
    for issue in source_association_issues(
            association, [Path(name).name
                          for name in discovery.receipt["source_sha256"]
                          if name.startswith("rtl/") and name.endswith(".sv")]):
        discovery.issue(issue)
    return {"copy": relative(destination), "inputs": relative(
        discovery.output / "fit-inputs.json"), "staged_sources": association}


def inspect_local_bridge(discovery, bridge):
    inventory = {
        "bridge_directory": str(bridge), "files": {},
        "transport_command_executed": False, "acceptance_evidence": False,
    }
    missing = []
    oversized = []
    for name in ("run_remote.py", "agent_heartbeat.json"):
        path = bridge / name
        present = path.is_file()
        size = path.stat().st_size if present else None
        inventory["files"][name] = {
            "path": str(path), "is_file": present, "bytes": size,
        }
        if not present:
            missing.append(str(path))
        elif size > 1024 * 1024:
            oversized.append(str(path))
    save(discovery.output / "supported-bridge-inventory.json", inventory)
    if missing or oversized:
        issues = (["Missing supported bridge prerequisite: " + name for name in missing]
                  + ["Bridge interface file exceeds 1 MiB: " + name
                     for name in oversized])
        raise RuntimeError("; ".join(issues))
    records = {}
    for name in ("run_remote.py", "agent_heartbeat.json"):
        path = bridge / name
        data = path.read_bytes()
        if len(data) > 1024 * 1024:
            raise RuntimeError("Bridge interface file exceeds 1 MiB: " + str(path))
        target = discovery.output / name
        target.write_bytes(data)
        records[name] = {"path": str(path), "sha256": digest(target),
                         "snapshot": relative(target)}
    return records


def local_binding(discovery):
    """Inspect only project-owned FPGA configuration and named image metadata."""
    config = ROOT / "fpga" / "board_hil.json"
    result = {"configuration": "fpga/board_hil.json", "exists": config.is_file(),
              "transport_command_executed": False, "images": []}
    if config.is_file():
        value = json.loads(config.read_text())
        if not isinstance(value, dict):
            raise ValueError("FPGA configuration must be a JSON object")
        # Do not execute configuration-provided build/flash or test commands.
        result["remote_test_cmd"] = value.get("remote_test_cmd")
        result["configuration_sha256"] = digest(config)
    for extension in ("*.sof", "*.rbf", "*.rpd", "*manifest*.json"):
        for path in sorted((ROOT / "fpga").glob(extension)):
            result["images"].append({
                "path": relative(path), "sha256": digest(path),
                "bytes": path.stat().st_size,
            })
    result["loaded_image_verified"] = False
    result["source_image_association_verified"] = False
    result["issues"] = local_binding_issues(result)
    save(discovery.output / "local-bitstream-binding.json", result)
    for issue in result["issues"]:
        discovery.issue(issue)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-dir", required=True)
    parser.add_argument("--revision", default="top")
    parser.add_argument("--bridge-dir", type=Path, default=Path(
        os.environ.get("VULCAN_BRIDGE_DIR", str(Path.home() / "netsys17_bridge"))))
    args = parser.parse_args()
    output = ROOT / "evidence/native-prerequisites" / ("run-" + uuid.uuid4().hex)
    output.mkdir(parents=True, exist_ok=False)
    discovery = Discovery(output, ["python3", "tests/native_prerequisites.py",
                                   *sys.argv[1:]])
    try:
        save(output / "diagnostic-sensitivity.json", diagnostic_self_test())
        save(output / "timing-observation-sensitivity.json",
             timing_observation_self_test())
        save(output / "report-parser-sensitivity.json",
             report_parser_self_test(output / "report-parser-fixtures"))
        save(output / "coverage-report-sensitivity.json",
             coverage_report_self_test(output / "coverage-report-fixtures"))
        discovery.operation("product-source-inventory", discovery.inventory)
        quartus_identity = None
        for name, argv in (
                ("python", ["python3", "--version"]),
                ("vulcan", ["vulcan", "--version"]),
                ("quartus_sta", ["quartus_sta", "--version"])):
            row = discovery.capture("version-" + name, argv)
            discovery.receipt["tool_versions"][name] = {
                key: row[key] for key in ("stdout", "stderr", "exit_code")}
            if name == "quartus_sta" and row["exit_code"] == 0 and not row["timed_out"]:
                quartus_identity = discovery.operation(
                    "required-quartus-release",
                    lambda: quartus_version((ROOT / row["stdout"]).read_text()))
                discovery.receipt["tool_versions"][name]["identity"] = quartus_identity
        for gate in ("quartus-sta", "board-hil"):
            discovery.capture("help-" + gate,
                              ["vulcan", "hardware", "fpga", gate, "--help"])
        def prepare_fit():
            return copy_fit(discovery, project_path(args.fit_dir), args.revision)
        # Validate before forming any Tcl command or fit filename.
        tcl = sta_tcl(args.revision)
        fit_result = (discovery.operation("copy-existing-fit", prepare_fit)
                      if quartus_identity is not None else None)
        diagnostics = None
        observations = None
        coverage = None
        port_details = None
        if fit_result is not None:
            path = output / "fit" / "prerequisites.tcl"
            path.write_text(tcl)
            row = discovery.capture("existing-fit-query",
                                    ["quartus_sta", "-t", path.name], cwd=path.parent)
            text = (ROOT / row["stdout"]).read_text()
            stderr = (ROOT / row["stderr"]).read_text()
            diagnostics = query_diagnostics(row, text, stderr)
            save(output / "query-diagnostics.json", diagnostics)
            if not diagnostics["query_execution_complete"]:
                discovery.issue("Incomplete successful TimeQuest query diagnostics")
            else:
                def retain_timing_observations():
                    observed = timing_observations(text)
                    save(output / "timing-observations.json", observed)
                    for issue in observed["issues"]:
                        discovery.issue("Unresolved numerical timing: " + issue)
                    return observed
                observations = discovery.operation("native-timing-observations",
                                                   retain_timing_observations)
                def retain_coverage():
                    coverage = coverage_reports(path.parent)
                    save(output / "coverage-diagnostics.json", coverage)
                    for issue in coverage_issues(coverage):
                        discovery.issue("Unresolved timing coverage: " + issue)
                    return coverage
                coverage = discovery.operation("native-coverage-reports", retain_coverage)
                if coverage is not None:
                    def retain_port_details():
                        details = unconstrained_port_details(
                            path.parent / "unconstrained.rpt",
                            coverage["unconstrained_summary_setup_hold"])
                        save(output / "unconstrained-port-details.json", details)
                        paths = unconstrained_path_details(
                            path.parent / "unconstrained.rpt",
                            coverage["unconstrained_summary_setup_hold"], details)
                        save(output / "unconstrained-path-details.json", paths)
                        return details
                    port_details = discovery.operation(
                        "native-unconstrained-port-details", retain_port_details)
        save(output / "timing-readiness.json",
             timing_readiness(
                 diagnostics, observations, coverage,
                 endpoint_details_reconciled=port_details is not None))
        discovery.operation("local-bitstream-source-binding",
                            lambda: local_binding(discovery))
        bridge = args.bridge_dir.expanduser().resolve()
        interface = discovery.operation(
            "supported-bridge-interface", lambda: inspect_local_bridge(discovery, bridge))
        if interface is not None:
            help_row = discovery.capture(
                "bridge-help", ["python3", str(bridge / "run_remote.py"), "--help"])
            if help_row["exit_code"] == 0 and not help_row["timed_out"]:
                (output / "remote-discovery.ps1").write_text(REMOTE_DISCOVERY)
                row = discovery.capture("bridge-read-only-discovery", [
                    "python3", str(bridge / "run_remote.py"), "--timeout", "300",
                    REMOTE_DISCOVERY], timeout=360)
                diagnostics = bridge_discovery_diagnostics(
                    row, (ROOT / row["stdout"]).read_text(),
                    (ROOT / row["stderr"]).read_text())
                save(output / "bridge-discovery-diagnostics.json", diagnostics)
                for issue in diagnostics["issues"]:
                    discovery.issue(issue)
        discovery.receipt["unresolved_acceptance"] = [
            "Raw TimeQuest coverage and synchronous-path reports require independent review",
            "Bridge discovery is not a graphics transport implementation or board test",
            "Readable image/source metadata is not proof of the currently loaded image",
            "Three consecutive exact deterministic physical graphics passes remain mandatory",
        ]
        discovery.receipt["status"] = (
            "discovery_incomplete" if discovery.receipt["issues"]
            else "discovery_retained_requires_independent_review")
        discovery.receipt["exit_code"] = int(bool(discovery.receipt["issues"]))
    except (OSError, ValueError, RuntimeError) as error:
        discovery.issue(f"{type(error).__name__}: {error}")
        discovery.receipt["status"] = "failed"
        discovery.receipt["exit_code"] = 1
    finally:
        discovery.receipt["end"] = time.time()
        discovery.persist()
        print(relative(output / "receipt.json"), flush=True)
    return discovery.receipt["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
