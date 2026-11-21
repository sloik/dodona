"""Judge a host against the misbehaving provider. Stage-0 helper (decision 0023).

    python tools/run_provider_cases.py -- <host command>

The host command is given the limits and the provider to start, in the form
tools/provider_host.py takes them. For each case in
conformance/provider/cases.json the judge checks that the host reported the
expected outcome and reason, returned within the deadline plus the grace
period, sent what the session text requires (as the provider recorded it), and
that no process the provider started is still running.

The host's contract (conformance/README.md, "The command") is one JSON object
on standard output; it says nothing of the exit status. The reference host and
both kernels exit 0 after printing a session's answer, their refusals included,
and exit otherwise only when they could not complete it. This judge therefore
judges only an answer completed with exit 0 that is one JSON object with a
string `outcome`. A host that could not be started, ran out of time, exited
other than 0 (a signal included), or exited 0 without such an object (not
UTF-8, not JSON, NaN, not an object, no string outcome) has answered nothing,
and that case is `UNFINISHED`. A host that runs out of time is ended through
the handle this judge holds on the process it started itself (subprocess.run's
own timeout); nothing else is ever ended.

A case is also `UNFINISHED` when the fixture could not be observed: a
transcript that is missing (every mode records hello before anything else, and
no case declares an absent transcript), not a regular file, too large or
unreadable; a process-id file likewise, or one holding anything but distinct
decimal ids in the platform's range (no process is asked about such a file);
an acknowledgment that is not a regular file, malformed, or not this case's; a
recorded process present after the host returned that did not acknowledge; a
survivor that did not acknowledge the stop file in time; or a temporary folder
that could not be removed. An unfinished case's folder is kept as evidence. A
completed answer that names the wrong outcome, reason or log flag or comes too
late, a wrong transcript, and a fixture process that acknowledged it was still
running before cleanup began are `MISMATCH`, named in `rejected`. A case with
both is unfinished.

Survival is told by the fixture, not by a process's id or command line: an id
read from a file may by then belong to another process. Each case gets a fresh
random nonce and its own private folder; after the host returns, the judge
creates the case's probe file, and every waiting fixture process answers with
`alive-<pid>` holding the nonce. What has acknowledged is fixed in a snapshot
taken before the stop file exists. Then, in a `finally` and even when
observation failed, the judge creates the stop file, on which each process
writes `stopped-<pid>` and exits. An acknowledgment that appears only after
the stop file was created never counts as survival seen before cleanup: such a
survivor leaves the case unfinished, not a mismatch. Every marker file is
created only if absent.

A recorded id is otherwise only asked about, never acted on. On POSIX, signal 0
says whether an id exists, and `ps -o stat= -p <id>` whether it is a zombie
(exited, not yet reaped), which signal 0 cannot tell; only a clearly reported
`Z` counts as exited, and a missing, late, failed or unexpected answer is
unknown. On Windows, OpenProcess and a zero wait (never os.kill, which ends a
process there). Neither tells whose a present process is, so a present id that
never acknowledged is unknown and never a pass. Every look and wait of a case,
each `ps` included, shares one deadline on the monotonic clock.

Exit status is 0 if every case matched, 1 if the run completed with
mismatches, and 2 if any case or the judge itself did not finish, after
mismatches too, or no case ran.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROVIDER = ROOT / "conformance" / "provider" / "misbehaving_provider.py"
WINDOWS = sys.platform == "win32"
# One budget, on the monotonic clock, for every look and wait after the host returned: settling, the probe, the stop.
OBSERVE_SECONDS = 6.0
PROBE_SECONDS = 1.5  # within OBSERVE_SECONDS: how long waiting fixture processes have to answer the probe
POLL = 0.1
# The largest process id the platform can name: pid_t is a signed 32-bit integer on POSIX, a DWORD on Windows.
PID_MAX = 0xFFFFFFFF if WINDOWS else 0x7FFFFFFF
# How much of each file the fixture writes is ever read: anything larger is not the fixture's.
LIMITS = {"seen": 1 << 20, "pids": 4096, "ack": 256}
ACK_NAME = re.compile(r"(alive|stopped)-([0-9]{1,10})")
STAT = re.compile(r"[A-Za-z][A-Za-z<>+]*")


class Unobserved(Exception):
    """What the fixture recorded could not be read: nothing about the host follows from it."""


def read_private(path: pathlib.Path, limit: int) -> bytes | None:
    """The bytes of a regular file the fixture wrote, or None if there is none. Anything else, a link, a pipe, a
    device, a folder, or a file over `limit`, is quarantined: never followed, never opened for blocking, never read."""
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as err:
        raise Unobserved(f"{path.name} could not be looked at: {type(err).__name__}: {err}") from err
    if not stat.S_ISREG(before.st_mode):
        raise Unobserved(f"{path.name} is not a regular file, so it is not read")
    if before.st_size > limit:
        raise Unobserved(f"{path.name} is larger than the fixture ever writes ({before.st_size} bytes)")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags)
    except OSError as err:
        raise Unobserved(f"{path.name} could not be opened: {type(err).__name__}: {err}") from err
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise Unobserved(f"{path.name} changed into something else while it was opened")
        data = os.read(fd, limit + 1)
    except OSError as err:
        raise Unobserved(f"{path.name} could not be read: {type(err).__name__}: {err}") from err
    finally:
        os.close(fd)
    if len(data) > limit:
        raise Unobserved(f"{path.name} is larger than the fixture ever writes")
    return data


def valid_pid(text: str) -> int | None:
    """A process id the platform can name, written as plain decimal digits; None for anything else."""
    if not re.fullmatch(r"[0-9]{1,10}", text):
        return None
    pid = int(text)
    if pid <= 1 or pid > PID_MAX or pid == os.getpid():
        return None
    return pid


def zombie_posix(pid: int, deadline: float, run=subprocess.run) -> str:
    """'zombie', 'live' or 'unknown', from `ps -o stat= -p <pid>`, bounded by the case's deadline. Read only."""
    left = deadline - time.monotonic()
    if left <= 0:
        return "unknown"
    try:
        said = run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, timeout=left,
                   env=dict(os.environ, LC_ALL="C"))
    except (OSError, subprocess.SubprocessError, ValueError, UnicodeError):
        return "unknown"
    if said.returncode != 0:
        return "unknown"
    words = (said.stdout or "").split()
    if len(words) != 1 or not STAT.fullmatch(words[0]):
        return "unknown"
    return "zombie" if words[0].startswith("Z") else "live"


