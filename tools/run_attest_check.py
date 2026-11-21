"""Check that a kernel and the reference signer agree. Stage-0 helper (decision 0023).

    python tools/run_attest_check.py -- <kernel command> <subcommand>

The acts scenarios carry check values worked out when the kit was written.
Here the values are made now, by tools/attest.py, over records the kit does
not contain, and a kernel must grade them as vouched for; and it must stop
doing so when the record is changed afterwards, the key is not the one policy
lists, or a field is left uncovered. The key is the kit's fixture: public by
design and worth nothing.

The kernel grades the seven records in one scenario run, which exits 0. A
completed grade that differs, or a per-case answer that is missing or
malformed (output that is not JSON included), is `MISMATCH`, named in
`rejected`. A kernel that could not be started, ran out of time, was ended by
a signal or exited other than 0 graded nothing: every case is `UNFINISHED`.
So is a case whose check by the signer itself did not finish or gave the other
answer than the fixture expects (a failure of the judge), and a run whose
records the fixture and signer could not make. The last line is
`{"cases", "matched", "all_matched", "unfinished", "rejected"}`. Exit status
is 0 if every case matched, 1 if the run completed with mismatches, and 2 if
any case or the judge itself did not finish, after mismatches too, or no case
ran (issue 41).
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
FACTS = ["actor", "brief", "fresh_context", "given", "known_bad", "transcript", "worker", "kind", "target", "result", "lineage", "ticket"]


def make_cases() -> tuple[dict, bytes, list[tuple[str, dict, str, str, bool]]]:
    """The policy, the fixture's key and the seven records with the grade each must earn."""
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
    flipped = dict(copy.deepcopy(good), result="refused")
    moved = dict(copy.deepcopy(good), target="sha256:" + "0" * 64)
    unbound = copy.deepcopy(base)  # signed by hand without the four fields that bind it: the value is good, and it earns nothing
    facts_only = sorted(f for f in FACTS if f not in attest.BINDS)
    unbound["attestation"] = {"harness": "harness-1", "key": "harness-1", "covers": facts_only, "mac": attest.check_value(base, facts_only, key)}
    cases = [("signed now by the reference signer", good, "cross-make", "attested", True),
             ("changed after signing", changed, "helper", "declared", False),
             ("the result changed after signing", flipped, "helper", "declared", False),
             ("the target changed after signing", moved, "helper", "declared", False),
             ("signed without what was judged", unbound, "helper", "declared", True),
             ("signed with a key policy does not list", other_key, "helper", "declared", False),
             ("one fact left uncovered", partly, "helper", "declared", True)]
    return policy, key, cases


def grade(command: list[str], scenario: dict) -> tuple[list | None, str]:
    """The kernel's per-case answers from a run that completed with exit 0, or None and why it gave none.
    Output that is not JSON, or has no list of results, is a completed answer in which every case is missing."""
    try:
        done = subprocess.run(command, input=json.dumps(scenario).encode("utf-8"), capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as err:
        return None, f"{type(err).__name__}: {err}"
    if done.returncode != 0:
        return None, f"the kernel exited with {done.returncode}"
    try:
        results = json.loads(done.stdout.decode("utf-8"))["results"]
    except (ValueError, KeyError, TypeError):
        return [], ""
    return results if isinstance(results, list) else [], ""


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    cases: list[tuple[str, dict, str, str, bool]] = []
    rejected: list[str] = []
    unfinished = 0
    try:
        policy, key, cases = make_cases()
    except Exception as err:  # the fixture or the signer could not make the records: nothing was judged, which is not a mismatch
        cases = []
        unfinished = 1
        print(f"UNFINISHED the records could not be made: {type(err).__name__}: {err}")
    if cases:
        scenario = {"kind": "acts", "name": "made-now", "policy": policy, "steps": [{"do": {"grade": record}} for _, record, _, _, _ in cases]}
        results, why = grade(command, scenario)
        if results is None:
            unfinished = len(cases)
            for name, _, _, _, _ in cases:
                print(f"UNFINISHED {name}: {why}")
        else:
            for number, (name, record, level, origin, valid) in enumerate(cases):
                got = results[number] if number < len(results) else None
                got = got if isinstance(got, dict) else {}
                try:
                    ours = attest.verify(record, key)
                except Exception as err:  # the signer's own check did not finish: this case showed nothing either way
                    unfinished += 1
                    print(f"UNFINISHED {name}: the signer's own check did not finish: {type(err).__name__}: {err}")
                    continue
                if ours != valid:  # the reference got its own known fixture wrong: a failure of the judge, not of the kernel
                    unfinished += 1
                    print(f"UNFINISHED {name}: the signer's own check says {ours} where the fixture says {valid}")
                    continue
                ok = got.get("level") == level and got.get("source") == origin
                if not ok:
                    rejected.append(name)
                print(f"{'match   ' if ok else 'MISMATCH'} {name}: kernel says {got.get('level')}, {got.get('source')}; the signer's own check says {ours}")
    matched = len(cases) - len(rejected) - unfinished if cases else 0
    print(json.dumps({"cases": len(cases), "matched": matched,
                      "all_matched": not rejected and not unfinished and bool(cases),
                      "unfinished": unfinished, "rejected": rejected}))
    if unfinished or not cases:
        return 2
    return 1 if rejected else 0


if __name__ == "__main__":
    sys.exit(main())
