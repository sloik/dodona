"""A provider that answers from a file, for the project status cases (decision 0034).

    python conformance/project/fixture_provider.py ANSWERS.json RECORD.jsonl

ANSWERS.json holds `manifest` (the manifest to send; its echo is copied from hello unless
`wrong_echo` is true), `checks` (for obligation.check, per obligation: `verdict`, `runs`, `by_exit` (passed when
the report's exit status is 0, failed otherwise), `strength_rank`, `no_tools_in_run`, `late_ms`, `edit_input` (a file changed while the check runs), `final_at_start`,
`strength_class`, `tool_digest`, `missing_input`, `neither_or_both`, `bad_input_identity`, `extra_input`, `run_platform`, `wall_ms`, `wrong_id_at_result`),
and, as before, 
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


STARTED: dict = {}  # check request id -> (obligation name, start body, runs so far)


def check_answer(script: dict, body: dict) -> dict:
    """Take a check as the case scripts it: `script[name]` is `{"verdict", "runs"}` (one run by default). Each run is
    described from what the start request gave: the checker tool, every input, the check's platform."""
    if body.get("op") == "start":
        name = body["obligation"]["name"]
        STARTED[CURRENT_ID[0]] = [name, body, 0]
        if script.get(name, {}).get("neither_or_both"):
            run = describe(script, body)
            return {"next": run, "final": {"verdict": "passed", "strength": {"class": "c", "rank": "bounded"}}}
        if script.get(name, {}).get("final_at_start"):
            return {"final": {"verdict": "passed", "strength": {"class": "c", "rank": "bounded"}}}  # no run behind it
        return {"next": describe(script, body)}
    name, start, done = STARTED[body["check"]]
    STARTED[body["check"]][2] = done + 1
    plan = script.get(name, {})
    if plan.get("edit_input"):
        with open(plan["edit_input"], "a", encoding="utf-8") as f:  # the provider runs in the project root
            f.write("changed while it was checked\n")
    if plan.get("late_ms"):
        time.sleep(plan["late_ms"] / 1000)  # answers the run's report later than the deadline
    if done + 1 < plan.get("runs", 1):
        return {"next": describe(script, start)}
    verdict = plan.get("verdict", "passed")
    if plan.get("by_exit"):
        verdict = "passed" if body.get("report", {}).get("exit_status") == 0 else "failed"
    final = {"verdict": verdict}
    if verdict in ("passed", "failed"):
        final["strength"] = {"class": plan.get("strength_class", "c"), "rank": plan.get("strength_rank", "bounded")}
    else:
        final["reason"] = "as the case scripts it"
    return {"final": final}


DESCRIBED = []  # every run described, written beside the record so a judge can compare what the executor was sent


def describe(script: dict, start: dict) -> dict:
    run = describe_run(script, start)
    DESCRIBED.append(run)
    with open(sys.argv[2].replace(".record.jsonl", ".described.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(run, ensure_ascii=False) + "\n")
    return run


def describe_run(script: dict, start: dict) -> dict:
    tools = [{"name": t["name"], "digest": t["digest"]} for t in start["tools"] if t["name"] == "checker"]
    plan = script.get(start["obligation"]["name"], {})
    if plan.get("no_tools_in_run"):
        tools = []  # the program's tool is not in the run's own tools: host rule 4
    if plan.get("tool_digest"):
        tools = [dict(t, digest="sha256:" + "0" * 64) for t in tools]  # not the digest the start gave
    inputs = [dict(i) for i in start["inputs"]]
    if plan.get("bad_input_identity"):
        inputs[0]["identity"] = "sha256:" + "1" * 64  # not the identity the start gave
    if plan.get("missing_input"):
        inputs = [i for i in inputs if i["path"] not in start["obligation"].get("targets", [])]  # a file the obligation names, left out
    if plan.get("extra_input"):
        inputs.append({"path": "m/zz.txt", "identity": "sha256:" + "2" * 64})  # a file the start did not give
    platform = dict(start["platform"], os="other") if plan.get("run_platform") else start["platform"]
    return {"program": {"tool": "checker", "path": "bin/check"}, "args": [], "inputs": inputs, "outputs": [],
            "tools": tools, "platform": platform, "limits": {"wall_ms": plan.get("wall_ms", 10000)}}


CURRENT_ID = [None]


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
            CURRENT_ID[0] = message.get("id")
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
            elif capability == "obligation.check" and "checks" in answers:
                body = check_answer(answers["checks"], message["body"])
                name = STARTED.get(message["body"].get("check"), [message["body"].get("obligation", {}).get("name")])[0]
                wrong = answers["checks"].get(name, {}).get("wrong_id_at_result") and message["body"].get("op") == "run.result"
                send({"type": "result", "id": str(message["id"]) + "x" if wrong else message["id"], "capability": capability, "body": body})
            elif capability in answers:
                send({"type": "result", "id": message["id"], "capability": capability, "body": answers[capability]})
            else:
                send({"type": "error", "id": message["id"], "code": "unsupported", "detail": "no answer in this case"})


if __name__ == "__main__":
    sys.exit(main())
