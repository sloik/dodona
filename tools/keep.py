"""What one model run keeps for the next, and what it reports about reuse. Stage-0 helper (decision 0029).

    python tools/keep.py dumps          --plan PLAN --fresh DIR --kept DIR --into DIR
    python tools/keep.py finish         --plan PLAN --ledger FILE --into DIR
    python tools/keep.py summary        --plan PLAN --conclude FILE --status FILE --kept-from FILE
    python tools/keep.py require-passed --status FILE

It judges nothing. Which checks are reused is decided by a kernel in
`tools/host.py plan`; this only moves files and prints what the plan said.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys

STATES = "dump.states.dump"


def dumps(args) -> int:
    """Put each model's list of states in one place: from this run if it ran, else kept from the last."""
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    for model in plan["dumps_run"] + plan["dumps_reuse"]:
        source = (args.fresh if model in plan["dumps_run"] else args.kept) / model / STATES
        if not source.exists():
            print(f"no list of states for {model} at {source}")
            return 1
        if model in plan["dumps_run"]:
            # Made this time: only from a run that ended with status 0 and said it searched everything.
            ended = (args.fresh / model / "dump.exit").read_text(encoding="ascii").strip() if (args.fresh / model / "dump.exit").exists() else ""
            said = (args.fresh / model / "dump.txt").read_text(encoding="utf-8", errors="replace") if (args.fresh / model / "dump.txt").exists() else ""
            if ended != "0" or "Model checking completed. No error has been found." not in said or ", 0 states left on queue." not in said:
                print(f"the list of states for {model} comes from a run that did not finish (exit {ended or 'none'}); it is not used or kept")
                return 1
        target = args.into / model / STATES
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(source, target)
        print(f"{model}: {'made in this run' if model in plan['dumps_run'] else 'kept from the last run'}")
    return 0


def finish(args) -> int:
    """What the next run gets: the ledger as it now stands, and each list of states with what it was made from."""
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    args.into.mkdir(parents=True, exist_ok=True)
    if not args.ledger.exists():
        print("there is no ledger to keep")
        return 1
    shutil.copy(args.ledger, args.into / "dodona.ledger")
    present = {m: k for m, k in plan["dump_keys"].items() if (args.into / "dumps" / m / STATES).exists()}
    (args.into / "dumps").mkdir(parents=True, exist_ok=True)
    (args.into / "dumps" / "dumps.json").write_text(json.dumps(present, indent=1) + "\n", encoding="utf-8")
    return 0


def summary(args) -> int:
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    concluded = json.loads(args.conclude.read_text(encoding="utf-8").strip().splitlines()[-1]) if args.conclude.exists() else {}
    report = json.loads(args.status.read_text(encoding="utf-8")) if args.status.exists() else {}
    source = args.kept_from.read_text(encoding="utf-8").strip() if args.kept_from.exists() else ""
    tally: dict[str, int] = {}
    for item in report.get("obligations", {}).values():
        tally[item["status"]] = tally.get(item["status"], 0) + 1
    print("### Checks in this run\n")
    print("| | Count |\n|---|---|")
    print(f"| Run this time | {len(plan['run'])} |")
    print(f"| Kept their result from an earlier run | {len(plan['reuse'])}" + (f" (ledger from run {source})" if source else "") + " |")
    print(f"| Lists of states made this time / kept | {len(plan['dumps_run'])} / {len(plan['dumps_reuse'])} |")
    for word in ("passed", "failed", "error", "unavailable", "refused"):
        if concluded.get(word):
            print(f"| New results: {word} | {concluded[word]} |")
    print(f"| Status of every check now | {', '.join(f'{n} {s}' for s, n in sorted(tally.items())) or 'none'} |")
    return 0


def require_passed(args) -> int:
    refused = json.loads(args.plan.read_text(encoding="utf-8")).get("refused_by_provider", []) if getattr(args, "plan", None) else []
    if refused:
        print(f"the provider could not make {len(refused)} case(s) into a check: {', '.join(refused[:10])}. A case that cannot be checked has not passed")
        return 1
    report = json.loads(args.status.read_text(encoding="utf-8"))
    checks = report.get("obligations", {})
    other = sorted(name for name, item in checks.items() if item["status"] != "passed")
    if not checks or other:
        print(f"{len(other)} of {len(checks)} checks have no passing result for the inputs as they are now:", ", ".join(other[:20]))
        return 1
    print(f"all {len(checks)} checks have a passing result for the inputs as they are now")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)
    one = sub.add_parser("dumps")
    for name in ("plan", "fresh", "kept", "into"):
        one.add_argument("--" + name, type=pathlib.Path, required=True)
    two = sub.add_parser("finish")
    for name in ("plan", "ledger", "into"):
        two.add_argument("--" + name, type=pathlib.Path, required=True)
    three = sub.add_parser("summary")
    for name in ("plan", "conclude", "status", "kept-from"):
        three.add_argument("--" + name, type=pathlib.Path, required=True)
    four = sub.add_parser("require-passed")
    four.add_argument("--status", type=pathlib.Path, required=True)
    four.add_argument("--plan", type=pathlib.Path, help="the plan of this run, for what the provider refused to list")
    args = ap.parse_args()
    return {"dumps": dumps, "finish": finish, "summary": summary, "require-passed": require_passed}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
