"""A small reference host for one provider session. Stage-0 helper (decision 0023).

    python tools/provider_host.py [--deadline-ms N] [--max-line N] [--max-log N] -- <provider command>

Starts the provider, exchanges hello, one request and shutdown, and prints one
JSON object:

    {"outcome": "ok" | "error", "reason": "<code>", "log_bytes": N, "log_truncated": true | false}

It exists to show that the session rules in protocol/README.md can be kept on
macOS, Linux and Windows, and to be judged by the misbehaving provider in the
conformance kit. It checks framing, encoding, line length, deadlines and
message envelopes. It does not validate message bodies against the schemas.

Rules it keeps:
- one message per line, ended by a single line feed; a carriage return or a
  byte-order mark is an error
- a line longer than the limit is an error, and is never buffered whole
- standard error is drained all the time and kept only up to a cap
- one deadline, on a clock that cannot be set back, covers the whole session
- whatever happens, every process the provider started is gone at the end
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time

WINDOWS = sys.platform == "win32"


class Tree:
    """Starts a process so that it, and everything it starts, can be ended together."""

    def __init__(self, argv: list[str]):
        self.job = None
        if WINDOWS:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.CreateJobObjectW.restype = wintypes.HANDLE
            k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            self._k32 = k32
            self.job = k32.CreateJobObjectW(None, None)
            # Started suspended, so nothing can be spawned before it is in the job.
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, creationflags=0x00000004)
            k32.AssignProcessToJobObject(self.job, wintypes.HANDLE(int(self.proc._handle)))
            ntdll = ctypes.WinDLL("ntdll")
            ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
            ntdll.NtResumeProcess(wintypes.HANDLE(int(self.proc._handle)))
        else:
            self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, start_new_session=True)

    def end(self) -> None:
        if WINDOWS:
            self._k32.TerminateJobObject(self.job, 1)
            self._k32.CloseHandle(self.job)
        else:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def read_lines(stream, max_line: int, out: "queue.Queue") -> None:
    """Hand over each line, or a marker, without ever holding more than the limit."""
    buffered = b""
    while True:
        chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
        if not chunk:
            out.put(("closed", buffered))
            return
        buffered += chunk
        while b"\n" in buffered:
            line, buffered = buffered.split(b"\n", 1)
            if len(line) > max_line:
                out.put(("too-long", b""))
                return
            out.put(("line", line))
        if len(buffered) > max_line:
            out.put(("too-long", b""))
            return


def drain(stream, cap: int, state: dict) -> None:
    while True:
        chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
        if not chunk:
            return
        state["bytes"] += len(chunk)
        room = cap - len(state["kept"])
        if room > 0:
            state["kept"] += chunk[:room]
        if state["bytes"] > cap:
            state["truncated"] = True


def session(argv: list[str], deadline_ms: int, max_line: int, max_log: int) -> dict:
    log = {"bytes": 0, "kept": b"", "truncated": False}
    try:
        tree = Tree(argv)
    except OSError:
        return {"outcome": "error", "reason": "could-not-start", "log_bytes": 0, "log_truncated": False}
    lines: "queue.Queue" = queue.Queue()
    threading.Thread(target=read_lines, args=(tree.proc.stdout, max_line, lines), daemon=True).start()
    threading.Thread(target=drain, args=(tree.proc.stderr, max_log, log), daemon=True).start()
    ends = time.monotonic() + deadline_ms / 1000

    def fail(reason: str) -> dict:
        return {"outcome": "error", "reason": reason}

    def send(obj: dict) -> bool:
        try:
            tree.proc.stdin.write(json.dumps(obj).encode("utf-8") + b"\n")
            tree.proc.stdin.flush()
            return True
        except (BrokenPipeError, OSError):
            return False

    def receive():
        """Return a message object, or a failure."""
        left = ends - time.monotonic()
        if left <= 0:
            return fail("deadline")
        try:
            kind, raw = lines.get(timeout=left)
        except queue.Empty:
            return fail("deadline")
        if kind == "too-long":
            return fail("too-long")
        if kind == "closed":
            return fail("closed")
        if raw.startswith(b"\xef\xbb\xbf") or raw.endswith(b"\r"):
            return fail("framing")
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return fail("encoding")
        try:
            message = json.loads(text)
        except ValueError:
            return fail("malformed")
        if not isinstance(message, dict) or not isinstance(message.get("type"), str):
            return fail("malformed")
        return message

    def run() -> dict:
        if not send({"type": "hello", "protocols": ["0.2"], "limits": {"max_line_bytes": max_line}}):
            return fail("closed")
        manifest = receive()
        if manifest.get("outcome") == "error":
            return manifest
        if manifest.get("type") != "manifest":
            return fail("unexpected")
        if not send({"type": "request", "id": "1", "capability": "decision.index", "body": {"files": []}}):
            return fail("closed")
        answer = receive()
        if answer.get("outcome") == "error":
            return answer
        if answer.get("type") not in ("result", "error"):
            return fail("unexpected")
        if answer.get("id") != "1":
            return fail("wrong-id")
        send({"type": "shutdown"})
        # Anything more from the provider after its one answer is not ignored.
        try:
            kind, _ = lines.get(timeout=max(0.0, min(0.5, ends - time.monotonic())))
            if kind in ("line", "too-long"):
                return fail("unexpected")
        except queue.Empty:
            pass
        return {"outcome": "ok"}

    try:
        result = run()
    finally:
        tree.end()
    time.sleep(0.05)  # let the drain thread see the end of the stream
    result["log_bytes"] = log["bytes"]
    result["log_truncated"] = log["truncated"]
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--deadline-ms", type=int, default=3000)
    ap.add_argument("--max-line", type=int, default=1048576)
    ap.add_argument("--max-log", type=int, default=65536)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        print(__doc__)
        return 2
    print(json.dumps(session(command, args.deadline_ms, args.max_line, args.max_log)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
