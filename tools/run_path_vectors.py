"""Run a kernel against the path-check vectors and judge it.

Stage-0 helper (decision 0023).

    python tools/run_path_vectors.py -- <kernel command> <subcommand for one path> <subcommand for a set>

Example: python tools/run_path_vectors.py -- kernel/target/release/dodona-kernel path path-set

For one path the kernel is started with {"hex": "<the path's bytes in hex>"}
on standard input and must print {"accepted": true} or {"refused": "<reason>"}.
For a set it is started with {"paths": ["...", ...]} and must print
{"collisions": [["a", "b"], ...]}, empty when no two paths collide.
Every collision vector holds two paths. Where they collide the answer must be
exactly one pair naming those two paths as given, in either order; where they
do not it must be an empty list. Anything else is a mismatch.
Exit status is 0 only if every vector matched.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def ask(command: list[str], payload: dict) -> dict | None:
    try:
        done = subprocess.run(command, input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=30)
        if done.returncode != 0:
            return None
        answer = json.loads(done.stdout.decode("utf-8"))
        return answer if isinstance(answer, dict) else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def collisions_match(answer: dict | None, paths: list[str], collide: bool) -> bool:
    """True only for the exact answer: one pair of the vector's own two paths, or an empty list."""
    got = answer.get("collisions") if isinstance(answer, dict) else None
    if not isinstance(got, list):
        return False
    if not collide:
        return got == []
    if len(got) != 1 or not isinstance(got[0], list) or len(got[0]) != 2:
        return False
    first, second = got[0]
    return (isinstance(first, str) and isinstance(second, str) and first != second
            and sorted([first, second]) == sorted(paths))


def main() -> int:
    if "--" not in sys.argv or len(sys.argv) - sys.argv.index("--") < 4:
        print(__doc__)
        return 2
    *command, one, many = sys.argv[sys.argv.index("--") + 1:]
    vectors = json.loads((ROOT / "conformance" / "vectors" / "paths.json").read_text(encoding="utf-8"))
    total = failed = 0

    def expect(label: str, got, want) -> None:
        nonlocal total, failed
        total += 1
        if got != want:
            failed += 1
            print(f"MISMATCH {label}: expected {want}, got {got}")

    for path in vectors["accept"]:
        expect(f"accept {path!r}", ask(command + [one], {"hex": path.encode("utf-8").hex()}), {"accepted": True})
    for item in vectors["reject"]:
        raw = item["path"].encode("utf-8", errors="surrogatepass")
        expect(f"reject {item['path']!r}", ask(command + [one], {"hex": raw.hex()}), {"refused": item["reason"]})
    for item in vectors["reject_bytes"]:
        expect(f"reject bytes {item['hex']}", ask(command + [one], {"hex": item["hex"]}), {"refused": item["reason"]})
    for item in vectors["collisions"]:
        answer = ask(command + [many], {"paths": item["paths"]})
        want = {"collisions": [item["paths"]] if item["collide"] else []}
        got = want if collisions_match(answer, item["paths"], item["collide"]) else answer
        expect(f"collision case {item['name']!r}", got, want)
    print(json.dumps({"vectors": total, "matched": total - failed, "all_matched": failed == 0 and total > 0}))
    return 0 if failed == 0 and total else 1


if __name__ == "__main__":
    sys.exit(main())
