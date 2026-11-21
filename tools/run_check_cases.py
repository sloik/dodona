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
not on any command line.

Only a completed answer is judged: the host exited 0 within its time and
printed one JSON object with a string `outcome`. A host that could not start,
ran out of time (it is ended through subprocess.run's own handle on the process
this judge started, and nothing else is ever ended), exited other than 0, or
printed anything else has answered nothing, and the case is `UNFINISHED`. So is
a case whose records cannot be observed: a transcript, run record or
process-id file that is not a regular file the judge created, too large, or
malformed; a missing transcript or process id, except for the cases whose
curated expectation is a refusal before the provider starts (outcome
`refused`, reason `bad-input` or `unknown-file`, zero runs: ten cases), where
the provider must never have been started; this is read from the curated case,
never from the answer. An empty run record, created by the judge, proves that
no run was given. The host reads its standard input from a private regular
file and writes its standard output to another, read back capped; no pipe is
shared with anything the host leaves behind. Survival is told by the
cooperative fixture through the one probe-and-stop of
tools/run_provider_cases.py (`watch_fixture`): a fresh nonce per case, a probe
file, then always a stop file; a recorded id is only asked about, never
signalled. A case is named by its mode, run ending and a
digest of its whole curated content, so two cases with the same label differ.

Exit status is 0 if every judged case matched, 1 if the run completed with
mismatches, and 2 if any case did not finish or no case was judged.

The reference host is `python tools/host.py check`.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import secrets
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import canonical  # noqa: E402
import run_provider_cases as observing  # noqa: E402  the capped reads, id checks and cooperative stop

KIT = ROOT / "conformance" / "provider"
OBLIGATION = {"binding": "b", "name": "o", "kind": "check", "specified_by": ["a.txt"], "targets": ["a.txt"], "expect": "holds", "config": {}}
TOOLS = [{"name": "checker", "version": "1", "digest": "sha256:" + "c" * 64}]
PLATFORM = {"os": "linux", "arch": "aarch64", "libc": "gnu"}
HOST_SECONDS = 120
RECORD_LIMIT = 1 << 26  # the largest transcript or run record the fixture writes, with every many_inputs entry
ANSWER_LIMIT = 1 << 20  # the most of the host's standard output that is ever read
Unobserved = observing.Unobserved


def preflight(case: dict) -> bool:
    """A case whose curated expectation is a refusal before the provider starts. Read from the fixture only,
    never from what the host answered."""
    return (case.get("outcome") == "refused" and case.get("reason") in ("unknown-file", "bad-input")
            and type(case.get("runs")) is int and case.get("runs") == 0)


def case_id(case: dict) -> str:
    """A stable identifier of the whole curated case, beside its readable label."""
    return hashlib.sha256(json.dumps(case, sort_keys=True, ensure_ascii=True).encode("ascii")).hexdigest()[:16]


def records(path: pathlib.Path) -> list:
    """The JSON lines the fixture wrote to a file the judge created. Missing, not regular, too large, not UTF-8,
    or holding anything but JSON objects: Unobserved."""
    data = observing.read_private(path, RECORD_LIMIT)
    if data is None:
        raise Unobserved(f"{path.name}, created by the judge, is gone")
    try:
        lines = [json.loads(line, parse_constant=observing.not_json) for line in data.decode("utf-8").splitlines() if line]
    except ValueError as err:
        raise Unobserved(f"{path.name} could not be read: {type(err).__name__}: {err}") from err
    if not all(isinstance(line, dict) for line in lines):
        raise Unobserved(f"{path.name} holds a line that is not a JSON object")
    return lines


def read_answer(path: pathlib.Path) -> dict:
    """The host's answer, from the private regular file its standard output went to: one JSON object with a string
    outcome. Anything else, an oversized or vanished file included, is no answer."""
    stdout = observing.read_private(path, ANSWER_LIMIT)
    if stdout is None:
        raise Unobserved("the host's standard output file, created by the judge, is gone")
    try:
        answer = json.loads(stdout.decode("utf-8"), parse_constant=observing.not_json)
    except ValueError as err:
        raise Unobserved(f"the host exited 0 without a JSON answer: {type(err).__name__}") from err
    if not isinstance(answer, dict) or not isinstance(answer.get("outcome"), str):
        raise Unobserved("the host exited 0 without a JSON object naming an outcome")
    return answer


def same(a, b) -> bool:
    """Equal as JSON text, so a boolean never stands in for a number, nor a float for an integer."""
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


# Modes in which the provider stops reading, or is still asleep when the host gives up on it, so it
# cannot record a shutdown that was sent.
CANNOT_SEE_SHUTDOWN = {"stops-reading", "too-slow"}


