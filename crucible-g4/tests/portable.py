"""Fresh project-relative bundle reproduction, without binaries or prior evidence."""

import shutil
import uuid

from execution import hashes, source_files


def portable(run):
    run.versions(("python3", "iverilog", "vvp", "verilator", "yosys"))
    isolated = run.folder / f"isolated-{uuid.uuid4().hex[:8]}"
    isolated.mkdir()
    before = hashes(run.root)
    for source in source_files(run.root):
        if not source.is_file():
            continue
        relative = source.relative_to(run.root)
        target = isolated / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    assert hashes(isolated) == before, "portable bundle source inventory differs"
    assert not (isolated / "evidence").exists()
    run.execute(["python3", "tests/reproduce.py"], "isolated-reproduction", cwd=isolated)
    assert hashes(isolated) == before, "reproduction modified declared sources"
    assert hashes(run.root) == before, "reproduction modified original declared sources"
    for directory in ("rtl", "design", "tests", "crucible_g3_reference"):
        for path in (isolated / directory).rglob("*"):
            assert path.name != "__pycache__" and path.suffix not in (".o", ".a", ".bin", ".vvp", ".pyc"), path
    run.receipt["comparisons"]["portable"] = {
        "copied_sources": len(before), "fresh_bundle": run.relative(isolated),
        "source_hashes_preserved": True,
        "stdout": run.relative(run.folder / "isolated-reproduction.stdout.txt"),
    }
    run.save()
