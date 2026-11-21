"""Measure whether the conformance kit rejects kernels with known defects.

Stage-0 helper (decision 0023).

    python tools/kit_adequacy.py

Copies kernel/ to a temporary directory, checks that the unchanged copy passes
the kit, then plants each defect listed in kernel/defects.json, one at a time,
rebuilds and runs the kit again: the scenarios, the ledger cases, the core-key vectors, the check values made at test time, the reference harness, the strict reading of input, the provider session and the host checks (decision 0033). A planted defect counts as caught when the
changed kernel builds and the kit rejects it. The unchanged kernel is run on every judge; a planted
defect is judged until the first judge rejects it, the scenarios first and, for a defect in the
host's own files, the host judges next. A scenario, ledger, core-key, attest, harness, strict-input, session or status rejection
needs a complete report and a replay on the same named case. The scenarios count `scenarios`, the ledger counts `checks`, the
core-key judge counts `vectors` and status counts `judged` with skips tallied separately. The other reporting judges count
`cases`. The caught line names the cases that repeated. Another auxiliary judge can reject
with exit 1 and no traceback or disk-full error; because it names no case, a repeat of it may be the same
environment failure twice, so it is PROVISIONAL, never caught, and leaves the batch unfinished. A run that ends
without this evidence is UNFINISHED (issue 41). A defect that names a case of a
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
          ("host-check", "run_check_cases.py", ["check"]), ("status", "run_status_cases.py", ["status"]))
# Judges that end with the scenarios' footer, and the key under which each counts its checks (issue 41).
REPORTING = {"ledger": "checks", "core-key": "vectors", "attest": "cases", "harness": "cases", "input": "cases",
             "session": "cases", "status": "judged"}
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
    target = kernel_dir / "target"
    build = subprocess.run(["cargo", "build", "--release", "--quiet", "--manifest-path", manifest,
                            "--target-dir", str(target)],
                           capture_output=True, text=True)
    if build.returncode != 0:
        return False, ["did not build"]
    binary = target / "release" / ("dodona-kernel.exe" if sys.platform == "win32" else "dodona-kernel")
    verdict, failing = run_scenarios(binary)
    if verdict == "unfinished":
        return False, ["scenario-judge unfinished"]
    ok = verdict == "passed"
    if not ok and defect_file is not None:
        repeat, repeated = run_scenarios(binary)
        confirmed = [case for case in failing if case in repeated]
        if repeat != "rejected" or not confirmed:
            return False, ["scenario-judge unsteady"]
        return False, confirmed
    judges = list(JUDGES)
    if defect_file in FIRST_JUDGE:
        first = FIRST_JUDGE[defect_file]
        judges.sort(key=lambda judge: (judge[0] != first, judge[0] not in ("session", "host-check", "status")))
    # The ledger, the core keys and freshly made check values are judged by their own tools.
    for label, tool, extra in judges:
        verdict, cases = judge_once(label, tool, extra, binary)
        if verdict == "unfinished":
            # The judge itself broke (a crash, a full disk): nothing was shown either way (issue 41).
            return False, [f"{label}-judge unfinished"]
        if verdict == "rejected":
            ok = False
            if defect_file is None:
                failing.append(f"{label}-judge")
                continue
            # A rejection that does not happen again, on the same named check where the judge names
            # them, was not the defect's doing (issue 41).
            repeat, repeated = judge_once(label, tool, extra, binary)
            confirmed = [case for case in cases if case in repeated]
            if repeat != "rejected" or (label in REPORTING and not confirmed):
                return False, [f"{label}-judge unsteady"]
            if label not in REPORTING:
                # A repeated exit 1 that names no case may be the same environment failure twice: provisional,
                # never a catch, and the batch is unfinished (issue 41).
                return False, [f"{label}-judge provisional"]
            failing.extend(f"{label}-judge: {case}" for case in confirmed)
            break
    return ok, failing


def run_scenarios(binary: pathlib.Path) -> tuple[str, list[str]]:
    return run_report([sys.executable, str(ROOT / "tools" / "run_kit.py"), "--", str(binary), "scenario"], "scenarios")


def distinct_fields(pairs: list[tuple[str, object]]) -> dict:
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("repeated field in the judge's report")
    return fields


def run_report(command: list[str], count: str) -> tuple[str, list[str]]:
    """Run a judge that ends with the scenarios' footer, its total under `count`: 'passed', 'rejected'
    with the cases it names, or 'unfinished' when the footer is missing, malformed or incomplete, says a
    kernel process did not finish, disagrees with the exit status, or anything was written to stderr."""
    try:
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
        report = json.loads(result.stdout.splitlines()[-1], object_pairs_hook=distinct_fields)
    except (OSError, ValueError, IndexError, RecursionError, subprocess.TimeoutExpired):
        return "unfinished", []
    if result.stderr or not isinstance(report, dict):
        return "unfinished", []
    unfinished = report.get("unfinished")
    if type(unfinished) is not int or unfinished != 0:
        return "unfinished", []
    total, matched, rejected = report.get(count), report.get("matched"), report.get("rejected")
    if (type(total) is not int or type(matched) is not int or not 0 <= matched <= total or total < 1
            or not isinstance(rejected, list) or len(rejected) != total - matched
            or any(not isinstance(case, str) or not case.strip() for case in rejected) or len(set(rejected)) != len(rejected)):
        return "unfinished", []
    if count == "judged":
        cases, skipped = report.get("cases"), report.get("skipped")
        if type(cases) is not int or type(skipped) is not int or skipped < 0 or cases != total + skipped:
            return "unfinished", []
    if result.returncode == 0 and not rejected and report.get("all_matched") is True:
        return "passed", []
    if result.returncode == 1 and rejected and report.get("all_matched") is False:
        return "rejected", rejected
    return "unfinished", []


def judge_once(label: str, tool: str, extra: list[str], binary: pathlib.Path) -> tuple[str, list[str]]:
    """One run of a judge: its verdict, and the cases it named when it reports them."""
    if label in REPORTING:
        return run_report(judge_command(label, tool, extra, binary), REPORTING[label])
    return run_judge(label, tool, extra, binary), []


def judge_command(label: str, tool: str, extra: list[str], binary: pathlib.Path) -> list[str]:
    before = ["--kernel"] + OTHER_KERNEL if label == "status" else []
    return [sys.executable, str(ROOT / "tools" / tool)] + before + ["--", str(binary)] + extra


def run_judge(label: str, tool: str, extra: list[str], binary: pathlib.Path) -> str:
    """Run one judge that names no case the runner reads: 'passed', 'rejected', or 'unfinished' when the
    judge itself crashed or the machine could not run it, which is no rejection of the kernel."""
    try:
        other = subprocess.run(judge_command(label, tool, extra, binary), capture_output=True, text=True)
    except (OSError, UnicodeError):
        return "unfinished"
    if other.returncode == 0:
        return "passed"
    if (other.returncode != 1 or "Traceback (most recent call last)" in other.stderr
            or "No space left on device" in other.stderr + other.stdout):
        return "unfinished"
    return "rejected"


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
        caught = unfinished = 0
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
            elif len(failing) == 1 and failing[0].endswith(" provisional"):
                unfinished += 1
                print(f"PROVISIONAL {defect['name']}: {failing[0]}, a repeated exit 1 naming no case, so nothing was shown")
            elif len(failing) == 1 and failing[0].endswith((" unfinished", " unsteady")):
                unfinished += 1
                print(f"UNFINISHED {defect['name']}: {failing[0]}, so nothing was shown")
            elif case and not covers.get(case, set()) & set(failing):
                print(f"MISLABELLED {defect['name']}: no scenario that says it covers {case} rejects it; "
                      f"rejected only by {', '.join(failing[:4])}")
            else:
                caught += 1
                print(f"caught   {defect['name']}: rejected by {', '.join(failing)}")
    print(json.dumps({"defects": len(defects), "caught": caught, "unfinished": unfinished,
                      "all_caught": caught == len(defects)}))
    return 0 if caught == len(defects) else 1


if __name__ == "__main__":
    sys.exit(main())
