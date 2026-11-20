"""The reference for a kernel's `status` command (decision 0034). Stage-0 helper.

    python tools/project_status.py [--kernel CMD...] < INPUT.json

It follows the rules in conformance/README.md, "How a project's status is judged", step by step:
it reads the project file, asks the providers the site names for the obligations and the intents,
reads the ledgers and the policy it is given, and prints the status scenario it would judge, with
the coverage and what it could not serve. It holds no status rules of its own: the report is what
a kernel's `scenario` command gives for that scenario, so without `--kernel` the report is left out.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402
import host  # noqa: E402
import ledger  # noqa: E402

SERVED = ("obligation.enumerate", "intent.index")
UNREAD_CRITERIA = False  # set in step 7: a criterion declares what no status rule reads yet
ENUMERATED: dict = {}  # step 5: each obligation's binding, as enumerated, and the files of F, for a run command
TRANSCRIPT: list = []  # every message sent to and read from a provider, in order, for a run command that keeps one
KEEP_OPEN: dict | None = None  # a run command sets this: step 5's sessions of bindings that check are kept open
NOTHING = {"do": {"set_gate": {"intent": "", "criterion": "", "to": "hard"}}}


class Stop(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def command_ok(value) -> bool:
    """A command: a non-empty list of strings, none holding a NUL, which no program's arguments can carry."""
    return strings(value) and bool(value) and all("\x00" not in x for x in value)


def sort_key(text: str) -> list[int]:
    """How the canonical encoding sorts keys: by UTF-16 code units."""
    return list(text.encode("utf-16-be"))


def canonical_sorted(items) -> list[str]:
    """Sorted as the canonical encoding sorts keys, each once."""
    return sorted(set(items), key=sort_key)


def relpath_ok(rel) -> bool:
    """Relative, and the same on every system: no drive (no `:`), no backslash, no empty, `.` or `..` segment."""
    return isinstance(rel, str) and bool(rel) and not rel.startswith("/") and "\\" not in rel and ":" not in rel \
        and all(seg not in ("", ".", "..") for seg in rel.split("/"))


def reached_without_link(root: pathlib.Path, rel: str) -> bool:
    here = root
    for part in rel.split("/"):
        here = here / part
        try:
            if here.is_symlink() or host.is_junction(here):
                return False
        except OSError:
            return True  # cannot be looked at; what reads the path then finds it unreadable
    return True


# Step 1. The input.

LEVELS = ("self", "helper", "apart", "tested", "cross-make", "credentialed")
FLOOR_KINDS = ("confirm-baseline", "match-check", "grant-amendment", "close-deferred", "change-policy")
POLICY_KEYS = {"required", "min_hard_gates", "floors", "not_applied"}


def policy_problem(policy) -> str | None:
    """Why the policy, in the form the site hands over, cannot be read; or None. The site has read the full policy,
    checked it against policy.schema.json, filled in its defaults, and named every field no status rule applies."""
    if not isinstance(policy, dict) or set(policy) != POLICY_KEYS:
        return "the policy must be an object holding exactly required, min_hard_gates, floors and not_applied"
    if not strings(policy["required"]):
        return "policy.required is not a list of strings"
    if not (type(policy["min_hard_gates"]) is int and policy["min_hard_gates"] >= 0):
        return "policy.min_hard_gates is not a whole number of at least 0"
    floors = policy["floors"]
    if not isinstance(floors, dict) or not all(k in FLOOR_KINDS and v in LEVELS for k, v in floors.items()):
        return "policy.floors maps kinds of act to levels on the scale"
    if not strings(policy["not_applied"]) or policy["not_applied"] != sorted(set(policy["not_applied"]), key=sort_key):
        return "policy.not_applied is not a sorted list of strings, each once"
    return None


