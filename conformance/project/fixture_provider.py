"""A provider that answers from a file, for the project status cases (decision 0034).

    python conformance/project/fixture_provider.py ANSWERS.json RECORD.jsonl

ANSWERS.json holds `manifest` (the manifest to send; its echo is copied from hello unless
`wrong_echo` is true) and, for each capability, the body to answer with; under `raw`, for a
capability, a line to send as it is instead, with %ID% replaced by the request's id; `delay_ms`, a
wait before each answer; and `long_line`, an answer longer than any line limit a host sets. Every message the host
sends is appended to RECORD.jsonl, so the judge can see what it was asked. A capability with no
answer gets an `error`.
"""
from __future__ import annotations

import json
import sys
import time


def main() -> int:
    answers = json.loads(open(sys.argv[1], encoding="utf-8").read())
    record = open(sys.argv[2], "a", encoding="utf-8")

    def send(message: dict) -> None:
        sys.stdout.buffer.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        sys.stdout.buffer.flush()

    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return 0
        message = json.loads(line.decode("utf-8"))
        record.write(json.dumps(message, ensure_ascii=False) + "\n")
        record.flush()
        kind = message.get("type")
        if kind == "hello":
            echo = "not what was sent" if answers.get("wrong_echo") else message.get("echo", "")
            send({"type": "manifest", "echo": echo, "manifest": answers["manifest"]})
        elif kind == "shutdown":
            return 0
        elif kind == "request":
            capability = message.get("capability")
            if answers.get("delay_ms"):
                time.sleep(answers["delay_ms"] / 1000)
            raw = answers.get("raw", {}).get(capability)
            if raw is not None:
                # Bytes as the case writes them, with the request's id put in: for answers no JSON writer makes.
                sys.stdout.buffer.write(raw.replace("%ID%", str(message["id"])).encode("utf-8") + b"\n")
                sys.stdout.buffer.flush()
            elif answers.get("long_line"):
                body = {"intents": [], "rejected": [], "x": "a" * 1100000}
                send({"type": "result", "id": message["id"], "capability": capability, "body": body})
            elif capability in answers:
                send({"type": "result", "id": message["id"], "capability": capability, "body": answers[capability]})
            else:
                send({"type": "error", "id": message["id"], "code": "unsupported", "detail": "no answer in this case"})


if __name__ == "__main__":
    sys.exit(main())