def judge(case: dict, host: list[str], tmp: pathlib.Path) -> tuple[list[str], list[str]]:
    """Run one case in its private folder: what the host got wrong, and what left the case unfinished."""
    problems: list[str] = []
    unfinished: list[str] = []
    nonce = secrets.token_hex(16)  # this case's: an acknowledgment left by any other case or run is not this one's
    if True:
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
        if case.get("non_ascii_input"):
            inputs.append({"path": "\u00c9.txt", "identity": "sha256:" + "0" * 64})
        if case.get("names_a_missing_spec"):
            obligation["specified_by"] = ["a.txt", "spec.txt"]
        tools = [dict(t) for t in TOOLS]
        for key, value in case.get("change_input", {}).items():
            # A host input that breaks its own shape: the host must refuse it, not crash.
            target, field = key.split(".")
            if target == "asked":
                continue  # applied to the whole input below
            item = {"obligation": obligation, "tool": tools[0], "input": inputs[0]}[target]
            if value is None:
                item.pop(field, None)
            else:
                item[field] = value
        asked = {"root": str(project), "provider": [sys.executable, str(KIT / "misbehaving_checker.py")],
                 "obligation": obligation, "inputs": inputs, "tools": tools, "platform": PLATFORM,
                 "executor": [sys.executable, str(KIT / "fake_executor.py")], "deadline_ms": case.get("deadline_ms", 20000)}
        for key, value in case.get("change_input", {}).items():
            target, field = key.split(".")
            if target == "asked":
                if value is None:
                    asked.pop(field, None)
                else:
                    asked[field] = value
        sent = json.dumps(asked) if "whole_input" not in case else json.dumps(case["whole_input"])
        if "input_text" in case:
            sent = case["input_text"]  # text that is not JSON at all
        env = dict(os.environ, DODONA_CHECKER_MODE=case["mode"], DODONA_TEST_SEEN=str(seen), DODONA_TEST_PIDFILE=str(pidfile),
                   DODONA_EXECUTOR_END=case["run"], DODONA_EXECUTOR_RECORD=str(record), DODONA_EXECUTOR_ROOT=str(project),
                   **observing.fixture_env(tmp, nonce))
        # The exact text sent, from a private regular file; the answer, into another. No pipe: a pipe inherited by
        # something the host left behind would hold subprocess.run past its own timeout on Windows.
        stdin_path, stdout_path = tmp / "stdin", tmp / "stdout"
        with open(stdin_path, "xb") as handle:
            handle.write(sent.encode("utf-8"))
        seen_by = {"answer": None}

        def work():
            with open(stdin_path, "rb") as given, open(stdout_path, "xb") as answered:
                try:
                    # On a timeout, subprocess.run ends the host through its own handle on the process it started.
                    done = subprocess.run(host, stdin=given, stdout=answered, stderr=subprocess.DEVNULL, env=env,
                                          timeout=HOST_SECONDS)
                except subprocess.TimeoutExpired:
                    done = None
                    unfinished.append(f"the host did not return within {HOST_SECONDS} s")
                except OSError as err:
                    done = None
                    unfinished.append(f"the host could not be started: {type(err).__name__}: {err}")
            if done is not None:
                if done.returncode != 0:
                    unfinished.append(f"the host exited with {done.returncode}, so it gave no answer")
                else:
                    try:
                        seen_by["answer"] = read_answer(stdout_path)
                    except Unobserved as err:
                        unfinished.append(str(err))
            deadline = time.monotonic() + observing.OBSERVE_SECONDS
            time.sleep(0.3)
            pids: list[int] = []
            try:
                seen_by["transcript"] = records(seen)
                seen_by["given"] = records(record)  # created empty by the judge: empty proves no run was given
                data = observing.read_private(pidfile, observing.LIMITS["pids"])
                if data is None:
                    raise Unobserved("the process-id file, created by the judge, is gone")
                if data.strip() or not preflight(case):
                    pids = observing.read_pids(pidfile)
            except Unobserved as err:
                unfinished.append(str(err))
                seen_by["answer"] = None  # nothing about the host follows from records that could not be read
            if seen_by.get("transcript") == [] and not preflight(case):
                unfinished.append("the checker's transcript is empty, and only a refusal before the provider starts may leave it so")
                seen_by["answer"] = None
            return pids, deadline

        gone_wrong, gone_unfinished = observing.watch_fixture(tmp, nonce, work)
        problems += gone_wrong
        unfinished += gone_unfinished
    answer = seen_by["answer"]
    if answer is None:
        return problems, unfinished  # no completed answer: nothing below is judged
    transcript, given_and_printed = seen_by["transcript"], seen_by["given"]
    got_msgs = [r for r in transcript if "got" in r]
    described = [r["described"] for r in transcript if "described" in r]
    started = [r for r in given_and_printed if "number" in r]
    printed = [r["printed"] for r in given_and_printed if "printed" in r]
    want = {k: case[k] for k in ("outcome", "verdict", "reason") if k in case}
    if {k: answer.get(k) for k in want} != want:
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
        if type(given.get("number")) is not int or given.get("number") != n:
            problems.append(f"run {n} was given to the executor as number {given.get('number')!r}")
        if given.get("run_key") != canonical.identity({"check": check_key, "run": n, "description": canonical.identity(given.get("run"))}):
            problems.append(f"run {n} was not given the key the contract gives")
    starts = [m for m in got_msgs if m["got"] == "start"]
    if starts and not same(starts[0].get("body"), {"obligation": obligation, "inputs": inputs, "tools": tools, "platform": PLATFORM}):
        problems.append("the start request did not carry the obligation, inputs, tools and platform the host was given")
    hellos = [m for m in got_msgs if m["got"] == "hello"]
    echo = hellos[0].get("echo") if hellos else None
    if hellos and not (isinstance(echo, str) and any(ord(c) > 127 for c in echo) and any(ord(c) < 32 for c in echo)):
        problems.append("hello's echo did not hold both a non-ASCII and a control character")
    if hellos:
        envelope = hellos[0].get("hello") or {}
        limits = envelope.get("limits")
        if not (same(envelope.get("protocol"), ["0.2"]) and isinstance(limits, dict)
                and all(type(limits.get(k)) is int for k in ("max_line_bytes", "deadline_ms"))):
            problems.append("hello did not offer protocol 0.2 with its limits")
    if any(m.get("capability") != "obligation.check" for m in got_msgs if m["got"] in ("start", "run.result")):
        problems.append("a request was sent for another capability than obligation.check")
    if hellos and case["mode"] not in CANNOT_SEE_SHUTDOWN and got_msgs[-1]["got"] != "shutdown":
        problems.append("the session did not end with shutdown")
    results = [m for m in got_msgs if m["got"] == "run.result"]
    for m in results:
        n = m.get("run")
        if type(n) is not int or not 1 <= n <= len(printed) or not same(m.get("report"), printed[n - 1]):
            problems.append(f"run {n!r} was passed back with a report other than the one the executor printed")
    if case["run"] in ("exited", "leaves-a-child", "slow"):
        for n in range(1, len(started) + 1):
            if not any(type(m.get("run")) is int and m.get("run") == n and start_ids and m.get("check") == start_ids[0] for m in results):
                problems.append(f"run {n} exited and was not passed back to the provider under the start request's id")
    elif results:
        problems.append("the provider was asked to interpret a run that did not exit")
    if "distinct_run_keys" in case and len({g.get("run_key") for g in started}) != case["distinct_run_keys"]:
        problems.append(f"expected {case['distinct_run_keys']} runs each under its own key")
    return problems, unfinished


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    host = sys.argv[sys.argv.index("--") + 1:]
    try:
        spec = json.loads((KIT / "check-cases.json").read_text(encoding="utf-8"))
        cases = spec["cases"]
        if not isinstance(cases, list) or not all(isinstance(c, dict) and isinstance(c.get("mode"), str)
                                                  and isinstance(c.get("run"), str) for c in cases):
            raise ValueError("cases is not a list of modes with run endings")
    except (OSError, ValueError, KeyError, TypeError) as err:
        print(f"UNFINISHED the cases could not be read: {type(err).__name__}: {err}")
        print(json.dumps({"cases": 0, "judged": 0, "skipped": 0, "matched": 0, "all_matched": False,
                          "unfinished": 1, "rejected": []}))
        return 2
    rejected: list[str] = []
    unfinished = skipped = 0
    for case in cases:
        label = f"{case['mode']} ({case['run']}) [{case_id(case)}]"
        if sys.platform in case.get("not_on", []):
            skipped += 1
            print(f"skip     {label}: not on {sys.platform}, where the provider cannot make what the case needs")
            continue
        wrong: list[str] = []
        broken: list[str] = []
        try:
            tmp = pathlib.Path(tempfile.mkdtemp(prefix="dodona-check-case-"))  # private: mode 0700, this case only
        except OSError as err:
            broken.append(f"no temporary folder could be made: {err}")
        else:
            try:
                wrong, broken = judge(case, host, tmp)
            except Exception as err:  # the judge itself failed: the case is unfinished, never a match
                broken.append(f"the judge failed: {type(err).__name__}: {err}")
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
            print(f"UNFINISHED {label}: " + "; ".join(broken + wrong))
        elif wrong:
            rejected.append(label)
            print(f"MISMATCH {label}: {'; '.join(wrong)}")
        else:
            print(f"match    {label}")
    total = len(cases)
    judged = total - skipped
    # A case skipped on this platform is reported as skipped, never as matched.
    print(json.dumps({"cases": total, "judged": judged, "skipped": skipped,
                      "matched": judged - len(rejected) - unfinished,
                      "all_matched": not rejected and not unfinished and judged > 0,
                      "unfinished": unfinished, "rejected": rejected}))
    if unfinished or not judged:
        return 2
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
