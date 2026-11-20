"""The reference for a kernel's `run` command (decision 0034). Stage-0 helper.

    python tools/project_run.py [--kernel CMD...] < INPUT.json

It follows conformance/README.md, "How a project's run is judged": the status command's steps 1 to 9 (done by
tools/project_status.py, with the sessions of bindings that check kept open), then a plan of what has no current
result, checks through those same sessions with their runs sent to the site's executor in batches, the verdicts
appended to the ledger, and the status report made again from what the ledgers now hold, with counts. Like the
status reference it holds no status rules: the plan reads whether a record counts as the status rules define it,
and the report comes from a kernel's `scenario`.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402
import host  # noqa: E402
import ledger  # noqa: E402
import project_status as ps  # noqa: E402
from project_status import Stop  # noqa: E402

VERDICTS = ("passed", "failed", "error", "unavailable", "unsupported")
# Reasons that say the session itself can no longer be trusted: the whole run is refused, nothing is recorded.
SESSION_REASONS = {"deadline", "closed", "framing", "too-long", "encoding", "malformed", "not-an-integer", "duplicate-key",
                   "too-deep", "wrong-id", "wrong-capability", "unexpected", "provider-error"}
LOCK_WAIT_S = 60


def check_run_input(asked) -> None:
    """The fields a run adds to the status command's input, checked in step 1 before anything is started."""
    if not isinstance(asked, dict):
        return  # the status command's own check refuses it
    rel, owner = asked.get("ledger"), asked.get("owner_ledger")
    if not ps.relpath_ok(rel) or rel not in (asked.get("ledgers") or []) or rel == owner:
        raise Stop("bad-input", "ledger must be a relative path listed among ledgers, and not the owner's ledger")
    executor = asked.get("executor")
    if not (isinstance(executor, list) and executor and all(isinstance(x, str) for x in executor)):
        raise Stop("bad-input", "executor must be a non-empty list of strings")
    if "transcript" in asked and (not ps.relpath_ok(asked["transcript"]) or asked["transcript"] in (asked.get("ledgers") or [])
                                  or asked["transcript"] in (owner, asked.get("project"))):
        raise Stop("bad-input", "transcript, where given, is a relative path that is no ledger and not the project file")
    root = pathlib.Path(asked["root"]) if isinstance(asked.get("root"), str) else None
    if root is None or not root.is_dir():
        return
    if not ps.reached_without_link(root, rel):
        raise Stop("bad-input", "the ledger a run appends to is reached without a link")
    if isinstance(owner, str) and ps.relpath_ok(owner) and ps.ledger_state(root, rel) == "present" \
            and ps.ledger_state(root, owner) == "present" and ps.same_file(root / rel, root / owner):
        raise Stop("bad-input", "ledger is the owner's ledger")
    if "transcript" in asked and os.path.lexists(root / asked["transcript"]):
        raise Stop("bad-input", "transcript names a path that already exists: a run writes only a new file")


def counts_for(entries: list[dict], name: str, preimage: dict, writer: str, platform: str) -> bool:
    """Whether a record counts for the obligation now, as the status rules say: an evidence record that is a record,
    is not rejected, names the obligation, was written by this writer on this platform under the current key."""
    key = canonical.identity(preimage)
    for e in entries:
        body = e.get("body")
        if e.get("kind") != "evidence" or not isinstance(body, dict):
            continue
        if body.get("verdict") not in ("passed", "failed") or not all(isinstance(body.get(k), str) for k in ("obligation", "platform", "writer", "core_key")) \
                or not isinstance(body.get("preimage"), dict):
            continue
        try:
            if canonical.identity(body["preimage"]) != body["core_key"]:
                continue  # rejected: its key is not its own preimage's
        except Exception:  # noqa: BLE001 - a preimage the encoding refuses is rejected too
            continue
        if body["obligation"] == name and body["writer"] == writer and body["platform"] == platform and body["core_key"] == key:
            return True
    return False


