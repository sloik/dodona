"""Judge the reference harness and a kernel together. Stage-0 helper (decision 0023).

    python tools/run_harness_check.py -- <kernel command> <subcommand>

The harness really starts a checker: a small one that reads the files it was
given, and one that agrees with everything. A kernel must grade what the
harness signed above `helper`, must see through the checker that agrees with
everything, and must cap a record the worker wrote itself, one changed after
signing, and one signed with a key policy does not list. The key is the
kit's fixture: public by design and worth nothing.
"""
from __future__ import annotations

import argparse
import copy
import json
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import harness  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
KIT = ROOT / "conformance" / "harness"


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    policy = json.loads((ROOT / "conformance" / "kernel" / "acts" / "attested_facts_earn_their_level.json").read_text(encoding="utf-8"))["policy"]
    with tempfile.TemporaryDirectory() as tmp:
        room = pathlib.Path(tmp)
        files = {"work": "the bridge holds and the gate opens\n", "criteria": "bridge gate\n", "brief": "say whether the work meets the criteria\n",
                 "wrong": "the bridge holds\n", "right": "a gate and a bridge\n", "good.key": policy["attestors"]["harness-1"], "other.key": "11" * 32}
        for name, text in files.items():
            (room / name).write_text(text, encoding="utf-8")

        def made(checker: str, key: str = "good.key", known: bool = True, makes: bool = True) -> dict:
            args = argparse.Namespace(key_file=str(room / key), key_name="harness-1", ticket="t-h1", kind="match-check",
                                      target="sha256:" + "5" * 64, intent="0001", criterion="c1", worker_id="worker-1", worker_session="s-100",
                                      brief_from="kernel", work=str(room / "work"), criteria=str(room / "criteria"), brief=str(room / "brief"),
                                      known_wrong=str(room / "wrong") if known else None, known_right=str(room / "right") if known else None,
                                      known_from="owner", checker_make="vendor-b/family-y" if makes else None,
                                      worker_make="vendor-a/family-x" if makes else None)
            return harness.run(args, [sys.executable, str(KIT / checker)])

        real = made("checker_reads.py")
        changed = copy.deepcopy(real)
        changed["result"], changed["given"] = "agreed", changed["given"][:-1]
        by_worker = {k: v for k, v in real.items() if k != "attestation"}
        cases = [("a real checker, tested, of another make", real, "agreed", "cross-make", "attested"),
                 ("the same with no makes stated", made("checker_reads.py", makes=False), "agreed", "tested", "attested"),
                 ("the same with no known cases", made("checker_reads.py", known=False), "agreed", "apart", "attested"),
                 ("a checker that agrees with everything", made("checker_nods.py"), "agreed", "apart", "attested"),
                 ("what was given changed after signing", changed, "agreed", "helper", "declared"),
                 ("signed with a key policy does not list", made("checker_reads.py", key="other.key"), "agreed", "helper", "declared"),
                 ("the same record written by the worker, unsigned", by_worker, "agreed", "helper", "declared")]
    scenario = {"kind": "acts", "name": "from-the-harness", "policy": policy, "steps": [{"do": {"grade": record}} for _, record, _, _, _ in cases]}
    try:
        done = subprocess.run(command, input=json.dumps(scenario).encode("utf-8"), capture_output=True, timeout=60)
        results = json.loads(done.stdout.decode("utf-8"))["results"] if done.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        results = []
    failed = 0
    for number, (name, record, result, level, origin) in enumerate(cases):
        got = results[number] if number < len(results) else {}
        ok = record["result"] == result and got.get("level") == level and got.get("source") == origin
        failed += not ok
        print(f"{'match   ' if ok else 'MISMATCH'} {name}: the checker {record['result']}; kernel says {got.get('level')}, {got.get('source')} (expected {level}, {origin})")
    wrong_seen = real["known_bad"]["rejected_wrong"] and real["known_bad"]["accepted_right"] and not cases[3][1]["known_bad"]["rejected_wrong"]
    if not wrong_seen:
        failed += 1
        print("MISMATCH the known cases did not tell the real checker from the one that agrees with everything")
    print(json.dumps({"cases": len(cases), "matched": len(cases) - min(failed, len(cases)), "all_matched": failed == 0}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
