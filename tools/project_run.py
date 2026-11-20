"""The reference for a kernel's `run` command (decision 0034). Stage-0 helper.

    python tools/project_run.py [--kernel CMD...] < INPUT.json

It follows conformance/README.md, "How a project's run is judged": the status command's steps 1 to 9 (done by
tools/project_status.py), then a plan of what has no current result, checks through the providers with their
runs sent to the site's executor in batches, the verdicts appended to the ledger, and the status report made
again from what the ledgers now hold, with counts. Like the status reference it holds no status rules: the plan
reads whether a record counts as the status rules define it, and the report comes from a kernel's `scenario`.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402
import host  # noqa: E402
import ledger  # noqa: E402
import project_status as ps  # noqa: E402
from project_status import Stop  # noqa: E402

VERDICTS = ("passed", "failed", "error", "unavailable", "unsupported")


def check_run_input(asked: dict) -> None:
    """The fields a run adds to the status command's input (step 1)."""
    if not isinstance(asked, dict):
        return  # the status command's own check refuses it
    if not ps.relpath_ok(asked.get("ledger")) or asked.get("ledger") not in (asked.get("ledgers") or []):
        raise Stop("bad-input", "ledger must be a relative path listed among ledgers")
    executor = asked.get("executor")
    if not (isinstance(executor, list) and executor and all(isinstance(x, str) for x in executor)):
        raise Stop("bad-input", "executor must be a non-empty list of strings")


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


def run_batch(root: pathlib.Path, executor: list[str], batch: list[dict]) -> dict | None:
    """The reports of one batch by run_key; None when the batch gives every check in it `unavailable`; the string
    'mismatch' when its reports name a run not in it, or one twice."""
    payload = json.dumps({"runs": [{"number": r["number"], "run_key": r["run_key"], "run": r["run"]} for r in batch]},
                         ensure_ascii=False).encode("utf-8") + b"\n"
    wall = max([r["run"].get("limits", {}).get("wall_ms") for r in batch if isinstance(r["run"].get("limits", {}).get("wall_ms"), int)] or [0])
    wait = min(wall / 1000 + 60, 86_400) if wall else 86_400
    try:
        tree = host.Session._start(executor, root)  # in root, in a process group or job of its own
    except OSError:
        return None
    try:
        out, _ = tree.proc.communicate(payload, timeout=wait)
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None
    finally:
        tree.end()  # everything the executor started is gone when it returns
    if tree.proc.returncode != 0 or not out.endswith(b"\n") or out.count(b"\n") != 1 or out.endswith(b"\r\n"):
        return None
    try:
        answer = host.strict_load(out[:-1])
    except host.Refused:
        return None
    if not isinstance(answer, dict) or answer.get("ended") is not True or not isinstance(answer.get("reports"), list):
        return None
    reports = {}
    wanted = {r["run_key"] for r in batch}
    for item in answer["reports"]:
        if not isinstance(item, dict) or item.get("run_key") not in wanted or item["run_key"] in reports or not isinstance(item.get("report"), dict):
            return "mismatch"
        reports[item["run_key"]] = item["report"]
    return reports


