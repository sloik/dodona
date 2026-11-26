"""Run a kernel against the canonical-encoding vectors and judge it.

Stage-0 helper (decision 0023).

    python tools/run_vectors.py -- <kernel command and arguments>

For each vector the command is started with a JSON text on standard input.
It must print one JSON object and exit with status 0:

    {"canonical": "<text>", "sha256": "<64 hex digits>"}     if it accepts
    {"refused": "<reason>"}                                  if it refuses

Accepted vectors must give exactly the expected text and hash. Refused vectors
must be refused with exactly the expected reason. A completed wrong answer is
a named mismatch. A failure to run or obtain a usable answer leaves that
vector unfinished. Exit 0 means every vector matched, 1 means a completed
suite with mismatches, and 2 means an unfinished or empty suite.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import host  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read_vectors() -> list[tuple[str, bytes, dict]]:
    vectors = json.loads((ROOT / "conformance" / "vectors" / "canonical.json").read_text(encoding="utf-8"))
    # The input is written with escapes and spacing a kernel must see through.
    cases = [(v["name"], json.dumps(v["value"], indent=1, ensure_ascii=True).encode("utf-8"),
              {"canonical": v["canonical"], "sha256": v["sha256"]}) for v in vectors["accept"]]
    cases += [(v["name"], v["text"].encode("utf-8"), {"refused": v["reason"]}) for v in vectors["reject"]]
    names = [name for name, _, _ in cases]
    if any(not isinstance(name, str) or not name for name in names) or len(set(names)) != len(names):
        raise ValueError("vectors must have distinct nonempty names")
    if any(not isinstance(value, str) for _, _, want in cases for value in want.values()):
        raise ValueError("canonical text, hash and refusal reason must be strings")
    return cases


def ask(command: list[str], data: bytes) -> tuple[dict | None, str]:
    try:
        done = subprocess.run(command, input=data, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as err:
        return None, f"{type(err).__name__}: {err}"
    if b"No space left on device" in done.stderr or b"ENOSPC" in done.stderr:
        return None, "the canonical command reported disk full"
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace")[-300:].strip()
        return None, f"the canonical command exited with {done.returncode}" + (f": {detail}" if detail else "")
    try:
        answer = host.strict_load(done.stdout, limit=None)
    except (host.Refused, RecursionError) as err:
        return None, f"the canonical command gave invalid JSON: {err}"
    if isinstance(answer, dict) and (isinstance(answer.get("refused"), str)
                                     or all(isinstance(answer.get(field), str) for field in ("canonical", "sha256"))):
        return answer, ""
    return None, "the canonical command gave no usable acceptance or refusal"


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    command = sys.argv[sys.argv.index("--") + 1:]
    cases = []
    matched = unfinished = 0
    rejected: list[str] = []
    try:
        cases = read_vectors()
    except (OSError, KeyError, TypeError, ValueError, RecursionError) as err:
        unfinished = 1
        print(f"UNFINISHED the vectors could not be read: {type(err).__name__}: {err}")
    for name, data, want in cases:
        answer, why = ask(command, data)
        if answer is None:
            unfinished += 1
            print(f"UNFINISHED {name}: {why}")
        elif answer != want:
            rejected.append(name)
            print(f"MISMATCH {name}: expected {want}, got {answer}")
        else:
            matched += 1
    print(json.dumps({"vectors": len(cases), "matched": matched,
                      "all_matched": bool(cases) and not rejected and not unfinished,
                      "unfinished": unfinished, "rejected": rejected}))
    if unfinished or not cases:
        return 2
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
