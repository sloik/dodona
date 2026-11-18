"""Judge a kernel against the core-key vectors. Stage-0 helper (decision 0023).

    python tools/run_key_vectors.py -- <kernel command> <subcommand>

Example: python tools/run_key_vectors.py -- kernel/target/release/dodona-kernel key
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
    for name in ("core-key.json", "core-key-more.json"):
        vectors = json.loads((ROOT / "conformance" / "vectors" / name).read_text(encoding="utf-8"))
        cases += [(v["name"], v["preimage"], {"core_key": v["core_key"]}) for v in vectors.get("accept", [])]
        cases += [(v["name"], v["preimage"], {"refused": v["reason"]}) for v in vectors.get("reject", [])]
    failed = 0
    for name, preimage, want in cases:
        try:
            done = subprocess.run(command, input=json.dumps(preimage).encode("utf-8"), capture_output=True, timeout=30)
            got = json.loads(done.stdout.decode("utf-8")) if done.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            got = None
        if got != want:
            failed += 1
            print(f"MISMATCH {name}: expected {want}, got {got}")
    print(json.dumps({"vectors": len(cases), "matched": len(cases) - failed, "all_matched": failed == 0 and bool(cases)}))
    return 0 if failed == 0 and cases else 1


if __name__ == "__main__":
    sys.exit(main())
