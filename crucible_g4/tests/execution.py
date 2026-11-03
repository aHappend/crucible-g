"""Fresh source-bound execution receipts and portable simulation compilation."""

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


def utc():
    return datetime.now(timezone.utc).isoformat()


def source_files(root):
    return sorted([*root.glob("rtl/*.sv"), *root.glob("design/*.md"),
                   *root.glob("tests/*"), *root.glob("crucible_g3_reference/rtl/*.sv")])


def hashes(root):
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in source_files(root) if path.is_file()}


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


class Run:
    def __init__(self, root, suite, preparation=False, repair_of=None):
        self.root = Path(root).resolve()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = self.root / "evidence" / ("preparation" if preparation else "")
        self.folder = base / f"{suite}-{stamp}-{uuid.uuid4().hex[:8]}"
        self.folder.mkdir(parents=True, exist_ok=False)
        self.receipt = {
            "suite": suite, "start": utc(), "source_hashes": hashes(self.root),
            "commands": [], "comparisons": {}, "coverage": {}, "status": "running",
            "argv": ["python3", Path(sys.argv[0]).resolve().relative_to(self.root).as_posix(),
                     *sys.argv[1:]],
            "cwd": ".",
        }
        if repair_of:
            self.receipt["repair_of"] = repair_of
        self.save()

    def relative(self, path):
        return Path(path).resolve().relative_to(self.root).as_posix()

    def save(self):
        dump(self.folder / "receipt.json", self.receipt)

    def execute(self, argv, name, cwd=None, expect_exit=0):
        """No private timeout policy: shared runtime owns execution limits."""
        cwd = Path(cwd or self.root)
        stdout = self.folder / f"{name}.stdout.txt"
        stderr = self.folder / f"{name}.stderr.txt"
        item = {"argv": [str(value) for value in argv], "cwd": self.relative(cwd),
                "start": utc(), "timeout_s": None, "timed_out": False,
                "stdout": self.relative(stdout), "stderr": self.relative(stderr)}
        self.receipt["commands"].append(item)
        self.save()
        try:
            with stdout.open("w") as out, stderr.open("w") as err:
                child = subprocess.Popen(item["argv"], cwd=cwd, stdout=out, stderr=err)
                while child.poll() is None:
                    try:
                        child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        print(f"PROGRESS {name}: tool execution remains active", flush=True)
                item["exit"] = child.returncode
                item["settled"] = True
        except OSError as error:
            item["launch_error"] = str(error)
            item["exit"] = None
            item["settled"] = True
            raise
        finally:
            item["end"] = utc()
            self.save()
        if expect_exit is not None and item["exit"] != expect_exit:
            raise RuntimeError(f"{name} exited {item['exit']}; see {item['stdout']} and {item['stderr']}")
        return stdout.read_text(), stderr.read_text(), item["exit"]

    def versions(self, tools):
        for tool in tools:
            if not shutil.which(tool):
                raise RuntimeError(f"required tool unavailable: {tool}")
            args = {"iverilog": ["-V"], "vvp": ["-V"], "verilator": ["--version"],
                    "yosys": ["-V"], "python3": ["--version"]}[tool]
            out, err, _ = self.execute([tool, *args], f"version-{tool}")
            self.receipt.setdefault("tool_versions", {})[tool] = (out + err).strip()
        self.save()

    def finish(self, error=None):
        self.receipt["end"] = utc()
        self.receipt["status"] = "failed" if error else "passed"
        if error:
            self.receipt["error"] = f"{type(error).__name__}: {error}"
        self.save()


