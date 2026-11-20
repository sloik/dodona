"""Judge a command that runs a project's checks and reports its status (decision 0034).

    python tools/run_run_cases.py --kernel KERNEL... --status "STATUS COMMAND" -- RUN COMMAND...

Each case in conformance/project/run-cases.json is a small project, set up afresh, with a provider that enumerates
and takes checks as the case scripts them (conformance/project/fixture_provider.py) and an executor that answers
batches as the case scripts them (conformance/project/fake_batch_executor.py). The command under judgement and the
reference, tools/project_run.py, run on their own copies. Most of what is judged does not come from the reference:

- a refusal must be the one the case names;
- the batches the executor was sent, the verdicts appended to the ledger, the counts and the statuses the case
  writes by hand must hold;
- the counts must add up: reused and checked to the obligations, the verdicts and refusals to checked;
- the report, but for its counts, must equal what the STATUS command reports on the same project straight after;
- run a second time, the command must send the executor nothing and check nothing;
- what it judged, the ledger it wrote and what it asked its providers must equal the reference's;
- the report must be what KERNEL's `scenario` command gives for what it judged (KERNEL other than the one judged).
"""
from __future__ import annotations

import argparse
import hashlib
import concurrent.futures
import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402
import ledger  # noqa: E402
import run_status_cases as rsc  # noqa: E402
from run_status_cases import Skip, same  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = ROOT / "conformance" / "project" / "run-cases.json"
EXECUTOR = ROOT / "conformance" / "project" / "fake_batch_executor.py"
REFERENCE = [sys.executable, str(ROOT / "tools" / "project_run.py")]
REFERENCE_STATUS = [sys.executable, str(ROOT / "tools" / "project_status.py")]
COMPARED = ("judged", "coverage", "ledger", "not_served", "not_checkable", "policy_not_applied", "project_doubts", "counts")
COUNT_KEYS = ("obligations", "reused", "checked", "passed", "failed", "error", "unavailable", "unsupported", "refused", "not_checkable")


def set_up(case: dict, site: dict, where: pathlib.Path) -> tuple[bytes, bytes, pathlib.Path, pathlib.Path]:
    """The project as the status judge sets it up, with the run's ledger and executor added; returns the run's input
    and the status command's input (the same, without them)."""
    preimages = rsc._preimages(case, site) if "$" in json.dumps(case["ledgers"]) + json.dumps(case.get("owner_ledger")) else {}
    stdin, root, aux = rsc.set_up(case, site, where, preimages)
    asked = json.loads(stdin)
    status_input = json.dumps(asked, ensure_ascii=False).encode("utf-8")
    script, record = aux / "executor.json", aux / "executor.record.jsonl"
    script.write_text(json.dumps(case.get("executor", {})), encoding="utf-8")
    asked["ledger"] = case.get("run_ledger", "l/run.ledger")
    if asked["ledger"] not in asked["ledgers"] and not case.get("run_ledger_unlisted"):
        asked["ledgers"].append(asked["ledger"])
    asked["executor"] = [sys.executable, str(EXECUTOR), str(script), str(record)]
    for path, value in case.get("run_input_edit", []):
        here = asked
        for key in path[:-1]:
            here = here[key]
        here[path[-1]] = value
    status_input = json.dumps({k: v for k, v in asked.items() if k not in ("ledger", "executor")}, ensure_ascii=False).encode("utf-8")
    return json.dumps(asked, ensure_ascii=False).encode("utf-8"), status_input, root, aux


def call(command: list[str], stdin: bytes) -> tuple[dict | None, str]:
    try:
        done = subprocess.run(command, input=stdin, capture_output=True, timeout=300)
    except subprocess.TimeoutExpired:
        return None, "timed out"
    if done.returncode != 0:
        return None, f"exit {done.returncode}: " + done.stderr.decode("utf-8", "replace")[-300:]
    try:
        return rsc.host.strict_load(done.stdout.rstrip(b"\n")), ""
    except Exception as err:  # noqa: BLE001
        return None, f"not one strict JSON object ({err})"


