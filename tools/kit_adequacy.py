"""Measure whether the conformance kit rejects kernels with known defects.

Stage-0 helper (decision 0023).

    python tools/kit_adequacy.py [--shard INDEX COUNT]

Copies kernel/ to a temporary directory, checks that the unchanged copy passes
the kit, then plants each defect listed in kernel/defects.json, one at a time,
rebuilds and runs the kit again: the scenarios, the ledger cases, the core-key vectors, the check values made at test time, the reference harness, the strict reading of input, the provider session and the host checks (decision 0033). A planted defect counts as caught when the
changed kernel builds and the kit rejects it. The unchanged kernel is run on every judge; a planted
defect is judged until the first judge rejects it, the scenarios first and, for a defect in the
host's own files, the host judges next. A judge that exits other than 0 rejects, unless it crashed
(a Python traceback) or the disk was full: then the defect is UNFINISHED, never caught. A judge that
rejects a planted defect is run a second time, and the defect counts as caught only if it rejects
again; a rejection that does not repeat is UNFINISHED too (issue 41). A defect that names a case of a
formal model must be rejected by a scenario that says it covers that case;
otherwise the scenario's label is wrong. Exit status is 0 only if the
unchanged kernel passes and every planted defect is caught, by the right
scenario where one is named. With --shard, INDEX is zero-based. Each shard
checks the unchanged kernel and must catch every defect assigned to it.
Only the unsharded invocation can report all_caught.

This measures the kit against defects someone thought of. It says nothing
about defects nobody thought of.
"""
from __future__ import annotations

import argparse
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
          ("host-check", "run_check_cases.py", ["check"]), ("status", "run_status_cases.py", ["status"]))
# The status judge recomputes each report with another kernel's scenario command, so that the kernel judged does
# not certify its own report: here the second kernel's.
OTHER_KERNEL = ["node", str(pathlib.Path(__file__).resolve().parent.parent / "kernel2" / "dodona-kernel2.js")]
# The host judges take about a minute each, so a defect in the host's own files is tried first on the
# judge meant for that file: the check judge for the check, the session judge for the session.
FIRST_JUDGE = {"src/host.rs": "host-check", "src/jsonread.rs": "host-check",
               "src/session.rs": "session", "src/proc.rs": "session", "src/wire.rs": "session",
               "src/project_status.rs": "status"}


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
    if defect_file in FIRST_JUDGE:
        first = FIRST_JUDGE[defect_file]
        judges.sort(key=lambda judge: (judge[0] != first, judge[0] not in ("session", "host-check", "status")))
    # The ledger, the core keys and freshly made check values are judged by their own tools.
    for label, tool, extra in judges:
        verdict = run_judge(label, tool, extra, binary)
        if verdict == "unfinished":
            # The judge itself broke (a crash, a full disk): nothing was shown either way (issue 41).
            return False, [f"{label}-judge unfinished"]
        if verdict == "rejected":
            if defect_file is not None and run_judge(label, tool, extra, binary) != "rejected":
                # A rejection that does not happen again was not the defect's doing (issue 41).
                return False, [f"{label}-judge unsteady"]
            ok = False
            failing.append(f"{label}-judge")
            if defect_file is not None:
                break
    return ok, failing


def run_judge(label: str, tool: str, extra: list[str], binary: pathlib.Path) -> str:
    """Run one judge: 'passed', 'rejected', or 'unfinished' when the judge itself crashed or the
    machine could not run it, which is no rejection of the kernel."""
    before = ["--kernel"] + OTHER_KERNEL if label == "status" else []
    other = subprocess.run([sys.executable, str(ROOT / "tools" / tool)] + before + ["--", str(binary)] + extra,
                           capture_output=True, text=True)
    if other.returncode == 0:
        return "passed"
    if "Traceback (most recent call last)" in other.stderr or "No space left on device" in other.stderr + other.stdout:
        return "unfinished"
    return "rejected"


def select_shard(defects: list, index: int, count: int) -> list:
    if not 0 <= index < count <= len(defects):
        raise ValueError("expected 0 <= INDEX < COUNT <= the number of listed defects")
    return defects[index::count]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shard", nargs=2, type=int, metavar=("INDEX", "COUNT"),
                        help="judge one zero-based shard of the defect manifest")
    args = parser.parse_args()
    defects = json.loads((ROOT / "kernel" / "defects.json").read_text(encoding="utf-8"))["defects"]
    inventory_count = len(defects)
    if args.shard is not None:
        try:
            defects = select_shard(defects, *args.shard)
        except ValueError as err:
            parser.error(str(err))
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
            elif len(failing) == 1 and failing[0].endswith((" unfinished", " unsteady")):
                print(f"UNFINISHED {defect['name']}: {failing[0]}, so nothing was shown")
            elif case and not covers.get(case, set()) & set(failing):
                print(f"MISLABELLED {defect['name']}: no scenario that says it covers {case} rejects it; "
                      f"rejected only by {', '.join(failing[:4])}")
            else:
                caught += 1
                print(f"caught   {defect['name']}: rejected by {len(failing)} scenario(s)")
    complete = caught == len(defects)
    summary = {"defects": len(defects), "caught": caught, "all_caught": args.shard is None and complete}
    if args.shard is not None:
        index, count = args.shard
        summary.update(shard_index=index, shard_count=count, inventory_count=inventory_count, shard_caught=complete)
    print(json.dumps(summary))
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
