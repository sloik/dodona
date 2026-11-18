"""Judge tools/host.py against the misbehaving checker. Stage-0 helper (decision 0023).

    python tools/run_check_cases.py

For each case in conformance/provider/check-cases.json the checker is started
in one mode and one obligation is taken through the host. The judge stands in
for the executor, so nothing is really run. Exit status is 0 only if every
case matched.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import host  # noqa: E402

ROOT = host.ROOT
OBLIGATION = {"binding": "b", "name": "o", "kind": "check", "specified_by": ["a.txt"], "targets": ["a.txt"], "expect": "holds", "config": {}}
INPUTS = [{"path": "a.txt", "identity": "sha256:" + "a" * 64}]  # a name only; the judge stands in for the executor
TOOLS = [{"name": "checker", "version": "1", "digest": "sha256:" + "c" * 64}]


def main() -> int:
    spec = json.loads((ROOT / "conformance" / "provider" / "check-cases.json").read_text(encoding="utf-8"))
    captured = ROOT / "conformance" / "provider" / "check-cases.json"  # any readable file serves as the captured output
    failed = 0
    for case in spec["cases"]:
        seen = {"runs": 0}

        def report_for(number, description, case=case, seen=seen):
            seen["runs"] += 1
            if seen["runs"] > 50:
                raise host.Refused("the-judge-stopped-a-check-that-never-ends")
            if case["run"] != "exited":
                return {"end": case["run"]}
            return {"handle": "h", "end": "exited", "exit_status": 0, "platform": host.PLATFORM, "isolation": "best-effort", "outputs": [],
                    "tools_ran": [{"name": "checker", "digest": TOOLS[0]["digest"]}],
                    "captured_output": {"path": captured.relative_to(ROOT).as_posix(), "identity": "sha256:" + "0" * 64}}

        transcript: list = []
        session = None
        try:
            session = host.Session([sys.executable, str(ROOT / "conformance" / "provider" / "misbehaving_checker.py"), case["mode"]], ROOT, transcript, deadline_s=20)
            got = host.drive_check(session, OBLIGATION, INPUTS, TOOLS, report_for)
            final = got["final"]
            verdict = "unavailable" if final.get("reason") == "run-unavailable" else final["verdict"]
            result = {"outcome": "verdict", "verdict": verdict}
            seen["keys"] = got.get("run_keys", [])
        except host.Refused as err:
            result = {"outcome": "refused", "reason": str(err)}
        finally:
            if session is not None:
                session.close()
        interpreted = any(m["to"] == "provider" and m["message"].get("body", {}).get("op") == "run.result" for m in transcript)
        want = {k: case[k] for k in ("outcome", "verdict", "reason") if k in case}
        problems = []
        if result != want:
            problems.append(f"expected {want}, got {result}")
        if case.get("ran") is False and seen["runs"]:
            problems.append("the run was started")
        if "runs" in case and seen["runs"] != case["runs"]:
            problems.append(f"expected {case['runs']} runs to be started, {seen['runs']} were")
        if case.get("asked_to_interpret") is False and interpreted:
            problems.append("the provider was asked to interpret a run that did not exit")
        if "distinct_run_keys" in case and len(set(seen.get("keys", []))) != case["distinct_run_keys"]:
            problems.append(f"expected {case['distinct_run_keys']} runs each under its own key, got keys {seen.get('keys')}")
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
