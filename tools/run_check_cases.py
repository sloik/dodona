"""Judge a host against the misbehaving checker. Stage-0 helper (decision 0023).

    python tools/run_check_cases.py -- <host command>

For each case in conformance/provider/check-cases.json the host command is
started once, in a project directory of its own, with one JSON object on
standard input (conformance/README.md, "Host checks"):

    {"root": DIR, "provider": [argv], "obligation": {...}, "inputs": [...],
     "tools": [...], "platform": {...}, "executor": [argv], "deadline_ms": N}

The host must take the one obligation through the provider, send each run to
the executor command, keep every rule a schema cannot express, and print one
JSON object: {"outcome": "verdict", "verdict": V} or {"outcome": "refused",
"reason": R}.

The judge does not take the host's word for what it did. The misbehaving
checker records every message it is sent and every run it describes; the fake
executor records every run it is given. A case matches only if the answer is
the expected one AND the records show the host did the work: the session
opened with hello, every run the executor was given is one the provider
described, in order, under the key and number the contract gives, every run
that exited was passed back to the provider under the start request's id, no
run that must not start was started, and no process the provider started is
still running. The mode and the way a run ends are given in the environment,
not on any command line. Exit status is 0 only if every case matched.

The reference host is `python tools/host.py check`.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import canonical  # noqa: E402

KIT = ROOT / "conformance" / "provider"
OBLIGATION = {"binding": "b", "name": "o", "kind": "check", "specified_by": ["a.txt"], "targets": ["a.txt"], "expect": "holds", "config": {}}
TOOLS = [{"name": "checker", "version": "1", "digest": "sha256:" + "c" * 64}]
PLATFORM = {"os": "linux", "arch": "aarch64", "libc": "gnu"}


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def records(path: pathlib.Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def judge(case: dict, host: list[str]) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        project = pathlib.Path(tmp) / "project"
        (project / "work").mkdir(parents=True)
        (project / "a.txt").write_bytes(b"a\n")
        (project / "evidence.txt").write_bytes(b"what the checker kept\n")
        (project / "captured.txt").write_bytes(b"what the run printed\n")
        seen, record, pidfile = (pathlib.Path(tmp) / n for n in ("seen", "runs", "pids"))
        for f in (seen, record, pidfile):
            f.write_text("", encoding="utf-8")
        inputs = [{"path": "a.txt", "identity": "sha256:" + hashlib.sha256(b"a\n").hexdigest()}]
        if case.get("second_input"):
            (project / "b.txt").write_bytes(b"b\n")
            inputs.append({"path": "b.txt", "identity": "sha256:" + hashlib.sha256(b"b\n").hexdigest()})
        for n in range(case.get("many_inputs", 0)):
            inputs.append({"path": f"many/file-{n:05d}.txt", "identity": "sha256:" + "0" * 64})
        obligation = dict(OBLIGATION)
        if case.get("names_a_missing_file"):
            obligation["targets"] = ["a.txt", "b.txt"]
        tools = [dict(t) for t in TOOLS]
        for key, value in case.get("change_input", {}).items():
            # A host input that breaks its own shape: the host must refuse it, not crash.
            target, field = key.split(".")
            item = {"obligation": obligation, "tool": tools[0], "input": inputs[0]}[target]
            if value is None:
                item.pop(field, None)
            else:
                item[field] = value
        asked = {"root": str(project), "provider": [sys.executable, str(KIT / "misbehaving_checker.py")],
                 "obligation": obligation, "inputs": inputs, "tools": tools, "platform": PLATFORM,
                 "executor": [sys.executable, str(KIT / "fake_executor.py")], "deadline_ms": case.get("deadline_ms", 20000)}
        env = dict(os.environ, DODONA_CHECKER_MODE=case["mode"], DODONA_TEST_SEEN=str(seen), DODONA_TEST_PIDFILE=str(pidfile),
                   DODONA_EXECUTOR_END=case["run"], DODONA_EXECUTOR_RECORD=str(record), DODONA_EXECUTOR_ROOT=str(project))
        proc = subprocess.Popen(host, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        try:
            out, _ = proc.communicate(json.dumps(asked).encode("utf-8"), timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            out = b""
            problems.append("the host did not return")
        try:
            answer = json.loads(out.decode("utf-8"))
        except ValueError:
            answer = None
        time.sleep(0.3)
        got_msgs = [r for r in records(seen) if "got" in r]
        described = [r["described"] for r in records(seen) if "described" in r]
        started = records(record)
        leftover = [int(p) for p in pidfile.read_text(encoding="utf-8").split() if p.strip() and alive(int(p))]
    want = {k: case[k] for k in ("outcome", "verdict", "reason") if k in case}
    if not isinstance(answer, dict):
        problems.append("the host printed no JSON object")
    elif {k: answer.get(k) for k in want} != want:
        problems.append(f"expected {want}, got {{{', '.join(f'{k!r}: {answer.get(k)!r}' for k in want)}}}")
    if case.get("reason") in ("unknown-file", "bad-input"):
        if got_msgs:
            problems.append("the provider was sent something before the check was refused")
    elif not got_msgs or got_msgs[0]["got"] != "hello":
        problems.append("the session did not open with hello")
    if len(started) != case["runs"]:
        problems.append(f"expected {case['runs']} runs to be started, {len(started)} were")
    start_ids = [m["id"] for m in got_msgs if m["got"] == "start"]
    check_key = canonical.identity({"obligation": obligation, "inputs": inputs})
    for n, given in enumerate(started, start=1):
        if n > len(described) or given.get("run") != described[n - 1]:
            problems.append(f"run {n} given to the executor is not the run the provider described")
        if given.get("number") != n:
            problems.append(f"run {n} was given to the executor as number {given.get('number')!r}")
        if given.get("run_key") != canonical.identity({"check": check_key, "run": n, "description": canonical.identity(given.get("run"))}):
            problems.append(f"run {n} was not given the key the contract gives")
    results = [m for m in got_msgs if m["got"] == "run.result"]
    if case["run"] in ("exited", "leaves-a-child"):
        for n in range(1, len(started) + 1):
            if not any(m.get("run") == n and start_ids and m.get("check") == start_ids[0] for m in results):
                problems.append(f"run {n} exited and was not passed back to the provider under the start request's id")
    elif results:
        problems.append("the provider was asked to interpret a run that did not exit")
    if "distinct_run_keys" in case and len({g.get("run_key") for g in started}) != case["distinct_run_keys"]:
        problems.append(f"expected {case['distinct_run_keys']} runs each under its own key")
    if leftover:
        problems.append(f"processes the provider started are still running: {leftover}")
        for pid in leftover:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
    return problems


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    host = sys.argv[sys.argv.index("--") + 1:]
    spec = json.loads((KIT / "check-cases.json").read_text(encoding="utf-8"))
    failed = 0
    for case in spec["cases"]:
        if sys.platform in case.get("not_on", []):
            print(f"skip     {case['mode']} ({case['run']}): not on {sys.platform}, where the provider cannot make what the case needs")
            continue
        problems = judge(case, host)
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