def run_batch(root: pathlib.Path, executor: list[str], batch: list[dict]):
    """The executor's answer to one batch: a dict of reports by run_key; 'unavailable'; 'timed-out'; or 'mismatch'."""
    payload = json.dumps({"runs": [{"number": r["number"], "run_key": r["run_key"], "run": r["run"]} for r in batch]},
                         ensure_ascii=False).encode("utf-8") + b"\n"
    walls = [r["run"].get("limits", {}).get("wall_ms") if isinstance(r["run"].get("limits"), dict) else None for r in batch]
    # At least each run's wall_ms plus 60 seconds, at most 24 hours; a run stating no wall_ms is waited 24 hours.
    wait = 86_400 if any(type(w) is not int for w in walls) else min(max(walls) / 1000 + 60, 86_400)
    try:
        tree = host.Session._start(executor, root)  # in root, in a process group or job of its own
    except OSError:
        return "unavailable"
    try:
        out, _ = tree.proc.communicate(payload, timeout=wait)
    except subprocess.TimeoutExpired:
        return "timed-out"
    except OSError:
        return "unavailable"
    finally:
        tree.end()  # everything the executor started is gone when it returns
    # The answer is the first line, ended by a line feed alone, as a host reads an executor's report.
    if tree.proc.returncode != 0 or b"\n" not in out:
        return "unavailable"
    line = out.split(b"\n", 1)[0]
    if line.endswith(b"\r") or line.startswith(b"\xef\xbb\xbf"):
        return "unavailable"
    try:
        answer = host.strict_load(line)
    except host.Refused:
        return "unavailable"
    if not isinstance(answer, dict) or answer.get("ended") is not True or not isinstance(answer.get("reports"), list):
        return "unavailable"
    reports = {}
    wanted = {r["run_key"] for r in batch}
    for item in answer["reports"]:
        key = item.get("run_key") if isinstance(item, dict) else None
        if not isinstance(key, str) or key not in wanted or key in reports or "report" not in item:
            return "mismatch"
        reports[key] = item["report"]  # read as the host checks read a report, for its own check alone
    return reports


def append(root: pathlib.Path, rel: str, bodies: list[dict]) -> None:
    """Append evidence entries as ledger-append does: take the lock (waiting up to a minute), cut a torn ending, then
    append one line per entry after the last and write it to disk, and release the lock."""
    path = root / rel
    lock = path.with_name(path.name + ".lock")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise Stop("ledger-not-written", f"{rel}: {err}") from None
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except (FileExistsError, PermissionError):
            if time.monotonic() >= deadline:
                raise Stop("ledger-not-written", f"{rel}: its lock was held for a minute") from None
            time.sleep(0.2)
        except OSError as err:
            raise Stop("ledger-not-written", f"{rel}: {err}") from None
    try:
        try:
            read = ledger.read(path)
        except ledger.Corrupt:
            raise Stop("ledger-not-written", f"{rel} is corrupt") from None
        data = path.read_bytes() if path.exists() else b""
        keep = data[: data.rfind(b"\n") + 1] if read["torn"] else data
        previous = None
        if read["entries"]:
            last = keep[:-1].rsplit(b"\n", 1)[-1]
            previous = canonical.identity(host.strict_load(last.split(b" ", 3)[3]))
        lines = b""
        for body in bodies:
            entry = {"previous": previous, "kind": "evidence", "body": body}
            raw = canonical.encode(entry).encode("utf-8")
            lines += b"dodona1 %d %s " % (len(raw), hashlib.sha256(raw).hexdigest().encode("ascii")) + raw + b"\n"
            previous = canonical.identity(entry)
        with open(path, "r+b" if path.exists() else "wb") as f:
            f.truncate(len(keep))  # a torn ending is cut before anything is appended
            f.seek(len(keep))
            f.write(lines)
            f.flush()
            os.fsync(f.fileno())
    except OSError as err:
        raise Stop("ledger-not-written", f"{rel}: {err}") from None
    finally:
        try:
            os.remove(lock)
        except OSError:
            pass


def run(asked) -> dict:
    check_run_input(asked)
    ps.ENUMERATED.clear()
    ps.KEEP_OPEN = {}
    try:
        return run_with_sessions(asked)
    finally:
        for sess in ps.KEEP_OPEN.values():
            sess.close()
        ps.KEEP_OPEN = None


