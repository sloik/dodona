"""Compare two kernels on inputs the conformance kit does not contain. Stage-0 helper (decision 0023).

    python tools/kernel_differential.py [--rounds N] [--seed S] --a <kernel command> --b <kernel command>

The kit checks the fields its scenarios name, on the step orders its authors
thought of. Two kernels written apart can both pass it and still differ. Here
every scenario of the kit is replayed with its steps drawn again at random,
repeated, dropped and reordered, and the two kernels must give the same
answer in full: every field of every result, not only the ones the kit names.

Each step of a scenario is valid in any order by the contract, so both
kernels must answer. One that fails where the other answers is a difference.
Agreement is not correctness: two kernels can be wrong the same way. The
sequence is fixed by the seed, so a difference can be shown again.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def ask(command: list[str], scenario: dict):
    try:
        done = subprocess.run(command + ["scenario"], input=json.dumps(scenario).encode("utf-8"), capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as err:
        return {"did-not-answer": type(err).__name__}
    if done.returncode != 0:
        return {"did-not-answer": "exit"}
    try:
        return json.loads(done.stdout.decode("utf-8"))
    except ValueError:
        return {"did-not-answer": "not-json"}


def variants(scenario: dict, rounds: int, rng: random.Random):
    steps = [{"do": step["do"]} for step in scenario["steps"]]
    base = {k: v for k, v in scenario.items() if k not in ("claim", "covers", "why", "steps")}
    for _ in range(rounds):
        length = rng.randint(1, max(2, 2 * len(steps)))
        yield dict(base, steps=[rng.choice(steps) for _ in range(length)])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=20, help="variants per scenario")
    ap.add_argument("--seed", type=int, default=20261117)
    ap.add_argument("--a", nargs="+", required=True)
    ap.add_argument("--b", nargs="+", required=True)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    compared = differed = unanswered = 0
    for path in sorted(ROOT.glob("conformance/kernel/*/*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        for number, variant in enumerate(variants(scenario, args.rounds, rng), start=1):
            one, two = ask(args.a, variant), ask(args.b, variant)
            compared += 1
            if "did-not-answer" in one and "did-not-answer" in two:
                unanswered += 1  # the kit's steps are valid in any order, so this is counted and reported
            if one != two:
                differed += 1
                if differed <= 5:
                    print(f"DIFFERENT {path.parent.name}/{path.stem}, variant {number} (seed {args.seed}):")
                    print("  input:", json.dumps(variant)[:1500])
                    print("  first: ", json.dumps(one, sort_keys=True)[:700])
                    print("  second:", json.dumps(two, sort_keys=True)[:700])
    print(json.dumps({"compared": compared, "different": differed, "neither_answered": unanswered,
                      "all_agree": differed == 0 and unanswered == 0 and compared > 0}))
    return 0 if differed == 0 and unanswered == 0 and compared else 1


if __name__ == "__main__":
    sys.exit(main())
