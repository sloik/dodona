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
import status  # noqa: E402

SERVED = ("obligation.enumerate", "intent.index")
NOTHING = {"do": {"set_gate": {"intent": "", "criterion": "", "to": "hard"}}}


class Stop(Exception):
    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def strings(value) -> bool:
    return isinstance(value, list) and all(isinstance(x, str) for x in value)


def check_input(asked) -> None:
    if not isinstance(asked, dict):
        raise Stop("bad-input", "the input is not an object")
    site = asked.get("site")
    ok = all(isinstance(asked.get(k), str) for k in ("root", "project", "policy_source", "owner_ledger")) \
        and isinstance(site, dict) and isinstance(asked.get("policy"), dict) and strings(asked.get("ledgers"))
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


HEADER = re.compile(r"\[(project|policy)\]|\[\[(binding|platform|tool)\]\]")
STRING = r'"[^"\\\x00-\x1f\x7f]*"'
VALUE = re.compile(rf"({STRING}|\[\s*(?:{STRING}(?:\s*,\s*{STRING})*)?\s*\])(\s+#.*)?\s*")
KEY = re.compile(r"([a-z_]+) = (.*)")


def read_project(text: str) -> dict:
    """The subset of TOML the contract allows, or Stop("bad-project")."""
    tables: dict = {"binding": [], "platform": [], "tool": []}
    here = None
    for number, line in enumerate(text.split("\n"), 1):
        bare = line.strip()
        if bare == "" or bare.startswith("#"):
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
        raw = value.group(1)
        here[pair.group(1)] = re.findall(STRING, raw) if raw.startswith("[") else raw
        here[pair.group(1)] = [s[1:-1] for s in here[pair.group(1)]] if raw.startswith("[") else raw[1:-1]
    names = []
    for binding in tables["binding"]:
        if not isinstance(binding.get("name"), str) or not isinstance(binding.get("provider"), str) \
                or not isinstance(binding.get("capabilities"), list) or not isinstance(binding.get("match", []), list):
            raise Stop("bad-project", "a binding needs a name, a provider and a list of capabilities, and match is a list")
        names.append(binding["name"])
    if len(names) != len(set(names)):
        raise Stop("bad-project", "two bindings have one name")
    return tables


def sort_key(text: str) -> list[int]:
    """How the canonical encoding sorts keys: by UTF-16 code units."""
    return list(text.encode("utf-16-be"))


def claimed(root: pathlib.Path, patterns: list[str]) -> list[dict]:
    paths = host.claimed(root, patterns)
    return [host.file_ref(root / p, root) for p in sorted(paths, key=sort_key)]


def session(root: pathlib.Path, site: dict, provider: str):
    deadline = site["deadline_ms"] / 1000
    try:
        return host.Session(site["providers"][provider]["command"], root, [], deadline_s=deadline)
    except host.Refused as err:
        raise Stop(str(err), provider) from None


def ask(sess, capability: str, body: dict) -> dict:
    try:
        return sess.ask(capability, body)
    except host.Refused as err:
        raise Stop(str(err), capability) from None


def code_digest(root: pathlib.Path, paths: list[str]) -> str:
    files = {}
    for rel in paths:
        path = root / rel
        if path.is_symlink() or not path.is_file():
            raise Stop("bad-input", f"{rel} is not a regular file")
        files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return canonical.identity(files)[len("sha256:"):][:16]


def obligations_of(root: pathlib.Path, site: dict, bindings: list[dict]) -> tuple[dict, list, list]:
    found, listed, unchecked = {}, [], []
    for binding in sorted((b for b in bindings if "obligation.enumerate" in b["capabilities"]), key=lambda b: sort_key(b["name"])):
        files = claimed(root, binding.get("match", []))
        identity = {f["path"]: f["identity"] for f in files}
        sess = session(root, site, binding["provider"])
        try:
            body = ask(sess, "obligation.enumerate", {"binding": binding["name"], "definitions": [], "files": files})
        finally:
            sess.close()
        items = body.get("obligations")
        if not isinstance(items, list):
            raise Stop("bad-answer", "obligations is not a list")
        for item in items:
            if not (isinstance(item, dict) and isinstance(item.get("name"), str) and "kind" in item and strings(item.get("specified_by"))
                    and strings(item.get("targets")) and "expect" in item and isinstance(item.get("config"), dict) and "inputs" in item):
                raise Stop("bad-answer", "an obligation does not have the shape the contract gives")
            inputs = item["inputs"]
            if not strings(inputs) or inputs != sorted(set(inputs), key=sort_key) or not set(inputs) <= set(identity):
                raise Stop("bad-inputs", item["name"])
            if not set(item["specified_by"] + item["targets"]) <= set(inputs):
                raise Stop("unknown-file", item["name"])
            if item["name"] in found:
                raise Stop("duplicate-obligation", item["name"])
            given = [{"path": p, "identity": identity[p]} for p in inputs]
            version = f"{sess.manifest['version']}+{code_digest(root, site['providers'][binding['provider']]['code'])}+{site['runner']}"
            found[item["name"]] = {"preimage": {
                "obligation": canonical.identity({"binding": binding["name"], "name": item["name"]}), "kind": "check",
                "inputs": {"specified_by": canonical.sort_set([f["identity"] for f in given if f["path"] in item["specified_by"]]),
                           "targets": canonical.sort_set([f["identity"] for f in given if f["path"] in item["targets"]]),
                           "closure": canonical.sort_set([canonical.identity({"path": f["path"], "identity": f["identity"]}) for f in given]),
                           "tools": [{"name": t["name"], "digest": t["digest"]} for t in site["tools"]],
                           "config": canonical.identity(item["config"]), "expect": item["expect"]},
                "provider": {"name": sess.manifest["name"], "version": version, "protocol": sess.manifest["protocol"]}}}
            listed.append({"binding": binding["name"], "name": item["name"]})
        unchecked += [r.get("name") for r in body.get("rejected", []) if isinstance(r, dict)]
    listed.sort(key=lambda o: (sort_key(o["binding"]), sort_key(o["name"])))
    return found, listed, sorted((u for u in unchecked if isinstance(u, str)), key=sort_key)


