"""Immutable per-invocation source bindings and bounded tool execution."""

import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Evidence:
    def __init__(self, root, suite, argv, preparation=False, repair_of=None):
        self.root = Path(root).resolve()
        stem = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        parent = self.root / "evidence"
        if preparation:
            parent /= "preparation"
        self.path = parent / f"{suite}-{stem}-{uuid.uuid4().hex[:8]}"
        self.path.mkdir(parents=True, exist_ok=False)
        self.data = {"schema": 1, "suite": suite, "argv": argv, "cwd": ".",
                     "started_at": utc(), "acceptance_evidence": not preparation,
                     "commands": [], "status": "running", "source_sha256": {}}
        if repair_of:
            self.data["repair_of"] = repair_of
        for pattern in ("rtl/*.sv", "design/*.md", "tests/*",
                        "crucible_g2_reference/rtl/*.sv"):
            for file in sorted(self.root.glob(pattern)):
                if file.is_file():
                    rel = file.relative_to(self.root)
                    self.data["source_sha256"][str(rel)] = sha(file)
                    snapshot = self.path / "sources" / rel
                    snapshot.parent.mkdir(parents=True, exist_ok=True)
                    snapshot.write_bytes(file.read_bytes())
        self.save()

    def relative(self, path):
        return os.path.relpath(path, self.root)

    def save(self):
        (self.path / "receipt.json").write_text(json.dumps(self.data, indent=2)+"\n")

    def run(self, argv, name, cwd=None, timeout=3600, expect=0):
        cwd = Path(cwd or self.root)
        stdout, stderr = self.path / (name+".stdout.txt"), self.path / (name+".stderr.txt")
        record = {"argv": [str(x) for x in argv], "cwd": self.relative(cwd),
                  "started_at": utc(), "timeout_s": timeout,
                  "stdout": self.relative(stdout), "stderr": self.relative(stderr)}
        self.data["commands"].append(record)
        self.save()
        start = time.monotonic()
        with stdout.open("wb") as out, stderr.open("wb") as err:
            try:
                process = subprocess.Popen([str(x) for x in argv], cwd=cwd,
                                           stdout=out, stderr=err, start_new_session=True)
                while True:
                    try:
                        code = process.wait(timeout=min(30, max(0.1, timeout-(time.monotonic()-start))))
                        record.update(exit_code=code, timed_out=False)
                        break
                    except subprocess.TimeoutExpired:
                        if time.monotonic()-start >= timeout:
                            import signal
                            os.killpg(process.pid, signal.SIGTERM)
                            try:
                                process.wait(timeout=10)
                            except subprocess.TimeoutExpired:
                                os.killpg(process.pid, signal.SIGKILL)
                                process.wait()
                            record.update(exit_code=process.returncode, timed_out=True)
                            break
                        print(f"PROGRESS {name} active {int(time.monotonic()-start)}s", flush=True)
            except OSError as exc:
                record.update(exit_code=None, timed_out=False, error=str(exc))
                raise
            finally:
                record.update(ended_at=utc(), duration_s=time.monotonic()-start)
                self.save()
        if record["timed_out"] or expect is not None and record["exit_code"] != expect:
            raise RuntimeError(f"{name}: tool exit={record['exit_code']} "
                               f"timeout={record['timed_out']}; {self.relative(stderr)}; "
                               f"{self.relative(stdout)}")
        return stdout.read_text(errors="replace"), stderr.read_text(errors="replace"), record["exit_code"]

    def versions(self, tools):
        for tool in tools:
            arg = "-V" if tool in ("iverilog", "vvp") else (
                "-V" if tool == "yosys" else "--version")
            self.run([tool, arg], "version-"+tool, expect=None)

    def finish(self, status, **fields):
        self.data.update(status=status, ended_at=utc(), **fields)
        self.save()
