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
import concurrent.futures
import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
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


def run_case(command: list[str], status: list[str], case: dict, site: dict) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        stdin, status_input, root, aux = set_up(case, site, pathlib.Path(tmp))
        try:
            first, err = call(command, stdin)
            sent = batches(aux)
            after, err_status = (call(status, status_input) if first and "refused" not in first else (None, ""))
            again, err_again = (call(command, stdin) if first and "refused" not in first else (None, ""))
            sent_again = batches(aux)[len(sent):]
            ledger_rel = json.loads(stdin)["ledger"]
            return {"first": first, "err": err, "sent": sent, "after": after, "err_status": err_status, "again": again,
                    "sent_again": sent_again, "recorded": recorded(root, ledger_rel), "asked": rsc.requests(aux),
                    "ledger_bytes": (root / ledger_rel).read_bytes() if (root / ledger_rel).exists() else b""}
        finally:
            for rel in list(case.get("unreadable", [])) + list(case.get("unreadable_mode", {})):
                try:
                    os.chmod(root / rel, 0o755)
                except OSError:
                    pass


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
        if got["sent"]:
            problems.append("the executor was sent a batch although the run was refused")
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
    if "recorded" in expect and not same(got["recorded"], expect["recorded"]):
        problems.append(f"recorded: expected {expect['recorded']}, got {got['recorded']}")
    after = got["after"]
    if not isinstance(after, dict) or "refused" in after:
        problems.append(f"the status command straight after did not report ({got['err_status'] or after})")
    else:
        mine = {k: v for k, v in first.items() if k != "counts"}
        if not same(mine, after):
            differ = sorted(k for k in set(mine) | set(after) if not same(mine.get(k), after.get(k)))
            problems.append(f"the report differs from what the status command reports straight after, in {differ}")
    again = got["again"]
    # Run again, it checks exactly what the first run did not record (verdicts other than passed and failed).
    left = counts["checked"] - counts["passed"] - counts["failed"]
    if not isinstance(again, dict) or again.get("counts", {}).get("checked") != left or (left == 0 and got["sent_again"]):
        problems.append(f"run a second time, it checked {(again or {}).get('counts', {}).get('checked')} obligations, not the {left} left without a recorded verdict")
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
