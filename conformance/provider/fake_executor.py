"""An executor that runs nothing. Part of the conformance kit.

    python fake_executor.py

A host gives it one run on standard input as {"number": N, "run_key": K, "run": <run description>}
and reads one report from standard output. How the run ends is taken from DODONA_EXECUTOR_END:

- `exited`: a report as protocol/messages.schema.json describes it, for the platform and tools
  the run described, exit status 0, and a captured output that is a real file in the project;
- `other-platform`, `other-tool`: the same, but on another platform, or with another tool digest;
- `report-with-a-fraction`: an exited report whose exit status is written `0.0`, which strict reading refuses;
- `fails`: exits with status 1 and prints nothing; `silent`: exits 0 and prints nothing;
- `exits-1-with-report`: prints a complete exited report and then exits with status 1, so the status alone
  must end the check;
- `leaves-a-child`: starts a process that sleeps, writes its id to DODONA_TEST_PIDFILE, then reports an exited
  run and exits; the host must end every process of the executor's process group or job when it returns;
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
    report = {"handle": "h", "end": END if END not in ("other-platform", "other-tool", "report-with-a-fraction", "exits-1-with-report", "leaves-a-child") else "exited", "exit_status": 0, "platform": platform, "isolation": "best-effort", "outputs": [],
              "tools_ran": tools, "captured_output": {"path": "captured.txt", "identity": identity}}
if END == "leaves-a-child":
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(os.environ["DODONA_TEST_PIDFILE"], "a", encoding="utf-8") as f:
        f.write(f"{child.pid}\n")
text = json.dumps(report)
if END == "report-with-a-fraction":
    text = text.replace('"exit_status": 0', '"exit_status": 0.0')  # read strictly, a report like this is no report
sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
if END == "exits-1-with-report":
    sys.stdout.buffer.flush()
    sys.exit(1)
