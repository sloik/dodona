"""Run every model-check case listed in spec/*/expected.json and judge it.

Stage-0 helper (decision 0023): disposable, to be replaced by dodona itself.

This script never starts a model checker, or anything else, on its own. Jobs
are sent only through tools/host.py, and a case matches only if the exit code
AND the checker's own output agree with what was expected. Anything else,
including a run that did not finish, is a mismatch. Exit status is 0 only if
every case matched.

    python tools/check_models.py --runs DIR                       # judge what tools/host.py collected
    python tools/check_models.py --site SITE.json --batch         # send every case as one job, then judge
    python tools/check_models.py --replay DIR                     # read saved outputs again; not proof

Any of them also takes [--report FILE] [--only MODEL]... [--save DIR], and
--batch takes [--dumps]:

    python tools/check_models.py --site SITE.json --batch --dumps --only kernel --save DIR --report FILE

--runs and --batch judge nothing unless the job ended well, its tools were
measured, and they are the pinned ones. --replay cannot know any of that: it
says what the files show, and its report is marked as not proof.

Replay directory layout: <model-dir-name>/<case>.txt and <case>.exit
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "providers" / "tlc"))
from judge import NO_ERROR, judge  # noqa: E402,F401  (one copy of the rule, shared with the provider)


def state_counts(output: str) -> str:
    lines = [l for l in output.splitlines() if "distinct states found" in l and "Progress" not in l]
    return lines[-1].strip() if lines else ""


def run_batch(site: dict, only: list[str], dumps: bool) -> pathlib.Path | None:
    """Send every selected case to the executor as one job; return where the outputs came back.

    The job goes through tools/host.py, the one place jobs are sent from, and
    nothing is returned unless it ended well, its tools were measured and they
    are the pinned ones.
    """
    import host
    where = site["tool_files"]
    tool = [where["java/bin/java"], "-cp", where["tla2tools/tla2tools.jar"], "tlc2.TLC"]
    bundle = pathlib.Path(tempfile.mkdtemp(prefix="dodona-batch-")) / "bundle"
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
                          "cwd": model_dir.name, "argv": tool + args})
        if dumps and (model_dir / "dump.cfg").exists():
            cases.append({"name": f"{model_dir.name}/dump", "cwd": model_dir.name, "keep": ["states.dump"],
                          "argv": tool + ["-workers", "1", "-config", "dump.cfg", "-dump", "states", "MCDump.tla"]})
    if not cases:
        return None
    job = host.send_job(site, bundle, cases)
    fault = host.job_fault(job)
    if fault:
        print(f"nothing is judged: {fault}")
        return None
    return job["fetched"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--site", type=pathlib.Path, help="JSON file describing the site's executor")
    mode.add_argument("--replay", type=pathlib.Path,
                      help="read saved outputs again. For looking, not for proof: it cannot know whether the job that left them completed")
    mode.add_argument("--runs", type=pathlib.Path,
                      help="judge what tools/host.py collected, and only if that job ended well with the pinned tools")
    ap.add_argument("--report", type=pathlib.Path, help="write the JSON report here")
    ap.add_argument("--only", action="append", default=[], metavar="MODEL",
                    help="run only this model directory under spec/ (may be repeated)")
    ap.add_argument("--save", type=pathlib.Path, help="keep each case's raw output under this directory")
    ap.add_argument("--batch", action="store_true", help="send all cases to the executor as one job")
    ap.add_argument("--dumps", action="store_true",
                    help="with --batch: also have each model that has a dump.cfg write out its states")
    args = ap.parse_args()

    site = json.loads(args.site.read_text(encoding="utf-8")) if args.site else None
    if args.site and not args.batch:
        ap.error("--site needs --batch: cases are sent to the executor as one job, never one at a time")
    sent: set[str] | None = None
    if args.runs:
        import host
        collected = json.loads((args.runs / "runs.json").read_text(encoding="utf-8"))
        sent = {item["obligation"]["name"] for item in collected.get("pending", [])}
        if collected.get("sent"):
            fault = host.job_fault(collected)
            if fault:
                print(f"nothing is judged: {fault}")
                print(json.dumps({"cases": 0, "matched": 0, "all_matched": False}))
                return 1
        if not sent:
            reused = len((collected.get("plan") or {}).get("reuse", []))
            print(f"nothing was run: {reused} checks kept their results from earlier runs, and the ledger says what they are")
            print(json.dumps({"cases": 0, "reused": reused, "all_matched": True}))
            return 0
        fault = host.job_fault(collected)
        if fault:
            print(f"nothing is judged: {fault}")
            print(json.dumps({"cases": 0, "matched": 0, "all_matched": False}))
            return 1
        args.replay = args.runs / "outputs"
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
            if sent is not None and f"{model_dir.name}/{name}" not in sent:
                continue  # not run this time: its result from an earlier run still counts
            exit_code: int | None
            if args.replay:
                out_file = args.replay / model_dir.name / f"{name}.out"
                if not out_file.exists():
                    out_file = args.replay / model_dir.name / f"{name}.txt"
                exit_file = args.replay / model_dir.name / f"{name}.exit"
                if out_file.exists() and exit_file.exists():
                    output = out_file.read_text(encoding="utf-8", errors="replace")
                    text = exit_file.read_text().strip()
                    exit_code = int(text) if text.lstrip("-").isdigit() else None  # "did-not-start" is not a run
                else:
                    output, exit_code = "", None
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
    if args.replay and not (args.runs or args.batch):
        summary["proof"] = False
        print("read from saved outputs: this says what the files show, not that a job completed")
    if args.report:
        args.report.write_text(json.dumps({"summary": summary, "cases": report}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0 if summary["all_matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