def write_workload(run, workload, stem):
    commands = run.folder / f"{stem}.commands.txt"
    expected = run.folder / f"{stem}.expected.txt"
    manifest = []
    with commands.open("w") as cf, expected.open("w") as ef:
        cf.write(f"{len(workload.transactions)}\n")
        for transaction in workload.transactions:
            cf.write(f"{len(transaction.command)} {transaction.bound} {transaction.gap} {transaction.stall}\n")
            cf.write(" ".join(f"{value & 0xFFFFFFFF:08x}" for value in transaction.command) + "\n")
            ef.write(f"{sum(len(rec) for rec, _ in transaction.records)}\n")
            for rec, terminal in transaction.records:
                for index, value in enumerate(rec):
                    ef.write(f"{value & 0xFFFFFFFF:08x} {int(terminal and index == len(rec) - 1)}\n")
            manifest.append({"tag": transaction.command[0], "opcode": transaction.command[2],
                             "words": sum(len(rec) for rec, _ in transaction.records),
                             "coverage": transaction.coverage})
    dump(run.folder / f"{stem}.manifest.json", manifest)
    return commands, expected


def compile_top(run, parameters, simulator, rtl=None, stem="top"):
    rtl = sorted((rtl or run.root / "rtl").glob("*.sv"))
    names = ("P_WIDTH", "P_HEIGHT", "P_TILE", "P_NODES", "P_SPLATS", "P_STACK")
    defines = [f"-D{name}={value}" for name, value in zip(names, parameters)]
    tb = run.relative(run.root / "tests/top_tb.sv")
    sources = [run.relative(path) for path in rtl]
    if simulator == "iverilog":
        binary = run.folder / f"{stem}.vvp"
        run.execute(["iverilog", "-g2012", "-Wall", "-s", "top_tb", *defines,
                     "-o", run.relative(binary), tb, *sources], f"{stem}-compile")
        return ["vvp", run.relative(binary)]
    obj = run.folder / f"{stem}-obj-{uuid.uuid4().hex[:8]}"
    binary = run.folder / f"{stem}.bin"
    run.execute(["verilator", "--binary", "--timing", "--top-module", "top_tb",
                 "-Wno-fatal", "-j", "2", "--Mdir", run.relative(obj),
                 "-o", f"../{binary.name}", *defines, tb, *sources], f"{stem}-compile")
    # Keep the executable and exact logs, not disposable compiler intermediates.
    shutil.rmtree(obj)
    return [run.relative(binary)]


def simulate_top(run, executable, workload, stem, expect_mismatch=False):
    commands, expected = write_workload(run, workload, stem)
    out, err, exit_code = run.execute([*executable, f"+commands={run.relative(commands)}",
                                      f"+expected={run.relative(expected)}"],
                                     stem, expect_exit=None)
    if expect_mismatch:
        if exit_code == 0 or not any(marker in out + err for marker in
                                     ("NUMERICAL_MISMATCH", "STALL_MISMATCH")):
            raise AssertionError(f"{stem}: functional mutation mismatch not observed")
        return
    if exit_code != 0:
        raise RuntimeError(f"{stem}: simulation exited {exit_code}; see {run.relative(run.folder / (stem + '.stdout.txt'))}")
    rows = re.findall(r"^TRANSACTION (\d+) WORDS (\d+) CYCLES (\d+)$", out, re.M)
    if len(rows) != len(workload.transactions):
        raise AssertionError(f"{stem}: missing or malformed transaction trace")
    coverage = Counter()
    words = 0
    for index, (row, transaction) in enumerate(zip(rows, workload.transactions)):
        number, observed, cycles = map(int, row)
        assert number == index and observed == sum(len(rec) for rec, _ in transaction.records)
        assert 0 < cycles <= transaction.bound
        words += observed
        coverage.update(transaction.coverage)
    summary = re.findall(r"^SUMMARY COMMANDS (\d+) WORDS (\d+) STALLED (\d+) GAPS (\d+)$", out, re.M)
    assert len(summary) == 1
    compared, count, stalled, gaps = map(int, summary[0])
    assert compared == len(rows) and count == words
    assert stalled > 0 and gaps > 0
    run.receipt["comparisons"][stem] = {"transactions": compared, "words": words,
                                       "stalled_edges": stalled, "gap_edges": gaps}
    run.receipt["coverage"][stem] = dict(coverage)
    run.save()
    return coverage
