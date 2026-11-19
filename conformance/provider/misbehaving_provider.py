"""A provider that misbehaves on purpose. Part of the conformance kit.

    python misbehaving_provider.py <mode>

It speaks just enough of the provider protocol to be started by a host: it
reads a `hello`, answers with a manifest, reads one request and answers it,
then waits for `shutdown`. In every mode but `well-behaved` it does one thing
wrong. `cases.json` lists the modes with the outcome a host must reach.

If the environment variable DODONA_TEST_PIDFILE is set, the provider appends
its own process id, and the id of any process it starts, to that file, one per
line, so a judge can check that nothing is left running afterwards.
"""
import json
import os
import subprocess
import sys
import time

MODE = sys.argv[1] if len(sys.argv) > 1 else "well-behaved"
OUT = sys.stdout.buffer


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
    return json.loads(line.decode("utf-8")) if line else None


def manifest(echo):
    return {"type": "manifest", "echo": echo + (" changed" if MODE == "wrong-echo" else ""),
            "manifest": {"protocol": "0.2", "name": "misbehaving", "version": "0",
                         "capabilities": [{"capability": "decision.index"}], "tools": [], "trusted_base": []}}


def sleeper() -> None:
    """Start a process that outlives this one and keeps the output pipe open."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    note_pid(child.pid)


def main() -> None:
    note_pid(os.getpid())
    hello = read() or {}
    if MODE == "byte-order-mark":
        OUT.write(b"\xef\xbb\xbf")
    if MODE == "garbage":
        OUT.write(b"this is not JSON\n")
        OUT.flush()
        time.sleep(600)
    if MODE == "not-an-object":
        send([1, 2, 3])
        time.sleep(600)
    if MODE == "exits-before-answering":
        return
    if MODE == "never-answers":
        time.sleep(600)
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
        time.sleep(600)
    if MODE == "over-long-line":
        answer["body"]["padding"] = "x" * (4 * 1024 * 1024)
    if MODE == "half-a-line":
        OUT.write(b'{"type": "result", "id": ')
        OUT.flush()
        time.sleep(600)
    if MODE == "late":
        time.sleep(600)
    if MODE == "flood-on-standard-error":
        chunk = b"E" * 65536
        for _ in range(96):  # about 6 MiB
            sys.stderr.buffer.write(chunk)
        sys.stderr.buffer.flush()
    if MODE in ("leaves-a-process-behind", "leaves-a-process-behind-and-hangs"):
        sleeper()
    if MODE == "leaves-a-process-behind-and-hangs":
        time.sleep(600)
    if MODE == "two-answers":
        send(answer)
    send(answer)
    read()  # shutdown


if __name__ == "__main__":
    main()
