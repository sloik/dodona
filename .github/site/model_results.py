"""Judge the native model workflow's ledger and captured output before keeping them.

    python .github/site/model_results.py RUN.json STATUS.json TRANSCRIPT.json [--report PATH]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "providers" / "tlc")]
import canonical  # noqa: E402
import host  # noqa: E402
from check_models import state_counts  # noqa: E402
from judge import judge  # noqa: E402


def expected_cases(root: pathlib.Path) -> dict:
    cases = {}
    for index in sorted(root.glob("spec/*/expected.json")):
        spec = json.loads(index.read_text(encoding="utf-8"))
        cwd = index.parent.relative_to(root).as_posix()
        inputs = [host.file_ref(file, root) for file in sorted(index.parent.iterdir())
                  if file.suffix in (".tla", ".cfg") and file.is_file()]
        identities = {item["path"]: item["identity"] for item in inputs}
        for case in spec["cases"]:
            name = f"{index.parent.name}/{case['config'].removesuffix('.cfg')}"
            if name in cases:
                raise ValueError(f"the protected model inventory names {name} twice")
            model = case.get("model", spec["model"])
            args = [model if arg == spec["model"] else arg.replace("<config>", case["config"]) for arg in spec["arguments"]]
            cases[name] = (case, cwd, model, args, identities)
    return cases


def transcript_cases(events: list) -> dict:
    """Pair each model check's start, description and single terminal report."""
    started, described, reported = {}, {}, {}
    seen_names = set()
    for entry in events:
        message = entry["message"]
        if message.get("capability") != "obligation.check" or "body" not in message:
            continue
        body = message["body"]
        if entry["to"] == "provider" and message["type"] == "request":
            if body["op"] == "start":
                identifier, obligation = message["id"], body["obligation"]
                if identifier in started or obligation["name"] in seen_names or obligation["binding"] != "kernel-models":
                    raise ValueError("the transcript names a duplicate or a foreign model check")
                started[identifier] = body
                seen_names.add(obligation["name"])
            elif body["op"] == "run.result":
                identifier = body["check"]
                if identifier not in described or identifier in reported or type(body["run"]) is not int or body["run"] != 1:
                    raise ValueError("the transcript has a report outside its single named model run")
                reported[identifier] = body["report"]
        elif entry["to"] == "kernel" and message["type"] == "result" and "next" in body:
            identifier = message["id"]
            if identifier not in started or identifier in described:
                raise ValueError("the transcript has a duplicate or unmatched model run description")
            described[identifier] = body["next"]
    if started.keys() != described.keys() or started.keys() != reported.keys():
        raise ValueError("the transcript lacks a description or terminal report for a started check")
    return {body["obligation"]["name"]: (body, described[key], reported[key]) for key, body in started.items()}


def judged_case(root: pathlib.Path, name: str, expected: tuple, sent: tuple, pinned: list) -> dict:
    case, cwd, model, args, identities = expected
    start, description, report = sent
    args = ["-cp", "${tool:tla2tools}/tla2tools.jar", "tlc2.TLC", *args]
    required_paths = {f"{cwd}/{model}", f"{cwd}/{case['config']}"}
    if (description["program"] != {"tool": "java", "path": "bin/java"} or description["cwd"] != cwd or description["args"] != args
            or description["tools"] != pinned or description["platform"] != host.PLATFORM
            or description["inputs"] != start["inputs"] or not required_paths <= identities.keys()):
        raise ValueError(f"{name} has a description other than its protected model case")
    inputs = {item["path"]: item["identity"] for item in start["inputs"]}
    if inputs != identities or len(start["inputs"]) != len(identities):
        raise ValueError(f"{name} did not run on the protected model inputs")
    if (report["end"] != "exited" or type(report.get("exit_status")) is not int
            or report["platform"] != host.PLATFORM or report["tools_ran"] != pinned):
        raise ValueError(f"{name} has no finished report with the pinned tools and platform")
    check = canonical.identity({key: start[key] for key in ("obligation", "inputs")})
    key = host.run_key(check, 1, description).removeprefix("sha256:")[:16]
    capture = report["captured_output"]
    path = f"out/kernel-runs/r1-{key}.txt"
    if report["handle"] != f"runs/r1-{key}" or capture["path"] != path:
        raise ValueError(f"{name} has a capture from a different run key")
    file = root / path
    if file.resolve() != file or not file.is_file():
        raise ValueError(f"{name} has no regular raw output at its run key")
    data = file.read_bytes()
    if capture["identity"] != "sha256:" + hashlib.sha256(data).hexdigest():
        raise ValueError(f"{name} has a raw output digest mismatch")
    output = data.decode("utf-8", errors="replace")
    verdict = judge(case, report["exit_status"], output)
    if not verdict["match"]:
        raise ValueError(f"{name} differs from its expected model outcome: {verdict['outcome']}")
    return {**verdict, "name": name, "states": state_counts(output), "capture": capture}


def verify(root: pathlib.Path, run: dict, status: dict, events: list) -> dict:
    root = root.resolve()
    cases = expected_cases(root)
    if "refused" in run or "refused" in status or {k: v for k, v in run.items() if k != "counts"} != status:
        raise ValueError("the independent status disagrees with the native run")
    obligations = status["report"]["obligations"]
    if not cases or obligations.keys() != cases.keys():
        raise ValueError("the native status differs from the protected model inventory")
    if status["ledger"]["torn"] is not False:
        raise ValueError("the model ledger is torn")
    if status["not_checkable"] or any(item["status"] != "passed" for item in obligations.values()):
        raise ValueError("a protected model obligation has no current passing result")
    sent = transcript_cases(events)
    if not sent.keys() <= cases.keys():
        raise ValueError("the native transcript ran a case outside the protected model inventory")
    fresh, reused = len(sent), len(cases) - len(sent)
    expected_counts = {"obligations": len(cases), "checked": fresh, "passed": fresh, "reused": reused,
                       **dict.fromkeys(("failed", "error", "unavailable", "unsupported", "refused", "not_checkable"), 0)}
    if run["counts"] != expected_counts or any(type(value) is not int for value in run["counts"].values()):
        raise ValueError("native run counts disagree with the protected inventory and transcript")
    pinned = [{k: tool[k] for k in ("name", "digest")} for tool in host.lock_tools()[0] if tool["name"] in ("java", "tla2tools")]
    results = [judged_case(root, name, cases[name], rows, pinned) for name, rows in sent.items()]
    return {"summary": {"cases": fresh, "matched": len(results), "reused": reused, "all_matched": True}, "cases": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in ("run", "status", "transcript"):
        parser.add_argument(name, type=pathlib.Path)
    parser.add_argument("--report", type=pathlib.Path)
    args = parser.parse_args()
    try:
        run, status, transcript = [json.loads(path.read_text(encoding="utf-8")) for path in (args.run, args.status, args.transcript)]
        verified = verify(ROOT, run, status, transcript)
        if args.report:
            args.report.write_text(json.dumps(verified, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, TypeError, AttributeError, KeyError) as err:
        print(f"model result refused: {err}", file=sys.stderr)
        return 1
    print(json.dumps(verified["summary"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
