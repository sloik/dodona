"""Judge a kernel's ledger against conformance/ledger/cases.json and more-damage.json. Stage-0 helper (decision 0023).

    python tools/run_ledger_cases.py -- <kernel command>
    python tools/run_ledger_cases.py --write LEDGER WRITER COUNT -- <kernel command>   # started by itself, as one of two writers

The kernel is given the subcommands `ledger-append` and `ledger-read`, as
conformance/README.md describes. The expected file is built here from the
reference encoder, so the kernel's bytes are compared with something no kernel
produced. A kernel that answers, wrongly, is reported as `MISMATCH` under the
check's name; a kernel that could not be started, timed out, was ended by a
signal or exited with a status other than 0, and a judge that could not go on
(a file it could not write, a writer it could not start or wait for), end the
run as `UNFINISHED`. Exit status is 0 if every check matched, 1 if the run
completed with mismatches, and 2 if it did not complete or no check ran.
Output that is not JSON from a kernel that exited with 0 is a wrong answer.

A writer exits 0 when every append was taken, 3 when the kernel answered
something else, and 2 when it could not finish. The parent treats other codes
as unfinished, including Python's default exit 1 before the writer starts.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
WRITER_MISMATCH = 3


class Deep(dict):
    """A request whose body is nested `levels` deep: written out here, since a JSON writer may not reach that deep."""

    def __init__(self, request: dict, levels: int):
        super().__init__(request)
        self.levels = levels

    def text(self) -> str:
        rest = json.dumps(dict(self))[1:]
        return '{"body": ' + '{"x": ' * (self.levels - 1) + "{}" + "}" * (self.levels - 1) + (", " + rest if rest != "}" else "}")


class Unfinished(Exception):
    """The kernel gave no answer: it could not be started, timed out, was ended by a signal or exited with a status other than 0."""


class Stopped:
    """Around a whole run, its cleanup included: ends it at the first thing that did not complete, and keeps why."""

    reason: str | None = None

    def __enter__(self) -> Stopped:
        return self

    def __exit__(self, kind, err, trace) -> bool:
        if isinstance(err, Exception):
            self.reason = f"{type(err).__name__}: {err}"
            return True
        return False


def ask(command: list[str], sub: str, payload: dict, timeout: int = 60):
    text = payload.text() if isinstance(payload, Deep) else json.dumps(payload)
    try:
        done = subprocess.run(command + [sub], input=text.encode("utf-8"), capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as err:
        raise Unfinished(f"{sub}: {type(err).__name__}: {err}") from err
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace")[-300:]
        raise Unfinished(f"{sub}: the kernel exited with {done.returncode}: {said}")
    try:
        return json.loads(done.stdout.decode("utf-8"))
    except (ValueError, RecursionError) as err:  # the kernel finished and answered something that is not JSON: a wrong answer
        return {"error": type(err).__name__}


def entries_of(answer) -> list[dict] | None:
    """The entries a read answered, or None when they are not a list of objects."""
    if isinstance(answer, dict) and isinstance(answer.get("entries"), list) and all(isinstance(e, dict) for e in answer["entries"]):
        return answer["entries"]
    return None


def line(entry: dict) -> bytes:
    raw = canonical.encode(entry).encode("utf-8")
    return b"dodona1 %d %s " % (len(raw), hashlib.sha256(raw).hexdigest().encode("ascii")) + raw + b"\n"


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    stopped = Stopped()
    with stopped, tempfile.TemporaryDirectory() as tmp:
        spec = json.loads((ROOT / "conformance" / "ledger" / "cases.json").read_text(encoding="utf-8"))
        good = spec["file"].encode("utf-8")
        lines = good.splitlines(keepends=True)
        last_id = spec["entries"][-1]["identity"]
        folder = pathlib.Path(tmp)

        def fresh(name: str, data: bytes) -> pathlib.Path:
            path = folder / name
            path.write_bytes(data)
            return path

        def read(path: pathlib.Path):
            return ask(command, "ledger-read", {"ledger": str(path)})

        def summary(answer) -> dict:
            if isinstance(answer, dict) and isinstance(answer.get("entries"), list):
                return {"torn": answer.get("torn"), "entries": len(answer["entries"])}
            return answer

        # Appending through the kernel must give exactly the reference bytes.
        built = folder / "built.ledger"
        identities = []
        for item in spec["append"]:
            answer = ask(command, "ledger-append", {"ledger": str(built), "kind": item["kind"], "body": item["body"], "wait_ms": 2000})
            identities.append(answer.get("appended") if isinstance(answer, dict) else None)
        check("appended entries have the expected identities", identities == [e["identity"] for e in spec["entries"]], str(identities))
        check("the file is byte for byte the reference file", built.exists() and built.read_bytes() == good)
        answer = read(built)
        check("reading it back gives the entries", isinstance(answer, dict) and answer.get("torn") is False
              and answer.get("entries") == [e["entry"] for e in spec["entries"]], str(summary(answer)))
        check("a ledger that does not exist is empty", summary(read(folder / "absent.ledger")) == {"torn": False, "entries": 0})
        check("an empty file is empty", summary(read(fresh("empty.ledger", b""))) == {"torn": False, "entries": 0})

        extra = {"previous": last_id, "kind": "evidence", "body": {"obligation": "ob-9", "verdict": "passed"}}
        for case in spec["damage"]:
            how, want = case["how"], case["expect"]
            if how == "truncate-last-entry-at-every-byte":
                wrong = []
                for cut in range(1, len(lines[-1])):
                    path = fresh("torn.ledger", good[:-cut])
                    got = summary(read(path))
                    if got != want:
                        wrong.append((cut, got))
                        continue
                    # Appending to a torn ledger drops the torn bytes and carries on from the last whole entry.
                    again = ask(command, "ledger-append", {"ledger": str(path), "kind": "evidence", "body": extra["body"], "wait_ms": 2000})
                    expected = b"".join(lines[:-1]) + line({"previous": spec["entries"][-2]["identity"], "kind": "evidence", "body": extra["body"]})
                    if not isinstance(again, dict) or "appended" not in again or path.read_bytes() != expected:
                        wrong.append((cut, "append after a torn ending"))
                check(case["name"], not wrong, f"{len(wrong)} of {len(lines[-1]) - 1} cuts wrong; first: {wrong[:1]}")
                continue
            data = {
                "drop-last-line": lambda: b"".join(lines[:-1]),
                "flip-byte-in-line-2": lambda: lines[0] + lines[1][:-10] + bytes([lines[1][-10] ^ 1]) + lines[1][-9:] + lines[2],
                "flip-byte-in-line-3": lambda: lines[0] + lines[1] + lines[2][:-10] + bytes([lines[2][-10] ^ 1]) + lines[2][-9:],
                "drop-line-2": lambda: lines[0] + lines[2],
                "swap-lines-1-2": lambda: lines[1] + lines[0] + lines[2],
                "append-garbage-line": lambda: good + b"this is not an entry\n",
                "crlf-line-1": lambda: lines[0][:-1] + b"\r\n" + lines[1] + lines[2],
                "append-entry-with-wrong-previous": lambda: good + line(dict(extra, previous=spec["entries"][0]["identity"])),
                "append-entry-not-canonical": lambda: good + not_canonical(extra),
                "append-entry-by-hand": lambda: good + line(extra),
            }[how]()
            got = summary(read(fresh("damaged.ledger", data)))
            check(case["name"], got == want, f"expected {want}, got {got}")
            if "refused" in want:
                refused = ask(command, "ledger-append", {"ledger": str(folder / "damaged.ledger"), "kind": "evidence", "body": {}, "wait_ms": 500})
                check(case["name"] + ": and nothing can be appended to it", refused == {"refused": "corrupt"}, str(refused))

        # More damage: each case is a whole file with the answer a reader must give.
        more = json.loads((ROOT / "conformance" / "ledger" / "more-damage.json").read_text(encoding="utf-8"))
        for case in more["damage"]:
            data, want = case["file"].encode("utf-8"), case["expect"]
            path = fresh("more.ledger", data)
            got = summary(read(path))
            check(case["name"], got == want, f"expected {want}, got {got}")
            if "refused" in want:
                refused = ask(command, "ledger-append", {"ledger": str(path), "kind": "evidence", "body": {}, "wait_ms": 500})
                check(case["name"] + ": and nothing can be appended to it", refused == {"refused": "corrupt"} and path.read_bytes() == data
                      and not pathlib.Path(str(path) + ".lock").exists(), f"answered {refused}; file {'unchanged' if path.read_bytes() == data else 'changed'}")

        # An entry of a kind no rule gives a meaning: written, kept, and followed like any other.
        other = more["unlisted_kind"]
        path = fresh("other-kind.ledger", good)
        answer = ask(command, "ledger-append", dict(other["append"], ledger=str(path), wait_ms=2000))
        check("an entry of an unlisted kind is appended", answer == {"appended": other["identity"]} and path.read_bytes() == other["file"].encode("utf-8"), str(answer))
        path = fresh("other-kind.ledger", other["file"].encode("utf-8"))
        answer = read(path)
        entries = entries_of(answer)
        check("an entry of an unlisted kind is kept by the reader", entries is not None and answer.get("torn") is False
              and [e.get("kind") for e in entries][-1:] == [other["append"]["kind"]] and len(entries) == 4
              and entries[-1].get("body") == other["append"]["body"], str(summary(answer)))
        answer = ask(command, "ledger-append", dict(other["then"]["append"], ledger=str(path), wait_ms=2000))
        check("an append after an entry of an unlisted kind works", isinstance(answer, dict) and "appended" in answer
              and path.read_bytes() == other["then"]["file"].encode("utf-8"), str(answer))

        # An entry as deep as a ledger allows: written, and followed like any other.
        deepest = more["deepest"]
        path = fresh("deepest.ledger", good)
        answer = ask(command, "ledger-append", dict(deepest["append"], ledger=str(path), wait_ms=2000))
        check("an entry nested 64 levels deep is appended", answer == {"appended": deepest["identity"]} and path.read_bytes() == deepest["file"].encode("utf-8"), str(answer)[:200])
        answer = ask(command, "ledger-append", dict(deepest["then"]["append"], ledger=str(path), wait_ms=2000))
        check("an append after an entry nested 64 levels deep works", isinstance(answer, dict) and "appended" in answer
              and path.read_bytes() == deepest["then"]["file"].encode("utf-8"), str(answer)[:200])

        # Requests that are not requests: refused, and nothing written.
        def req(case: dict, **more_fields):
            asked = dict(case["request"], **more_fields)
            return Deep(asked, case["body_levels"]) if "body_levels" in case else asked

        for case in more["bad_requests"]:
            absent = folder / "bad-request.ledger"
            if absent.exists():
                absent.unlink()
            answer = ask(command, "ledger-append", req(case, ledger=str(absent), wait_ms=500))
            check(f"a request to append with {case['name']} is refused, new ledger", answer == {"refused": "bad-request"} and not absent.exists()
                  and not pathlib.Path(str(absent) + ".lock").exists(), f"answered {answer}; file {'written' if absent.exists() else 'not written'}")
            existing = fresh("bad-request-existing.ledger", good)
            answer = ask(command, "ledger-append", req(case, ledger=str(existing), wait_ms=500))
            check(f"a request to append with {case['name']} is refused, existing ledger", answer == {"refused": "bad-request"} and existing.read_bytes() == good
                  and not pathlib.Path(str(existing) + ".lock").exists(), f"answered {answer}; file {'unchanged' if existing.read_bytes() == good else 'changed'}")
            # The request is judged before the lock is taken and the ledger read: bad-request before locked and corrupt.
            damaged = next(d["file"].encode("utf-8") for d in more["damage"] if d["expect"].get("refused") == "corrupt")
            spoilt = fresh("bad-request-corrupt.ledger", damaged)
            answer = ask(command, "ledger-append", req(case, ledger=str(spoilt), wait_ms=500))
            check(f"a request to append with {case['name']} is refused, corrupt ledger", answer == {"refused": "bad-request"} and spoilt.read_bytes() == damaged, f"answered {answer}")
            held = fresh("bad-request-held.ledger", good)
            pathlib.Path(str(held) + ".lock").write_text("held by the judge\n", encoding="ascii")
            answer = ask(command, "ledger-append", req(case, ledger=str(held), wait_ms=300))
            check(f"a request to append with {case['name']} is refused, held lock", answer == {"refused": "bad-request"} and held.read_bytes() == good, f"answered {answer}")
            pathlib.Path(str(held) + ".lock").unlink()

        # A held lock.
        held = fresh("held.ledger", good)
        lock = pathlib.Path(str(held) + ".lock")
        marker = b"held by the judge\n"
        lock.write_bytes(marker)
        refused = ask(command, "ledger-append", {"ledger": str(held), "kind": "evidence", "body": {}, "wait_ms": 300})
        unchanged = held.read_bytes() == good
        try:
            observed_marker = lock.read_bytes()
        except FileNotFoundError:
            observed_marker = None
        intact = observed_marker == marker
        check("a held lock refuses an append", refused == {"refused": "locked"} and unchanged and intact,
              f"answered {refused}; ledger unchanged: {unchanged}; marker intact: {intact}")
        # A wrong answer may already have removed the fixture's marker.
        lock.unlink(missing_ok=observed_marker is None)

        # Two writers at once.
        shared = folder / "shared.ledger"
        each = 20
        writers: list[subprocess.Popen] = []
        try:
            for n in range(2):
                writers.append(subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), "--write", str(shared), str(n), str(each), "--"]
                                                + command))
            codes = [w.wait(timeout=300) for w in writers]
        finally:  # a writer already started is not left running when its peer could not start or finish
            cleanup_error = None
            for w in writers:
                try:
                    if w.poll() is None:
                        w.kill()
                        w.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired) as err:
                    cleanup_error = err
            if cleanup_error is not None:
                raise Unfinished(f"could not reap a writer: {cleanup_error}") from cleanup_error
        if any(code not in (0, WRITER_MISMATCH) for code in codes):
            raise Unfinished(f"a writer did not finish: exit codes {codes}")
        answer = read(shared)
        entries = entries_of(answer) or []
        bodies = [entry.get("body") for entry in entries]
        seen = sorted(json.dumps([body.get("writer"), body.get("n")]) for body in bodies if isinstance(body, dict))
        check("two kernels appending at once lose nothing", codes == [0, 0] and isinstance(answer, dict) and answer.get("torn") is False
              and len(seen) == len(bodies) and seen == sorted(json.dumps([w, n]) for w in range(2) for n in range(each))
              and not pathlib.Path(str(shared) + ".lock").exists(),
              f"exit codes {codes}, {len(seen)} entries")

    rejected = []
    for name, ok, detail in results:
        if ok:
            print(f"match    {name}")
        else:
            rejected.append(name)
            print(f"MISMATCH {name}: {detail}")
    unfinished = 1 if stopped.reason else 0
    if unfinished:
        print(f"UNFINISHED after {len(results)} checks: {stopped.reason}")
    print(json.dumps({"checks": len(results), "matched": len(results) - len(rejected),
                      "all_matched": not rejected and not unfinished and bool(results),
                      "unfinished": unfinished, "rejected": rejected}))
    if unfinished or not results:
        return 2
    return 1 if rejected else 0


def not_canonical(entry: dict) -> bytes:
    """A well-formed line whose payload is valid JSON for the entry but not in canonical form."""
    raw = json.dumps(entry, sort_keys=False, separators=(", ", ": ")).encode("utf-8")
    return b"dodona1 %d %s " % (len(raw), hashlib.sha256(raw).hexdigest().encode("ascii")) + raw + b"\n"


def writer() -> int:
    """Used by the two-writers check: append a run of entries through the kernel."""
    try:
        at = sys.argv.index("--write")
        path, who, count = sys.argv[at + 1], int(sys.argv[at + 2]), int(sys.argv[at + 3])
        command = sys.argv[sys.argv.index("--", at) + 1:]
        for n in range(count):
            answer = ask(command, "ledger-append", {"ledger": path, "kind": "evidence", "body": {"writer": who, "n": n}, "wait_ms": 60000})
            if not isinstance(answer, dict) or "appended" not in answer:
                print(f"writer {who} gave up at entry {n}: the kernel answered {answer}")
                return WRITER_MISMATCH
    except Exception as err:  # no answer to judge, which is not a wrong one: exit 2, never 1
        print(f"writer did not finish: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(writer() if "--write" in sys.argv else main())
