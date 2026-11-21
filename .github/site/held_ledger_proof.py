"""Issue a completed receipt for the hosted held-ledger qualification.

    python .github/site/held_ledger_proof.py SYSTEM RECEIPT

SYSTEM is macos, linux or windows. RECEIPT is the output JSON path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCE = "15fe061c47d5cef91fa4c7c0b88e872af485e5f0"
REF = "refs/heads/dodona-eight-41-held-ledger-proof"
SYSTEMS = {"macos": "darwin", "linux": "linux", "windows": "win32"}
MOCK_TESTS = 10
CHECKS = 110
NEEDED = {"a held lock refuses an append", "two kernels appending at once lose nothing"}


class Unfinished(ValueError):
    """A complete, passing proof receipt cannot be emitted."""


def run(command: list[str], seconds: int) -> tuple[str, str]:
    print(subprocess.list2cmdline(command), flush=True)
    # Files let the invocation's timeout finish even if a child still holds inherited output.
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            done = subprocess.run(command, cwd=ROOT, stdout=out, stderr=err, timeout=seconds, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise Unfinished(f"{command[0]}: {error}") from error
        out.seek(0)
        err.seek(0)
        stdout, stderr = (file.read().decode("utf-8", "backslashreplace") for file in (out, err))
    print(stdout, end="", flush=True)
    print(stderr, end="", file=sys.stderr, flush=True)
    if done.returncode != 0:
        raise Unfinished(f"{subprocess.list2cmdline(command)} exited {done.returncode}")
    return stdout, stderr


def invocation(system: str) -> dict:
    lane = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REPOSITORY": "sloik/dodona",
            "GITHUB_REF": REF, "GITHUB_JOB": "held-ledger-proof"}
    if sys.platform != SYSTEMS[system] or any(os.environ.get(key) != value for key, value in lane.items()):
        raise Unfinished("wrong platform or manual proof lane")
    revisions = run(["git", "rev-parse", "HEAD", "HEAD^"], 10)[0].splitlines()
    head = os.environ.get("GITHUB_SHA", "")
    if (revisions != [head, SOURCE] or not re.fullmatch(r"[0-9a-f]{40}", head)
            or head != os.environ.get("GITHUB_WORKFLOW_SHA")):
        raise Unfinished("checkout, pinned source or dispatched workflow revision differs")
    if run(["git", "status", "--porcelain"], 10)[0].strip():
        raise Unfinished("proof checkout is dirty")
    run(["git", "diff", "--exit-code", SOURCE, head, "--", "kernel", "kernel2", "tools", "conformance", "spec"], 20)
    run_id, attempt = (os.environ.get(key, "") for key in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT"))
    if any(not re.fullmatch(r"[1-9][0-9]*", value) for value in (run_id, attempt)):
        raise Unfinished("missing run or attempt metadata")
    return {"source": SOURCE, "head": head, "system": system, "run_id": int(run_id), "attempt": int(attempt)}


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise Unfinished("duplicate judge footer field")
    return result


def ledger_result(stdout: str, stderr: str) -> dict:
    lines = stdout.splitlines()
    names = {line.removeprefix("match    ") for line in lines[:-1] if line.startswith("match    ")}
    if stderr or len(lines) != CHECKS + 1 or len(names) != CHECKS or "" in names or not NEEDED <= names:
        raise Unfinished("ledger judge did not report every named match cleanly")
    try:
        footer = json.loads(lines[-1], object_pairs_hook=unique_object)
    except ValueError as error:
        raise Unfinished(f"unusable ledger judge footer: {error}") from error
    expected = {"checks": CHECKS, "matched": CHECKS, "all_matched": True, "unfinished": 0, "rejected": []}
    if (not isinstance(footer, dict) or footer.keys() != expected.keys()
            or any(type(footer[key]) is not type(value) or footer[key] != value for key, value in expected.items())):
        raise Unfinished("ledger judge footer is incomplete or inconsistent")
    return dict(footer, exit=0)


def prove(system: str) -> dict:
    receipt = invocation(system)
    _, mocks = run([sys.executable, "-m", "unittest", "-v", "tools.check_repo.LedgerJudgeTests"], 60)
    if not re.search(rf"^Ran {MOCK_TESTS} tests in ", mocks, re.MULTILINE) or mocks.rstrip().splitlines()[-1] != "OK":
        raise Unfinished("ledger judge mocks did not all complete")
    run(["cargo", "build", "--release", "--locked", "--manifest-path", "kernel/Cargo.toml"], 480)
    rust = "kernel/target/release/dodona-kernel" + (".exe" if system == "windows" else "")
    judge = [sys.executable, "tools/run_ledger_cases.py", "--"]
    results = {}
    failures = []
    for name, kernel in (("rust", [rust]), ("javascript", ["node", "kernel2/dodona-kernel2.js"])):
        try:
            results[name] = ledger_result(*run([*judge, *kernel], 300))
        except Unfinished as error:
            failures.append(f"{name}: {error}")
    if failures:
        raise Unfinished(" | ".join(failures))
    vectors = (ROOT / "conformance/ledger/cases.json").read_bytes()
    return dict(receipt, status="completed", mocks={"exit": 0, "tests": MOCK_TESTS},
                ledger=results, cases_sha256=hashlib.sha256(vectors).hexdigest())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("system", choices=SYSTEMS)
    parser.add_argument("receipt", type=pathlib.Path)
    args = parser.parse_args()
    try:
        line = json.dumps(prove(args.system), sort_keys=True)
        with args.receipt.open("x", encoding="utf-8") as output:
            output.write(line + "\n")
    except (OSError, Unfinished) as error:
        print(json.dumps({"status": "unfinished", "system": args.system, "reason": str(error)}))
        return 2
    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
