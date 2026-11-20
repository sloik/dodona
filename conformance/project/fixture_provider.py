"""A provider that answers from a file, for the project status cases (decision 0034).

    python conformance/project/fixture_provider.py ANSWERS.json RECORD.jsonl

ANSWERS.json holds `manifest` (the manifest to send; its echo is copied from hello unless
`wrong_echo` is true) and, for each capability, the body to answer with. Every message the host
sends is appended to RECORD.jsonl, so the judge can see what it was asked. A capability with no
answer gets an `error`.
"""
from __future__ import annotations

import json
import sys


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
            if capability in answers:
                send({"type": "result", "id": message["id"], "capability": capability, "body": answers[capability]})
            else:
                send({"type": "error", "id": message["id"], "code": "unsupported", "detail": "no answer in this case"})


if __name__ == "__main__":
    sys.exit(main())
