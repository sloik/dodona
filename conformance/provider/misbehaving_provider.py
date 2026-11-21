"""A provider that misbehaves on purpose. Part of the conformance kit.

    python misbehaving_provider.py <mode>

It speaks just enough of the provider protocol to be started by a host: it
reads a `hello`, answers with a manifest, reads one request and answers it,
then waits for `shutdown`. In every mode but `well-behaved` it does one thing
wrong. `cases.json` lists the modes with the outcome a host must reach.

If DODONA_TEST_SEEN is set, every message the provider receives is appended to that file, one per line.
If the environment variable DODONA_TEST_PIDFILE is set, the provider appends
its own process id, and the id of any process it starts, to that file, one per
line, so a judge can check that nothing is left running afterwards.
While they wait, the provider and the process it leaves behind answer a judge's
files: they acknowledge DODONA_TEST_PROBE and DODONA_TEST_STOP with
DODONA_TEST_NONCE in DODONA_TEST_ACK, and exit on the stop file, so a judge can
tell what is still running and clear it up without signalling a recorded id.
"""
import json
import os
import subprocess
import sys
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "well-behaved"
OUT = sys.stdout.buffer
# How every waiting process of the fixture waits, the provider and the child it leaves behind alike: up to ten
# minutes, looking every tenth of a second for the judge's files. Once DODONA_TEST_PROBE exists it creates
# alive-<pid> in DODONA_TEST_ACK, holding DODONA_TEST_NONCE; once DODONA_TEST_STOP exists it creates stopped-<pid>
# the same way and exits. Files are created only if absent. The judge never has to signal a process by its id.
POLL = r'''
import os, time
def _note(kind):
    folder, nonce = os.environ.get("DODONA_TEST_ACK"), os.environ.get("DODONA_TEST_NONCE")
    if folder and nonce:
        try:
            with open(os.path.join(folder, "%s-%d" % (kind, os.getpid())), "x", encoding="ascii") as handle:
                handle.write(nonce)
        except OSError:
            pass
def wait():
    probe, stop, told = os.environ.get("DODONA_TEST_PROBE"), os.environ.get("DODONA_TEST_STOP"), False
    for _ in range(6000):
        if not told and probe and os.path.exists(probe):
            _note("alive")
            told = True
        if stop and os.path.exists(stop):
            _note("stopped")
            os._exit(0)
        time.sleep(0.1)
'''
exec(POLL)  # defines wait(), the same code the child left behind runs


def note_pid(pid: int) -> None:
    path = os.environ.get("DODONA_TEST_PIDFILE")
    if path:
        with open(path, "a", encoding="ascii") as handle:
            handle.write(f"{pid}\n")


def send(obj, ending: bytes = b"\n") -> None:
    OUT.write(json.dumps(obj).encode("utf-8") + ending)
    OUT.flush()


def read():
    line = sys.stdin.buffer.readline()
    message = json.loads(line.decode("utf-8")) if line else None
    seen = os.environ.get("DODONA_TEST_SEEN")
    if seen and message is not None:
        # For the judge only: every message as it arrived, so what the host sends is judged, not taken on its word.
        with open(seen, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(message) + "\n")
    return message


def manifest(echo):
    return {"type": "manifest", "echo": echo + (" changed" if MODE == "wrong-echo" else ""),
            "manifest": {"protocol": "0.2", "name": "misbehaving", "version": "0",
                         "capabilities": [{"capability": "decision.index"}], "tools": [], "trusted_base": []}}


def sleeper() -> None:
    """Start a process that outlives this one and keeps the output pipe open."""
    child = subprocess.Popen([sys.executable, "-c", POLL + "wait()\n"])
    note_pid(child.pid)


def main() -> None:
    note_pid(os.getpid())
    hello = read() or {}
    if MODE == "byte-order-mark":
        OUT.write(b"\xef\xbb\xbf")
    if MODE == "garbage":
        OUT.write(b"this is not JSON\n")
        OUT.flush()
        wait()
    if MODE == "not-an-object":
        send([1, 2, 3])
        wait()
    if MODE == "exits-before-answering":
        return
    if MODE == "never-answers":
        wait()
    if MODE == "loose-but-valid-json":
        # Valid JSON that the strict reading of a check would refuse: a session reads it as JSON.
        text = json.dumps(manifest(hello.get("echo", "")))[:-1] + ', "extra": {"v": 1.5, "w": 1, "w": 2, "deep": ' + "[" * 70 + "]" * 70 + "}}"
        OUT.write(text.encode("utf-8") + b"\n")
        OUT.flush()
    else:
        send(manifest(hello.get("echo", "")), b"\r\n" if MODE == "carriage-return" else b"\n")
    request = read()
    if request is None:
        return
    answer = {"type": "result", "id": request.get("id"), "capability": request.get("capability"), "body": {"decisions": []}}
    if MODE == "wrong-id":
        answer["id"] = "not-the-id-that-was-asked"
    if MODE == "answers-with-an-error":
        answer = {"type": "error", "id": request.get("id"), "code": "internal", "message": "no"}
    if MODE == "answers-another-capability":
        answer["capability"] = "obligation.check"
    if MODE == "bad-encoding":
        OUT.write(b'{"type": "result", "id": "\xff\xfe"}\n')
        OUT.flush()
        wait()
    if MODE == "over-long-line":
        answer["body"]["padding"] = "x" * (4 * 1024 * 1024)
    if MODE == "half-a-line":
        OUT.write(b'{"type": "result", "id": ')
        OUT.flush()
        wait()
    if MODE == "late":
        wait()
    if MODE == "flood-on-standard-error":
        chunk = b"E" * 65536
        for _ in range(96):  # about 6 MiB
            sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()
    if MODE in ("leaves-a-process-behind", "leaves-a-process-behind-and-hangs"):
        sleeper()
    if MODE == "leaves-a-process-behind-and-hangs":
        wait()
    if MODE == "two-answers":
        send(answer)
    if MODE == "nan-in-an-answer":
        OUT.write(('{"type": "result", "id": %s, "capability": %s, "body": {"x": NaN}}\n'
                   % (json.dumps(request.get("id")), json.dumps(request.get("capability")))).encode("utf-8"))
        OUT.flush()
        wait()
    send(answer)
    read()  # shutdown
    if MODE == "ignores-shutdown":
        wait()


if __name__ == "__main__":
    main()
