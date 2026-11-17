"""Run a kernel against the conformance kit and judge it.

Stage-0 helper (decision 0023).

    python tools/run_kit.py -- <kernel command and arguments>

For each scenario under conformance/kernel/, the kernel command is started
with the scenario as JSON on standard input and must print one JSON object:

    {"results": [ <result after step 1>, <result after step 2>, ... ]}

The shape of a result is described in conformance/README.md. Every field a
scenario expects must be present and equal; fields it does not mention are
ignored. Exit status is 0 only if every scenario matched. A kernel that
crashes, times out or prints something else fails that scenario.
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
    failed = 0
    for path in scenarios:
        scenario = json.loads(path.read_text(encoding="utf-8"))
        try:
            done = subprocess.run(command, input=json.dumps(scenario), capture_output=True, text=True,
                                  encoding="utf-8", timeout=60)
            diffs = judge(scenario, done.stdout) if done.returncode == 0 else [f"kernel exited with {done.returncode}"]
        except (OSError, subprocess.TimeoutExpired) as err:
            diffs = [f"kernel did not run to completion: {type(err).__name__}"]
        name = f"{path.parent.name}/{path.stem}"
        if diffs:
            failed += 1
            print(f"MISMATCH {name}")
            for line in diffs:
                print(f"    {line}")
        else:
            print(f"match    {name}")
    print(json.dumps({"scenarios": len(scenarios), "matched": len(scenarios) - failed,
                      "all_matched": failed == 0 and bool(scenarios)}))
    return 0 if failed == 0 and scenarios else 1


if __name__ == "__main__":
    sys.exit(main())
