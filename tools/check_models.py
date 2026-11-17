"""Run every model-check case listed in spec/*/expected.json and judge it.

Stage-0 helper (decision 0023): disposable, to be replaced by dodona itself.

This script never starts a model checker on its own. It hands each case to the
site's executor, described in a JSON file, and judges what comes back
(decision 0007). A case matches only if the exit code AND the checker's own
output agree with what was expected. Anything else, including a run that did
not finish, is a mismatch. Exit status is 0 only if every case matched.

    python tools/check_models.py --site .github/site/executor.json
    python tools/check_models.py --replay DIR     # judge recorded outputs

Replay directory layout: <model-dir-name>/<case>.out and <case>.exit
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NO_ERROR = "Model checking completed. No error has been found."


def judge(case: dict, exit_code: int | None, output: str) -> dict:
    """Decide whether one finished case matches its expectation."""
    want = case["expect"]
    result = {"config": case["config"], "expected": want, "exit": exit_code}
    if exit_code is None:
        return {**result, "outcome": "did-not-run", "match": False}
    if want == "no-violation":
        complete = NO_ERROR in output and ", 0 states left on queue." in output
        ok = exit_code == case["expect_exit"] and complete
        outcome = "no-violation" if ok else "did-not-complete"
        if "is violated" in output:
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--site", type=pathlib.Path, help="JSON file describing the site's executor")
    mode.add_argument("--replay", type=pathlib.Path, help="judge recorded outputs instead of running")
    ap.add_argument("--report", type=pathlib.Path, help="write the JSON report here")
    args = ap.parse_args()

    site = json.loads(args.site.read_text(encoding="utf-8")) if args.site else None
    report = []
    for expected in sorted(ROOT.glob("spec/*/expected.json")):
        model_dir = expected.parent
        spec = json.loads(expected.read_text(encoding="utf-8"))
        for case in spec["cases"]:
            name = case["config"].removesuffix(".cfg")
            exit_code: int | None
            if args.replay:
                out_file = args.replay / model_dir.name / f"{name}.out"
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
