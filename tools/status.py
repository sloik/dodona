"""Report the status of this project from its ledger. Stage-0 helper (decision 0026).

    python tools/status.py --ledger FILE --writer NAME [--json] --kernel CMD...

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
import pathlib
import subprocess
import sys
import tomllib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import host  # noqa: E402

ROOT = host.ROOT
OWNER_LEDGER = ROOT / "records" / "owner.ledger"


def read_intents(obligations: list[str]) -> dict:
    """Intents from intents/*.md: the front matter, and the criteria table.

    `checks` in the front matter ties a criterion to obligations by name
    pattern. A criterion with none is not covered, whatever its table says.
    """
    intents, parents = {}, {}
    for path in sorted((ROOT / "intents").glob("[0-9]*.md")):
        text = path.read_text(encoding="utf-8")
        front = text.split("---")[1]
        fields = {}
        for line in front.splitlines():
            if line and not line.startswith(" ") and ":" in line:
                key, _, value = line.partition(":")
                fields[key.strip()] = value.strip()
        ident = fields["id"].strip('"')
        checks = json.loads(fields["checks"]) if fields.get("checks") else {}
        criteria = {}
        for line in text.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if line.startswith("|") and len(cells) >= 3 and cells[0].isdigit():
                names = sorted(n for pattern in checks.get(cells[0], []) for n in obligations if fnmatch.fnmatchcase(n, pattern))
                criteria[cells[0]] = {"gate": cells[2], "checked_by": sorted(set(names))}
        intents[ident] = {"owner": fields.get("owner", ""), "worker": fields.get("worker", ""), "children": [], "criteria": criteria}
        parents[ident] = fields.get("parent", "").strip('"')
    for ident, parent in parents.items():
        if parent in intents:
            intents[parent]["children"].append(ident)
    return intents


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
        if pathlib.Path(path).resolve() == OWNER_LEDGER.resolve():
            entries += read["entries"]
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


def render(report: dict, torn: bool, entries: int, note: str) -> str:
    lines = [f"project: {report['project']['status']}", note,
             f"ledger: {entries} entries" + (", ending in an entry that was cut short" if torn else "")
             + (f", {report['rejected']} rejected" if report.get("rejected") else "")]
    tally: dict[str, int] = {}
    for item in report["obligations"].values():
        tally[item["status"]] = tally.get(item["status"], 0) + 1
    lines.append("obligations: " + ", ".join(f"{count} {status}" for status, count in sorted(tally.items())))
    for ident, item in sorted(report["intents"].items()):
        gates, score, apart = item["gates"], item["score"], item["separation"]
        shown, asked = item.get("shown", {}), item.get("exceptions", {})
        below = f" and {asked['below_floor']} below the floor" if asked.get("below_floor") else ""
        lines.append(f"{ident}  {item['status']} · gates: {gates['hard']} hard, {gates['soft']} soft, {gates['deferred']} deferred"
                     f" ({gates['deferred_open']} open) · met: {score['met']} of {score['of']}"
                     f" · shown: {shown.get('level', '?')} (weakest: criterion {shown.get('criterion', '?')})"
                     f" · exceptions: {asked.get('counted', '?')}{below}"
                     f" · separation: {apart['weakest']} ({apart['act']}), {apart['apart_or_better']} of {apart['of']} acts apart or better")
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
    ledgers = ([owner] if owner.exists() and owner not in args.ledger else []) + args.ledger
    entries = read_ledgers(ledgers, args.kernel)
    if entries is None:
        return 1
    policy, note = anchored_policy(args.policy_ref)
    answer = host.kernel(args.kernel, "scenario", scenario(entries, args.writer, policy))
    report = answer["results"][-1]
    report["policy_source"] = note
    print(json.dumps(report, indent=1, sort_keys=True) if args.json else render(report, False, len(entries), note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
