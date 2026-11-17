"""Run a kernel against the canonical-encoding vectors and judge it.

Stage-0 helper (decision 0023).

    python tools/run_vectors.py -- <kernel command and arguments>

For each vector the command is started with a JSON text on standard input.
It must print one JSON object and exit with status 0:

    {"canonical": "<text>", "sha256": "<64 hex digits>"}     if it accepts
    {"refused": "<reason>"}                                  if it refuses

Accepted vectors must give exactly the expected text and hash. Refused vectors
must be refused with exactly the expected reason. Exit status is 0 only if
every vector matched.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def ask(command: list[str], text: str) -> dict | None:
    try:
        done = subprocess.run(command, input=text.encode("utf-8"), capture_output=True, timeout=30)
        if done.returncode != 0:
            return None
        answer = json.loads(done.stdout.decode("utf-8"))
        return answer if isinstance(answer, dict) else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    vectors = json.loads((ROOT / "conformance" / "vectors" / "canonical.json").read_text(encoding="utf-8"))
    total = failed = 0
    for item in vectors["accept"]:
        total += 1
        # The input is written with escapes and spacing a kernel must see through.
        answer = ask(command, json.dumps(item["value"], indent=1, ensure_ascii=True))
        if answer != {"canonical": item["canonical"], "sha256": item["sha256"]}:
            failed += 1
            print(f"MISMATCH accept: {item['name']}: got {answer}")
    for item in vectors["reject"]:
        total += 1
        answer = ask(command, item["text"])
        if answer != {"refused": item["reason"]}:
            failed += 1
            print(f"MISMATCH reject: {item['name']}: expected refusal {item['reason']}, got {answer}")
    print(json.dumps({"vectors": total, "matched": total - failed, "all_matched": failed == 0 and total > 0}))
    return 0 if failed == 0 and total else 1


if __name__ == "__main__":
    sys.exit(main())