def batches(aux: pathlib.Path) -> list[dict]:
    path = aux / "executor.record.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def recorded(root: pathlib.Path, rel: str) -> dict:
    """The verdicts in the run's ledger, by obligation, as the reference reader reads them."""
    try:
        read = ledger.read(root / rel)
    except Exception:  # noqa: BLE001
        return {"unreadable": True}
    return {e["body"]["obligation"]: e["body"]["verdict"] for e in read["entries"]
            if e["kind"] == "evidence" and isinstance(e["body"], dict) and "obligation" in e["body"]}


def normal_transcript(kept) -> list:
    """A transcript with the ids a host chooses taken out, so that two hosts' transcripts can be compared in order."""
    if not isinstance(kept, list):
        return [kept]
    out = []
    for m in kept:
        message = dict(m.get("message", {})) if isinstance(m, dict) and isinstance(m.get("message"), dict) else m
        if isinstance(message, dict):
            message.pop("id", None)
            message.pop("echo", None)
            if isinstance(message.get("body"), dict):
                message["body"] = {k: v for k, v in message["body"].items() if k != "check"}
        out.append([m.get("to") if isinstance(m, dict) else None, message])
    return out


def tree_digest(root: pathlib.Path) -> str:
    """Every file under the project root, by path and bytes: a refused run must leave the project as it was."""
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file() and not p.is_symlink()):
        h.update(path.relative_to(root).as_posix().encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def provider_records(aux: pathlib.Path) -> list[dict]:
    """Every message the providers were sent, as they recorded them, in no particular order across providers."""
    found = []
    for record in sorted(aux.glob("*.record.jsonl")):
        if record.name == "executor.record.jsonl":
            continue  # the executor's batches, not a provider's messages
        found += [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line.strip()]
    return found


def run_case(command: list[str], status: list[str], case: dict, site: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        stdin, status_input, root, aux = set_up(case, site, pathlib.Path(tmp))
        try:
            before = tree_digest(root)
            first, err = call(command, stdin)
            after_first = tree_digest(root)
            changed_files = after_first != before
            locks_left = sorted(p.relative_to(root).as_posix() for p in root.rglob("*.lock"))
            sent = batches(aux)
            records_first = provider_records(aux)
            described_first = sorted(json.dumps(json.loads(l), sort_keys=True) for d in sorted(aux.glob("*.described.jsonl"))
                                     for l in d.read_text(encoding="utf-8").splitlines() if l.strip())
            transcript_rel = json.loads(stdin).get("transcript")
            transcript = None
            if transcript_rel:
                try:
                    transcript = json.loads((root / transcript_rel).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    transcript = "unreadable"
            after, err_status = (call(status, status_input) if first and "refused" not in first else (None, ""))
            second = json.loads(stdin)
            second.pop("transcript", None)  # a transcript is written once, to a new file
            again, err_again = (call(command, json.dumps(second, ensure_ascii=False).encode("utf-8")) if first and "refused" not in first else (None, ""))
            sent_again = batches(aux)[len(sent):]
            ledger_rel = json.loads(stdin)["ledger"]
            return {"first": first, "err": err, "sent": sent, "after": after, "err_status": err_status, "again": again,
                    "sent_again": sent_again, "recorded": recorded(root, ledger_rel), "asked": rsc.requests(aux),
                    "transcript": transcript, "provider_records": records_first, "changed_files": changed_files,
                    "after_first": after_first, "locks_left": locks_left,
                    "described": described_first,
                    "ledger_bytes": (root / ledger_rel).read_bytes() if (root / ledger_rel).exists() else b""}
        finally:
            for rel in list(case.get("unreadable", [])) + list(case.get("unreadable_mode", {})):
                try:
                    os.chmod(root / rel, 0o755)
                except OSError:
                    pass


def described_problems(got: dict) -> list[str]:
    """Every run sent to the executor must be a run its provider described, as described: a command may not change
    a run (its program, arguments, inputs, tools or limits) between the provider and the executor."""
    left = list(got.get("described", []))
    for batch in got["sent"]:
        for item in batch.get("runs", []):
            text = json.dumps(item.get("run"), sort_keys=True)
            if text not in left:
                return [f"run {item.get('number')} sent to the executor is not a run its provider described"]
            left.remove(text)
    return []


def run_key_problems(got: dict) -> list[str]:
    """Each run in a batch must carry the number and run key the host checks give it, recomputed here from the start
    request its provider received and the description the executor was sent."""
    starts = {}
    for m in got["provider_records"]:
        body = m.get("body") if isinstance(m, dict) else None
        if m.get("type") == "request" and m.get("capability") == "obligation.check" and isinstance(body, dict) and body.get("op") == "start":
            starts[body["obligation"]["name"]] = canonical.identity({"obligation": body["obligation"], "inputs": body["inputs"]})
    numbers: dict = {}
    for batch in got["sent"]:
        for item in batch.get("runs", []):
            run = item.get("run", {})
            owner = [n for n, check in starts.items()
                     if item.get("run_key") == canonical.identity({"check": check, "run": item.get("number"), "description": canonical.identity(run)})]
            if len(owner) != 1:
                return [f"a run sent to the executor carries a run key no check gives it (run {item.get('number')})"]
            numbers[owner[0]] = numbers.get(owner[0], 0) + 1
            if item.get("number") != numbers[owner[0]]:
                return [f"run {item.get('number')} of {owner[0]} is numbered out of order"]
    return []


def judge(case: dict, site: dict, command: list[str], status: list[str], kernel: list[str]) -> list[str]:
    got = run_case(command, status, case, site)
    ref = run_case(REFERENCE + ["--kernel"] + kernel, REFERENCE_STATUS + ["--kernel"] + kernel, case, site)
    expect, problems = case["expect"], []
    first = got["first"]
    if not isinstance(first, dict):
        return [f"no JSON object answered ({got['err']})"]
    if "refused" in expect:
        if (ref["first"] or {}).get("refused") != expect["refused"]:
            problems.append(f"the kit is wrong: the reference gives {ref['first']} ({ref['err']})")
        if first.get("refused") != expect["refused"] or set(first) != {"refused", "detail"}:
            problems.append(f"expected exactly refused {expect['refused']}, got {json.dumps(first)[:200]}")
        if not same(got["sent"], ref["sent"]):
            problems.append("the batches sent before the refusal differ from the reference's")
        # A refusal changes nothing, but for what the text keeps from before it (verdicts recorded before a transcript
        # that cannot be written, or before the ledgers are read again): exactly what the reference leaves.
        if got["after_first"] != ref["after_first"]:
            problems.append("a refused run left the project's files other than the reference leaves them")
        if got["locks_left"]:
            problems.append(f"a lock was left behind: {got['locks_left']}")
        if not same(got["asked"], ref["asked"]):
            problems.append("the providers started or asked differ from the reference's")
        return problems
    if "refused" in first:
        return [f"refused {first['refused']} ({first.get('detail')}), expected a report"]
    if not isinstance(ref["first"], dict) or "refused" in ref["first"]:
        return [f"the kit is wrong: the reference gives {ref['first']} ({ref['err']})"]
    # Judged without the reference.
    counts = first.get("counts", {})
    if set(counts) != set(COUNT_KEYS) or not all(type(counts[k]) is int for k in COUNT_KEYS):
        return [f"counts must hold exactly {list(COUNT_KEYS)}, as whole numbers"]
    if counts["reused"] + counts["checked"] != counts["obligations"] or \
            sum(counts[v] for v in ("passed", "failed", "error", "unavailable", "unsupported", "refused")) != counts["checked"]:
        problems.append(f"the counts do not add up: {counts}")
    if "counts" in expect and not same(counts, dict(counts, **expect["counts"])):
        problems.append(f"counts: expected {expect['counts']}, got {counts}")
    if "batches" in expect:
        shape = [sorted(r["run"]["inputs"][0]["path"] if r["run"]["inputs"] else "" for r in b["runs"]) for b in got["sent"]]
        if len(got["sent"]) != expect["batches"]:
            problems.append(f"expected {expect['batches']} batches sent to the executor, got {len(got['sent'])} ({shape})")
    problems += run_key_problems(got)
    problems += described_problems(got)
    if "recorded" in expect and not same(got["recorded"], expect["recorded"]):
        problems.append(f"recorded: expected {expect['recorded']}, got {got['recorded']}")
    after = got["after"]
    if not isinstance(after, dict) or "refused" in after:
        problems.append(f"the status command straight after did not report ({got['err_status'] or after})")
    else:
        mine = {k: v for k, v in first.items() if k != "counts"}
        if case.get("files_change_during_run"):
            # The project's files changed under the run, so the status straight after keys them anew and cannot
            # equal the run's view; what the run withheld is judged by the case's own "recorded".
            pass
        elif not same(mine, after):
            differ = sorted(k for k in set(mine) | set(after) if not same(mine.get(k), after.get(k)))
            problems.append(f"the report differs from what the status command reports straight after, in {differ}")
    again = got["again"]
    # Run again, it checks exactly what the first run did not record (verdicts other than passed and failed).
    left = counts["checked"] - counts["passed"] - counts["failed"]
    if not isinstance(again, dict) or again.get("counts", {}).get("checked") != left or (left == 0 and got["sent_again"]):
        problems.append(f"run a second time, it checked {(again or {}).get('counts', {}).get('checked')} obligations, not the {left} left without a recorded verdict")
    if got["locks_left"]:
        problems.append(f"a lock was left behind: {got['locks_left']}")
    if "transcript" in json.dumps(case.get("run_input_edit", [])):
        # The transcript of the first run holds what the providers were sent then (the second run appended none to it).
        kept = got["transcript"]
        if not isinstance(kept, list) or not all(isinstance(m, dict) and m.get("to") in ("provider", "kernel") for m in kept):
            problems.append("no transcript as the text gives it was written")
        else:
            sent_to = sorted(json.dumps(m["message"], sort_keys=True) for m in kept if m["to"] == "provider")
            received = sorted(json.dumps(m, sort_keys=True) for m in got["provider_records"])
            if not sent_to or sent_to != received:
                problems.append("the transcript's messages to providers are not exactly what the providers received")
            elif normal_transcript(kept) != normal_transcript(ref["transcript"]):
                problems.append("the transcript is not the reference's, in order and in both directions (ids aside)")
    # Judged against the reference.
    for field in COMPARED:
        if not same(first.get(field), ref["first"].get(field)):
            problems.append(f"{field} differs from the reference")
    if got["ledger_bytes"] != ref["ledger_bytes"]:
        problems.append("the ledger it wrote differs, byte for byte, from the reference's")
    if not same(got["asked"], ref["asked"]):
        problems.append("the requests sent to the providers differ from the reference's")
    own, _ = call(kernel + ["scenario"], json.dumps(first.get("judged")).encode("utf-8")) if first.get("judged") else (None, "")
    own_report = (own or {}).get("results", [None])[-1] if isinstance(own, dict) else None
    if own_report is None or not same(first.get("report"), own_report):
        problems.append("the report is not what the scenario command gives for what was judged")
    status = expect.get("status", {})
    report = first.get("report") or {}
    for name, want in status.get("obligations", {}).items():
        if report.get("obligations", {}).get(name, {}).get("status") != want:
            problems.append(f"obligation {name}: expected {want}")
    if "project_status" in expect and first.get("project_status") != expect["project_status"]:
        problems.append(f"project_status: expected {expect['project_status']}, got {first.get('project_status')}")
    return problems


def main() -> int:
    # Case names hold characters a Windows console cannot show; they are printed escaped rather than crash the judge.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kernel", nargs="+", required=True)
    ap.add_argument("--status", required=True, help="the status command of the same kernel, as one string split as a shell would")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    kernel, command = args.kernel, args.command[1:] if args.command[:1] == ["--"] else args.command
    status = shlex.split(args.status)
    if "--" in kernel:
        kernel, command = kernel[:kernel.index("--")], kernel[kernel.index("--") + 1:]
    spec = json.loads(CASES.read_text(encoding="utf-8"))

    def one(case):
        try:
            return case, judge(case, spec["site"], command, status, kernel), None
        except Skip as why:
            return case, None, why
        except Exception as err:  # noqa: BLE001 - a case the judge cannot run is a mismatch, never a pass
            return case, [f"the judge could not run this case: {type(err).__name__}: {err}"], None
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(one, spec["cases"]))
    matched = skipped = 0
    for case, problems, why in results:
        if why is not None:
            skipped += 1
            print(f"skipped  {case['name']}: {why}")
            continue
        matched += not problems
        print(("match    " if not problems else "MISMATCH ") + case["name"] + ("" if not problems else ": " + "; ".join(problems)))
    judged = len(spec["cases"]) - skipped
    print(json.dumps({"cases": len(spec["cases"]), "judged": judged, "skipped": skipped, "matched": matched, "all_matched": matched == judged}))
    return 0 if judged and matched == judged else 1


if __name__ == "__main__":
    sys.exit(main())
