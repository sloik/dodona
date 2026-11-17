"""Measure whether the conformance kit rejects kernels with known defects.

Stage-0 helper (decision 0023).

    python tools/kit_adequacy.py

Copies kernel/ to a temporary directory, checks that the unchanged copy passes
the kit, then plants each defect listed in kernel/defects.json, one at a time,
rebuilds and runs the kit again. A planted defect counts as caught when the
kit rejects that kernel. Exit status is 0 only if the unchanged kernel passes
and every planted defect is caught.

This measures the kit against defects someone thought of. It says nothing
about defects nobody thought of.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent


def passes_kit(kernel_dir: pathlib.Path) -> tuple[bool, list[str]]:
    manifest = str(kernel_dir / "Cargo.toml")
    build = subprocess.run(["cargo", "build", "--release", "--quiet", "--manifest-path", manifest],
                           capture_output=True, text=True)
    if build.returncode != 0:
        return False, ["did not build"]
    binary = kernel_dir / "target" / "release" / ("dodona-kernel.exe" if sys.platform == "win32" else "dodona-kernel")
    run = subprocess.run([sys.executable, str(ROOT / "tools" / "run_kit.py"), "--", str(binary), "scenario"],
                         capture_output=True, text=True)
    failing = [line.split()[1] for line in run.stdout.splitlines() if line.startswith("MISMATCH")]
    return run.returncode == 0, failing


def main() -> int:
    defects = json.loads((ROOT / "kernel" / "defects.json").read_text(encoding="utf-8"))["defects"]
    with tempfile.TemporaryDirectory() as tmp:
        copy = pathlib.Path(tmp) / "kernel"
        shutil.copytree(ROOT / "kernel", copy, ignore=shutil.ignore_patterns("target"))
        clean, failing = passes_kit(copy)
        if not clean:
            print("the unchanged kernel does not pass the kit:", failing)
            return 1
        caught = 0
        for defect in defects:
            source = copy / defect["file"]
            original = source.read_text(encoding="utf-8")
            if defect["find"] not in original:
                print(f"STALE    {defect['name']}: the text to replace is no longer in {defect['file']}")
                continue
            source.write_text(original.replace(defect["find"], defect["replace"], 1), encoding="utf-8")
            ok, failing = passes_kit(copy)
            source.write_text(original, encoding="utf-8")
            if ok:
                print(f"MISSED   {defect['name']}: the kit accepts a kernel with this defect")
            else:
                caught += 1
                print(f"caught   {defect['name']}: rejected by {len(failing)} scenario(s)")
    print(json.dumps({"defects": len(defects), "caught": caught, "all_caught": caught == len(defects)}))
    return 0 if caught == len(defects) else 1


if __name__ == "__main__":
    sys.exit(main())