def exists_posix(pid: int, deadline: float, kill=os.kill, run=subprocess.run) -> str:
    """'gone', 'present' or 'unknown'. Signal 0 asks and changes nothing; `ps` tells an unreaped exit apart."""
    try:
        kill(pid, 0)
    except ProcessLookupError:
        return "gone"
    except PermissionError:
        pass  # some process has the id; whose is not known
    except OSError:
        return "unknown"
    state = zombie_posix(pid, deadline, run)
    if state == "zombie":
        return "gone"
    return "present" if state == "live" else "unknown"


def exists_windows(pid: int) -> str:
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(0x1000 | 0x00100000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE
    if not handle:
        return "gone" if ctypes.get_last_error() == 87 else "unknown"  # 87: no process has this id
    try:
        waited = k32.WaitForSingleObject(handle, 0)
    finally:
        k32.CloseHandle(handle)
    return {0: "gone", 0x102: "present"}.get(waited, "unknown")


def observe(pid: int, deadline: float) -> str:
    if valid_pid(str(pid)) != pid:
        return "unknown"  # never asked about: only an id read_pids accepted reaches the system
    return exists_windows(pid) if WINDOWS else exists_posix(pid, deadline)


def create(path: pathlib.Path, text: str) -> str | None:
    """Create `path` only if it is absent. None when made, else why not."""
    try:
        with open(path, "x", encoding="ascii") as handle:
            handle.write(text)
        return None
    except OSError as err:
        return f"{type(err).__name__}: {err}"


def read_acks(folder: pathlib.Path, nonce: str, pids: list[int]) -> tuple[set, set, list[str]]:
    """The recorded ids that acknowledged the probe and the stop with this case's nonce, and anything malformed."""
    alive, stopped, bad = set(), set(), []
    try:
        if not stat.S_ISDIR(os.lstat(folder).st_mode):
            return alive, stopped, ["the acknowledgment folder is not a folder"]
        names = sorted(os.listdir(folder))
    except OSError as err:
        return alive, stopped, [f"the acknowledgments could not be read: {err}"]
    for name in names:
        matched = ACK_NAME.fullmatch(name)
        pid = valid_pid(matched.group(2)) if matched else None
        if pid is None or pid not in pids:
            bad.append(f"acknowledgment {name!r} is not one of a recorded process")
            continue
        try:
            text = read_private(folder / name, LIMITS["ack"])
        except Unobserved as err:
            bad.append(f"acknowledgment {name!r}: {err}")
            continue
        if text != nonce.encode("ascii"):
            bad.append(f"acknowledgment {name!r} is not this case's")
        else:
            (alive if matched.group(1) == "alive" else stopped).add(pid)
    return alive, stopped, bad


def same(a, b) -> bool:
    """Equal as JSON text, so a boolean never stands in for a number, nor a float for an integer."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def not_json(text):
    raise ValueError(f"{text} is not JSON")


def read_transcript(seen: pathlib.Path) -> list:
    """Every message the provider recorded. Every mode records hello first, so a missing transcript is no observation."""
    data = read_private(seen, LIMITS["seen"])
    if data is None:
        raise Unobserved("the provider's transcript is missing, and no case declares it absent")
    try:
        return [json.loads(line, parse_constant=not_json) for line in data.decode("utf-8").splitlines() if line]
    except ValueError as err:
        raise Unobserved(f"the provider's transcript could not be read: {type(err).__name__}: {err}") from err


def read_pids(pidfile: pathlib.Path) -> list[int]:
    """The distinct process ids the provider recorded, at least one: its own is written before anything else. A file
    with anything but valid ids is refused whole, before any process is asked about."""
    data = read_private(pidfile, LIMITS["pids"])
    if data is None:
        raise Unobserved("the provider recorded no process id, so it was not seen to start")
    try:
        words = data.decode("ascii").split()
    except UnicodeDecodeError as err:
        raise Unobserved("the provider's process-id file is not ASCII") from err
    pids = [valid_pid(word) for word in words]
    if not words or None in pids:
        raise Unobserved(f"the provider's process-id file holds no ids, or one that is not a process id: {words[:8]}")
    return list(dict.fromkeys(pids))  # an id written twice is one process: it is asked about once


def sent_problems(case: dict, got: list, limits: dict) -> list[str]:
    """What the host sent, as the provider recorded it, against what the session text requires."""
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


def read_answer(stdout: bytes) -> dict:
    """The host's answer: one JSON object with a string outcome. Anything else is no answer."""
    try:
        answer = json.loads(stdout.decode("utf-8"), parse_constant=not_json)
    except ValueError as err:  # UnicodeDecodeError included
        raise Unobserved(f"the host exited 0 without a JSON answer: {type(err).__name__}") from err
    if not isinstance(answer, dict) or not isinstance(answer.get("outcome"), str):
        raise Unobserved("the host exited 0 without a JSON object naming an outcome")
    return answer


def answer_problems(case: dict, answer: dict, took: float, limits: dict) -> list[str]:
    """What is wrong with an answer the host completed with exit 0."""
    problems = []
    if answer["outcome"] != case["outcome"]:
        problems.append(f"outcome {answer['outcome']!r}, expected {case['outcome']!r} (reason given: {answer.get('reason')!r})")
    elif case["outcome"] == "error" and answer.get("reason") != case["reason"]:
        problems.append(f"reason {answer.get('reason')!r}, expected {case['reason']!r}")
    if "log_truncated" in case and answer.get("log_truncated") != case["log_truncated"]:
        problems.append(f"log_truncated {answer.get('log_truncated')!r}, expected {case['log_truncated']!r}")
    if answer.get("log_bytes", 0) and not isinstance(answer.get("log_bytes"), int):
        problems.append("log_bytes is not a number")
    if took > limits["deadline_ms"] + limits["grace_ms"]:
        problems.append(f"took {took:.0f} ms, over the deadline plus grace")
    return problems


def fixture_env(tmp: pathlib.Path, nonce: str) -> dict:
    """The files through which a case's cooperative fixture is probed and stopped. The folder `tmp/ack` is made here."""
    (tmp / "ack").mkdir(mode=0o700)
    return {"DODONA_TEST_ACK": str(tmp / "ack"), "DODONA_TEST_PROBE": str(tmp / "probe"),
            "DODONA_TEST_STOP": str(tmp / "stop"), "DODONA_TEST_NONCE": nonce}


def watch_fixture(tmp: pathlib.Path, nonce: str, work) -> tuple[list[str], list[str]]:
    """The one probe-and-stop of every judge of a cooperative fixture. `work()` runs the host and reads the records,
    returning (pids, deadline), deadline None if it ended before observation began. Then the probe, the snapshot taken
    before the stop file exists, and, in a `finally` even when `work` or observation failed, the stop file. Returns
    the mismatches and what left the case unfinished. A recorded id is only asked about, never signalled."""
    wrong: list[str] = []
    unfinished: list[str] = []
    ack, probe, stop = tmp / "ack", tmp / "probe", tmp / "stop"
    pids: list[int] = []
    present: list[int] = []
    before_stop: set = set()  # acknowledged before the stop file existed: the only survival a mismatch rests on
    deadline = None
    try:
        pids, deadline = work()
        if pids and deadline is not None:
            why = create(probe, nonce)
            if why:
                unfinished.append(f"the probe file could not be created: {why}")
            else:
                ends = min(deadline, time.monotonic() + PROBE_SECONDS)
                while True:
                    alive, _, _ = read_acks(ack, nonce, pids)
                    present = [pid for pid in pids if pid not in alive and observe(pid, deadline) != "gone"]
                    if not present or time.monotonic() >= ends:
                        break
                    time.sleep(POLL)
                before_stop, _, _ = read_acks(ack, nonce, pids)  # the snapshot, taken before the stop file exists
                present = [pid for pid in present if pid not in before_stop]
                if before_stop:
                    wrong.append(f"{len(before_stop)} process(es) started by the provider acknowledged they were"
                                 " still running")
    finally:
        # Asked even when observation failed, so that whatever of the fixture still waits can exit.
        why = create(stop, nonce)
        if why:
            unfinished.append(f"the stop file could not be created: {why}")
    if deadline is None:
        return wrong, unfinished
    # After the stop: only `stopped-<pid>` and absence are read; an `alive` written now is not survival seen before.
    _, stopped, bad = read_acks(ack, nonce, pids)
    waiting = sorted(before_stop | set(present))
    while waiting and time.monotonic() < deadline:
        time.sleep(POLL)
        _, stopped, bad = read_acks(ack, nonce, pids)
        waiting = [pid for pid in waiting if pid not in stopped and observe(pid, deadline) != "gone"]
    unfinished += bad
    late = sorted(pid for pid in stopped if pid not in before_stop)
    if late:
        unfinished.append(f"process(es) {late} survived, shown only by acknowledging the stop file, not before cleanup")
    silent = sorted(pid for pid in present if pid not in stopped)
    if silent:
        unfinished.append(f"process id(s) {silent} were present after the host returned and never acknowledged:"
                          " whose they are is unknown")
    if waiting:
        unfinished.append(f"process(es) {waiting} were not seen to stop before the deadline; nothing was signalled")
    return wrong, unfinished


def judge_case(host: list[str], case: dict, limits: dict, tmp: pathlib.Path) -> tuple[list[str], list[str]]:
    """Run one case in its private folder `tmp`: what the host got wrong, and what left the case unfinished."""
    wrong: list[str] = []
    unfinished: list[str] = []
    nonce = secrets.token_hex(16)  # this case's: an acknowledgment left by any other case or run is not this one's
    pidfile, seen = tmp / "pids", tmp / "seen"
    env = dict(os.environ, DODONA_TEST_PIDFILE=str(pidfile), DODONA_TEST_SEEN=str(seen), **fixture_env(tmp, nonce))
    command = host + ["--deadline-ms", str(limits["deadline_ms"]), "--max-line", str(limits["max_line_bytes"]),
                      "--max-log", str(limits["max_log_bytes"]), "--", sys.executable, str(PROVIDER), case["mode"]]
    allowed = (limits["deadline_ms"] + limits["grace_ms"]) / 1000 + 20

    def work():
        nonlocal wrong
        started = time.monotonic()
        try:
            # On a timeout, subprocess.run ends the host through its own handle on the process it started.
            done = subprocess.run(command, capture_output=True, env=env, timeout=allowed)
        except subprocess.TimeoutExpired:
            unfinished.append(f"the host did not return within {allowed:.0f} s")
        except OSError as err:
            unfinished.append(f"the host could not be started: {type(err).__name__}: {err}")
        else:
            took = (time.monotonic() - started) * 1000
            if done.returncode != 0:
                unfinished.append(f"the host exited with {done.returncode}, so it gave no answer")
            else:
                try:
                    wrong += answer_problems(case, read_answer(done.stdout), took, limits)
                except Unobserved as err:
                    unfinished.append(str(err))
        deadline = time.monotonic() + OBSERVE_SECONDS
        time.sleep(0.3)
        got = None
        try:
            got = read_transcript(seen)
        except Unobserved as err:
            unfinished.append(str(err))
        try:
            pids = read_pids(pidfile)
        except Unobserved as err:
            unfinished.append(str(err))
            pids = []
        if got is not None and pids:
            wrong += sent_problems(case, got, limits)
        return pids, deadline

    seen_wrong, seen_unfinished = watch_fixture(tmp, nonce, work)
    return wrong + seen_wrong, unfinished + seen_unfinished


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    host = sys.argv[sys.argv.index("--") + 1:]
    try:
        spec = json.loads((ROOT / "conformance" / "provider" / "cases.json").read_text(encoding="utf-8"))
        limits = spec["limits"]
        cases = spec["cases"]
        if not isinstance(cases, list) or not all(isinstance(c, dict) and isinstance(c.get("mode"), str) for c in cases):
            raise ValueError("cases is not a list of modes")
    except (OSError, ValueError, KeyError, TypeError) as err:
        print(f"UNFINISHED the cases could not be read: {type(err).__name__}: {err}")
        print(json.dumps({"cases": 0, "matched": 0, "all_matched": False, "unfinished": 1, "rejected": []}))
        return 2
    rejected: list[str] = []
    unfinished = 0
    for case in cases:
        wrong: list[str] = []
        broken: list[str] = []
        try:
            tmp = pathlib.Path(tempfile.mkdtemp(prefix="dodona-provider-case-"))  # private: mode 0700, this case only
        except OSError as err:
            broken.append(f"no temporary folder could be made: {err}")
        else:
            try:
                wrong, broken = judge_case(host, case, limits, tmp)
            finally:
                if broken:
                    broken.append(f"the case's folder {tmp} is kept as evidence, with its stop file")
                else:
                    try:
                        shutil.rmtree(tmp)
                    except OSError as err:
                        broken.append(f"the case's temporary folder could not be removed: {err}")
        if broken:
            unfinished += 1
            print(f"UNFINISHED {case['mode']}: " + "; ".join(broken + wrong))
        elif wrong:
            rejected.append(case["mode"])
            print(f"MISMATCH {case['mode']}: " + "; ".join(wrong))
        else:
            print(f"match    {case['mode']}")
    total = len(cases)
    print(json.dumps({"cases": total, "matched": total - len(rejected) - unfinished,
                      "all_matched": not rejected and not unfinished and total > 0,
                      "unfinished": unfinished, "rejected": rejected}))
    if unfinished or not total:
        return 2
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
