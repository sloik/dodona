"""The owner confirms an intent's criteria and gates. Stage-0 helper (decision 0028).

    python tools/confirm.py --intent ID --kernel CMD...

Run by the owner of the intent, at a terminal. It shows what is about to be
confirmed, exactly as a kernel sees it, and asks for the intent's number to be
typed. Then it adds one entry to the ledger kept in the repository,
records/owner.ledger, which the owner commits like any other change.

What the entry says: the owner agrees that these criteria, with these gates
and these checks behind them, are what was meant. It names the baseline, a
hash of exactly those things, so it stops counting the moment any of them
changes. It does not say the work is done.

What it is worth: it is the owner's word, written down. Nothing vouches for
who typed it, so a kernel grades it `helper`, and it counts only while the
project's policy sets the floor for confirmations no higher than that. An
agent must not run this for the owner; it refuses to run without a terminal,
which stops accidents and nothing more.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import secrets
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import host  # noqa: E402
import status  # noqa: E402

ROOT = host.ROOT
OWNER_LEDGER = status.OWNER_LEDGER


def record(intent_id: str, intent: dict, baseline: str) -> dict:
    """The act record of a confirmation. Every fact in it is declared, none vouched for."""
    return {"ticket": "owner-" + secrets.token_hex(8), "kind": "confirm-baseline", "target": baseline,
            "lineage": {"intent": intent_id, "kind": "confirm-baseline"}, "result": "agreed",
            "actor": {"id": intent["owner"], "session": "terminal-" + secrets.token_hex(4)},
            "worker": {"id": intent["worker"], "session": "not-recorded"}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--intent", required=True)
    ap.add_argument("--ledger", type=pathlib.Path, default=OWNER_LEDGER,
                    help="only for trying the command out: a confirmation counts only in records/owner.ledger")
    ap.add_argument("--policy-ref", default="origin/main")
    ap.add_argument("--kernel", nargs=argparse.REMAINDER, required=True)
    args = ap.parse_args()
    if args.ledger.absolute().resolve() != args.ledger.absolute():
        print("refused: the owner's ledger must be a file in the repository, not a link to one elsewhere")
        return 2
    args.ledger = args.ledger.resolve()
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("refused: a confirmation is the owner's own act and is made at a terminal")
        return 2
    # The terminal check stops an agent running this by accident. It does not stop one that means to:
    # a program can give it a terminal. What stops that is that the entry is a committed change to
    # records/owner.ledger, reviewed before it reaches the protected branch (decision 0028).
    policy, note = status.anchored_policy(args.policy_ref)
    entries = status.read_ledgers([args.ledger], args.kernel)
    if entries is None:
        return 1
    asked = status.scenario(entries, "owner", policy)
    if args.intent not in asked["intents"]:
        print(f"there is no intent {args.intent}")
        return 1
    intent = asked["intents"][args.intent]
    if not asked["steps"]:
        # Nothing recorded yet: one step that names nothing, so the kernel reports the state as it is.
        asked["steps"] = [{"do": {"set_gate": {"intent": "", "criterion": "", "to": "hard"}}}]
    report = host.kernel(args.kernel, "scenario", asked)["results"][-1]["intents"][args.intent]
    if not intent["owner"] or not intent["worker"]:
        print("the intent must name its owner and the worker whose work it judges, in its front matter")
        return 1
    print(f"Intent {args.intent}, owned by {intent['owner']}; the work is done by {intent['worker']}.")
    print(note)
    for name, criterion in sorted(intent["criteria"].items()):
        checks = ", ".join(criterion["checked_by"][:3]) + (f" and {len(criterion['checked_by']) - 3} more" if len(criterion["checked_by"]) > 3 else "")
        print(f"  criterion {name}: gate {criterion['gate']}; checked by {checks or 'nothing a kernel can read yet'}")
    if intent["children"]:
        print("  children:", ", ".join(sorted(intent["children"])))
    print(f"Status now: {report['status']}. Baseline: {report['baseline']}")
    print("Confirming says these criteria and gates are what you meant. It does not say the work is done.")
    if input(f"Type {args.intent} to confirm, anything else to leave it: ").strip() != args.intent:
        print("nothing was recorded")
        return 1
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    answer = host.kernel(args.kernel, "ledger-append", {"ledger": str(args.ledger), "kind": "act", "wait_ms": 5000,
                                                         "body": record(args.intent, intent, report["baseline"])})
    if "appended" not in answer:
        print("the kernel refused to write the entry:", answer)
        return 1
    where = args.ledger.relative_to(ROOT) if args.ledger.is_relative_to(ROOT) else args.ledger
    print(f"recorded in {where}. Only records/owner.ledger counts; commit it to make the confirmation count.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
