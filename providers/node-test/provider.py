"""A provider for Node's built-in test runner (decision 0035). The second real provider.

It speaks the provider protocol on standard input and output and offers two capabilities: listing a project's
tests as obligations, and checking one. It never runs a test. It describes the run a check needs, and is later
handed what the run printed, which it reads.

What it reads: each file its binding gives it that is named `test.js` or ends in `.test.js` is a test file; every
top-level `test('name', ...)` call in it, at the start of a line and named by one string literal, is one obligation.
A check reads every file the binding gives (a test may read any of them), so each obligation's inputs are all of
them.

    python providers/node-test/provider.py
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

NAME, VERSION, PROTOCOL = "dodona.node-test", "0.1.0", "0.2"
STRENGTH = {"class": "test", "rank": "sampled"}
WALL_MS = 120_000
TEST_FILE = re.compile(r"(?:.*/)?(?:test|[^/]+\.test)\.js")
# A top-level call: `test(` at the start of a line, then a quoted literal, then a comma.
CALL = re.compile(r"""test\((['"])((?:\\.|(?!\1)[^\\\n])*)\1\s*,""")
ESCAPES = {"\\'": "'", '\\"': '"', "\\\\": "\\"}


def send(message: dict) -> None:
    sys.stdout.buffer.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def read():
    line = sys.stdin.buffer.readline()
    return json.loads(line.decode("utf-8")) if line else None


def literal(raw: str) -> str | None:
    """The value of a quoted literal's body, or None if it uses an escape other than \\' \\" \\\\."""
    out, i = [], 0
    while i < len(raw):
        if raw[i] == "\\":
            pair = raw[i:i + 2]
            if pair not in ESCAPES:
                return None
            out.append(ESCAPES[pair])
            i += 2
        else:
            out.append(raw[i])
            i += 1
    return "".join(out)


def tests_in(text: str) -> tuple[list[str], list[dict]]:
    """The names of the top-level tests in a file, and what was refused, with a reason each."""
    names, rejected = [], []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.startswith("test("):
            continue
        m = CALL.match(line)
        name = literal(m.group(2)) if m else None
        if name is None:
            rejected.append({"line": number, "code": "name-not-literal", "detail": "a test named by anything but one plain string literal"})
        elif not name.strip() or "#" in name or "\\" in name:
            # The runner's TAP output escapes # and \ in names; a name holding them could not be told apart.
            rejected.append({"line": number, "code": "name-unreadable", "detail": "an empty name, or one holding # or \\"})
        elif name in names:
            rejected.append({"line": number, "code": "name-twice", "detail": f"the name {name!r} is used twice in the file"})
        else:
            names.append(name)
    twice = {r["detail"] for r in rejected if r["code"] == "name-twice"}
    names = [n for n in names if f"the name {n!r} is used twice in the file" not in twice]  # neither copy is checked
    return names, rejected


def enumerate_obligations(body: dict) -> dict:
    files = sorted(f["path"] for f in body["files"])
    obligations, rejected = [], []
    for path in files:
        if not TEST_FILE.fullmatch(path):
            continue
        names, refused = tests_in(pathlib.Path(path).read_text(encoding="utf-8"))
        rejected += [{"name": f"{path}:{r['line']}", "code": r["code"], "detail": r["detail"]} for r in refused]
        for name in names:
            obligations.append({"name": f"{path}::{name}", "kind": "check", "specified_by": [path],
                                "targets": [f for f in files if f != path], "expect": "holds",
                                "config": {"file": path, "test": name}, "inputs": files})
    return {"obligations": obligations, "rejected": rejected}


def pattern(name: str) -> str:
    """A pattern Node's runner matches against test names, matching this name only."""
    return "^" + re.sub(r"([\\^$.|?*+()\[\]{}/-])", r"\\\1", name) + "$"


def describe_run(body: dict) -> dict:
    config = body["obligation"]["config"]
    return {"next": {"program": {"tool": "node", "path": "bin/node"},
                     "args": ["--test", "--test-reporter=tap", "--test-name-pattern=" + pattern(config["test"]), config["file"]],
                     "inputs": body["inputs"], "outputs": [], "limits": {"wall_ms": WALL_MS, "output_bytes": 8_388_608},
                     "platform": body["platform"], "cwd": ".",
                     "tools": [{"name": t["name"], "digest": t["digest"]} for t in body["tools"]]}}


TOP_LEVEL = re.compile(r"(not ok|ok) [0-9]+ - (.*)")


def interpret(obligation: dict, report: dict) -> dict:
    """The verdict, from the TAP lines at the top level and the exit status together. Node reports a file whose
    pattern matched no test as one passing test named after the file, so a count alone would pass a test that
    does not exist: exactly one top-level line, naming this test, is required."""
    text = pathlib.Path(report["captured_output"]["path"]).read_text(encoding="utf-8", errors="replace")
    status = report.get("exit_status")
    tops = [TOP_LEVEL.fullmatch(line) for line in text.splitlines() if TOP_LEVEL.fullmatch(line)]
    name = obligation["config"]["test"]
    summary = {"exit_status": status if isinstance(status, int) else -1, "top_level_results": len(tops)}
    if len(tops) != 1 or tops[0].group(2) != name:
        # No test of this name ran, another ran, or a result carries a directive such as # SKIP or # TODO.
        return {"final": {"verdict": "error", "reason": "not-this-test", "summary": summary}}
    if tops[0].group(1) == "ok" and status == 0:
        return {"final": {"verdict": "passed", "strength": STRENGTH, "summary": summary}}
    if tops[0].group(1) == "not ok" and status == 1:
        return {"final": {"verdict": "failed", "strength": STRENGTH, "summary": summary}}
    return {"final": {"verdict": "error", "reason": "result-and-exit-disagree", "summary": summary}}


def main() -> int:
    hello = read()
    if not hello:
        return 1
    send({"type": "manifest", "echo": hello.get("echo", ""), "manifest": {
        "protocol": PROTOCOL, "name": NAME, "version": VERSION,
        "capabilities": [{"capability": "obligation.enumerate", "determinism": "deterministic"},
                         {"capability": "obligation.check", "determinism": "deterministic", "strength": STRENGTH}],
        "tools": [{"name": "node", "constraint": ">=22"}],
        "trusted_base": ["the test shows the property on the examples it runs, and no more",
                         "the Node runtime runs the test and reports its result correctly"]}})
    started: dict[str, dict] = {}
    while True:
        message = read()
        if message is None or message.get("type") == "shutdown":
            return 0
        body, capability = message.get("body", {}), message.get("capability")
        try:
            if capability == "obligation.enumerate":
                answer = enumerate_obligations(body)
            elif capability == "obligation.check" and body.get("op") == "start":
                started[message["id"]] = body["obligation"]
                answer = describe_run(body)
            elif capability == "obligation.check" and body.get("op") == "run.result":
                answer = interpret(started[body["check"]], body["report"])
            else:
                send({"type": "error", "id": message.get("id"), "code": "unsupported", "detail": "not something this provider does"})
                continue
        except (KeyError, OSError, ValueError) as err:
            send({"type": "error", "id": message.get("id"), "code": "invalid-request", "detail": f"{type(err).__name__}: {err}"})
            continue
        send({"type": "result", "id": message["id"], "capability": capability, "body": answer})


if __name__ == "__main__":
    sys.exit(main())
