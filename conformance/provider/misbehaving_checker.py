"""A checking provider that breaks one rule on purpose. Part of the conformance kit.

    python misbehaving_checker.py <mode>

It offers `obligation.check` and is otherwise well-behaved. `check-cases.json`
lists the modes with what a host must do about each. These are the rules a
schema cannot express (protocol/README.md): every message here is well-formed.
"""
import json
import sys

MODE = sys.argv[1] if len(sys.argv) > 1 else "well-behaved"
RANK = "bounded"


def send(obj) -> None:
    sys.stdout.buffer.write(json.dumps(obj).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def read():
    line = sys.stdin.buffer.readline()
    return json.loads(line.decode("utf-8")) if line else None


def run(body: dict) -> dict:
    described = {"program": {"tool": "checker", "path": "bin/checker"}, "args": ["--lib", "${tool:checker}/lib/rules.jar", "a.txt"],
                 "inputs": [body["inputs"][0]], "outputs": [], "limits": {"wall_ms": 1000, "output_bytes": 1000},
                 "platform": body["platform"], "tools": [{"name": t["name"], "digest": t["digest"]} for t in body["tools"]], "cwd": "work"}
    if MODE == "undeclared-tool":
        described["program"]["tool"] = "shell"
    if MODE == "undeclared-tool-in-argument":
        described["args"][1] = "${tool:shell}/bin/sh"
    if MODE == "program-outside-its-tool":
        described["program"]["path"] = "../../bin/sh"
    if MODE == "argument-outside-its-tool":
        described["args"][1] = "${tool:checker}/../../etc/passwd"
    if MODE == "starts-outside":
        described["cwd"] = "../elsewhere"
    if MODE == "input-not-in-key":
        described["inputs"] = [{"path": "secrets.txt", "identity": "sha256:" + "0" * 64}]
    if MODE == "lies-about-an-input":
        described["inputs"] = [dict(body["inputs"][0], identity="sha256:" + "f" * 64)]
    if MODE == "output-outside":
        described["outputs"] = [{"path": "/tmp/report.txt"}]
    return described


def main() -> None:
    hello = read()
    send({"type": "manifest", "echo": hello["echo"], "manifest": {
        "protocol": "0.2", "name": "misbehaving.checker", "version": "0",
        "capabilities": [{"capability": "obligation.check", "determinism": "deterministic", "strength": {"class": "test", "rank": RANK}}],
        "tools": [{"name": "checker", "constraint": "=1"}], "trusted_base": []}})
    while True:
        request = read()
        if request is None or request.get("type") == "shutdown":
            return
        body = request["body"]
        passed = {"final": {"verdict": "passed", "strength": {"class": "test", "rank": RANK}}}
        if body["op"] == "start":
            answer = {"next": run(body)}
            if MODE == "verdict-without-run":
                answer = passed
            if MODE == "next-and-final":
                answer = {"next": run(body), **passed}
            if MODE == "neither":
                answer = {}
        else:
            answer = passed
            if MODE == "stronger-than-declared":
                answer = {"final": {"verdict": "passed", "strength": {"class": "test", "rank": "exhaustive"}}}
            if MODE == "no-strength":
                answer = {"final": {"verdict": "passed"}}
            if MODE == "lies-about-an-attachment":
                answer = {"final": dict(passed["final"], attachments=[{"path": "conformance/provider/check-cases.json", "identity": "sha256:" + "f" * 64}])}
            if MODE == "attachment-outside":
                answer = {"final": dict(passed["final"], attachments=[{"path": "../outside.txt", "identity": "sha256:" + "f" * 64}])}
            if MODE == "same-run-twice":
                answer = {"next": run(body_of_start)} if body["run"] == 1 else passed
            if MODE == "invented-verdict":
                answer = {"final": {"verdict": "probably-fine"}}
            if MODE == "second-run-with-new-input":
                answer = {"next": dict(run(body_of_start), inputs=[{"path": "later.txt", "identity": "sha256:" + "1" * 64}])} if body["run"] == 1 else passed
        if body["op"] == "start":
            globals()["body_of_start"] = body
        message = {"type": "result", "id": request["id"], "capability": request["capability"], "body": answer}
        if MODE == "answers-another-capability":
            message["capability"] = "obligation.enumerate"
        send(message)


if __name__ == "__main__":
    main()