def append(root: pathlib.Path, rel: str, bodies: list[dict]) -> None:
    """Append evidence entries as ledger-append does: under the lock, after the last entry, written to disk."""
    path = root / rel
    lock = path.with_name(path.name + ".lock")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise Stop("ledger-not-written", f"{rel}: {err}") from None
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        raise Stop("ledger-not-written", f"{rel}: its lock is held") from None
    try:
        os.close(fd)
        try:
            read = ledger.read(path)
        except ledger.Corrupt:
            raise Stop("ledger-not-written", f"{rel} is corrupt") from None
        data = path.read_bytes() if path.exists() else b""
        if read["torn"]:
            data = data[: data.rfind(b"\n") + 1]
        previous = None
        if read["entries"]:
            last = data[:-1].rsplit(b"\n", 1)[-1]
            previous = canonical.identity(host.strict_load(last.split(b" ", 3)[3]))
        for body in bodies:
            entry = {"previous": previous, "kind": "evidence", "body": body}
            raw = canonical.encode(entry).encode("utf-8")
            data += b"dodona1 %d %s " % (len(raw), hashlib.sha256(raw).hexdigest().encode("ascii")) + raw + b"\n"
            previous = canonical.identity(entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
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
    check_run_input(asked if isinstance(asked, dict) else None)
    ps.ENUMERATED.clear()
    out = ps.run(asked)  # steps 1 to 9, and the status command's view
    root, site = pathlib.Path(asked["root"]), asked["site"]
    if ps.same_file(root / asked["ledger"], root / asked["owner_ledger"]) if (root / asked["ledger"]).exists() and (root / asked["owner_ledger"]).exists() else False:
        raise Stop("bad-input", "ledger is the owner's ledger")
    judged = out["judged"]
    entries = [s["do"]["append"] for s in judged["steps"] if "append" in s["do"]]
    writer, platform = judged["self"]["writer"], judged["self"]["platform"]
    names = sorted(judged["obligations"], key=lambda n: (ps.sort_key(ps.ENUMERATED[n]["binding"]["name"]), ps.sort_key(n)))
    # Step 10: the plan.
    plan = [n for n in names if not counts_for(entries, n, judged["obligations"][n]["preimage"], writer, platform)]
    reused = len(names) - len(plan)
    counts = {"obligations": len(names), "reused": reused, "checked": len(plan), "refused": 0, "not_checkable": len(out["not_checkable"])}
    counts.update({v: 0 for v in VERDICTS})
    finals = {}
    if plan:
        # Step 11: one session per binding, the checks started in plan order.
        sessions, steps, waiting = {}, {}, {}
        try:
            for name in plan:
                binding = ps.ENUMERATED[name]["binding"]
                if binding["name"] not in sessions:
                    sessions[binding["name"]] = ps.session(root, site, binding)
                item = {k: v for k, v in ps.ENUMERATED[name]["item"].items() if k != "inputs"}
                obligation = dict(item, binding=binding["name"])
                gen = host.check_steps(sessions[binding["name"]], obligation, ps.ENUMERATED[name]["inputs"],
                                       [dict(t) for t in site["tools"]], site["platform"], root)
                try:
                    waiting[name] = next(gen)
                    steps[name] = gen
                except StopIteration as done:
                    finals[name] = done.value
                except host.Refused as err:
                    finals[name] = {"refused": str(err)}
            # Step 12: batches until no check waits for a run.
            while waiting:
                batch = [{"name": n, "number": waiting[n][0], "run": waiting[n][1], "run_key": waiting[n][2]} for n in plan if n in waiting]
                reports = run_batch(root, asked["executor"], batch)
                waiting = {}
                for r in batch:
                    name = r["name"]
                    if reports is None:
                        finals[name] = {"final": {"verdict": "unavailable"}, "unavailable": True}
                        continue
                    if reports == "mismatch":
                        finals[name] = {"final": {"verdict": "error", "reason": "batch-report-mismatch"}}
                        continue
                    if r["run_key"] not in reports:
                        finals[name] = {"final": {"verdict": "error", "reason": "run-missing"}}
                        continue
                    try:
                        waiting[name] = steps[name].send(reports[r["run_key"]])
                    except StopIteration as done:
                        finals[name] = done.value
                    except host.Refused as err:
                        finals[name] = {"refused": str(err)}
        finally:
            for sess in sessions.values():
                sess.close()
    # Step 13: record passed and failed verdicts, in plan order.
    bodies = []
    for name in plan:
        got = finals.get(name, {})
        if "refused" in got:
            counts["refused"] += 1
            continue
        verdict = "unavailable" if got.get("unavailable") else got.get("final", {}).get("verdict")
        counts[verdict] = counts.get(verdict, 0) + 1
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
    try:
        out = run(asked)
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
