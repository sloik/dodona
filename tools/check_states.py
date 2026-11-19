"""Check the kernel's answer on every state a model reached.

Stage-0 helper (decision 0023).

    python tools/check_states.py --model kernel --dump FILE [--settings FILE] -- <kernel command>
    python tools/check_states.py --model intent --dump FILE -- <kernel command>

The model checker can write out every state it reached (its `-dump` option).
The dump models in spec/kernel/MCDump.tla and spec/intent/MCDump.tla add a
variable `report` holding the model's own answer in each state. This tool
reads such a file, turns each state into the kernel's `states` input, and
requires the kernel to give the model's answer for every one.

That is a stronger link between model and code than scenarios: every state
within the model's bounds, not a sample. It is still bounded by the model, and
it checks only what the model's states contain.

Exit status is 0 only if the file holds at least one state and the kernel
agrees on all of them.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys


class Parser:
    """A reader for the values the model checker prints: records, functions
    with string keys, sets, tuples, strings, integers and booleans."""

    def __init__(self, text: str):
        self.text, self.at = text, 0

    def space(self) -> None:
        while self.at < len(self.text) and self.text[self.at].isspace():
            self.at += 1

    def take(self, token: str) -> bool:
        self.space()
        if self.text.startswith(token, self.at):
            self.at += len(token)
            return True
        return False

    def need(self, token: str) -> None:
        if not self.take(token):
            raise ValueError(f"expected {token!r} at {self.text[self.at:self.at + 30]!r}")

    def value(self):
        self.space()
        ch = self.text[self.at]
        if ch == '"':
            end = self.text.index('"', self.at + 1)
            out = self.text[self.at + 1:end]
            self.at = end + 1
            return out
        if self.take("<<"):
            items = self.items(">>")
            return items
        if self.take("{"):
            return self.items("}")
        if self.take("["):
            record = {}
            while True:
                self.space()
                key = re.compile(r"[A-Za-z_][A-Za-z0-9_]*").match(self.text, self.at)
                if not key:
                    raise ValueError(f"expected a field name at {self.text[self.at:self.at + 30]!r}")
                self.at = key.end()
                self.need("|->")
                record[key.group(0)] = self.value()
                if self.take("]"):
                    return record
                self.need(",")
        if self.take("("):  # a function written as (k :> v @@ k :> v)
            mapping = {}
            while True:
                key = self.value()
                self.need(":>")
                mapping[str(key)] = self.value()
                if self.take(")"):
                    return mapping
                self.need("@@")
        if self.take("TRUE"):
            return True
        if self.take("FALSE"):
            return False
        number = re.compile(r"-?\d+").match(self.text, self.at)
        if number:
            self.at = number.end()
            return int(number.group(0))
        raise ValueError(f"cannot read a value at {self.text[self.at:self.at + 30]!r}")

    def items(self, close: str) -> list:
        out = []
        if self.take(close):
            return out
        while True:
            out.append(self.value())
            if self.take(close):
                return out
            self.need(",")


def states(text: str):
    """Yield each state as a dictionary of variable name to value."""
    for block in re.split(r"^State \d+:\s*$", text, flags=re.M)[1:]:
        state = {}
        for part in re.split(r"^/\\ ", block.strip(), flags=re.M):
            part = part.strip()
            if not part:
                continue
            name, _, value = part.partition(" = ")
            state[name.strip()] = Parser(value).value()
        yield state


def kernel_case(state: dict, obligations: dict) -> tuple[dict, dict]:
    def entry(item: dict) -> dict:
        return {"obligation": item["ob"], "inputs": {d: str(h) for d, h in item["key"]["deps"].items()},
                "tool": str(item["key"]["tool"])}
    case = {"definitions": {d: str(h) for d, h in state["defHash"].items()}, "tool": str(state["toolHash"]),
            "records": [dict(entry(r), verdict=r["verdict"]) for r in state["ledger"]],
            "running": [entry(j) for j in state["running"]]}
    return case, state["report"]


def kernel_answer(result: dict) -> dict:
    return {o: (r["status"] if r["status"] != "unknown" else ("pending" if r.get("pending") else "unknown"))
            for o, r in result.items()}


def intent_case(state: dict) -> tuple[dict, dict]:
    amendments = sorted(state["amendments"], key=lambda a: json.dumps(a, sort_keys=True))
    case = {"confirmed": state["confirmed"],
            "criteria": {c: {"gate": g, "check": state["chk"][c]} for c, g in state["effGate"].items()},
            "amendments": [dict({"by": a["by"], "source": a["source"]},
                                **({} if a["recorded"] == "missing" else {"claims": a["recorded"]})) for a in amendments]}
    want = {"delivered": state["report"]["delivered"], "fulfilled": state["report"]["fulfilled"],
            "amendments": [{"takes_effect": a["counted"], "level": a["level"]} for a in amendments]}
    return case, want


def intent_answer(result: dict) -> dict:
    return {"delivered": result["status"] in ("delivered", "fulfilled"), "fulfilled": result["status"] == "fulfilled",
            "amendments": [{"takes_effect": a["takes_effect"], "level": a["level"]} for a in result["amendments"]]}


def ask(command: list[str], payload: dict) -> list:
    done = subprocess.run(command + ["states"], input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=600)
    if done.returncode != 0:
        raise RuntimeError(f"the kernel exited with {done.returncode}")
    return json.loads(done.stdout.decode("utf-8"))["results"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, choices=["kernel", "intent"])
    ap.add_argument("--dump", required=True, type=pathlib.Path)
    ap.add_argument("--settings", type=pathlib.Path, help="JSON with what the dump configuration fixed")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    settings = json.loads(args.settings.read_text(encoding="utf-8")) if args.settings else {}
    parsed = list(states(args.dump.read_text(encoding="utf-8")))
    cases, wanted = [], []
    for state in parsed:
        case, want = kernel_case(state, settings) if args.model == "kernel" else intent_case(state)
        cases.append(case)
        wanted.append(want)
    differences = 0
    for start in range(0, len(cases), 5000):
        chunk = cases[start:start + 5000]
        payload = dict(settings, kind="evidence" if args.model == "kernel" else "intent", states=chunk)
        results = ask(command, payload)
        if len(results) != len(chunk):
            print(f"the kernel returned {len(results)} results for {len(chunk)} states")
            return 1
        for offset, result in enumerate(results):
            got = kernel_answer(result) if args.model == "kernel" else intent_answer(result)
            if got != wanted[start + offset]:
                differences += 1
                if differences <= 5:
                    print(f"DIFFERENT in state {start + offset + 1}: model {json.dumps(wanted[start + offset], sort_keys=True)}, "
                          f"kernel {json.dumps(got, sort_keys=True)}")
    print(json.dumps({"model": args.model, "states": len(cases), "differences": differences,
                      "all_agree": differences == 0 and bool(cases)}))
    return 0 if differences == 0 and cases else 1


if __name__ == "__main__":
    sys.exit(main())
