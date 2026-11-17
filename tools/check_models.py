"""Run every model-check case listed in spec/*/expected.json and judge it.

Stage-0 helper (decision 0023): disposable, to be replaced by dodona itself.

This script never starts a model checker on its own. It hands each case to the
site's executor, described in a JSON file, and judges what comes back
(decision 0007). A case matches only if the exit code AND the checker's own
output agree with what was expected. Anything else, including a run that did
not finish, is a mismatch. Exit status is 0 only if every case matched.

    python tools/check_models.py --site .github/site/executor.json
    python tools/check_models.py --site .github/site/executor.json --batch
    python tools/check_models.py --replay DIR     # judge recorded outputs

With --batch every case goes to the executor as one job instead of one job
each, which is kinder to a shared queue. The cases run one after another
inside the executor and the outputs come back together.

Replay directory layout: <model-dir-name>/<case>.out and <case>.exit
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
NO_ERROR = "Model checking completed. No error has been found."


def judge(case: dict, exit_code: int | None, output: str) -> dict:
    """Decide whether one finished case matches its expectation."""
    want = case["expect"]
    result = {"config": case["config"], "expected": want, "exit": exit_code}
    if exit_code is None:
        return {**result, "outcome": "did-not-run", "match": False}
    if want == "temporal-violation":
        ok = exit_code == case["expect_exit"] and "Temporal properties were violated." in output
        outcome = "temporal violation" if ok else ("no-violation" if NO_ERROR in output else "did-not-complete")
        return {**result, "outcome": outcome, "match": ok}
    if want == "no-violation":
        complete = NO_ERROR in output and ", 0 states left on queue." in output
        ok = exit_code == case["expect_exit"] and complete
        outcome = "no-violation" if ok else "did-not-complete"
        if "is violated" in output or "were violated" in output:
            outcome = "violation"
        return {**result, "outcome": outcome, "match": ok}
    # The checker words a violation found in the very first state differently.
    named = re.compile(rf"Invariant {re.escape(case['of'])} is violated(\.| by the initial state:)")
    if exit_code == case["expect_exit"] and named.search(output):
        return {**result, "outcome": f"violation of {case['of']}", "match": True}
    if "is violated" in output:
        outcome = "violation of a different property"
    elif NO_ERROR in output:
        outcome = "no-violation"
    else:
        outcome = "did-not-complete"
    return {**result, "outcome": outcome, "match": False}


def state_counts(output: str) -> str:
    lines = [l for l in output.splitlines() if "distinct states found" in l and "Progress" not in l]
    return lines[-1].strip() if lines else ""


def command_for(site: dict, model_dir: pathlib.Path, spec: dict, case: dict) -> list[str]:
    """Build the executor's argument list for one case. No shell is involved."""
    root_module = case.get("model", spec["model"])
    includes = sorted(p.name for p in model_dir.glob("*.tla")) + [case["config"]]
    tool_args = [a.replace("<config>", case["config"]) for a in spec["arguments"]]
    tool_args = [root_module if a == spec["model"] else a for a in tool_args]
    values = {"source": str(model_dir), "timeout": str(site.get("timeout_seconds", 900))}
    argv: list[str] = []
    for part in site["command"]:
        if part == "{includes}":
            for name in includes:
                argv += [site["include_flag"], name]
        elif part == "{tool}":
            argv += site["tool"] + tool_args
        else:
            argv.append(part.format(**values))
    return argv


