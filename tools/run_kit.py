"""Run a kernel against the conformance kit and judge it.

Stage-0 helper (decision 0023).

    python tools/run_kit.py -- <kernel command and arguments>

For each scenario under conformance/kernel/, the kernel command is started
with the scenario as JSON on standard input, without its expected results,
and must print one JSON object:

    {"results": [ <result after step 1>, <result after step 2>, ... ]}

The shape of a result is described in conformance/README.md. Every field a
scenario expects must be present and equal; fields it does not mention are
ignored. Exit status is 0 if every scenario matched, 1 if the suite completed
with mismatches, and 2 if a process did not complete or no scenarios ran.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def contains(actual, expected) -> bool:
    """True if every field in `expected` is present in `actual` with the same value."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(k in actual and contains(actual[k], v) for k, v in expected.items())
    return actual == expected


def question(scenario: dict) -> dict:
    """What the kernel is shown: the scenario without the answers or the notes about it.

    The first version of this judge sent the whole scenario, expected results
    included, and a program that echoed them back passed every scenario.
    """
    asked = {k: v for k, v in scenario.items() if k not in ("claim", "covers", "why")}
    asked["steps"] = [{"do": step["do"]} for step in scenario["steps"]]
    return asked


def judge(scenario: dict, output: str) -> list[str]:
    """Return the list of differences; empty means the scenario matched."""
    try:
        results = json.loads(output)["results"]
    except (ValueError, KeyError, TypeError):
        return ["output is not a JSON object with a results list"]
    steps = scenario["steps"]
    if not isinstance(results, list) or len(results) != len(steps):
        return [f"expected {len(steps)} results, got {len(results) if isinstance(results, list) else 'none'}"]
    diffs = []
    for number, (step, result) in enumerate(zip(steps, results), start=1):
        if not contains(result, step["expect"]):
            diffs.append(f"step {number}: expected {json.dumps(step['expect'], sort_keys=True)}, "
                         f"got {json.dumps(result, sort_keys=True)}")
    return diffs


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    scenarios = sorted(ROOT.glob("conformance/kernel/*/*.json"))
    rejected: list[str] = []
    unfinished = 0
    for path in scenarios:
        name = f"{path.parent.name}/{path.stem}"
        try:
            scenario = json.loads(path.read_text(encoding="utf-8"))
            done = subprocess.run(command, input=json.dumps(question(scenario)), capture_output=True, text=True,
                                  encoding="utf-8", timeout=60)
        except (OSError, ValueError, subprocess.TimeoutExpired) as err:
            unfinished += 1
            print(f"UNFINISHED {name}: {type(err).__name__}: {err}")
            continue
        if done.returncode != 0:
            unfinished += 1
            print(f"UNFINISHED {name}: kernel exited with {done.returncode}")
            continue
        diffs = judge(scenario, done.stdout)
        if diffs:
            rejected.append(name)
            print(f"MISMATCH {name}")
            for line in diffs:
                print(f"    {line}")
        else:
            print(f"match    {name}")
    matched = len(scenarios) - len(rejected) - unfinished
    print(json.dumps({"scenarios": len(scenarios), "matched": matched,
                      "all_matched": matched == len(scenarios) and bool(scenarios),
                      "unfinished": unfinished, "rejected": rejected}))
    if unfinished or not scenarios:
        return 2
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
