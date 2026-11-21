"""Check that the intents provider answers what the stage-0 helper reads (decision 0034).

    python tools/check_intents_provider.py

It asks the model-checker provider for this repository's obligations, asks the intents provider
for the intents with those obligations, and compares what the status rules take from each intent
(owner, worker, children, the whole text, and each criterion's words, gate and obligations) with
what tools/status.py reads. It fails if they differ, if the provider rejects a file, or if no
criterion is checked by any obligation, which would make the comparison show nothing.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import host  # noqa: E402
import status  # noqa: E402

ROOT = host.ROOT


def provider_view(root: pathlib.Path) -> tuple[dict, list, list[str]]:
    checker = host.Session([sys.executable, str(root / "providers" / "tlc" / "provider.py")], root, [])
    try:
        found, _ = host.list_project(checker, root)
    finally:
        checker.close()
    files = [host.file_ref(root / p, root) for p in host.claimed(root, host.binding("intents")["match"])]
    asked = {"binding": "intents", "files": files,
             "obligations": sorted(({"binding": o["binding"], "name": o["name"]} for o in found), key=lambda o: (o["binding"], o["name"]))}
    reader = host.Session([sys.executable, str(root / "providers" / "intents" / "provider.py")], root, [])
    try:
        body = reader.ask("intent.index", asked)
    finally:
        reader.close()
    seen = {}
    for it in body["intents"]:
        seen[it["name"]] = {"owner": it["owner"]["id"], "worker": it.get("worker", {}).get("id", ""), "children": sorted(it["children"]),
                            "words": it["text"],
                            "criteria": {c["id"]: {"words": c["statement"], "gate": c["gate"],
                                                   "checked_by": sorted(link["obligation"] for link in c["links"])} for c in it["criteria"]}}
    return seen, body["rejected"], [o["name"] for o in found]


def main() -> int:
    seen, rejected, names = provider_view(ROOT)
    read = status.read_intents(names)
    for item in read.values():
        item["children"] = sorted(item["children"])
    linked = sum(1 for it in seen.values() for c in it["criteria"].values() if c["checked_by"])
    problems = []
    if rejected:
        problems.append(f"the provider rejected {json.dumps(rejected)}")
    if seen != read:
        differ = sorted(set(seen) ^ set(read)) or sorted(i for i in seen if seen[i] != read.get(i))
        problems.append(f"the provider and tools/status.py read these intents differently: {differ}")
    if not linked:
        problems.append("no criterion is checked by any obligation, so the comparison shows nothing")
    print(json.dumps({"intents": len(seen), "criteria_with_links": linked, "problems": problems}))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
