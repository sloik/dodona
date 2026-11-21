"""Report the status of this project from its ledger. Stage-0 helper (decision 0026).

    python tools/status.py --ledger FILE --writer NAME [--json] [--policy-ref REF] --kernel CMD...

--ledger may be repeated; the owner's ledger in the repository is always read
too. --policy-ref names the protected branch the policy is read from
(origin/main unless given).

It gathers what a kernel needs and judges nothing itself: the intents and
their criteria from intents/, the bar from policy.toml, the obligations and
the inputs each depends on as things stand now (asked of the provider), and
the entries of the ledger (read by the kernel). The kernel works out every
status. The rules are the status rules in conformance/README.md.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import pathlib
import subprocess
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import host  # noqa: E402
import intents as intents_tool  # noqa: E402

ROOT = host.ROOT
OWNER_LEDGER = ROOT / "records" / "owner.ledger"


def unclear(text: str) -> str | None:
    """Why an intent's text could be read two ways, or None. The rules are in tools/intents.py."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "0000-probe.md"
        path.write_text(text, encoding="utf-8")
        try:
            intents_tool.read(path)
        except intents_tool.Unreadable as err:
            return str(err)
    return None


def read_intents(obligations: list[str], folder: pathlib.Path | None = None) -> dict:
    """Intents from intents/*.md, read by tools/intents.py: criteria come from the front matter only.

    `checks` in each criterion ties it to obligations by name pattern. A
    criterion with none is not covered, whatever its words say.
    """
    intents, parents = {}, {}
    for path in sorted((folder or ROOT / "intents").glob("[0-9]*.md")):
        try:
            fields, items, text = intents_tool.read(path)
        except intents_tool.Unreadable as err:
            raise SystemExit(f"{path.name} cannot be read one way only: {err}") from None
        ident = fields["id"].strip('"')
        if ident in intents:
            raise SystemExit(f"{path.name} has the id {ident} of another intent file; no status is reported")
        criteria = {}
        for item in items:
            names = sorted({n for pattern in item.get("checks", []) for n in obligations if fnmatch.fnmatchcase(n, pattern)})
            criteria[item["id"]] = {"words": item["words"], "gate": item["gate"], "checked_by": names}
        intents[ident] = {"owner": fields.get("owner", ""), "worker": fields.get("worker", ""), "children": [],
                          "words": text, "criteria": criteria}
        parents[ident] = fields.get("parent", "").strip('"')
    for ident, parent in parents.items():
        if parent in intents:
            intents[parent]["children"].append(ident)
    return intents


def written_criteria(intent_id: str) -> list[dict]:
    """The criteria of one intent as its front matter gives them, with every field."""
    for path in sorted((ROOT / "intents").glob("[0-9]*.md")):
        fields, items, _ = intents_tool.read(path)
        if fields["id"].strip('"') == intent_id:
            return items
    return []


def anchored_policy(ref: str) -> tuple[dict, str]:
    """The policy as the protected reference has it, and a sentence saying where it came from.

    The bar a project is held to, and the keys allowed to vouch for an act,
    must not be editable by the agent being judged. So the policy is read from
    the reference branch, not from the working copy, whenever that is possible.
    """
    here = (ROOT / "policy.toml").read_text(encoding="utf-8")
    try:
        done = subprocess.run(["git", "-C", str(ROOT), "show", f"{ref}:policy.toml"], capture_output=True, timeout=30)
        there = done.stdout.decode("utf-8") if done.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        there = None
    if there is None:
        return tomllib.loads(here), f"policy: the working copy. Not anchored: {ref} could not be read, so whoever can edit this copy can lower the bar"
    note = f"policy: as on {ref}" + ("" if there == here else ". The working copy differs and is not used")
    return tomllib.loads(there), note


def read_ledgers(paths: list[pathlib.Path], kernel: list[str]) -> list[dict] | None:
    """The entries of each ledger in turn, read by the kernel; None if one is damaged."""
    entries: list[dict] = []
    for path in paths:
        read = host.kernel(kernel, "ledger-read", {"ledger": str(path)})
        if "refused" in read:
            print(f"the ledger {path} is damaged at line {read.get('at')}; no status is reported")
            return None
        if OWNER_LEDGER.exists() and OWNER_LEDGER.resolve() != OWNER_LEDGER.absolute():
            print("records/owner.ledger is a link to somewhere else; no status is reported")
            return None
        if pathlib.Path(path).resolve() == OWNER_LEDGER.resolve():
            # The owner's ledger holds owners' acts and nothing else. A result found there was not
            # produced by a run, so it is not read.
            entries += [e for e in read["entries"] if e.get("kind") == "act"]
        else:
            # Acts of owners count only from the owner's ledger kept in the repository, where every
            # one is a reviewed change. An act found anywhere else is not read at all.
            entries += [e for e in read["entries"] if e.get("kind") != "act"]
    return entries


