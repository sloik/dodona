"""Judge a host against the misbehaving provider. Stage-0 helper (decision 0023).

    python tools/run_provider_cases.py -- <host command>

The host command is given the limits and the provider to start, in the form
tools/provider_host.py takes them. For each case in
conformance/provider/cases.json the judge checks that the host reported the
expected outcome and reason, returned within the deadline plus the grace
period, and that no process the provider started is still running. Exit status
is 0 only if every case matched.
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROVIDER = ROOT / "conformance" / "provider" / "misbehaving_provider.py"


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        handle = k32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return code.value == 259
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # A process that has ended and not yet been collected still answers; look closer.
    try:
        state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(state) and not state.startswith("Z")
    except OSError:
        return True


def same(a, b) -> bool:
    """Equal as JSON text, so a boolean never stands in for a number, nor a float for an integer."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def sent_problems(case: dict, seen: pathlib.Path, limits: dict) -> list[str]:
    """What the host sent, as the provider recorded it, against what the session text requires."""
    got = [json.loads(line) for line in seen.read_text(encoding="utf-8").splitlines() if line] if seen.exists() else []
    problems = []
    hello = got[0] if got else None
    echo = hello.get("echo") if isinstance(hello, dict) else None
    if not (isinstance(hello, dict) and hello.get("type") == "hello"):
        problems.append("the session did not open with hello")
    elif not (same({k: v for k, v in hello.items() if k != "echo"},
                   {"type": "hello", "protocol": ["0.2"], "limits": {"max_line_bytes": limits["max_line_bytes"], "deadline_ms": limits["deadline_ms"]}})
              and isinstance(echo, str) and any(ord(c) > 127 for c in echo) and any(ord(c) < 32 for c in echo)):
        problems.append("hello was not the message the session text gives")
    requests = [m for m in got if isinstance(m, dict) and m.get("type") == "request"]
    want = {"type": "request", "id": "1", "deadline_ms": limits["deadline_ms"], "capability": "decision.index", "body": {"files": []}}
    if any(not same(m, want) for m in requests) or len(requests) > 1:
        problems.append("the request was not the one the session text gives")
    if case["outcome"] == "ok":
        if not requests:
            problems.append("no request was sent")
        if not got or not same(got[-1], {"type": "shutdown"}):
            problems.append("the session did not end with shutdown")
    return problems


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    host = sys.argv[sys.argv.index("--") + 1:]
    spec = json.loads((ROOT / "conformance" / "provider" / "cases.json").read_text(encoding="utf-8"))
    limits = spec["limits"]
    failed = 0
    for case in spec["cases"]:
        problems = []
        with tempfile.TemporaryDirectory() as tmp:
            pidfile = pathlib.Path(tmp) / "pids"
            seen = pathlib.Path(tmp) / "seen"
            env = dict(os.environ, DODONA_TEST_PIDFILE=str(pidfile), DODONA_TEST_SEEN=str(seen))
            command = host + ["--deadline-ms", str(limits["deadline_ms"]), "--max-line", str(limits["max_line_bytes"]),
                              "--max-log", str(limits["max_log_bytes"]), "--", sys.executable, str(PROVIDER), case["mode"]]
            started = time.monotonic()
            try:
                done = subprocess.run(command, capture_output=True, env=env,
                                      timeout=(limits["deadline_ms"] + limits["grace_ms"]) / 1000 + 20)
                took = (time.monotonic() - started) * 1000
                try:
                    answer = json.loads(done.stdout.decode("utf-8"))
                except ValueError:
                    answer = None
                if not isinstance(answer, dict):
                    problems.append("the host printed no JSON object")
                else:
                    if answer.get("outcome") != case["outcome"]:
                        problems.append(f"outcome {answer.get('outcome')!r}, expected {case['outcome']!r} (reason given: {answer.get('reason')!r})")
                    elif case["outcome"] == "error" and answer.get("reason") != case["reason"]:
                        problems.append(f"reason {answer.get('reason')!r}, expected {case['reason']!r}")
                    if "log_truncated" in case and answer.get("log_truncated") != case["log_truncated"]:
                        problems.append(f"log_truncated {answer.get('log_truncated')!r}, expected {case['log_truncated']!r}")
                    if answer.get("log_bytes", 0) and not isinstance(answer.get("log_bytes"), int):
                        problems.append("log_bytes is not a number")
                if took > limits["deadline_ms"] + limits["grace_ms"]:
                    problems.append(f"took {took:.0f} ms, over the deadline plus grace")
            except subprocess.TimeoutExpired:
                problems.append("the host itself did not return")
            time.sleep(0.3)
            problems += sent_problems(case, seen, limits)
            pids = [int(p) for p in pidfile.read_text().split()] if pidfile.exists() else []
            left = [p for p in pids if alive(p)]
            if left:
                problems.append(f"{len(left)} process(es) started by the provider are still running")
                for pid in left:  # do not leave them for the next case
                    try:
                        if sys.platform == "win32":
                            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                        else:
                            os.kill(pid, 9)
                    except OSError:
                        pass
        if problems:
            failed += 1
            print(f"MISMATCH {case['mode']}: " + "; ".join(problems))
        else:
            print(f"match    {case['mode']}")
    total = len(spec["cases"])
    print(json.dumps({"cases": total, "matched": total - failed, "all_matched": failed == 0 and total > 0}))
    return 0 if failed == 0 and total else 1


if __name__ == "__main__":
    sys.exit(main())
