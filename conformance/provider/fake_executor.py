"""An executor that runs nothing. Part of the conformance kit.

    python fake_executor.py <end> <record-file>

A host gives it one run on standard input as {"number": N, "run_key": K, "run": <run description>}
and reads one report from standard output. It reports the run as ended with <end>: `exited` (with
exit status 0 and an empty captured output), or anything else, which the host must treat as a run
that did not finish. It appends what it was given to <record-file>, so the judge can count the runs
that were really started and the keys they were started under, without taking the host's word.
"""
import json
import sys

END, RECORD = sys.argv[1], sys.argv[2]
asked = json.loads(sys.stdin.buffer.read().decode("utf-8"))
with open(RECORD, "a", encoding="utf-8") as log:
    log.write(json.dumps({"number": asked.get("number"), "run_key": asked.get("run_key")}) + "\n")
if END != "exited":
    report = {"end": END}
else:
    report = {"handle": "h", "end": "exited", "exit_status": 0, "platform": asked["run"].get("platform"), "isolation": "best-effort",
              "outputs": [], "tools_ran": asked["run"].get("tools", []),
              "captured_output": {"path": "conformance/provider/check-cases.json", "identity": "sha256:" + "0" * 64}}
sys.stdout.buffer.write(json.dumps(report).encode("utf-8") + b"\n")
