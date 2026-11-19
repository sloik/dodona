"""Measure whether the conformance kit rejects kernels with known defects.

Stage-0 helper (decision 0023).

    python tools/kit_adequacy.py

Copies kernel/ to a temporary directory, checks that the unchanged copy passes
the kit, then plants each defect listed in kernel/defects.json, one at a time,
rebuilds and runs the kit again: the scenarios, the ledger cases, the core-key vectors, the check values made at test time, the reference harness, the strict reading of input, the provider session and the host checks (decision 0033). A planted defect counts as caught when the
changed kernel builds and the kit rejects it. The unchanged kernel is run on every judge; a planted
defect is judged until the first judge rejects it, the scenarios first and, for a defect in the
host's own files, the host judges next. Any judge that exits other than 0 rejects, so a judge that
crashes on a defect counts as catching it. A defect that names a case of a
formal model must be rejected by a scenario that says it covers that case;
otherwise the scenario's label is wrong. Exit status is 0 only if the
unchanged kernel passes and every planted defect is caught, by the right
scenario where one is named.

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


JUDGES = (("ledger", "run_ledger_cases.py", []), ("core-key", "run_key_vectors.py", ["key"]),
          ("attest", "run_attest_check.py", ["scenario"]), ("harness", "run_harness_check.py", ["scenario"]),
          ("input", "run_input_cases.py", []), ("session", "run_provider_cases.py", ["session"]),
          ("host-check", "run_check_cases.py", ["check"]))
# The host judges take about a minute each, so a defect in the host's own files is tried on them first.
HOST_FILES = ("src/host.rs", "src/session.rs", "src/proc.rs", "src/wire.rs", "src/jsonread.rs")


def passes_kit(kernel_dir: pathlib.Path, defect_file: str | None = None) -> tuple[bool, list[str]]:
    """Build the kernel and judge it. With `defect_file`, stop at the first judge that rejects it:
    a defect is caught once any judge rejects it, and running the rest would only cost time. The
    scenarios always run first, so a defect that names a model case is judged by its scenarios."""
    manifest = str(kernel_dir / "Cargo.toml")
    build = subprocess.run(["cargo", "build", "--release", "--quiet", "--manifest-path", manifest],
                           capture_output=True, text=True)
    if build.returncode != 0:
        return False, ["did not build"]
    binary = kernel_dir / "target" / "release" / ("dodona-kernel.exe" if sys.platform == "win32" else "dodona-kernel")
    run = subprocess.run([sys.executable, str(ROOT / "tools" / "run_kit.py"), "--", str(binary), "scenario"],
                         capture_output=True, text=True)
    failing = [line.split()[1] for line in run.stdout.splitlines() if line.startswith("MISMATCH")]
    ok = run.returncode == 0
    if not ok and defect_file is not None:
        return ok, failing
    judges = list(JUDGES)
    if defect_file in HOST_FILES:
        judges.sort(key=lambda judge: judge[0] not in ("session", "host-check"))
    # The ledger, the core keys and freshly made check values are judged by their own tools.
    for label, tool, extra in judges:
        other = subprocess.run([sys.executable, str(ROOT / "tools" / tool), "--", str(binary)] + extra, capture_output=True, text=True)
        if other.returncode != 0:
            ok = False
            failing.append(f"{label}-judge")
            if defect_file is not None:
                break
    return ok, failing


def main() -> int:
    defects = json.loads((ROOT / "kernel" / "defects.json").read_text(encoding="utf-8"))["defects"]
    covers: dict[str, set[str]] = {}
    for path in sorted(ROOT.glob("conformance/kernel/*/*.json")):
        for case in json.loads(path.read_text(encoding="utf-8")).get("covers", []):
            covers.setdefault(case, set()).add(f"{path.parent.name}/{path.stem}")
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
            ok, failing = passes_kit(copy, defect["file"])
            source.write_text(original, encoding="utf-8")
            case = defect.get("model_case")
            if ok:
                print(f"MISSED   {defect['name']}: the kit accepts a kernel with this defect")
            elif failing == ["did not build"]:
                print(f"BROKEN   {defect['name']}: the kernel does not build with this defect, so nothing was shown")
            elif case and not covers.get(case, set()) & set(failing):
                print(f"MISLABELLED {defect['name']}: no scenario that says it covers {case} rejects it; "
                      f"rejected only by {', '.join(failing[:4])}")
            else:
                caught += 1
                print(f"caught   {defect['name']}: rejected by {len(failing)} scenario(s)")
    print(json.dumps({"defects": len(defects), "caught": caught, "all_caught": caught == len(defects)}))
    return 0 if caught == len(defects) else 1


if __name__ == "__main__":
    sys.exit(main())
