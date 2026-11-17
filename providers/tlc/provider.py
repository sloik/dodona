"""A provider for the TLC model checker. The first real provider (issue #19).

It speaks the provider protocol on standard input and output and offers two
capabilities: listing the obligations of a directory of models, and checking
one. It never starts the model checker. It describes the run it needs, and is
later handed what the run printed, which it interprets.

What it reads: in each model directory, `expected.json` lists the
configurations, what each must show, and the arguments the checker takes.
A configuration that must show a violation is a planted defect: its obligation
is passed when the violation is found.

    python providers/tlc/provider.py
"""
from __future__ import annotations

import json
import pathlib
import sys

NAME, VERSION, PROTOCOL = "dodona.tla", "0.1.0", "0.2"
STRENGTH = {"class": "bounded-model-check", "rank": "bounded"}
NO_ERROR = "Model checking completed. No error has been found."


def send(message: dict) -> None:
    sys.stdout.buffer.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def read():
    line = sys.stdin.buffer.readline()
    return json.loads(line.decode("utf-8")) if line else None


def enumerate_obligations(body: dict) -> dict:
    obligations, rejected = [], []
    folders = sorted({str(pathlib.PurePosixPath(f["path"]).parent) for f in body["files"] if f["path"].endswith("expected.json")})
    for folder in folders:
        spec = json.loads(pathlib.Path(folder, "expected.json").read_text(encoding="utf-8"))
        modules = sorted(f["path"] for f in body["files"] if f["path"].startswith(folder + "/") and f["path"].endswith(".tla"))
        designs = [c for c in spec["cases"] if c["expect"] == "no-violation"]
        for case in spec["cases"]:
            config = f"{folder}/{case['config']}"
            item = {"name": f"{pathlib.PurePosixPath(folder).name}/{case['config'][:-4]}", "kind": "check",
                    "specified_by": modules, "targets": [config],
                    "expect": "holds" if case["expect"] == "no-violation" else "violated",
                    "config": {"root": case.get("model", spec["model"]), "config": case["config"], "folder": folder,
                               "arguments": spec["arguments"], "model": spec["model"]}}
            if case["expect"] != "no-violation":
                item["config"]["property"] = case["of"]
                item["config"]["temporal"] = case["expect"] == "temporal-violation"
                guarded = [d for d in designs if case["of"] in pathlib.Path(folder, d["config"]).read_text(encoding="utf-8").split()]
                if guarded:
                    item["defect_of"] = f"{pathlib.PurePosixPath(folder).name}/{guarded[0]['config'][:-4]}"
            obligations.append(item)
    return {"obligations": obligations, "rejected": rejected}


def describe_run(body: dict) -> dict:
    config = body["obligation"]["config"]
    # The program starts in the working directory, so the files are named with their folder.
    folder = config["folder"]
    args = [f"{folder}/{config['root']}" if a == config["model"] else a.replace("<config>", f"{folder}/{config['config']}")
            for a in config["arguments"]]
    return {"next": {"program": {"tool": "java", "path": "bin/java"},
                     "args": ["-cp", "${tool:tla2tools}/tla2tools.jar", "tlc2.TLC"] + args,
                     "inputs": [f for f in body["inputs"] if f["path"].startswith(config["folder"] + "/")],
                     "outputs": [], "limits": {"wall_ms": 1800000, "output_bytes": 33554432},
                     "platform": body["platform"], "tools": body["tools"]}}


def interpret(obligation: dict, report: dict) -> dict:
    text = pathlib.Path(report["captured_output"]["path"]).read_text(encoding="utf-8", errors="replace")
    config, status = obligation["config"], report.get("exit_status")
    complete = NO_ERROR in text and ", 0 states left on queue." in text
    states = [line for line in text.splitlines() if "distinct states found" in line and "Progress" not in line]
    summary = {"exit_status": status if isinstance(status, int) else -1}
    if states:
        numbers = [int(part) for part in states[-1].replace(",", "").split() if part.isdigit()]
        if len(numbers) >= 2:
            summary.update(states_generated=numbers[0], distinct_states=numbers[1])
    if obligation["expect"] == "holds":
        if status == 0 and complete:
            return {"final": {"verdict": "passed", "strength": STRENGTH, "summary": summary}}
        if status == 12 and "is violated" in text:
            return {"final": {"verdict": "failed", "strength": STRENGTH, "summary": summary}}
        return {"final": {"verdict": "error", "reason": "did-not-complete"}}
    if config.get("temporal"):
        found = status == 13 and "Temporal properties were violated." in text
    else:
        found = status == 12 and (f"Invariant {config['property']} is violated." in text
                                  or f"Invariant {config['property']} is violated by the initial state:" in text)
    if found:
        return {"final": {"verdict": "passed", "strength": STRENGTH, "summary": summary}}
    if status == 0 and complete:
        return {"final": {"verdict": "failed", "strength": STRENGTH, "summary": summary}}
    return {"final": {"verdict": "error", "reason": "did-not-complete"}}


def main() -> int:
    hello = read()
    if not hello:
        return 1
    send({"type": "manifest", "echo": hello.get("echo", ""), "manifest": {
        "protocol": PROTOCOL, "name": NAME, "version": VERSION,
        "capabilities": [{"capability": "obligation.enumerate", "determinism": "deterministic"},
                         {"capability": "obligation.check", "determinism": "deterministic", "strength": STRENGTH}],
        "tools": [{"name": "tla2tools", "constraint": "=1.7.4"}, {"name": "java", "constraint": ">=17"}],
        "trusted_base": ["the model checker explores every state within the bounds of the configuration",
                         "the Java runtime under it runs it correctly"]}})
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