def scenario(ledger_entries: list[dict], writer: str, policy: dict) -> dict:
    tools, _ = host.lock_tools()
    session = host.Session([sys.executable, str(ROOT / "providers" / "tlc" / "provider.py")], ROOT, [])
    try:
        found, files = host.list_project(session, ROOT)
        obligations = {o["name"]: {"preimage": host.preimage(o, host.inputs_of(o, files), tools, session.manifest)} for o in found}
    finally:
        session.close()
    floors = {kind: entry["level"] for kind, entry in policy.get("separation", {}).get("floor", {}).items()}
    return {"kind": "status", "name": "this-project",
            "self": {"writer": writer, "platform": "linux/aarch64"},
            "policy": {"min_hard_gates": policy.get("gates", {}).get("min_hard", 1), "required": policy.get("required", {}).get("intents", []),
                       "trusted_writers": policy.get("trusted_writers", []), "floors": floors,
                       "attestors": policy.get("attestors", {}), "makes": policy.get("makes", [])},
            "obligations": obligations, "intents": read_intents(sorted(obligations)),
            "steps": [{"do": {"append": {"kind": e["kind"], "body": e["body"]}}} for e in ledger_entries] or
                     [{"do": {"change": {"obligation": next(iter(sorted(obligations))), "preimage": obligations[next(iter(sorted(obligations)))]["preimage"]}}}]}


def coverage(intents: dict, floor: int) -> dict:
    """Where the hard gates of each intent tree sit (decision 0030).

    The floor is counted over a whole tree, so a child can be delivered with
    fewer hard gates of its own than policy demands. That is the rule; this
    says where it happens, so nobody reads a child's status as meeting the
    floor alone. Each intent is counted once, however it is reached.
    """
    floor = max(floor, 1)
    parent = {c: p for p, it in intents.items() for c in it["children"]}

    def root_of(ident: str) -> str:
        seen = {ident}
        while ident in parent and parent[ident] not in seen:
            ident = parent[ident]
            seen.add(ident)
        return ident

    def below(ident: str) -> set:
        found, todo = set(), [ident]
        while todo:
            here = todo.pop()
            if here not in found and here in intents:
                found.add(here)
                todo.extend(intents[here]["children"])
        return found

    # Hard as the status rules count it: a gate that is not exactly soft or deferred.
    own = {i: sum(1 for c in it["criteria"].values() if c["gate"] not in ("soft", "deferred")) for i, it in intents.items()}
    out = {}
    for ident in intents:
        root = root_of(ident)
        out[ident] = {"own_hard": own[ident], "subtree_hard": sum(own[i] for i in below(ident)),
                      "root": root, "tree_hard": sum(own[i] for i in below(root)), "floor": floor}
        out[ident]["floor_met_only_over_tree"] = ident != root and out[ident]["subtree_hard"] < floor
    thinnest = {}
    for ident, item in out.items():
        best = thinnest.get(item["root"])
        if best is None or (item["own_hard"], ident) < (out[best]["own_hard"], best):
            thinnest[item["root"]] = ident
    return {"intents": out, "thinnest": thinnest}


def render(report: dict, torn: bool, entries: int, note: str) -> str:
    lines = [f"project: {report['project']['status']}", note,
             f"ledger: {entries} entries" + (", ending in an entry that was cut short" if torn else "")
             + (f", {report['rejected']} rejected" if report.get("rejected") else "")]
    tally: dict[str, int] = {}
    for item in report["obligations"].values():
        tally[item["status"]] = tally.get(item["status"], 0) + 1
    lines.append("obligations: " + ", ".join(f"{count} {status}" for status, count in sorted(tally.items())))
    where = report.get("coverage", {"intents": {}, "thinnest": {}})
    for root, ident in sorted(where["thinnest"].items()):
        lines.append(f"thinnest in tree {root}: intent {ident}, {where['intents'][ident]['own_hard']} hard gates of its own")
    for ident, item in sorted(report["intents"].items()):
        gates, score, apart = item["gates"], item["score"], item["separation"]
        shown, asked = item.get("shown", {}), item.get("exceptions", {})
        below = f" and {asked['below_floor']} below the floor" if asked.get("below_floor") else ""
        lines.append(f"{ident}  {item['status']} · gates: {gates['hard']} hard, {gates['soft']} soft, {gates['deferred']} deferred"
                     f" ({gates['deferred_open']} open) · met: {score['met']} of {score['of']}"
                     f" · shown: {shown.get('level', '?')} (weakest: criterion {shown.get('criterion', '?')})"
                     f" · exceptions: {asked.get('counted', '?')}{below}"
                     f" · separation: {apart['weakest']} ({apart['act']}), {apart['apart_or_better']} of {apart['of']} acts apart or better")
        mine = where["intents"].get(ident)
        if mine and mine["floor_met_only_over_tree"]:
            lines[-1] += (f" · floor: {mine['subtree_hard']} hard of its own and below, under the floor of {mine['floor']};"
                          f" met only over tree {mine['root']} ({mine['tree_hard']} hard)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ledger", type=pathlib.Path, action="append", default=[],
                    help="a ledger to read; may be repeated. The owner's ledger in the repository is always read too")
    ap.add_argument("--writer", required=True)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--policy-ref", default="origin/main", help="the protected branch the policy is read from")
    ap.add_argument("--kernel", nargs=argparse.REMAINDER, required=True)
    args = ap.parse_args()
    owner = OWNER_LEDGER
    ledgers = ([owner] if owner.exists() and all(p.resolve() != owner.resolve() for p in args.ledger) else []) + args.ledger
    entries = read_ledgers(ledgers, args.kernel)
    if entries is None:
        return 1
    policy, note = anchored_policy(args.policy_ref)
    answer = host.kernel(args.kernel, "scenario", scenario(entries, args.writer, policy))
    report = answer["results"][-1]
    report["policy_source"] = note
    report["coverage"] = coverage(read_intents([]), policy.get("gates", {}).get("min_hard", 1))
    print(json.dumps(report, indent=1, sort_keys=True) if args.json else render(report, False, len(entries), note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