def intents_of(root: pathlib.Path, site: dict, bindings: list[dict], listed: list) -> dict:
    intents = {}
    for binding in sorted((b for b in bindings if "intent.index" in b["capabilities"]), key=lambda b: sort_key(b["name"])):
        files = claimed(root, binding.get("match", []))
        sess = session(root, site, binding["provider"])
        try:
            body = ask(sess, "intent.index", {"binding": binding["name"], "files": files, "obligations": listed})
        finally:
            sess.close()
        if body.get("rejected"):
            raise Stop("intent-unreadable", ", ".join(str(r.get("path")) for r in body["rejected"] if isinstance(r, dict)))
        for it in body.get("intents", []):
            if it["name"] in intents:
                raise Stop("duplicate-intent", it["name"])
            intents[it["name"]] = {"owner": it["owner"]["id"], "worker": it.get("worker", {}).get("id", ""),
                                   "children": it["children"], "words": it["text"],
                                   "criteria": {c["id"]: {"words": c["statement"], "gate": c["gate"],
                                                          "checked_by": sorted((link["obligation"] for link in c["links"]), key=sort_key)}
                                                for c in it["criteria"]}}
    return intents


def read_ledger(path: pathlib.Path, shown: str) -> dict:
    """The entries of a ledger, read by the reference reader, never by a kernel."""
    try:
        return ledger.read(path)
    except ledger.Corrupt as err:
        raise Stop("corrupt-ledger", f"{shown}, line {err.at}") from None


def reached_without_link(root: pathlib.Path, rel: str) -> bool:
    here = root
    for part in pathlib.PurePosixPath(rel).parts:
        here = here / part
        if here.is_symlink():
            return False
    return True


def entries_of(root: pathlib.Path, asked: dict) -> tuple[list, dict]:
    owner = root / asked["owner_ledger"]
    entries, count, torn = [], 0, False
    sources = []
    if not reached_without_link(root, asked["owner_ledger"]) or (owner.exists() and not owner.is_file()):
        raise Stop("owner-ledger-link", asked["owner_ledger"])
    if owner.exists():
        sources.append((owner, True, asked["owner_ledger"]))
    sources += [(root / p, False, p) for p in asked["ledgers"] if not (owner.exists() and (root / p).resolve() == owner.resolve())]
    for path, is_owner, shown in sources:
        read = read_ledger(path, shown)
        taken = [e for e in read["entries"] if (e.get("kind") == "act") == is_owner]
        entries += taken
        count += len(taken)
        torn = torn or read["torn"]
    return entries, {"entries": count, "torn": torn}


def policy_of(policy: dict) -> dict:
    return {"min_hard_gates": policy.get("gates", {}).get("min_hard", 1), "required": policy.get("required", {}).get("intents", []),
            "trusted_writers": [], "floors": {k: v["level"] for k, v in policy.get("separation", {}).get("floor", {}).items()},
            "attestors": {}, "makes": []}


def run(asked) -> dict:
    check_input(asked)
    root = pathlib.Path(asked["root"])
    site = asked["site"]
    path = root / asked["project"]
    try:
        project = read_project(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as err:
        raise Stop("bad-project", str(err)) from None
    bindings = project["binding"]
    not_served = sorted((b["name"] for b in bindings if not set(b["capabilities"]) & set(SERVED)), key=sort_key)
    for b in bindings:
        if set(b["capabilities"]) & set(SERVED) and b["provider"] not in site["providers"]:
            raise Stop("no-provider", b["provider"])
    obligations, listed, unchecked = obligations_of(root, site, bindings)
    intents = intents_of(root, site, bindings, listed)
    entries, ledger_note = entries_of(root, asked)
    policy = policy_of(asked["policy"])
    judged = {"kind": "status", "name": "this-project",
              "self": {"writer": site["writer"], "platform": f"{site['platform']['os']}/{site['platform']['arch']}"},
              "policy": policy, "obligations": obligations, "intents": intents,
              "steps": [{"do": {"append": {"kind": e["kind"], "body": e["body"]}}} for e in entries] + [NOTHING]}
    return {"judged": judged, "coverage": status.coverage(intents, policy["min_hard_gates"]), "policy_source": asked["policy_source"],
            "ledger": ledger_note, "not_served": not_served, "not_checkable": unchecked}


def main() -> int:
    kernel = sys.argv[sys.argv.index("--kernel") + 1:] if "--kernel" in sys.argv else None
    try:
        asked = host.strict_json(sys.stdin.buffer.read()) if hasattr(host, "strict_json") else json.loads(sys.stdin.buffer.read())
    except Exception:  # noqa: BLE001 - any input that is not JSON is bad input
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
