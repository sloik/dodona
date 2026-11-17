"""Check that a kernel and the reference signer agree. Stage-0 helper (decision 0023).

    python tools/run_attest_check.py -- <kernel command> <subcommand>

The acts scenarios carry check values worked out when the kit was written.
Here the values are made now, by tools/attest.py, over records the kit does
not contain, and a kernel must grade them as vouched for; and it must stop
doing so when the record is changed afterwards, the key is not the one policy
lists, or a field is left uncovered. The key is the kit's fixture: public by
design and worth nothing.
"""
from __future__ import annotations

import copy
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import attest  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
FACTS = ["actor", "brief", "fresh_context", "given", "known_bad", "transcript", "worker"]


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    source = json.loads((ROOT / "conformance" / "kernel" / "acts" / "attested_facts_earn_their_level.json").read_text(encoding="utf-8"))
    policy = source["policy"]
    key = bytes.fromhex(policy["attestors"]["harness-1"])
    base = {k: v for k, v in source["steps"][0]["do"]["grade"].items() if k != "attestation"}
    base["ticket"], base["actor"] = "t-made-now", dict(base["actor"], id="checker-made-now", session="s-made-now")
    good = attest.sign(base, FACTS, key, "harness-1")
    changed = copy.deepcopy(good)
    changed["actor"]["session"] = "s-changed-afterwards"
    other_key = attest.sign(base, FACTS, bytes.fromhex("00" * 32), "harness-1")
    partly = attest.sign(base, [f for f in FACTS if f != "transcript"], key, "harness-1")  # its check value is good, and still it earns nothing
    cases = [("signed now by the reference signer", good, "cross-make", "attested", True),
             ("changed after signing", changed, "helper", "declared", False),
             ("signed with a key policy does not list", other_key, "helper", "declared", False),
             ("one fact left uncovered", partly, "helper", "declared", True)]
    scenario = {"kind": "acts", "name": "made-now", "policy": policy, "steps": [{"do": {"grade": record}} for _, record, _, _, _ in cases]}
    try:
        done = subprocess.run(command, input=json.dumps(scenario).encode("utf-8"), capture_output=True, timeout=60)
        results = json.loads(done.stdout.decode("utf-8"))["results"] if done.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        results = []
    failed = 0
    for number, (name, record, level, origin, valid) in enumerate(cases):
        got = results[number] if number < len(results) else {}
        ours = attest.verify(record, key)
        ok = got.get("level") == level and got.get("source") == origin and ours == valid
        failed += not ok
        print(f"{'match   ' if ok else 'MISMATCH'} {name}: kernel says {got.get('level')}, {got.get('source')}; the signer's own check says {ours}")
    print(json.dumps({"cases": len(cases), "matched": len(cases) - failed, "all_matched": failed == 0}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