def run_batch(site: dict, only: list[str], dumps: bool) -> pathlib.Path | None:
    """Send every selected case to the executor as one job; return where the outputs came back."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="dodona-batch-"))
    bundle, dest = work / "bundle", work / "fetched"
    cases = []
    for expected in sorted(ROOT.glob("spec/*/expected.json")):
        model_dir = expected.parent
        if only and model_dir.name not in only:
            continue
        spec = json.loads(expected.read_text(encoding="utf-8"))
        shutil.copytree(model_dir, bundle / model_dir.name, ignore=shutil.ignore_patterns("expected.json"))
        for case in spec["cases"]:
            root_module = case.get("model", spec["model"])
            args = [a.replace("<config>", case["config"]) for a in spec["arguments"]]
            args = [root_module if a == spec["model"] else a for a in args]
            cases.append({"name": f"{model_dir.name}/{case['config'].removesuffix('.cfg')}",
                          "cwd": model_dir.name, "argv": site["tool"] + args})
        if dumps and (model_dir / "dump.cfg").exists():
            cases.append({"name": f"{model_dir.name}/dump", "cwd": model_dir.name, "keep": ["states.dump"],
                          "argv": site["tool"] + ["-workers", "1", "-config", "dump.cfg", "-dump", "states", "MCDump.tla"]})
    if not cases:
        return None
    shutil.copy(ROOT / ".github" / "site" / "batch_driver.py", bundle / "batch_driver.py")
    (bundle / "manifest.json").write_text(json.dumps({"out": "out", "cases": cases}, indent=1), encoding="utf-8")
    values = {"source": str(bundle), "dest": str(dest), "timeout": str(site.get("batch_timeout_seconds", 3600))}
    argv = [part.format(**values) for part in site["batch_command"]]
    print(f"sending {len(cases)} cases to the executor as one job", flush=True)
    done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if not dest.exists():
        print("the executor returned nothing:", (done.stderr or done.stdout)[-400:])
        return None
    fetched = dest / "out" if (dest / "out").exists() else dest
    for path in fetched.glob("*/*.exit"):
        if path.read_text().strip() == "did-not-start":
            path.unlink()
    return fetched


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--site", type=pathlib.Path, help="JSON file describing the site's executor")
    mode.add_argument("--replay", type=pathlib.Path, help="judge recorded outputs instead of running")
    ap.add_argument("--report", type=pathlib.Path, help="write the JSON report here")
    ap.add_argument("--only", action="append", default=[], metavar="MODEL",
                    help="run only this model directory under spec/ (may be repeated)")
    ap.add_argument("--save", type=pathlib.Path, help="keep each case's raw output under this directory")
    ap.add_argument("--batch", action="store_true", help="send all cases to the executor as one job")
    ap.add_argument("--dumps", action="store_true",
                    help="with --batch: also have each model that has a dump.cfg write out its states")
    args = ap.parse_args()

    site = json.loads(args.site.read_text(encoding="utf-8")) if args.site else None
    if args.batch:
        fetched = run_batch(site, args.only, args.dumps)
        if fetched is None:
            print(json.dumps({"cases": 0, "matched": 0, "all_matched": False}))
            return 1
        args.replay = fetched
        if args.save:
            shutil.copytree(fetched, args.save, dirs_exist_ok=True)
    report = []
    for expected in sorted(ROOT.glob("spec/*/expected.json")):
        model_dir = expected.parent
        if args.only and model_dir.name not in args.only:
            continue
        spec = json.loads(expected.read_text(encoding="utf-8"))
        for case in spec["cases"]:
            name = case["config"].removesuffix(".cfg")
            exit_code: int | None
            if args.replay:
                out_file = args.replay / model_dir.name / f"{name}.out"
                if not out_file.exists():
                    out_file = args.replay / model_dir.name / f"{name}.txt"
                exit_file = args.replay / model_dir.name / f"{name}.exit"
                if out_file.exists() and exit_file.exists():
                    output = out_file.read_text(encoding="utf-8", errors="replace")
                    exit_code = int(exit_file.read_text().strip())
                else:
                    output, exit_code = "", None
            else:
                argv = command_for(site, model_dir, spec, case)
                done = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace")
                output, exit_code = done.stdout, done.returncode
            if args.save and exit_code is not None:
                (args.save / model_dir.name).mkdir(parents=True, exist_ok=True)
                (args.save / model_dir.name / f"{name}.txt").write_text(output, encoding="utf-8")
            verdict = judge(case, exit_code, output)
            verdict.update(model=model_dir.name, states=state_counts(output))
            report.append(verdict)
            mark = "match   " if verdict["match"] else "MISMATCH"
            print(f"{mark} {model_dir.name}/{name}: expected {verdict['expected']}, "
                  f"got {verdict['outcome']} (exit {exit_code})", flush=True)

    matched = sum(1 for r in report if r["match"])
    summary = {"cases": len(report), "matched": matched, "all_matched": matched == len(report) and bool(report)}
    if args.report:
        args.report.write_text(json.dumps({"summary": summary, "cases": report}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0 if summary["all_matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
