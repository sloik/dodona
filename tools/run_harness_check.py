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
CONTROL = "the known cases tell the real checker from the one that agrees with everything"


def main() -> int:
    if "--" not in sys.argv or sys.argv[-1] == "--":
        print(__doc__)
        return 2
    command = sys.argv[sys.argv.index("--") + 1:]
    try:
        policy, cases = make_cases()
    except Exception as err:  # the fixture, a checker or the signer could not make the records: nothing was judged
        print(f"UNFINISHED the records could not be made: {type(err).__name__}: {err}")
        print(json.dumps({"cases": 0, "matched": 0, "all_matched": False, "unfinished": 1, "rejected": []}))
        return 2
    rejected: list[str] = []
    unfinished = 0
    total = len(cases) + 1  # the seven kernel cases and the known-answer control, CONTROL
    # The known-answer control is the eighth case, judged on the harness alone: the real checker refused the known-wrong
    # work and agreed to the known-right, and the checker that agrees with everything did not refuse the known-wrong.
    # The records are made in strict mode, so a checker that did not finish is never read as a refusal here. When the
    # control does not hold, the harness or its fixture failed: it is unfinished, never a kernel mismatch.
    real_known, nods_known = cases[0][1].get("known_bad", {}), cases[3][1].get("known_bad", {})
    control = real_known.get("rejected_wrong") is True and real_known.get("accepted_right") is True \
        and nods_known.get("rejected_wrong") is False
    print(f"{'match   ' if control else 'UNFINISHED'} {CONTROL}: real checker {real_known.get('rejected_wrong')}, "
          f"{real_known.get('accepted_right')}; agrees-with-everything rejected the known-wrong: {nods_known.get('rejected_wrong')}")
    unfinished += not control
    scenario = {"kind": "acts", "name": "from-the-harness", "policy": policy, "steps": [{"do": {"grade": record}} for _, record, _, _, _ in cases]}
    results, why = grade(command, scenario)
    if results is None:
        for name, _, _, _, _ in cases:
            print(f"UNFINISHED {name}: {why}")
        print(json.dumps({"cases": total, "matched": int(control), "all_matched": False,
                          "unfinished": unfinished + len(cases), "rejected": []}))
        return 2
    case_unfinished = 0
    for number, (name, record, result, level, origin) in enumerate(cases):
        got = results[number] if number < len(results) else None
        got = got if isinstance(got, dict) else {}
        if record.get("result") != result:  # the harness's own checker run did not give the fixture's grade: a judge failure
            case_unfinished += 1
            print(f"UNFINISHED {name}: the checker {record.get('result')} where the fixture says {result}")
            continue
        known = record.get("known_bad")
        if known is not None and number != 3 and not (known.get("rejected_wrong") is True and known.get("accepted_right") is True):
            # the real checker's own known-answer runs for this record did not hold (it may have crashed): a judge failure
            case_unfinished += 1
            print(f"UNFINISHED {name}: the real checker's known cases did not hold ({known.get('rejected_wrong')}, {known.get('accepted_right')})")
            continue
        ok = got.get("level") == level and got.get("source") == origin
        if not ok:
            rejected.append(name)
        print(f"{'match   ' if ok else 'MISMATCH'} {name}: the checker {record['result']}; kernel says {got.get('level')}, {got.get('source')} (expected {level}, {origin})")
    unfinished += case_unfinished
    print(json.dumps({"cases": total, "matched": total - len(rejected) - unfinished,
                      "all_matched": not rejected and not unfinished, "unfinished": unfinished, "rejected": rejected}))
    if unfinished:
        return 2
    return 1 if rejected else 0


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


def make_cases() -> tuple[dict, list]:
    """The policy and the seven records the harness signs now, each with the checker's grade, level and source expected."""
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
            return harness.run(args, [sys.executable, str(KIT / checker)], strict=True)

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
    return policy, cases


if __name__ == "__main__":
    sys.exit(main())
