"""Judge a kernel against the core-key vectors. Stage-0 helper (decision 0023).

    python tools/run_key_vectors.py -- <kernel command> <subcommand>

Example: python tools/run_key_vectors.py -- kernel/target/release/dodona-kernel key

A kernel answers each preimage with exit 0 and `{"core_key": ...}`, and refuses
one with exit 0 and `{"refused": ...}`. A completed answer that differs, output
that is not JSON included, is `MISMATCH`, named in `rejected`. A key command
that could not be started, ran out of time, was ended by a signal or exited
other than 0 answered nothing, and that vector is `UNFINISHED`. The last line is
`{"vectors", "matched", "all_matched", "unfinished", "rejected"}`. Exit status
is 0 if every vector matched, 1 if the run completed with mismatches, and 2 if
any vector or the judge itself did not finish, after mismatches too, or no
vector ran (issue 41).
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    cases = []
    rejected: list[str] = []
    unfinished = 0
    try:
        for name in ("core-key.json", "core-key-more.json"):
            vectors = json.loads((ROOT / "conformance" / "vectors" / name).read_text(encoding="utf-8"))
            cases += [(v["name"], v["preimage"], {"core_key": v["core_key"]}) for v in vectors.get("accept", [])]
            cases += [(v["name"], v["preimage"], {"refused": v["reason"]}) for v in vectors.get("reject", [])]
    except Exception as err:  # the judge could not read its vectors: nothing was judged, which is not a pass or a mismatch
        cases = []
        unfinished = 1
        print(f"UNFINISHED the vectors could not be read: {type(err).__name__}: {err}")
    for name, preimage, want in cases:
        try:
            done = subprocess.run(command, input=json.dumps(preimage).encode("utf-8"), capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as err:
            unfinished += 1
            print(f"UNFINISHED {name}: {type(err).__name__}: {err}")
            continue
        if done.returncode != 0:
            unfinished += 1
            print(f"UNFINISHED {name}: the key command exited with {done.returncode}")
            continue
        try:
            got = json.loads(done.stdout.decode("utf-8"))
        except ValueError:
            got = None
        if got != want:
            rejected.append(name)
            print(f"MISMATCH {name}: expected {want}, got {got}")
    matched = len(cases) - len(rejected) - unfinished if cases else 0
    print(json.dumps({"vectors": len(cases), "matched": matched,
                      "all_matched": not rejected and not unfinished and bool(cases),
                      "unfinished": unfinished, "rejected": rejected}))
    if unfinished or not cases:
        return 2
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
