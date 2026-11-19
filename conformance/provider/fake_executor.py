"""An executor that runs nothing. Part of the conformance kit.

    python fake_executor.py

A host gives it one run on standard input as {"number": N, "run_key": K, "run": <run description>}
and reads one report from standard output. How the run ends is taken from DODONA_EXECUTOR_END:

- `exited`: a report as protocol/messages.schema.json describes it, for the platform and tools
  the run described, exit status 0, and a captured output that is a real file in the project;
- `other-platform`, `other-tool`: the same, but on another platform, or with another tool digest;
- `fails`: exits with status 1 and prints nothing; `silent`: exits 0 and prints nothing;
- anything else: a complete report with that `end`, which the host must treat as a run that did not finish.

It appends what it was given to DODONA_EXECUTOR_RECORD, so the judge can count the runs that were
really started and the keys they were started under, without taking the host's word.
"""
import hashlib
import json
import os
import sys

END = os.environ.get("DODONA_EXECUTOR_END", "exited")
asked = json.loads(sys.stdin.buffer.read().decode("utf-8"))
with open(os.environ["DODONA_EXECUTOR_RECORD"], "a", encoding="utf-8") as log:
    log.write(json.dumps({"number": asked.get("number"), "run_key": asked.get("run_key"), "run": asked.get("run")}) + "\n")
if END == "fails":
    sys.exit(1)
if END == "silent":
    sys.exit(0)
run = asked.get("run") or {}
if True:
    # Every report is complete, whatever its end, so a run that did not exit differs from one that did
    # in its end alone, and each rule is judged on its own.
    captured = os.path.join(os.environ["DODONA_EXECUTOR_ROOT"], "captured.txt")
    with open(captured, "rb") as f:
        identity = "sha256:" + hashlib.sha256(f.read()).hexdigest()
    tools = [dict(t) for t in run.get("tools", [])]
    if END == "other-tool" and tools:
        tools[0]["digest"] = "sha256:" + "d" * 64
    platform = {"os": "macos", "arch": "x86_64"} if END == "other-platform" else run.get("platform")
    report = {"handle": "h", "end": END if END not in ("other-platform", "other-tool") else "exited", "exit_status": 0, "platform": platform, "isolation": "best-effort", "outputs": [],
              "tools_ran": tools, "captured_output": {"path": "captured.txt", "identity": identity}}
sys.stdout.buffer.write(json.dumps(report).encode("utf-8") + b"\n")
