"""Measure whether the conformance kit rejects kernels with known defects.

Stage-0 helper (decision 0023).

    python tools/kit_adequacy.py [--shard INDEX COUNT]

Copies kernel/ to a temporary directory, checks that the unchanged copy passes
the kit, then plants each defect listed in kernel/defects.json, one at a time,
rebuilds and runs the kit again: the scenarios, the ledger cases, the core-key vectors, the check values made at test time, the reference harness, the strict reading of input, the provider session and the host checks (decision 0033). A planted defect counts as caught when the
changed kernel builds and the kit rejects it. The unchanged kernel is run on every judge; a planted
defect is judged until the first judge rejects it, the scenarios first and, for a defect in the
host's own files, the host judges next. A rejection needs a complete report and a replay on the same named case. The
scenarios count `scenarios`, the ledger counts `checks`, the core-key judge counts `vectors` and host-check and status count
`judged` with skips tallied separately. The other judges count `cases`. The caught line names the cases that repeated.
An auxiliary judge without a report can reject
with exit 1 and no traceback or disk-full error; because it names no case, a repeat of it may be the same
environment failure twice, so it is PROVISIONAL, never caught, and leaves the batch unfinished. A run that ends
without this evidence is UNFINISHED (issue 41). A defect that names a case of a
formal model must be rejected by a scenario that says it covers that case;
otherwise the scenario's label is wrong. Exit status is 0 only if the
unchanged kernel passes and every planted defect is caught, by the right
scenario where one is named. With --shard, INDEX is zero-based. Each shard
checks the unchanged kernel and must catch every defect assigned to it.
Only the unsharded invocation can report all_caught. The CLI supervisor
owns the batch directory and publishes the worker's summary after removal.
A worker crash, an invalid receipt or a cleanup failure exits 2. An abrupt
kill of the supervisor can leave the directory.

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
from multiprocessing import get_context

ROOT = pathlib.Path(__file__).resolve().parent.parent


JUDGES = (("ledger", "run_ledger_cases.py", []), ("core-key", "run_key_vectors.py", ["key"]),
          ("attest", "run_attest_check.py", ["scenario"]), ("harness", "run_harness_check.py", ["scenario"]),
          ("input", "run_input_cases.py", []), ("session", "run_provider_cases.py", ["session"]),
          ("host-check", "run_check_cases.py", ["check"]), ("status", "run_status_cases.py", ["status"]))
# Judges that end with the scenarios' footer, and the key under which each counts its checks (issue 41).
REPORTING = {"ledger": "checks", "core-key": "vectors", "attest": "cases", "harness": "cases", "input": "cases",
             "session": "cases", "host-check": "judged", "status": "judged"}
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


def select_shard(defects: list, index: int, count: int) -> list:
    if not 0 <= index < count <= len(defects):
        raise ValueError("expected 0 <= INDEX < COUNT <= the number of listed defects")
    return defects[index::count]


def main(argv: list[str] | None = None, *, tmp=None, emit_summary=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shard", nargs=2, type=int, metavar=("INDEX", "COUNT"),
                        help="judge one zero-based shard of the defect manifest")
    args = parser.parse_args([] if argv is None else argv)
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
    with tempfile.TemporaryDirectory(dir=tmp) as directory:
        copy = pathlib.Path(directory) / "kernel"
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
            elif "witness" in defect and defect["witness"] not in failing:
                print(f"MISLABELLED {defect['name']}: the named witness did not reject on both runs: {defect['witness']}")
            else:
                caught += 1
                print(f"caught   {defect['name']}: rejected by {', '.join(failing)}")
    complete = caught == len(defects)
    summary = {"defects": len(defects), "caught": caught, "unfinished": unfinished, "all_caught": args.shard is None and complete}
    if args.shard is not None:
        index, count = args.shard
        summary.update(shard_index=index, shard_count=count, inventory_count=inventory_count, shard_caught=complete)
    if emit_summary is None:
        print(json.dumps(summary))
    else:
        emit_summary(summary)
    return 0 if complete else 1


def run_batch_worker(argv, owned, sender) -> None:
    sys.stdout.reconfigure(line_buffering=True)
    summary = None

    def remember(record):
        nonlocal summary
        summary = record

    with sender:
        try:
            status = main(argv, tmp=owned, emit_summary=remember)
        except SystemExit as err:
            sender.send((err.code, None, True))
            raise
        sender.send((status, summary, False))
    sys.exit(status)


def receive_batch_receipt(receiver):
    if not receiver.poll():
        return None
    try:
        receipt = receiver.recv()
    except EOFError:
        return None
    if receiver.poll():
        try:
            receiver.recv()
        except EOFError:
            return receipt
        return None
    return receipt


def run_owned_batch(argv, owned, start_worker):
    context = get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    with receiver, sender:
        worker = context.Process(target=start_worker, args=(argv, owned, sender))
        worker.start()
        try:
            sender.close()
            worker.join()
            return worker.exitcode, receive_batch_receipt(receiver)
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join()
            worker.close()


def receipt_matches_exit(receipt, status) -> bool:
    if not isinstance(receipt, tuple) or len(receipt) != 3 or status not in (0, 1, 2):
        return False
    reported, summary, argument_exit = receipt
    if type(reported) is not int or reported != status:
        return False
    if summary is None:
        return status != 0 or argument_exit is True
    if argument_exit or not isinstance(summary, dict) or type(summary.get("all_caught")) is not bool:
        return False
    if any(type(summary.get(key)) is not int for key in ("defects", "caught", "unfinished")):
        return False
    if status != 0:
        return not summary["all_caught"] and summary.get("shard_caught") is not True
    if summary["caught"] != summary["defects"] or summary["unfinished"]:
        return False
    if summary["all_caught"]:
        return "shard_caught" not in summary
    index, count, inventory = (summary.get(key) for key in ("shard_index", "shard_count", "inventory_count"))
    return (summary.get("shard_caught") is True
            and all(type(value) is int for value in (index, count, inventory))
            and 0 <= index < count <= inventory)


def supervise(argv: list[str], *, tmp=None, worker=run_batch_worker, cleanup=shutil.rmtree) -> int:
    try:
        owned = pathlib.Path(tempfile.mkdtemp(prefix="dodona-rust-plant-batch-", dir=tmp))
        try:
            status, receipt = run_owned_batch(argv, owned, worker)
        finally:
            cleanup(owned)
            if owned.exists():
                raise OSError("the batch directory is still present after cleanup")
    except OSError as err:
        print(f"UNFINISHED: the planted-defect batch could not run or clean up ({err})")
        return 2
    if not receipt_matches_exit(receipt, status):
        print(f"UNFINISHED: the planted-defect worker produced no valid completion receipt (exit {status})")
        return 2
    if receipt[1] is not None:
        print(json.dumps(receipt[1]))
    return status


if __name__ == "__main__":
    sys.exit(supervise(sys.argv[1:]))
