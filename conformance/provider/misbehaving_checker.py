"""A checking provider that breaks one rule on purpose. Part of the conformance kit.

    python misbehaving_checker.py [<mode>]

The mode is taken from DODONA_CHECKER_MODE, or else from the argument.

It offers `obligation.check` and is otherwise well-behaved. `check-cases.json`
lists the modes with what a host must do about each. These are the rules a
schema cannot express (protocol/README.md): every message here is well-formed.
"""
import json
import os
import sys

MODE = os.environ.get("DODONA_CHECKER_MODE") or (sys.argv[1] if len(sys.argv) > 1 else "well-behaved")
SEEN = os.environ.get("DODONA_TEST_SEEN")


def note(entry) -> None:
    """For the judge only: what this provider was asked and what it described, so the judge need not take
    the host's word for either."""
    if SEEN:
        with open(SEEN, "a", encoding="utf-8") as log:
            log.write(json.dumps(entry) + "\n")
RANK = "bounded"


def send(obj) -> None:
    sys.stdout.buffer.write(json.dumps(obj).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def read():
    line = sys.stdin.buffer.readline()
    message = json.loads(line.decode("utf-8")) if line else None
    if isinstance(message, dict):
        body = message.get("body") if isinstance(message.get("body"), dict) else {}
        note({"got": body.get("op") or message.get("type"), "id": message.get("id"), "check": body.get("check"), "run": body.get("run")})
    return message


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
    if MODE == "declared-tool-not-given":
        described["program"] = {"tool": "shell", "path": "bin/sh"}
    if MODE == "declared-tool-not-given-in-argument":
        described["args"][1] = "${tool:shell}/bin/sh"
    if MODE == "undeclared-tool-in-argument-no-slash":
        described["args"][1] = "${tool:shell}"
    if MODE == "second-undeclared-tool-in-one-argument":
        described["args"][1] = "${tool:checker}/lib/rules.jar:${tool:shell}/bin/sh"
    if MODE == "another-tool-digest":
        described["tools"] = [{"name": "checker", "digest": "sha256:" + "e" * 64}]
    if MODE == "tool-list-names-another-tool":
        described["tools"] = described["tools"] + [{"name": "shell", "digest": "sha256:" + "e" * 64}]
    if MODE == "nul-in-argument":
        described["args"][2] = "a.txt\u0000--other"
    if MODE == "path-inside-an-option":
        described["args"] = ["-config=/etc/passwd", "a.txt"]
    if MODE == "file-list-from-elsewhere":
        described["args"] = ["@/etc/passwd", "a.txt"]
    if MODE == "home-directory":
        described["args"] = ["~/.ssh/id_rsa", "a.txt"]
    if MODE == "a-url":
        described["args"] = ["file:///etc/passwd", "a.txt"]
    if MODE == "path-glued-to-a-flag":
        described["args"] = ["-I/etc/passwd", "a.txt"]
    if MODE == "parent-glued-to-a-flag":
        described["args"] = ["-I..", "a.txt"]
    if MODE == "tool-file-with-a-tail":
        described["args"] = ["${tool:checker}/lib/x=/etc/passwd", "a.txt"]
    if MODE == "an-environment":
        described["env"] = {"JAVA_TOOL_OPTIONS": "-javaagent:x.jar"}
    if MODE == "output-over-an-input":
        described["outputs"] = [{"path": "a.txt"}]
    if MODE == "look-alike-separator":
        described["args"] = ["-config=\uff0fetc\uff0fpasswd", "a.txt"]
    if MODE == "argument-outside":
        described["args"] = ["/etc/passwd", "a.txt"]
    if MODE == "argument-climbs-out":
        described["args"] = ["../../secrets/other.tla"]
    if MODE == "reads-nothing-it-was-given":
        described["inputs"], described["args"] = [], ["-version"]
    if MODE == "another-platform":
        described["platform"] = {"os": "windows", "arch": "x86_64"}
    if MODE == "output-outside":
        described["outputs"] = [{"path": "/tmp/report.txt"}]
    if MODE == "args-not-a-list":
        described["args"] = "a.txt"
    if MODE == "outputs-not-a-list":
        described["outputs"] = {"path": "/etc/passwd"}
    if MODE == "inputs-not-a-list":
        described["inputs"] = {"path": "/etc/passwd", "identity": "sha256:" + "0" * 64}
    if MODE == "tools-missing":
        del described["tools"]
    if MODE == "env-null":
        described["env"] = None
    if MODE == "output-over-another-input":
        described["outputs"] = [{"path": "b.txt"}]
    if MODE == "output-differs-in-case":
        described["outputs"] = [{"path": "A.TXT"}]
    if MODE == "nul-in-tool-argument":
        described["args"][1] = "-I${tool:checker}/x\u0000"
    if MODE == "wall-ms-huge":
        described["limits"]["wall_ms"] = 2147483648
    if MODE == "two-faults-platform-and-tool":
        described["platform"] = {"os": "windows", "arch": "x86_64"}
        described["program"]["tool"] = "shell"
    return described


def main() -> None:
    pidfile = os.environ.get("DODONA_TEST_PIDFILE")
    if pidfile:
        with open(pidfile, "a", encoding="utf-8") as out:
            out.write(f"{os.getpid()}\n")
    if MODE == "leaves-a-child":
        import subprocess
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        if pidfile:
            with open(pidfile, "a", encoding="utf-8") as out:
                out.write(f"{child.pid}\n")
    hello = read()
    tools = [{"name": "checker", "constraint": "=1"}]
    if MODE.startswith("declared-tool-not-given"):
        tools.append({"name": "shell", "constraint": "*"})  # declared, and the host hands this check no such tool
    capabilities = [{"capability": "obligation.check", "determinism": "deterministic", "strength": {"class": "test", "rank": RANK}}]
    if MODE == "two-check-capabilities":
        capabilities.append({"capability": "obligation.check", "determinism": "deterministic", "strength": {"class": "test", "rank": "exhaustive"}})
    if MODE == "capability-not-an-object":
        capabilities.append("obligation.check")
    if MODE == "unknown-ceiling":
        capabilities[0]["strength"]["rank"] = "certain"
    if MODE == "tools-as-names":
        tools = ["checker"]
    if MODE == "tool-name-with-a-slash":
        tools = [{"name": "checker", "constraint": "=1"}, {"name": "a/b", "constraint": "*"}]
    send({"type": "manifest", "echo": hello["echo"] + (" changed" if MODE == "wrong-echo" else ""), "manifest": {
        "protocol": "0.2", "name": "misbehaving.checker", "version": "0",
        "capabilities": capabilities, "tools": tools, "trusted_base": []}})
    if MODE == "stops-reading":
        import time
        time.sleep(60)
        return
    while True:
        request = read()
        if request is None or request.get("type") == "shutdown":
            return
        body = request["body"]
        passed = {"final": {"verdict": "passed", "strength": {"class": "test", "rank": RANK}}}
        if MODE == "too-slow":
            import time
            time.sleep(30)
        if body["op"] == "start":
            answer = {"next": run(body)}
            if MODE == "final-unsupported":
                answer = {"final": {"verdict": "unsupported", "reason": "cannot-check-this"}}
            if MODE == "two-faults-attachment-and-verdict":
                answer = {"final": {"verdict": "probably-fine", "attachments": [{"path": "../outside.txt", "identity": "sha256:" + "f" * 64}]}}
            if MODE == "verdict-without-run":
                answer = passed
            if MODE == "next-and-final":
                answer = {"next": run(body), **passed}
            if MODE == "neither":
                answer = {}
            if MODE == "failed-without-run":
                answer = {"final": {"verdict": "failed", "strength": {"class": "test", "rank": RANK}}}
        else:
            answer = passed
            if MODE == "stronger-than-declared":
                answer = {"final": {"verdict": "passed", "strength": {"class": "test", "rank": "exhaustive"}}}
            if MODE == "failed-stronger-than-declared":
                answer = {"final": {"verdict": "failed", "strength": {"class": "test", "rank": "exhaustive"}}}
            if MODE == "another-strength-class":
                answer = {"final": {"verdict": "passed", "strength": {"class": "proof", "rank": RANK}}}
            if MODE == "runs-without-end":
                answer = {"next": run(body_of_start)}
            if MODE == "eight-runs":
                answer = {"next": run(body_of_start)} if body["run"] < 8 else passed
            if MODE == "final-error":
                answer = {"final": {"verdict": "error", "reason": "checker-crashed"}}
            if MODE == "failed-another-class":
                answer = {"final": {"verdict": "failed", "strength": {"class": "proof", "rank": RANK}}}
            if MODE == "true-attachment":
                import hashlib
                data = open("evidence.txt", "rb").read()
                answer = {"final": dict(passed["final"], attachments=[{"path": "evidence.txt", "identity": "sha256:" + hashlib.sha256(data).hexdigest()}])}
            if MODE == "attachments-not-a-list":
                answer = {"final": dict(passed["final"], attachments={"path": "evidence.txt"})}
            if MODE == "strength-without-class":
                answer = {"final": {"verdict": "passed", "strength": {"rank": RANK}}}
            if MODE == "final-not-an-object":
                answer = {"final": "passed"}
            if MODE == "attachment-is-a-pipe":
                os.mkfifo("pipe")
                answer = {"final": dict(passed["final"], attachments=[{"path": "pipe", "identity": "sha256:" + "0" * 64}])}
            if MODE == "attachment-is-a-link-outside":
                import hashlib
                outside = os.path.join(os.path.dirname(os.getcwd()), "outside.txt")
                with open(outside, "wb") as f:
                    f.write(b"outside the project\n")
                os.symlink(outside, "leak.txt")
                answer = {"final": dict(passed["final"], attachments=[{"path": "leak.txt", "identity": "sha256:" + hashlib.sha256(b"outside the project\n").hexdigest()}])}
            if MODE == "no-strength":
                answer = {"final": {"verdict": "passed"}}
            if MODE == "lies-about-an-attachment":
                answer = {"final": dict(passed["final"], attachments=[{"path": "evidence.txt", "identity": "sha256:" + "f" * 64}])}
            if MODE == "attachment-outside":
                # The file exists and the identity is true, so only the path check can refuse it.
                import hashlib
                with open(os.path.join(os.path.dirname(os.getcwd()), "outside.txt"), "wb") as f:
                    f.write(b"outside the project\n")
                answer = {"final": dict(passed["final"], attachments=[{"path": "../outside.txt", "identity": "sha256:" + hashlib.sha256(b"outside the project\n").hexdigest()}])}
            if MODE == "attachment-through-a-link":
                # A link at an inner step that stays inside the project is still a link.
                import hashlib
                os.symlink(os.getcwd(), os.path.join("work", "via"), target_is_directory=True)
                data = open("evidence.txt", "rb").read()
                answer = {"final": dict(passed["final"], attachments=[{"path": "work/via/evidence.txt", "identity": "sha256:" + hashlib.sha256(data).hexdigest()}])}
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
        if MODE == "answers-another-request":
            message["id"] = request["id"] + "0"
        raw = {"fraction-in-a-body": '{"type": "result", "id": "%s", "capability": "obligation.check", "body": {"next": null, "x": 1.0}}',
               "duplicate-key-nested": '{"type": "result", "id": "%s", "capability": "obligation.check", "body": {"x": {"a": 1, "a": 2}}}',
               "integer-too-large": '{"type": "result", "id": "%s", "capability": "obligation.check", "body": {"x": 9007199254740992}}',
               "lone-surrogate": '{"type": "result", "id": "%s", "capability": "obligation.check", "body": {"x": "\\ud800"}}',
               "result-without-a-body": '{"type": "result", "id": "%s", "capability": "obligation.check"}',
               "deep-and-duplicate": '{"type": "result", "id": "%s", "capability": "obligation.check", "body": ' + '{"x": ' * 65 + '1' + '}' * 65 + ', "body": {}}'}
        if MODE in raw and body.get("op") == "start":
            sys.stdout.buffer.write((raw[MODE] % request["id"]).encode("utf-8") + b"\n")
            sys.stdout.buffer.flush()
            continue
        if MODE == "next-is-null" and body.get("op") == "start":
            answer = {"next": None}
            message["body"] = answer
        if MODE == "provider-error" and body.get("op") == "start":
            message = {"type": "error", "id": request["id"], "code": "internal", "message": "no"}
        if "next" in answer:
            note({"described": answer["next"]})
        send(message)


if __name__ == "__main__":
    main()
