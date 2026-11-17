"""Judge a kernel's ledger against conformance/ledger/cases.json. Stage-0 helper (decision 0023).

    python tools/run_ledger_cases.py -- <kernel command>

The kernel is given the subcommands `ledger-append` and `ledger-read`, as
conformance/README.md describes. The expected file is built here from the
reference encoder, so the kernel's bytes are compared with something no kernel
produced. Exit status is 0 only if every check matched.
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


def ask(command: list[str], sub: str, payload: dict, timeout: int = 60):
    try:
        done = subprocess.run(command + [sub], input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=timeout)
        return json.loads(done.stdout.decode("utf-8")) if done.returncode == 0 else {"exit": done.returncode}
    except (OSError, subprocess.TimeoutExpired, ValueError) as err:
        return {"error": type(err).__name__}


def line(entry: dict) -> bytes:
    raw = canonical.encode(entry).encode("utf-8")
    return b"dodona1 %d %s " % (len(raw), hashlib.sha256(raw).hexdigest().encode("ascii")) + raw + b"\n"


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    spec = json.loads((ROOT / "conformance" / "ledger" / "cases.json").read_text(encoding="utf-8"))
    good = spec["file"].encode("utf-8")
    lines = good.splitlines(keepends=True)
    last_id = spec["entries"][-1]["identity"]
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    with tempfile.TemporaryDirectory() as tmp:
        folder = pathlib.Path(tmp)

        def fresh(name: str, data: bytes) -> pathlib.Path:
            path = folder / name
            path.write_bytes(data)
            return path

        def read(path: pathlib.Path):
            return ask(command, "ledger-read", {"ledger": str(path)})

        def summary(answer) -> dict:
            if isinstance(answer, dict) and "entries" in answer:
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

        # A held lock.
        held = fresh("held.ledger", good)
        lock = pathlib.Path(str(held) + ".lock")
        lock.write_text("held by the judge\n", encoding="ascii")
        refused = ask(command, "ledger-append", {"ledger": str(held), "kind": "evidence", "body": {}, "wait_ms": 300})
        check("a held lock refuses an append", refused == {"refused": "locked"} and held.read_bytes() == good, str(refused))
        lock.unlink()

        # Two writers at once.
        shared = folder / "shared.ledger"
        each = 20
        writers = [subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), "--write", str(shared), str(n), str(each), "--"] + command)
                   for n in range(2)]
        codes = [w.wait(timeout=300) for w in writers]
        answer = read(shared)
        seen = sorted((e["body"].get("writer"), e["body"].get("n")) for e in answer.get("entries", [])) if isinstance(answer, dict) else []
        check("two kernels appending at once lose nothing", codes == [0, 0] and answer.get("torn") is False
              and seen == sorted((w, n) for w in range(2) for n in range(each)) and not pathlib.Path(str(shared) + ".lock").exists(),
              f"exit codes {codes}, {len(seen)} entries")

    failed = 0
    for name, ok, detail in results:
        if ok:
            print(f"match    {name}")
        else:
            failed += 1
            print(f"MISMATCH {name}: {detail}")
    print(json.dumps({"checks": len(results), "matched": len(results) - failed, "all_matched": failed == 0 and bool(results)}))
    return 0 if failed == 0 and results else 1


def not_canonical(entry: dict) -> bytes:
    """A well-formed line whose payload is valid JSON for the entry but not in canonical form."""
    raw = json.dumps(entry, sort_keys=False, separators=(", ", ": ")).encode("utf-8")
    return b"dodona1 %d %s " % (len(raw), hashlib.sha256(raw).hexdigest().encode("ascii")) + raw + b"\n"


def writer() -> int:
    """Used by the two-writers check: append a run of entries through the kernel."""
    at = sys.argv.index("--write")
    path, who, count = sys.argv[at + 1], int(sys.argv[at + 2]), int(sys.argv[at + 3])
    command = sys.argv[sys.argv.index("--", at) + 1:]
    for n in range(count):
        answer = ask(command, "ledger-append", {"ledger": path, "kind": "evidence", "body": {"writer": who, "n": n}, "wait_ms": 60000})
        if not isinstance(answer, dict) or "appended" not in answer:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(writer() if "--write" in sys.argv else main())
