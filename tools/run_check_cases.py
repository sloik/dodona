"""Judge a host against the misbehaving checker. Stage-0 helper (decision 0023).

    python tools/run_check_cases.py -- <host command>

For each case in conformance/provider/check-cases.json the host command is
started once, with one JSON object on standard input (conformance/README.md,
"Host checks"):

    {"root": DIR, "provider": [argv], "obligation": {...}, "inputs": [...],
     "tools": [...], "platform": {...}, "executor": [argv], "deadline_ms": N}

The host must take the one obligation through the provider, send each run to
the executor command, keep every rule a schema cannot express, and print one
JSON object: {"outcome": "verdict", "verdict": V} or {"outcome": "refused",
"reason": R}. The judge stands in for the executor (conformance/provider/
fake_executor.py), so nothing is really run, and it counts the runs that were
started, the keys they were started under and the operations the provider was
asked for from records the host does not write. Exit status is 0 only if every
case matched.

The reference host is `python tools/host.py check`.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
KIT = ROOT / "conformance" / "provider"
OBLIGATION = {"binding": "b", "name": "o", "kind": "check", "specified_by": ["a.txt"], "targets": ["a.txt"], "expect": "holds", "config": {}}
INPUTS = [{"path": "a.txt", "identity": "sha256:" + "a" * 64}]  # a name only; the judge stands in for the executor
TOOLS = [{"name": "checker", "version": "1", "digest": "sha256:" + "c" * 64}]
PLATFORM = {"os": "linux", "arch": "aarch64", "libc": "gnu"}


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    host = sys.argv[sys.argv.index("--") + 1:]
    spec = json.loads((KIT / "check-cases.json").read_text(encoding="utf-8"))
    failed = 0
    for case in spec["cases"]:
        with tempfile.TemporaryDirectory() as tmp:
            record, seen = pathlib.Path(tmp) / "runs", pathlib.Path(tmp) / "seen"
            record.write_text("", encoding="utf-8")
            seen.write_text("", encoding="utf-8")
            asked = {"root": str(ROOT), "provider": [sys.executable, str(KIT / "misbehaving_checker.py"), case["mode"]],
                     "obligation": OBLIGATION, "inputs": INPUTS, "tools": TOOLS, "platform": PLATFORM,
                     "executor": [sys.executable, str(KIT / "fake_executor.py"), case["run"], str(record)], "deadline_ms": 20000}
            problems = []
            try:
                done = subprocess.run(host, input=json.dumps(asked).encode("utf-8"), capture_output=True, timeout=120,
                                      env={**__import__("os").environ, "DODONA_TEST_SEEN": str(seen)})
                try:
                    answer = json.loads(done.stdout.decode("utf-8"))
                except ValueError:
                    answer = None
            except subprocess.TimeoutExpired:
                answer = None
                problems.append("the host did not return")
            started = [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]
            ops = [json.loads(line) for line in seen.read_text(encoding="utf-8").splitlines() if line]
            want = {k: case[k] for k in ("outcome", "verdict", "reason") if k in case}
            got = {k: answer[k] for k in ("outcome", "verdict", "reason") if isinstance(answer, dict) and k in answer}
            if not isinstance(answer, dict):
                problems.append("the host printed no JSON object")
            elif got != want:
                problems.append(f"expected {want}, got {got}")
            if case.get("ran") is False and started:
                problems.append("the run was started")
            if "runs" in case and len(started) != case["runs"]:
                problems.append(f"expected {case['runs']} runs to be started, {len(started)} were")
            if case.get("asked_to_interpret") is False and "run.result" in ops:
                problems.append("the provider was asked to interpret a run that did not exit")
            if "distinct_run_keys" in case:
                keys = [r["run_key"] for r in started]
                if len(set(keys)) != case["distinct_run_keys"] or None in keys:
                    problems.append(f"expected {case['distinct_run_keys']} runs each under its own key, the executor was given {keys}")
        label = f"{case['mode']} ({case['run']})"
        if problems:
            failed += 1
            print(f"MISMATCH {label}: {'; '.join(problems)}")
        else:
            print(f"match    {label}")
    total = len(spec["cases"])
    print(json.dumps({"cases": total, "matched": total - failed, "all_matched": failed == 0 and total > 0}))
    return 0 if failed == 0 and total else 1


if __name__ == "__main__":
    sys.exit(main())
