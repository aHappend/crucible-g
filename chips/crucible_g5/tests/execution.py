"""Bounded, immutable, project-relative execution and artifact retention."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid

from preparation import inventory


class Run:
    def __init__(self, output_root, stem, argv, cwd=Path("."), repair_of=None):
        output = Path(output_root)
        if output.exists() and not output.is_dir():
            raise ValueError("output root is not a directory: " + str(output))
        output.mkdir(parents=True, exist_ok=True)
        self.directory = output / (stem + "-" + uuid.uuid4().hex)
        self.directory.mkdir()
        self.cwd = Path(cwd)
        self.receipt = {"schema": 1, "argv": argv, "cwd": str(self.cwd),
                        "start_time": time.time(), "source_sha256": inventory(self.cwd),
                        "commands": [], "repair_of": repair_of,
                        "python_version": sys.version}
        self.deadline = time.monotonic() + 2700
        self.finished = False

    def snapshot(self, destination=None):
        destination = destination or self.directory / "source"
        for name in self.receipt["source_sha256"]:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.cwd / name, target)
        return destination

    def execute(self, argv, stem, cwd=None, timeout=600, expected_exit=0):
        cwd = Path(cwd) if cwd is not None else self.cwd
        stdout = self.directory / (stem + ".stdout.txt")
        stderr = self.directory / (stem + ".stderr.txt")
        timeout = min(timeout, max(0, self.deadline-time.monotonic()))
        item = {"argv": [str(a) for a in argv], "cwd": str(cwd), "start_time": time.time(),
                "timeout_s": timeout, "stdout": str(stdout), "stderr": str(stderr),
                "exit_code": None}
        self.receipt["commands"].append(item)
        process = None
        timed_out = False
        try:
            with stdout.open("w") as out, stderr.open("w") as err:
                process = subprocess.Popen(item["argv"], cwd=cwd, stdout=out, stderr=err,
                                           start_new_session=True)
                deadline = time.monotonic()+timeout
                while process.poll() is None:
                    remaining = deadline-time.monotonic()
                    if remaining <= 0:
                        timed_out = True
                        raise TimeoutError("execution timeout: " + stem)
                    try:
                        process.wait(timeout=min(remaining, 25))
                    except subprocess.TimeoutExpired:
                        print("PROGRESS stage="+stem+" elapsed_s="+str(
                            int(time.time()-item["start_time"])), flush=True)
                item["exit_code"] = process.returncode
            if expected_exit is not None and process.returncode != expected_exit:
                raise RuntimeError(f"{stem} exit {process.returncode}; see {stdout}, {stderr}")
            return stdout, stderr, process.returncode
        except OSError as error:
            item["launch_error"] = str(error)
            raise
        finally:
            if process is not None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                if process.poll() is None:
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                if item["exit_code"] is None:
                    item["exit_code"] = process.returncode
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                settlement_deadline = time.monotonic()+5
                while True:
                    try:
                        os.killpg(process.pid, 0)
                    except ProcessLookupError:
                        break
                    if time.monotonic() >= settlement_deadline:
                        item.update(end_time=time.time(), timed_out=timed_out,
                                    settled=False, settlement_scope="owned_process_group")
                        raise RuntimeError("owned process group did not settle: "+stem)
                    time.sleep(0.05)
            item.update(end_time=time.time(), timed_out=timed_out, settled=True,
                        settlement_scope="owned_process_group")

    def finish(self, exit_code, error=None, **fields):
        if self.finished:
            raise RuntimeError("receipt already finalized")
        self.receipt.update(fields, end_time=time.time(), exit_code=exit_code,
                            source_unchanged=self.receipt["source_sha256"] == inventory(self.cwd))
        if error is not None:
            self.receipt["error"] = str(error)
        path = self.directory / "receipt.json"
        with path.open("x") as output:
            json.dump(self.receipt, output, indent=2)
            output.write("\n")
        self.finished = True
        return path

    def hash_file(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def summary(path):
    lines = [line for line in Path(path).read_text().splitlines() if line.startswith("SUMMARY ")]
    if len(lines) != 1:
        raise RuntimeError("missing or duplicate completed simulation summary")
    return {key: int(value) for key, value in (
        field.split("=") for field in lines[0].split()[1:])}


def compile_stream(run, parameters, stem="compile", sources=None,
                   driver="stream_driver.cpp"):
    obj = run.directory / (stem + "-obj-" + uuid.uuid4().hex)
    obj.mkdir()
    shutil.copyfile(run.cwd / "tests/stream_driver.cpp", obj / "stream_driver.cpp")
    if driver != "stream_driver.cpp":
        shutil.copyfile(run.cwd / ("tests/"+driver), obj / driver)
    rtl = sources or sorted(str(p) for p in (run.cwd / "rtl").glob("*.sv"))
    run.execute(["verilator", "--cc", "--exe", "--build", "-j", "2", "-Wno-fatal",
                 "--top-module", "crucible_g5_top", "--Mdir", str(obj),
                 *[f"-G{key}={value}" for key, value in parameters.items()],
                 *rtl, driver], stem, timeout=1200)
    binary = run.directory / (stem + "-simulation")
    shutil.copy2(obj / "Vcrucible_g5_top", binary)
    shutil.rmtree(obj)
    return binary