def check_input(asked) -> None:
    if not isinstance(asked, dict):
        raise Stop("bad-input", "the input is not an object")
    site = asked.get("site")
    ok = all(isinstance(asked.get(k), str) for k in ("root", "project", "policy_source", "owner_ledger")) \
        and isinstance(site, dict) and strings(asked.get("ledgers")) \
        and relpath_ok(asked.get("project")) and relpath_ok(asked.get("owner_ledger")) and all(relpath_ok(p) for p in asked.get("ledgers", []))
    if ok:
        platform, tools, providers, deadline = site.get("platform"), site.get("tools"), site.get("providers"), site.get("deadline_ms")
        ok = isinstance(site.get("writer"), str) and isinstance(site.get("runner"), str) \
            and isinstance(platform, dict) and isinstance(platform.get("os"), str) and isinstance(platform.get("arch"), str) \
            and isinstance(tools, list) and all(isinstance(t, dict) and all(isinstance(t.get(k), str) for k in ("name", "version", "digest")) for t in tools) \
            and isinstance(providers, dict) and all(isinstance(p, dict) and command_ok(p.get("command")) and strings(p.get("code"))
                                                    for p in providers.values()) \
            and type(deadline) is int and 0 < deadline <= 86_400_000
    if not ok:
        raise Stop("bad-input", "the input does not have the shape the contract gives")
    problem = policy_problem(asked.get("policy"))
    if problem:
        raise Stop("bad-input", problem)
    root = pathlib.Path(asked["root"])
    if not root.is_dir():
        raise Stop("bad-input", "root is not a directory")
    for name, provider in sorted(site["providers"].items()):
        if len(set(provider["code"])) != len(provider["code"]):
            raise Stop("bad-input", f"{name}: a code path listed twice")
        for rel in provider["code"]:
            if not relpath_ok(rel) or not reached_without_link(root, rel) or not (root / rel).is_file():
                raise Stop("bad-input", f"{name}: code path {rel!r} is not a regular file under root reached without a link")
    # Then every provider's code is read, before any provider is started.
    for name, provider in sorted(site["providers"].items()):
        provider["digest"] = code_digest(root, provider["code"])


# Step 2. The project file.

HEADER = re.compile(r"\[(project|policy)\]|\[\[(binding|platform|tool)\]\]")
STRING = r'"[^"\\]*"'
VALUE = re.compile(rf"({STRING}|\[ *(?:{STRING}(?: *, *{STRING})*)? *\])( +#.*)? *")
KEY = re.compile(r"([a-z_]+) = (.*)")
FORBIDDEN = re.compile("[\x00-\x09\x0b-\x1f\x7f-\x9f]")


