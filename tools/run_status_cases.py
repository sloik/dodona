"""Judge a command that reports a project's status (decision 0034).

    python tools/run_status_cases.py --kernel KERNEL... -- STATUS COMMAND...

Each case in conformance/project/cases.json is a small project, set up afresh in a directory of
its own, with providers that answer from a file of the case (conformance/project/fixture_provider.py)
and ledgers written by the reference encoder. The command under judgement and the reference,
tools/project_status.py, are each run on their own copy. A case matches when:

- a refusal is expected and the command refuses with that reason;
- otherwise the command does not refuse; what it judged, the coverage, the ledger note, the bindings
  it does not serve, the obligations nobody can check and the policy source equal the reference's;
  every request it sent its providers equals the reference's; its report is exactly what KERNEL's
  `scenario` command gives as the last result for what it judged; and the statuses the case names,
  written by hand from the status rules, are the report's.

The expected refusals and statuses are never taken from a kernel. KERNEL is used only to recompute
the report from what the command says it judged, so that it cannot show one thing and judge another.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES = ROOT / "conformance" / "project" / "cases.json"
FIXTURE = ROOT / "conformance" / "project" / "fixture_provider.py"
REFERENCE = [sys.executable, str(ROOT / "tools" / "project_status.py")]
class Skip(Exception):
    """A case this system cannot set up, such as one that needs a symbolic link. Never a match."""


COMPARED = ("judged", "coverage", "ledger", "not_served", "not_checkable", "policy_source")


def ledger_bytes(entries: list[dict]) -> bytes:
    out, previous = b"", None
    for e in entries:
        entry = {"previous": previous, "kind": e["kind"], "body": e["body"]}
        raw = canonical.encode(entry).encode("utf-8")
        out += b"dodona1 %d %s " % (len(raw), hashlib.sha256(raw).hexdigest().encode("ascii")) + raw + b"\n"
        previous = canonical.identity(entry)
    return out


def fill(value, preimages: dict):
    """Placeholders in a case's ledger entries: `$preimage:NAME` and `$key:NAME` stand for the
    obligation's preimage as things stand, and its identity."""
    if isinstance(value, str) and value.startswith("$preimage:"):
        return preimages.get(value[len("$preimage:"):], {})
    if isinstance(value, str) and value.startswith("$key:"):
        return canonical.identity(preimages.get(value[len("$key:"):], {}))
    if isinstance(value, dict):
        return {k: fill(v, preimages) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, preimages) for v in value]
    return value


def set_up(case: dict, site: dict, where: pathlib.Path, preimages: dict) -> tuple[bytes, pathlib.Path, pathlib.Path]:
    """The project of a case in where/root, the providers' answer files and records in where/aux; returns the input."""
    root, aux = where / "root", where / "aux"
    root.mkdir(parents=True)
    aux.mkdir()
    for rel, text in case["files"].items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(text.encode("utf-8"))
    for rel, target in case.get("links", {}).items():
        try:
            os.symlink(root / target, root / rel)
        except (OSError, NotImplementedError):
            raise Skip("this system cannot make a symbolic link") from None
    providers = {}
    for name, p in case["providers"].items():
        answers, record = aux / f"{name}.answers.json", aux / f"{name}.record.jsonl"
        answers.write_text(json.dumps(p["answers"], ensure_ascii=False), encoding="utf-8")
        providers[name] = {"command": [sys.executable, str(FIXTURE), str(answers), str(record)], "code": p["code"]}
    ledgers = []
    for item in case["ledgers"]:
        ledgers.append(item["path"])
        if item.get("absent") or item.get("same_as_owner"):
            continue
        path = root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        data = item["raw"].encode("utf-8") if "raw" in item else ledger_bytes(fill(item["entries"], preimages))
        path.write_bytes(data + item.get("torn_tail", "").encode("utf-8"))
    owner = case.get("owner_ledger")
    if owner is not None:
        (root / "records").mkdir(exist_ok=True)
        data = ledger_bytes(fill(owner["entries"], preimages))
        if owner.get("link"):
            (root / "records" / "elsewhere.ledger").write_bytes(data)
            try:
                os.symlink(root / "records" / "elsewhere.ledger", root / "records" / "owner.ledger")
            except (OSError, NotImplementedError):
                raise Skip("this system cannot make a symbolic link") from None
        else:
            (root / "records" / "owner.ledger").write_bytes(data)
    if "raw_input" in case:
        return case["raw_input"].encode("utf-8"), root, aux
    asked = {"root": str(root), "project": "dodona.toml", "site": dict(site, providers=providers), "policy": case["policy"],
             "policy_source": "policy: as the judge gives it", "ledgers": ledgers, "owner_ledger": "records/owner.ledger"}
    for path, value in case.get("input_edit", []):
        here = asked
        for key in path[:-1]:
            here = here[key]
        here[path[-1]] = value
    return json.dumps(asked, ensure_ascii=False).encode("utf-8"), root, aux