def run_with_sessions(asked) -> dict:
    out = ps.run(asked)  # steps 1 to 9, and the status command's view; step 5's checking sessions stay open
    root, site = pathlib.Path(asked["root"]), asked["site"]
    judged = out["judged"]
    entries = [s["do"]["append"] for s in judged["steps"] if "append" in s["do"]]
    writer, platform = judged["self"]["writer"], judged["self"]["platform"]
    names = sorted(judged["obligations"], key=lambda n: (ps.sort_key(ps.ENUMERATED[n]["binding"]["name"]), ps.sort_key(n)))
    # Step 10: the plan.
    plan = [n for n in names if not counts_for(entries, n, judged["obligations"][n]["preimage"], writer, platform)]
    counts = {"obligations": len(names), "reused": len(names) - len(plan), "checked": len(plan), "refused": 0,
              "not_checkable": len(out["not_checkable"])}
    counts.update({v: 0 for v in VERDICTS})
    finals = {}
    # Step 11: each check started, in plan order, on its binding's session from step 5.
    steps, waiting = {}, {}
    for name in plan:
        binding = ps.ENUMERATED[name]["binding"]
        sess = ps.KEEP_OPEN.get(binding["name"])
        offered = {c.get("capability") for c in sess.manifest.get("capabilities", []) if isinstance(c, dict)} if sess else set()
        if sess is None or "obligation.check" not in offered:
            finals[name] = {"refused": "no-check"}  # the binding or its provider does not check
            continue
        item = {k: v for k, v in ps.ENUMERATED[name]["item"].items() if k != "inputs"}
        gen = host.check_steps(sess, dict(item, binding=binding["name"]), ps.ENUMERATED[name]["inputs"],
                               [dict(t) for t in site["tools"]], site["platform"], root)
        advance(name, lambda gen=gen: next(gen), steps, waiting, finals, gen)
    # Step 12: batches until no check waits for a run.
    while waiting:
        batch = [{"name": n, "number": waiting[n][0], "run": waiting[n][1], "run_key": waiting[n][2]} for n in plan if n in waiting]
        answer = run_batch(root, asked["executor"], batch)
        waiting = {}
        for r in batch:
            name = r["name"]
            if answer == "unavailable":
                finals[name] = {"final": {"verdict": "unavailable"}, "unavailable": True}
            elif answer == "timed-out":
                finals[name] = {"final": {"verdict": "error", "reason": "run-timed-out"}}
            elif answer == "mismatch":
                finals[name] = {"final": {"verdict": "error", "reason": "batch-report-mismatch"}}
            elif r["run_key"] not in answer:
                finals[name] = {"final": {"verdict": "error", "reason": "run-missing"}}
            elif not isinstance(answer[r["run_key"]], dict):
                finals[name] = {"final": {"verdict": "error", "reason": "run-report-not-an-object"}}
            else:
                advance(name, lambda name=name, rep=answer[r["run_key"]]: steps[name].send(rep), steps, waiting, finals, steps[name])
    # Step 13: record passed and failed verdicts, in plan order.
    bodies = []
    for name in plan:
        got = finals[name]
        if "refused" in got:
            counts["refused"] += 1
            continue
        verdict = "unavailable" if got.get("unavailable") else got["final"]["verdict"]
        counts[verdict] += 1
        if verdict in ("passed", "failed"):
            preimage = judged["obligations"][name]["preimage"]
            bodies.append({"obligation": name, "preimage": preimage, "core_key": canonical.identity(preimage),
                           "platform": platform, "verdict": verdict, "writer": writer})
    if bodies:
        append(root, asked["ledger"], bodies)
    # Step 14: the ledgers read again, the status view made from them.
    new_entries, note, absent = ps.entries_of(root, asked)
    judged["steps"] = [{"do": {"append": {"kind": e["kind"], "body": e["body"]}}} for e in new_entries] + [ps.NOTHING]
    out["ledger"] = note
    out["project_doubts"] = ps.doubts(out, absent)
    out["counts"] = counts
    return out


def advance(name, step, steps, waiting, finals, gen) -> None:
    """Advance one check to its next run, or to its end. A rule of the check refuses that check; a broken session
    refuses the whole run, since every check on it is in doubt."""
    try:
        waiting[name] = step()
        steps[name] = gen
    except StopIteration as done:
        finals[name] = done.value
    except host.Refused as err:
        if str(err) in SESSION_REASONS:
            raise Stop(str(err), f"the session broke while checking {name}") from None
        finals[name] = {"refused": str(err)}


def keep_transcript(asked) -> None:
    """Every message sent to and read from a provider, in order, as tools/check_transcript.py reads them, written to a
    new file when the input asks for one and the run reported."""
    path = pathlib.Path(asked["root"]) / asked["transcript"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "x", encoding="utf-8") as f:  # never over a file that is there
            f.write(json.dumps(ps.TRANSCRIPT, ensure_ascii=False, indent=1) + "\n")
    except OSError:
        raise Stop("transcript-not-written", asked["transcript"]) from None


def emit(value: dict) -> None:
    """One JSON object, as UTF-8 bytes whatever the console's encoding (Windows' is not UTF-8), and a line feed."""
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main() -> int:
    kernel = sys.argv[sys.argv.index("--kernel") + 1:] if "--kernel" in sys.argv else None
    try:
        raw = sys.stdin.buffer.read()
        body = raw[:-1] if raw.endswith(b"\n") else raw
        if not (body.startswith(b"{") and body.endswith(b"}")):
            raise ValueError("not one JSON object alone")
        asked = host.strict_load(body)
    except Exception:  # noqa: BLE001 - any input that is not strict JSON is bad input
        asked = None
    ps.TRANSCRIPT.clear()
    try:
        out = run(asked)
        if "transcript" in asked:
            keep_transcript(asked)
    except Stop as stop:
        emit({"refused": stop.reason, "detail": stop.detail})
        return 0
    if kernel:
        answer = subprocess.run(kernel + ["scenario"], input=json.dumps(out["judged"]).encode("utf-8"), capture_output=True, check=True)
        out["report"] = json.loads(answer.stdout)["results"][-1]
        out["project_status"] = ps.headline(out["report"]["project"]["status"], out["project_doubts"])
    emit(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
