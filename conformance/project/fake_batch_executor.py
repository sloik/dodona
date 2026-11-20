"""An executor that answers batches as a run case scripts it, for the project run cases (decision 0034).

    python conformance/project/fake_batch_executor.py SCRIPT.json RECORD.jsonl

Reads `{"runs": [{"number", "run_key", "run"}]}` on standard input, appends what it was sent to RECORD.jsonl
(one line per batch), and answers `{"ended": true, "reports": [{"run_key", "report"}]}`, each report saying the run
exited on the run's platform with the run's tools. SCRIPT.json's `mode` breaks that in one way: `not-ended`,
`exit-1`, `missing-report`, `extra-report`, `repeated-report`, `unavailable`, `crlf`, `wrong-platform`, `exit-status-1`
(the run exited with status 1). It runs nothing.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    script = json.loads(open(sys.argv[1], encoding="utf-8").read())
    asked = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    with open(sys.argv[2], "a", encoding="utf-8") as record:
        record.write(json.dumps(asked, ensure_ascii=False) + "\n")
    mode = script.get("mode", "")
    reports = []
    for item in asked["runs"]:
        run = item["run"]
        report = {"end": "unavailable" if mode == "unavailable" else "exited", "exit_status": 1 if mode == "exit-status-1" else 0,
                  "platform": {"os": "other", "arch": "x"} if mode == "wrong-platform" else run["platform"],
                  "tools_ran": run["tools"], "isolation": "best-effort", "outputs": []}
        reports.append({"run_key": item["run_key"], "report": report})
    if mode == "missing-report" and reports:
        reports.pop(0)
    if mode == "extra-report":
        reports.append({"run_key": "sha256:" + "0" * 64, "report": reports[0]["report"] if reports else {}})
    if mode == "repeated-report" and reports:
        reports.append(reports[0])
    answer = {"ended": mode != "not-ended", "reports": reports}
    sys.stdout.buffer.write(json.dumps(answer).encode("utf-8") + (b"\r\n" if mode == "crlf" else b"\n"))
    sys.stdout.buffer.flush()
    return 1 if mode == "exit-1" else 0


if __name__ == "__main__":
    sys.exit(main())
