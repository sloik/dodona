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
do not it must be an empty list. A usable wrong answer is a named mismatch.
A failed process or unusable answer is unfinished. Exit status is 0 for a
complete match, 1 for completed mismatches, and 2 for an unfinished or empty suite.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import host  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def read_vectors() -> list[tuple[str, dict, dict]]:
    vectors = json.loads((ROOT / "conformance" / "vectors" / "paths.json").read_text(encoding="utf-8"))
    if any(not isinstance(vectors[group], list) for group in ("accept", "reject", "reject_bytes", "collisions")):
        raise ValueError("each path vector group must be a list")
    if (any(not isinstance(p, str) for p in vectors["accept"])
            or any(not isinstance(v["path"], str) for v in vectors["reject"])):
        raise ValueError("text path vectors must hold strings")
    cases = [(f"accept {p!a}", {"hex": p.encode("utf-8").hex()}, {"accepted": True}) for p in vectors["accept"]]
    cases += [(f"reject {v['path']!a}", {"hex": v["path"].encode("utf-8", errors="surrogatepass").hex()},
               {"refused": v["reason"]}) for v in vectors["reject"]]
    cases += [(f"reject bytes {v['hex']}", {"hex": v["hex"]}, {"refused": v["reason"]}) for v in vectors["reject_bytes"]]
    if any(not isinstance(payload["hex"], str) or ("refused" in want and not isinstance(want["refused"], str))
           for _, payload, want in cases):
        raise ValueError("path bytes and refusal reasons must be strings")
    for item in vectors["collisions"]:
        name, pair, collide = item["name"], item["paths"], item["collide"]
        if not (isinstance(name, str) and name and isinstance(pair, list) and len(pair) == 2
                and all(isinstance(p, str) for p in pair) and pair[0] != pair[1] and type(collide) is bool):
            raise ValueError("each collision vector must name two distinct paths and give a boolean expectation")
        cases.append((f"collision case {name!a}", {"paths": pair}, {"collisions": [pair] if collide else []}))
    names = [name for name, _, _ in cases]
    if len(set(names)) != len(names):
        raise ValueError("vectors must have distinct identifiers")
    return cases


def ask(command: list[str], payload: dict) -> tuple[dict | None, str]:
    try:
        done = subprocess.run(command, input=json.dumps(payload).encode("utf-8"), capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as err:
        return None, f"{type(err).__name__}: {err}"
    if b"No space left on device" in done.stderr or b"ENOSPC" in done.stderr:
        return None, "the path command reported disk full"
    if done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace")[-300:].strip()
        return None, f"the path command exited with {done.returncode}" + (f": {detail}" if detail else "")
    try:
        answer = host.strict_load(done.stdout, limit=None)
    except (host.Refused, RecursionError) as err:
        return None, f"the path command gave invalid JSON: {err}"
    if not isinstance(answer, dict):
        return None, "the path command gave no JSON object"
    if "paths" in payload:
        pairs = answer.get("collisions")
        if not (isinstance(pairs, list) and all(isinstance(pair, list) and len(pair) == 2
                                                and all(isinstance(p, str) for p in pair) for pair in pairs)):
            return None, "the path-set command gave no usable collision pairs"
    elif type(answer.get("accepted")) is not bool and not isinstance(answer.get("refused"), str):
        return None, "the path command gave no usable acceptance or refusal"
    return answer, ""


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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    *command, one, many = sys.argv[sys.argv.index("--") + 1:]
    cases = []
    matched = unfinished = 0
    rejected: list[str] = []
    try:
        cases = read_vectors()
    except (OSError, KeyError, TypeError, ValueError, RecursionError) as err:
        unfinished = 1
        print(f"UNFINISHED the vectors could not be read: {type(err).__name__}: {err}")
    for name, payload, want in cases:
        is_set = "paths" in payload
        answer, why = ask(command + [many if is_set else one], payload)
        if answer is None:
            unfinished += 1
            print(f"UNFINISHED {name}: {why}")
            continue
        right = collisions_match(answer, payload["paths"], bool(want["collisions"])) if is_set else answer == want
        if right:
            matched += 1
        else:
            rejected.append(name)
            print(f"MISMATCH {name}: expected {want}, got {answer}")
    print(json.dumps({"vectors": len(cases), "matched": matched,
                      "all_matched": bool(cases) and not rejected and not unfinished,
                      "unfinished": unfinished, "rejected": rejected}))
    if unfinished or not cases:
        return 2
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