def requests(aux: pathlib.Path) -> dict:
    """What each provider was asked, without the parts a host chooses for itself (ids, echo, limits)."""
    seen = {}
    for record in sorted(aux.glob("*.record.jsonl")):
        lines = [json.loads(l) for l in record.read_text(encoding="utf-8").splitlines() if l.strip()]
        seen[record.name] = [{"type": m.get("type"), "capability": m.get("capability"), "body": m.get("body")} for m in lines]
    return seen


def run(command: list[str], case: dict, site: dict, preimages: dict, timeout: int = 120) -> tuple[dict | None, dict, str]:
    with tempfile.TemporaryDirectory() as tmp:
        stdin, root, aux = set_up(case, site, pathlib.Path(tmp), preimages)
        try:
            done = subprocess.run(command, input=stdin, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, requests(aux), "timed out"
        try:
            return json.loads(done.stdout), requests(aux), done.stderr.decode("utf-8", "replace")[-300:]
        except ValueError:
            return None, requests(aux), f"exit {done.returncode}: " + done.stderr.decode("utf-8", "replace")[-300:]


def judge(case: dict, site: dict, command: list[str], kernel: list[str]) -> list[str]:
    # The current preimages, for ledgers that hold results under the current key: from the reference.
    preimages = {}
    if "$" in json.dumps(case["ledgers"]) + json.dumps(case.get("owner_ledger")):
        bare = dict(case, ledgers=[], owner_ledger=None)
        ref, _, _ = run(REFERENCE, bare, site, {})
        preimages = {n: o["preimage"] for n, o in (ref or {}).get("judged", {}).get("obligations", {}).items()}
    got, asked, err = run(command, case, site, preimages)
    ref, ref_asked, ref_err = run(REFERENCE, case, site, preimages)
    problems = []
    expect = case["expect"]
    if got is None:
        return [f"no JSON answer ({err})"]
    if "refused" in expect:
        if (ref or {}).get("refused") != expect["refused"]:
            problems.append(f"the kit is wrong: the reference gives {ref} ({ref_err})")
        if got.get("refused") != expect["refused"]:
            problems.append(f"expected refused {expect['refused']}, got {json.dumps(got)[:200]}")
        return problems
    if "refused" in got:
        return [f"refused {got['refused']} ({got.get('detail')}), expected a report"]
    if ref is None or "refused" in ref:
        return [f"the kit is wrong: the reference gives {ref} ({ref_err})"]
    for field in COMPARED:
        if got.get(field) != ref.get(field):
            problems.append(f"{field} differs from the reference")
    if asked != ref_asked:
        problems.append("the requests sent to the providers differ from the reference's")
    answer = subprocess.run(kernel + ["scenario"], input=json.dumps(got.get("judged")).encode("utf-8"), capture_output=True, timeout=120)
    try:
        own = json.loads(answer.stdout)["results"][-1]
    except (ValueError, KeyError, IndexError):
        own = None
    if got.get("report") != own:
        problems.append("the report is not what the scenario command gives for what was judged")
    report = got.get("report") or {}
    status = expect.get("status", {})
    for name, want in status.get("obligations", {}).items():
        if report.get("obligations", {}).get(name, {}).get("status") != want:
            problems.append(f"obligation {name}: expected {want}")
    for name, want in status.get("intents", {}).items():
        if report.get("intents", {}).get(name, {}).get("status") != want:
            problems.append(f"intent {name}: expected {want}")
    if "project" in status and report.get("project", {}).get("status") != status["project"]:
        problems.append(f"project: expected {status['project']}, got {report.get('project')}")
    for field in ("not_served", "not_checkable", "ledger"):
        if field in expect and got.get(field) != expect[field]:
            problems.append(f"{field}: expected {expect[field]}, got {got.get(field)}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kernel", nargs="+", required=True, help="a kernel command whose `scenario` recomputes the report")
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    kernel = args.kernel
    if "--" in kernel:
        kernel, command = kernel[:kernel.index("--")], kernel[kernel.index("--") + 1:]
    spec = json.loads(CASES.read_text(encoding="utf-8"))
    matched, skipped = 0, 0
    for case in spec["cases"]:
        try:
            problems = judge(case, spec["site"], command, kernel)
        except Skip as why:
            skipped += 1
            print(f"skipped  {case['name']}: {why}")
            continue
        matched += not problems
        print(("match    " if not problems else "MISMATCH ") + case["name"] + ("" if not problems else ": " + "; ".join(problems)))
    judged = len(spec["cases"]) - skipped
    print(json.dumps({"cases": len(spec["cases"]), "judged": judged, "skipped": skipped, "matched": matched, "all_matched": matched == judged}))
    return 0 if matched == judged else 1


if __name__ == "__main__":
    sys.exit(main())
