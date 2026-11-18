"""The digest of a tool tree: the reference for protocol/tool-tree-digest.md. Stage-0 helper (decision 0023).

    python tools/tooltree.py DIRECTORY      # print the listing and digest of a tree on disk
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import posixpath
import stat
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import canonical  # noqa: E402
import pathcheck  # noqa: E402


class Unusable(Exception):
    """The tree has no digest. The reason is a stable code."""


def digest(items: list[dict]) -> str:
    """The digest of a listing, or Unusable."""
    if not items:
        raise Unusable("empty")
    paths = [item["path"] for item in items]
    for path in paths:
        if pathcheck.check(path.encode("utf-8", errors="surrogatepass")) is not None:
            raise Unusable("bad-path")
    if pathcheck.collisions(paths):
        raise Unusable("colliding-paths")
    for item in items:
        if item["kind"] not in ("file", "program", "link"):
            raise Unusable("not-a-file-or-link")
        if item["kind"] == "link":
            target = item["target"]
            if target.startswith("/") or (len(target) > 1 and target[1] == ":") or "\\" in target:
                raise Unusable("link-leaves-the-tree")
            landed = posixpath.normpath(posixpath.join(posixpath.dirname(item["path"]), target))
            if landed == ".." or landed.startswith("../"):
                raise Unusable("link-leaves-the-tree")
    order = {path: place for place, path in enumerate(canonical.sort_set(paths))}
    ordered = sorted(items, key=lambda item: order[item["path"]])
    return canonical.identity({"tree": 1, "items": ordered})


def listing(root: pathlib.Path) -> list[dict]:
    items = []
    for folder, _, names in os.walk(root, followlinks=False):
        for name in list(names) + [d for d in os.listdir(folder) if os.path.islink(os.path.join(folder, d)) and d not in names]:
            full = pathlib.Path(folder, name)
            path = full.relative_to(root).as_posix()
            mode = full.lstat().st_mode
            if stat.S_ISLNK(mode):
                items.append({"path": path, "kind": "link", "target": os.readlink(full)})
            elif stat.S_ISREG(mode):
                items.append({"path": path, "kind": "program" if mode & stat.S_IXUSR else "file",
                              "identity": "sha256:" + hashlib.sha256(full.read_bytes()).hexdigest()})
            else:
                items.append({"path": path, "kind": "other"})
    return items


if __name__ == "__main__":
    found = listing(pathlib.Path(sys.argv[1]))
    try:
        print(json.dumps({"digest": digest(found), "items": len(found)}))
    except Unusable as err:
        print(json.dumps({"refused": str(err)}))
        sys.exit(1)
