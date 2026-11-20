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
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402
import host  # noqa: E402
import ledger  # noqa: E402

SERVED = ("obligation.enumerate", "intent.index")
NOTHING = {"do": {"set_gate": {"intent": "", "criterion": "", "to": "hard"}}}


class Stop(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def sort_key(text: str) -> list[int]:
    """How the canonical encoding sorts keys: by UTF-16 code units."""
    return list(text.encode("utf-16-be"))


def canonical_sorted(items) -> list[str]:
    """Sorted as the canonical encoding sorts keys, each once."""
    return sorted(set(items), key=sort_key)


def relpath_ok(rel) -> bool:
    return isinstance(rel, str) and bool(rel) and not rel.startswith("/") and "\\" not in rel \
        and all(seg not in ("", ".", "..") for seg in rel.split("/"))


def reached_without_link(root: pathlib.Path, rel: str) -> bool:
    here = root
    for part in rel.split("/"):
        here = here / part
        if here.is_symlink():
            return False
    return True


# Step 1. The input.

def policy_ok(policy) -> bool:
    if not isinstance(policy, dict):
        return False
    required, gates, separation = policy.get("required", {}), policy.get("gates", {}), policy.get("separation", {})
    if not isinstance(required, dict) or not strings(required.get("intents", [])):
        return False
    if not isinstance(gates, dict) or ("min_hard" in gates and not (type(gates["min_hard"]) is int and gates["min_hard"] >= 0)):
        return False
    if not isinstance(separation, dict):
        return False
    floor = separation.get("floor", {})
    return isinstance(floor, dict) and all(isinstance(v, dict) and isinstance(v.get("level"), str) for v in floor.values())


def check_input(asked) -> None:
    if not isinstance(asked, dict):
        raise Stop("bad-input", "the input is not an object")
    site = asked.get("site")
    ok = all(isinstance(asked.get(k), str) for k in ("root", "project", "policy_source", "owner_ledger")) \
        and isinstance(site, dict) and policy_ok(asked.get("policy")) and strings(asked.get("ledgers")) \
        and relpath_ok(asked.get("project")) and relpath_ok(asked.get("owner_ledger")) and all(relpath_ok(p) for p in asked.get("ledgers", []))
    if ok:
        platform, tools, providers, deadline = site.get("platform"), site.get("tools"), site.get("providers"), site.get("deadline_ms")
        ok = isinstance(site.get("writer"), str) and isinstance(site.get("runner"), str) \
            and isinstance(platform, dict) and isinstance(platform.get("os"), str) and isinstance(platform.get("arch"), str) \
            and isinstance(tools, list) and all(isinstance(t, dict) and all(isinstance(t.get(k), str) for k in ("name", "version", "digest")) for t in tools) \
            and isinstance(providers, dict) and all(isinstance(p, dict) and strings(p.get("command")) and p["command"] and strings(p.get("code"))
                                                    for p in providers.values()) \
            and type(deadline) is int and deadline > 0
    if not ok:
        raise Stop("bad-input", "the input does not have the shape the contract gives")
    root = pathlib.Path(asked["root"])
    if not root.is_dir():
        raise Stop("bad-input", "root is not a directory")
    for name, provider in sorted(site["providers"].items()):
        for rel in provider["code"]:
            if not relpath_ok(rel) or not reached_without_link(root, rel) or not (root / rel).is_file():
                raise Stop("bad-input", f"{name}: code path {rel!r} is not a regular file under root reached without a link")


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
    return [host.file_ref(root / p, root) for p in sorted(host.claimed(root, patterns), key=sort_key)]


def session(root: pathlib.Path, site: dict, binding: dict):
    try:
        sess = host.Session(site["providers"][binding["provider"]]["command"], root, [], deadline_s=site["deadline_ms"] / 1000)
    except host.Refused as err:
        raise Stop(str(err), binding["provider"]) from None
    manifest = sess.manifest
    if not all(isinstance(manifest.get(k), str) for k in ("name", "version", "protocol")):
        sess.close()
        raise Stop("bad-manifest", "name, version and protocol must be strings")
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
    files = {rel: hashlib.sha256((root / rel).read_bytes()).hexdigest() for rel in paths}
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
        try:
            body = ask(sess, "obligation.enumerate", {"binding": binding["name"], "definitions": [], "files": files})
        finally:
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
            version = f"{sess.manifest['version']}+{code_digest(root, site['providers'][binding['provider']]['code'])}+{site['runner']}"
            found[item["name"]] = {"preimage": {
                "obligation": canonical.identity({"binding": binding["name"], "name": item["name"]}), "kind": "check",
                "inputs": {"specified_by": canonical_sorted(f["identity"] for f in given if f["path"] in item["specified_by"]),
                           "targets": canonical_sorted(f["identity"] for f in given if f["path"] in item["targets"]),
                           "closure": canonical_sorted(canonical.identity({"path": f["path"], "identity": f["identity"]}) for f in given),
                           "tools": [{"name": t["name"], "digest": t["digest"]} for t in site["tools"]],
                           "config": canonical.identity(item["config"]), "expect": item["expect"]},
                "provider": {"name": sess.manifest["name"], "version": version, "protocol": sess.manifest["protocol"]}}}
            listed.append({"binding": binding["name"], "name": item["name"]})
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
                or not all(isinstance(r, dict) and isinstance(r.get("path"), str) for r in rejected) \
                or not all(intent_shape(it) for it in items):
            raise Stop("bad-answer", f"binding {binding['name']}: the answer does not have the shape the contract gives")
        if rejected:
            raise Stop("intent-unreadable", ", ".join(r["path"] for r in rejected))
        answers += items
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

def read_ledger(root: pathlib.Path, rel: str) -> dict:
    path = root / rel
    if path.exists() and not path.is_file():
        raise Stop("corrupt-ledger", f"{rel} is not a file")
    try:
        return ledger.read(path)
    except ledger.Corrupt as err:
        raise Stop("corrupt-ledger", f"{rel}, line {err.at}") from None


def entries_of(root: pathlib.Path, asked: dict) -> tuple[list, dict]:
    owner_rel = asked["owner_ledger"]
    owner = root / owner_rel
    if not reached_without_link(root, owner_rel) or (owner.exists() and not owner.is_file()):
        raise Stop("owner-ledger-link", owner_rel)
    sources = [(owner_rel, True)] if owner.exists() else []
    sources += [(p, False) for p in asked["ledgers"] if not (owner.exists() and (root / p).resolve() == owner.resolve())]
    entries, torn = [], False
    for rel, is_owner in sources:
        read = read_ledger(root, rel)
        # Acts are read only from the owner's ledger, and nothing else is read from it.
        entries += [e for e in read["entries"] if (e.get("kind") == "act") == is_owner]
        torn = torn or read["torn"]
    return entries, {"entries": len(entries), "torn": torn}


# Step 9. Policy.

def policy_of(policy: dict) -> dict:
    return {"min_hard_gates": policy.get("gates", {}).get("min_hard", 1), "required": policy.get("required", {}).get("intents", []),
            "trusted_writers": [], "floors": {k: v["level"] for k, v in policy.get("separation", {}).get("floor", {}).items()},
            "attestors": {}, "makes": []}


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


def run(asked) -> dict:
    check_input(asked)
    root = pathlib.Path(asked["root"])
    site = asked["site"]
    if not reached_without_link(root, asked["project"]) or not (root / asked["project"]).is_file():
        raise Stop("bad-project", "the project file is not a regular file reached without a link")
    project = read_project((root / asked["project"]).read_bytes())
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
    entries, ledger_note = entries_of(root, asked)
    policy = policy_of(asked["policy"])
    judged = {"kind": "status", "name": "this-project",
              "self": {"writer": site["writer"], "platform": f"{site['platform']['os']}/{site['platform']['arch']}"},
              "policy": policy, "obligations": obligations, "intents": intents,
              "steps": [{"do": {"append": {"kind": e["kind"], "body": e["body"]}}} for e in entries] + [NOTHING]}
    return {"judged": judged, "coverage": coverage(intents, policy["min_hard_gates"]), "policy_source": asked["policy_source"],
            "ledger": ledger_note, "not_served": not_served, "not_checkable": unchecked}


def main() -> int:
    kernel = sys.argv[sys.argv.index("--kernel") + 1:] if "--kernel" in sys.argv else None
    try:
        asked = host.strict_load(sys.stdin.buffer.read())
    except Exception:  # noqa: BLE001 - any input that is not strict JSON is bad input
        asked = None
    try:
        out = run(asked)
    except Stop as stop:
        print(json.dumps({"refused": stop.reason, "detail": stop.detail}, ensure_ascii=False))
        return 0
    if kernel:
        answer = subprocess.run(kernel + ["scenario"], input=json.dumps(out["judged"]).encode("utf-8"), capture_output=True, check=True)
        out["report"] = json.loads(answer.stdout)["results"][-1]
    print(json.dumps(out, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