def read_project(raw: bytes) -> dict:
    """The subset of TOML the contract allows, or Stop("bad-project")."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise Stop("bad-project", "not UTF-8") from None
    if text.startswith("﻿"):
        raise Stop("bad-project", "a byte-order mark")
    tables: dict = {"binding": [], "platform": [], "tool": []}
    here = None
    for number, line in enumerate(text.split("\n"), 1):
        if FORBIDDEN.search(line):
            raise Stop("bad-project", f"line {number}: a carriage return, tab or control character")
        if line.strip(" ") == "" or line.lstrip(" ").startswith("#"):
            continue
        header = HEADER.fullmatch(line)
        if header:
            if header.group(1):
                if header.group(1) in tables:
                    raise Stop("bad-project", f"line {number}: [{header.group(1)}] is given twice")
                here = tables[header.group(1)] = {}
            else:
                here = {}
                tables[header.group(2)].append(here)
            continue
        pair = KEY.fullmatch(line)
        value = VALUE.fullmatch(pair.group(2)) if pair else None
        if not pair or not value:
            raise Stop("bad-project", f"line {number}: not in the subset of TOML a kernel reads")
        if here is None or pair.group(1) in here:
            raise Stop("bad-project", f"line {number}: a key before any header, or given twice")
        raw_value = value.group(1)
        here[pair.group(1)] = [s[1:-1] for s in re.findall(STRING, raw_value)] if raw_value.startswith("[") else raw_value[1:-1]
    names = []
    for binding in tables["binding"]:
        if not isinstance(binding.get("name"), str) or not isinstance(binding.get("provider"), str) \
                or not isinstance(binding.get("capabilities"), list) or not isinstance(binding.get("match", []), list):
            raise Stop("bad-project", "a binding needs a name, a provider and a list of capabilities, and match is a list")
        if not all(host.pattern_ok(p) for p in binding.get("match", [])):
            raise Stop("bad-project", f"binding {binding['name']}: a match pattern outside the pattern language")
        names.append(binding["name"])
    if len(names) != len(set(names)):
        raise Stop("bad-project", "two bindings have one name")
    return tables


# Steps 4 and 5. Files and obligations.

def claimed(root: pathlib.Path, patterns: list[str]) -> list[dict]:
    try:
        return [host.file_ref(root / p, root) for p in sorted(host.claimed(root, patterns), key=sort_key)]
    except (host.Unreadable, OSError) as err:
        raise Stop("unreadable-file", str(err)) from None


def session(root: pathlib.Path, site: dict, binding: dict):
    try:
        sess = host.Session(site["providers"][binding["provider"]]["command"], root, TRANSCRIPT, deadline_ms=site["deadline_ms"])
    except host.Refused as err:
        raise Stop(str(err), binding["provider"]) from None
    except OSError as err:
        raise Stop("provider-not-started", f"{binding['provider']}: {err}") from None
    manifest = sess.manifest
    if not all(isinstance(manifest.get(k), str) for k in ("name", "version", "protocol")) or manifest["protocol"] != "0.2":
        sess.close()
        raise Stop("bad-manifest", "name and version must be strings, and protocol the one hello offered, 0.2")
    if manifest["name"] != binding["provider"]:
        sess.close()
        raise Stop("provider-mismatch", f"binding {binding['name']} names {binding['provider']}, the provider says {manifest['name']}")
    return sess


def ask(sess, capability: str, body: dict) -> dict:
    try:
        return sess.ask(capability, body)
    except host.Refused as err:
        raise Stop(str(err), capability) from None


def code_digest(root: pathlib.Path, paths: list[str]) -> str:
    try:
        files = {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in paths}
    except OSError as err:
        raise Stop("unreadable-file", str(err)) from None
    return canonical.identity(files)[len("sha256:"):][:16]


def obligation_shape(item) -> bool:
    return isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"] != "" and isinstance(item.get("kind"), str) \
        and strings(item.get("specified_by")) and strings(item.get("targets")) and isinstance(item.get("expect"), str) \
        and isinstance(item.get("config"), dict) and "inputs" in item and isinstance(item.get("defect_of", ""), str)


def obligations_of(root: pathlib.Path, site: dict, bindings: list[dict], claims: dict) -> tuple[dict, list, list]:
    found, listed, unchecked = {}, [], []
    for binding in sorted((b for b in bindings if "obligation.enumerate" in b["capabilities"]), key=lambda b: sort_key(b["name"])):
        files = claims[binding["name"]]
        identity = {f["path"]: f["identity"] for f in files}
        sess = session(root, site, binding)
        keep = KEEP_OPEN is not None and "obligation.check" in binding["capabilities"]
        try:
            body = ask(sess, "obligation.enumerate", {"binding": binding["name"], "definitions": [], "files": files})
        except Stop:
            sess.close()
            raise
        if keep:
            KEEP_OPEN[binding["name"]] = sess  # a run command checks with this same session: the provider cannot change
        else:
            sess.close()
        items, rejected = body.get("obligations"), body.get("rejected", [])
        # Each rule over every obligation of the answer, before the next rule.
        if not isinstance(items, list) or not isinstance(rejected, list) \
                or not all(isinstance(r, dict) and isinstance(r.get("name"), str) for r in rejected) \
                or not all(obligation_shape(item) for item in items):
            raise Stop("bad-answer", f"binding {binding['name']}: the answer does not have the shape the contract gives")
        for item in items:
            inputs = item["inputs"]
            if not strings(inputs) or inputs != sorted(set(inputs), key=sort_key) or not set(inputs) <= set(identity):
                raise Stop("bad-inputs", item["name"])
        for item in items:
            if not set(item["specified_by"] + item["targets"]) <= set(item["inputs"]):
                raise Stop("unknown-file", item["name"])
        for item in items:
            if item["name"] in found:
                raise Stop("duplicate-obligation", item["name"])
            given = [{"path": p, "identity": identity[p]} for p in item["inputs"]]
            uses = {t.get("name") for t in sess.manifest.get("tools", []) if isinstance(t, dict)}
            version = f"{sess.manifest['version']}+{site['providers'][binding['provider']]['digest']}+{site['runner']}"
            found[item["name"]] = {"preimage": {
                "obligation": canonical.identity({"binding": binding["name"], "name": item["name"]}), "kind": "check",
                "inputs": {"specified_by": canonical_sorted(f["identity"] for f in given if f["path"] in item["specified_by"]),
                           "targets": canonical_sorted(f["identity"] for f in given if f["path"] in item["targets"]),
                           "closure": canonical_sorted(canonical.identity({"path": f["path"], "identity": f["identity"]}) for f in given),
                           # Only the tools the provider's manifest says it uses: pinning another tool for another provider
                           # changes no key of this one.
                           "tools": [{"name": t["name"], "digest": t["digest"]} for t in site["tools"] if t["name"] in uses],
                           "config": canonical.identity(item["config"]), "expect": item["expect"]},
                "provider": {"name": sess.manifest["name"], "version": version, "protocol": sess.manifest["protocol"]}}}
            listed.append({"binding": binding["name"], "name": item["name"]})
            ENUMERATED[item["name"]] = {"binding": binding, "item": item, "inputs": given}
        unchecked += [r["name"] for r in rejected]
    listed.sort(key=lambda o: (sort_key(o["binding"]), sort_key(o["name"])))
    return found, listed, canonical_sorted(unchecked)


# Step 7. Intents.

def intent_shape(it) -> bool:
    def person(p):
        return isinstance(p, dict) and isinstance(p.get("id"), str)
    return isinstance(it, dict) and isinstance(it.get("name"), str) and it["name"] != "" and isinstance(it.get("text"), str) \
        and person(it.get("owner")) and ("worker" not in it or person(it["worker"])) \
        and isinstance(it.get("children"), list) and all(isinstance(c, str) and c != "" for c in it["children"]) \
        and isinstance(it.get("criteria"), list) and all(
            isinstance(c, dict) and isinstance(c.get("id"), str) and c["id"] != "" and isinstance(c.get("statement"), str)
            and isinstance(c.get("gate"), str) and isinstance(c.get("links"), list)
            and all(isinstance(link, dict) and isinstance(link.get("binding"), str) and isinstance(link.get("obligation"), str)
                    for link in c["links"])
            for c in it["criteria"])


def intents_of(root: pathlib.Path, site: dict, bindings: list[dict], listed: list, claims: dict) -> dict:
    answers = []
    for binding in sorted((b for b in bindings if "intent.index" in b["capabilities"]), key=lambda b: sort_key(b["name"])):
        sess = session(root, site, binding)
        try:
            body = ask(sess, "intent.index", {"binding": binding["name"], "files": claims[binding["name"]], "obligations": listed})
        finally:
            sess.close()
        items, rejected = body.get("intents"), body.get("rejected", [])
        if not isinstance(items, list) or not isinstance(rejected, list) \
                or not all(isinstance(r, dict) and isinstance(r.get("path"), str) and r["path"] != "" for r in rejected) \
                or not all(intent_shape(it) for it in items):
            raise Stop("bad-answer", f"binding {binding['name']}: the answer does not have the shape the contract gives")
        if rejected:
            raise Stop("intent-unreadable", ", ".join(r["path"] for r in rejected))
        answers += items
    global UNREAD_CRITERIA
    UNREAD_CRITERIA = any("limit_days" in c or "not_applicable" in c or any("varying" in link for link in c["links"])
                          for it in answers for c in it["criteria"])
    known = {(o["binding"], o["name"]) for o in listed}
    for it in answers:
        ids = [c["id"] for c in it["criteria"]]
        if len(ids) != len(set(ids)):
            raise Stop("duplicate-criterion", it["name"])
    for it in answers:
        for c in it["criteria"]:
            for link in c["links"]:
                if (link["binding"], link["obligation"]) not in known:
                    raise Stop("unknown-link", f"{it['name']} criterion {c['id']}: {link['binding']}/{link['obligation']}")
    intents = {}
    for it in answers:
        if it["name"] in intents:
            raise Stop("duplicate-intent", it["name"])
        intents[it["name"]] = {"owner": it["owner"]["id"], "worker": it.get("worker", {}).get("id", ""),
                               "children": canonical_sorted(it["children"]), "words": it["text"],
                               "criteria": {c["id"]: {"words": c["statement"], "gate": c["gate"],
                                                      "checked_by": canonical_sorted(link["obligation"] for link in c["links"])}
                                            for c in it["criteria"]}}
    parent: dict = {}
    for name, it in intents.items():
        for child in it["children"]:
            if child in parent:
                raise Stop("two-parents", child)
            parent[child] = name
    for name in intents:
        seen, here = {name}, name
        while here in parent:
            here = parent[here]
            if here in seen:
                raise Stop("intent-cycle", name)
            seen.add(here)
    return intents


# Step 8. Ledgers.

def ledger_state(root: pathlib.Path, rel: str) -> str:
    """'present', 'absent' (no file there and nothing in the way), or 'unreadable' (a folder that cannot be entered,
    a link to nothing at any step, or any other error). Only a clean absence may be read as no entries."""
    here = root
    for part in rel.split("/"):
        here = here / part
        try:
            os.stat(here)
        except FileNotFoundError:
            try:
                os.lstat(here)
            except FileNotFoundError:
                return "absent"  # this step is not there, and every step before it was entered
            except OSError:
                return "unreadable"
            return "unreadable"  # a link to nothing
        except OSError:
            return "unreadable"
    return "present"


def same_file(a: pathlib.Path, b: pathlib.Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def read_ledger(root: pathlib.Path, rel: str) -> dict:
    path = root / rel
    state = ledger_state(root, rel)
    if state == "unreadable":
        raise Stop("unreadable-file", f"{rel}: a link to nothing or a folder that cannot be entered on the way")
    if state == "absent":
        return {"entries": [], "torn": False, "absent": True}
    try:
        regular = path.is_file()
    except OSError:
        raise Stop("unreadable-file", rel) from None
    if not regular:
        raise Stop("corrupt-ledger", f"{rel} is not a file")
    try:
        return ledger.read(path)
    except ledger.Corrupt as err:
        raise Stop("corrupt-ledger", f"{rel}, line {err.at}") from None
    except OSError as err:
        raise Stop("unreadable-file", f"{rel}: {err}") from None


def entries_of(root: pathlib.Path, asked: dict) -> tuple[list, dict]:
    owner_rel = asked["owner_ledger"]
    owner = root / owner_rel
    if not reached_without_link(root, owner_rel):
        raise Stop("owner-ledger-link", owner_rel)
    state = ledger_state(root, owner_rel)
    if state == "unreadable":
        raise Stop("unreadable-file", f"{owner_rel}: a folder on its way cannot be entered")
    if state == "present" and not owner.is_file():
        raise Stop("owner-ledger-link", owner_rel)
    sources = [(owner_rel, True)] if state == "present" else []
    seen = [owner] if state == "present" else []
    # The same file as the owner's ledger, however its path is spelled (case, links, hard links), is not read again.
    for p in asked["ledgers"]:
        # A file already read, the owner's ledger included, however its path is spelt, is not read again.
        if ledger_state(root, p) == "present" and any(same_file(root / p, other) for other in seen):
            continue
        sources.append((p, False))
        if ledger_state(root, p) == "present":
            seen.append(root / p)
    entries, torn, absent = [], False, []
    for rel, is_owner in sources:
        read = read_ledger(root, rel)
        if read.get("absent") and not is_owner:
            absent.append(rel)  # the owner's ledger may well not exist yet; a ledger the site names should
        # Acts are read only from the owner's ledger, and nothing else is read from it.
        entries += [e for e in read["entries"] if (e.get("kind") == "act") == is_owner]
        torn = torn or read["torn"]
    return entries, {"entries": len(entries), "torn": torn}, absent


# Step 9. Policy.

def policy_of(policy: dict) -> dict:
    # A floor below 1 is handed over as 1: an intent with no hard gate is never delivered (decision 0018).
    return {"min_hard_gates": max(policy["min_hard_gates"], 1), "required": policy["required"], "trusted_writers": [],
            "floors": dict(policy["floors"]), "attestors": {}, "makes": []}


# Step 11. Coverage.

def coverage(intents: dict, floor: int) -> dict:
    floor = max(floor, 1)
    parent = {c: p for p, it in intents.items() for c in it["children"]}

    def root_of(ident: str) -> str:
        while ident in parent:
            ident = parent[ident]
        return ident

    def below(ident: str) -> set:
        found, todo = set(), [ident]
        while todo:
            here = todo.pop()
            if here not in found and here in intents:
                found.add(here)
                todo.extend(intents[here]["children"])
        return found

    own = {i: sum(1 for c in it["criteria"].values() if c["gate"] not in ("soft", "deferred")) for i, it in intents.items()}
    out = {}
    for ident in intents:
        root = root_of(ident)
        out[ident] = {"own_hard": own[ident], "subtree_hard": sum(own[i] for i in below(ident)), "root": root,
                      "tree_hard": sum(own[i] for i in below(root)), "floor": floor}
        out[ident]["floor_met_only_over_tree"] = ident != root and out[ident]["subtree_hard"] < floor
    thinnest = {}
    for ident in sorted(out, key=sort_key):
        best = thinnest.get(out[ident]["root"])
        if best is None or out[ident]["own_hard"] < out[best]["own_hard"]:
            thinnest[out[ident]["root"]] = ident
    return {"intents": out, "thinnest": thinnest}


def doubts(out: dict, absent: list) -> list[str]:
    """What keeps the report's passed or nothing-required from being the project's: each could hide a failure."""
    found = []
    if out["policy_not_applied"]:
        found.append("policy no status rule applies")
    if any(out["judged"]["intents"].get(name, {}).get("children") for name in out["judged"]["policy"]["required"]):
        found.append("a required intent has children, and no status rule reads descendants yet")
    if out["not_checkable"]:
        found.append("obligations the provider could not make into checks")
    if UNREAD_CRITERIA:
        found.append("criteria declare what no status rule reads yet: a deferred gate's limit, runs that must agree, or evidence not applicable")
    if out["ledger"]["torn"]:
        found.append("a ledger ends in an entry cut short")
    if absent:
        found.append("a ledger the site names does not exist")
    return found


def headline(status: str, doubt: list) -> str:
    """The project's status as the command states it: the report's, except unknown where the report says passed or
    nothing-required while anything named in `doubts` is so: what was not applied or not read could fail it."""
    return "unknown" if doubt and status in ("passed", "nothing-required") else status


def run(asked) -> dict:
    check_input(asked)
    root = pathlib.Path(asked["root"])
    site = asked["site"]
    if not reached_without_link(root, asked["project"]) or not (root / asked["project"]).is_file():  # a link at any step, the last included
        raise Stop("bad-project", "the project file is not a regular file reached without a link")
    try:
        raw = (root / asked["project"]).read_bytes()
    except OSError as err:
        raise Stop("unreadable-file", f"{asked['project']}: {err}") from None
    project = read_project(raw)
    bindings = project["binding"]
    # Step 3.
    not_served = sorted(({"binding": b["name"], "capability": c} for b in bindings for c in set(b["capabilities"]) if c not in SERVED),
                        key=lambda x: (sort_key(x["binding"]), sort_key(x["capability"])))
    served = [b for b in bindings if set(b["capabilities"]) & set(SERVED)]
    for b in served:
        if b["provider"] not in site["providers"]:
            raise Stop("no-provider", b["provider"])
    # Step 4.
    claims = {b["name"]: claimed(root, b.get("match", [])) for b in served}
    for capability in SERVED:
        owners: dict = {}
        for b in served:
            if capability in b["capabilities"]:
                for f in claims[b["name"]]:
                    if f["path"] in owners:
                        raise Stop("overlapping-bindings", f"{f['path']} is claimed by {owners[f['path']]} and {b['name']} for {capability}")
                    owners[f["path"]] = b["name"]
    obligations, listed, unchecked = obligations_of(root, site, bindings, claims)
    intents = intents_of(root, site, bindings, listed, claims)
    entries, ledger_note, absent = entries_of(root, asked)
    policy = policy_of(asked["policy"])
    judged = {"kind": "status", "name": "this-project",
              "self": {"writer": site["writer"], "platform": f"{site['platform']['os']}/{site['platform']['arch']}"},
              "policy": policy, "obligations": obligations, "intents": intents,
              "steps": [{"do": {"append": {"kind": e["kind"], "body": e["body"]}}} for e in entries] + [NOTHING]}
    out = {"judged": judged, "coverage": coverage(intents, policy["min_hard_gates"]), "policy_source": asked["policy_source"],
           "ledger": ledger_note, "not_served": not_served, "not_checkable": unchecked,
           "policy_not_applied": asked["policy"]["not_applied"]}
    out["project_doubts"] = doubts(out, absent)
    return out


def emit(value: dict) -> None:
    """One JSON object, as UTF-8 bytes whatever the console's encoding (Windows' is not UTF-8), and a line feed."""
    sys.stdout.buffer.write(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


def main() -> int:
    kernel = sys.argv[sys.argv.index("--kernel") + 1:] if "--kernel" in sys.argv else None
    try:
        raw = sys.stdin.buffer.read()
        body = raw[:-1] if raw.endswith(b"\n") else raw  # one JSON object, then at most one line feed, nothing else
        if not (body.startswith(b"{") and body.endswith(b"}")):
            raise ValueError("not one JSON object alone")
        asked = host.strict_load(body)
    except Exception:  # noqa: BLE001 - any input that is not strict JSON is bad input
        asked = None
    try:
        out = run(asked)
    except Stop as stop:
        emit({"refused": stop.reason, "detail": stop.detail})
        return 0
    if kernel:
        answer = subprocess.run(kernel + ["scenario"], input=json.dumps(out["judged"]).encode("utf-8"), capture_output=True, check=True)
        out["report"] = json.loads(answer.stdout)["results"][-1]
        out["project_status"] = headline(out["report"]["project"]["status"], out["project_doubts"])
    emit(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
