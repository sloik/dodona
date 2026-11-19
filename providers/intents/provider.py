"""A provider for dodona's intent files: it answers intent.index (decision 0034).

It speaks the provider protocol on standard input and output. Asked for the intents among the
files it is given, it reads each with intents_md.py, which refuses a file that could be read more
than one way, and answers each intent with its whole text, its owner and worker, its children and
its criteria. Each criterion names the obligations that check it: the obligations the request
lists whose names its `checks` patterns match. So the kernel matches no patterns.

    python providers/intents/provider.py
"""
from __future__ import annotations

import fnmatch
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from intents_md import Unreadable, read as read_intent  # noqa: E402

NAME, VERSION, PROTOCOL = "dodona.intent.markdown", "0.1.0", "0.2"


def send(message: dict) -> None:
    sys.stdout.buffer.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def read():
    line = sys.stdin.buffer.readline()
    return json.loads(line.decode("utf-8")) if line else None


def touches_of(text: str) -> list[str]:
    """The items listed under `touches:` in the front matter."""
    head = text[4:].split("\n---\n", 1)[0].splitlines()
    found, inside = [], False
    for line in head:
        if re.fullmatch(r"[a-z_]+:.*", line):
            inside = line == "touches:"
        elif inside and line.startswith("  - "):
            found.append(line[4:])
    return sorted(set(found))


def index(body: dict) -> dict:
    obligations = sorted({(o["binding"], o["name"]) for o in body.get("obligations", [])})
    intents, rejected, parents = [], [], {}
    for ref in sorted(body["files"], key=lambda f: f["path"]):
        path = ref["path"]
        if not re.fullmatch(r"intents/[0-9][^/]*\.md", path):
            rejected.append({"path": path, "code": "not-an-intent", "detail": "an intent file is intents/ followed by a number and .md"})
            continue
        try:
            fields, items, text = read_intent(pathlib.Path(path))
        except Unreadable as err:
            rejected.append({"path": path, "code": "read-more-than-one-way", "detail": str(err)})
            continue
        ident = fields.get("id", "").strip('"')
        if not ident:
            rejected.append({"path": path, "code": "no-id", "detail": "the front matter gives no id"})
            continue
        criteria = []
        for item in items:
            links = sorted({(b, n) for pattern in item.get("checks", []) for b, n in obligations if fnmatch.fnmatchcase(n, pattern)})
            criteria.append({"id": item["id"], "statement": item["words"], "gate": item["gate"],
                             "links": [{"binding": b, "obligation": n} for b, n in links]})
        intent = {"name": ident, "file": path, "statement": fields.get("title", ""), "text": text,
                  "owner": {"id": fields.get("owner", "")}, "criteria": criteria, "children": [], "touches": touches_of(text)}
        if fields.get("worker"):
            intent["worker"] = {"id": fields["worker"]}
        intents.append(intent)
        parents[ident] = fields.get("parent", "").strip('"')
    by_name = {i["name"]: i for i in intents}
    for ident, parent in parents.items():
        if parent in by_name:
            by_name[parent]["children"].append(ident)
    for intent in intents:
        intent["children"].sort()
    return {"intents": intents, "amendments": [], "rejected": rejected}


def main() -> int:
    hello = read()
    if not hello:
        return 1
    send({"type": "manifest", "echo": hello.get("echo", ""), "manifest": {
        "protocol": PROTOCOL, "name": NAME, "version": VERSION,
        "capabilities": [{"capability": "intent.index", "determinism": "deterministic"}],
        "tools": [], "trusted_base": ["the intent files are read as the repository holds them"]}})
    while True:
        message = read()
        if message is None or message.get("type") == "shutdown":
            return 0
        body, capability = message.get("body", {}), message.get("capability")
        try:
            if capability == "intent.index":
                answer = index(body)
            else:
                send({"type": "error", "id": message.get("id"), "code": "unsupported", "detail": "not something this provider does"})
                continue
        except (KeyError, OSError, ValueError, TypeError) as err:
            send({"type": "error", "id": message.get("id"), "code": "invalid-request", "detail": f"{type(err).__name__}: {err}"})
            continue
        send({"type": "result", "id": message["id"], "capability": capability, "body": answer})


if __name__ == "__main__":
    sys.exit(main())
