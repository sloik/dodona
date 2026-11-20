#!/usr/bin/env python3
"""How complete and how well checked dodona is, in numbers read from its own files.

Every number is counted from a file in this repository that a reader can open, and each
names that file. Nothing here runs a kernel, a model or a checker, and no number says that
what a file states is true: a claim marked checked is counted as marked checked.

    python tools/metrics.py                        the numbers, as a table
    python tools/metrics.py --json                 the numbers, as JSON
    python tools/metrics.py --rev REV              the numbers of a commit, read from git objects
    python tools/metrics.py --base REV --head REV  the change from one commit to another;
                                                   exits 1 if a ratcheted item was taken away
    python tools/metrics.py --compare FILE         the change from an earlier --json output
    python tools/metrics.py jobs --head REV --own FILE --name NAME ...
                                                   exits 1 if another workflow of REV defines
                                                   a job with one of these ids or names
    python tools/metrics.py workflow-check FILE    exits 1 if the gate workflow is unsafe
    python tools/metrics.py self-test              plants changes and requires each to be judged right

A ratcheted metric is a set of identities (scenario names, claim ids, defect names, ...),
or a count where the items have none. Taking any identity away fails, even if another was
added. A line "Metrics-down: <metric>: <reason>" in a commit of the change is shown with
the failure as the author's explanation; it never turns a failure into a pass.

Exit codes: 0 fine, 1 a ratcheted item was taken away (or an unsafe workflow, or a job
name clash), 2 something could not be measured or read. A file that is missing or does not
read the way this tool expects is never counted as zero, and a crash is 2, never 1.

Standard library only. Standard output is ASCII, so it prints on any console. Git trees
are read with git (ls-tree, cat-file, log): nothing from them is checked out or run.
"""
from __future__ import annotations

import argparse
import ast
import concurrent.futures
import contextlib
import fnmatch
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

FORMAT = "dodona-metrics/2"
ROOT = pathlib.Path(__file__).resolve().parent.parent

# The files the numbers are read from. The self-test copies exactly these, and the gate workflow.
SOURCES = [
    "conformance/kernel",
    "conformance/vectors",
    "conformance/ledger/cases.json",
    "conformance/ledger/more-damage.json",
    "conformance/provider/cases.json",
    "conformance/provider/check-cases.json",
    "conformance/README.md",
    "kernel/defects.json",
    "kernel2/defects.json",
    "spec/CLAIMS.md",
    "decisions",
    "docs/gap-checks.md",
    "tools/check_repo.py",
    "tools/check_docs.py",   # optional: where it exists, its CHECKS are listed in docs/gap-checks.md too
]
OPTIONAL_SOURCES = {"tools/check_docs.py"}
GATE_WORKFLOW = ".github/workflows/metrics.yml"
SELF_TEST_WORKFLOW = ".github/workflows/metrics-self-test.yml"
# A change to any of these changes how changes are judged: the gate fails it, and the owner merges over that.
JUDGE_FILES = ("tools/metrics.py", GATE_WORKFLOW, SELF_TEST_WORKFLOW)
# The last commit of main before this tool lives in one place only: BOOTSTRAP_BEFORE in the env of the gate
# workflow's step. The workflow guard below requires it to be a full commit id used in exactly one test.

KERNEL_VECTOR_FILES = ("canonical", "core-key", "core-key-more", "paths")  # what the kernels are judged with
TOOL_TREE_VECTOR_FILES = ("tool-tree",)                                    # judged against the reference only
# The lists each vector file may hold, and must: any other list, or one missing, is unreadable.
VECTOR_LISTS = {"canonical": ("accept", "reject"), "core-key": ("accept", "reject"), "core-key-more": ("accept", "reject"),
                "paths": ("accept", "reject", "reject_bytes", "collisions"), "tool-tree": ("accept", "reject")}
DECISION_STATUSES = ("proposed", "accepted", "superseded", "rejected")      # decisions/README.md
EXPLANATION_KEY = "Metrics-down:"
EXPLANATION_MIN_WORDS = 6
METRIC_NAME = re.compile(r"[a-z0-9_]+(\.[a-z0-9_-]+)*")  # always used with fullmatch
SHOW_IDS = 20


class Unmeasurable(Exception):
    """A source is missing or does not read the way this tool expects."""


class BadBaseline(Exception):
    """The earlier metrics file cannot be read."""


# --------------------------------------------------------------------------- trees


def git(repo: pathlib.Path, *args: str, stdin: bytes | None = None) -> bytes:
    try:
        done = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=repo, input=stdin, capture_output=True)
    except OSError as err:
        raise Unmeasurable(f"git could not be started: {err}") from None
    if done.returncode != 0:
        raise Unmeasurable(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def _decode(data: bytes, rel: str) -> str:
    try:
        return data.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError as err:
        raise Unmeasurable(f"{rel}: not UTF-8: {err}") from None


class DirTree:
    """A folder on disk."""

    def __init__(self, root: pathlib.Path):
        self.root = pathlib.Path(root)
        self.label = str(root)

    def listing(self, rel: str) -> tuple[list[str], list[str]]:
        """Files and folders directly in rel. A link in a source is refused, never followed."""
        path = self.root / rel
        if path.is_symlink() or not path.is_dir():
            raise Unmeasurable(f"{rel}: missing, or not a folder")
        files, dirs = [], []
        for entry in sorted(path.iterdir()):
            if entry.is_symlink():
                raise Unmeasurable(f"{rel}/{entry.name}: a link, not a file")
            (dirs if entry.is_dir() else files).append(entry.name)
        return files, dirs

    def exists(self, rel: str) -> bool:
        return (self.root / rel).exists() or (self.root / rel).is_symlink()

    def read(self, rel: str) -> str:
        path = self.root / rel
        if path.is_symlink():
            raise Unmeasurable(f"{rel}: a link, not a file")
        if not path.is_file():
            raise Unmeasurable(f"{rel}: missing")
        return _decode(path.read_bytes(), rel)


class GitTree:
    """A commit, read from git objects only."""

    def __init__(self, repo: pathlib.Path, rev: str):
        self.repo = pathlib.Path(repo)
        self.label = rev
        if not re.fullmatch(r"[\w./^~@{}-]+", rev) or rev.startswith("-"):
            raise Unmeasurable(f"{rev!r} is not a revision")
        commit = git(self.repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").decode().strip()
        self.commit = commit
        self.entries: dict[str, tuple[str, str]] = {}
        self.dirs: set[str] = set()
        for item in git(self.repo, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
            if not item:
                continue
            meta, _, raw = item.partition(b"\t")
            mode, _kind, oid = meta.decode().split()
            path = _decode(raw, "a path")
            self.entries[path] = (mode, oid)
            parts = path.split("/")
            for i in range(1, len(parts)):
                self.dirs.add("/".join(parts[:i]))
        self.blobs: dict[str, bytes] = {}
        wanted = [oid for path, (mode, oid) in self.entries.items()
                  if mode in ("100644", "100755") and any(path == s or path.startswith(s + "/") for s in SOURCES)]
        self._load(wanted)

    def _load(self, oids: list[str]) -> None:
        if not oids:
            return
        out = git(self.repo, "cat-file", "--batch", stdin=("\n".join(oids) + "\n").encode())
        pos = 0
        for oid in oids:
            end = out.index(b"\n", pos)
            header = out[pos:end].decode().split()
            if len(header) != 3 or header[0] != oid or header[1] != "blob":
                raise Unmeasurable(f"git cat-file gave {out[pos:end]!r} for {oid}")
            size = int(header[2])
            self.blobs[oid] = out[end + 1:end + 1 + size]
            pos = end + 1 + size + 1

    def listing(self, rel: str) -> tuple[list[str], list[str]]:
        if rel not in self.dirs:
            raise Unmeasurable(f"{rel}: missing, or not a folder")
        files, dirs = set(), set()
        prefix = rel + "/"
        for path, (mode, _) in self.entries.items():
            if path.startswith(prefix):
                rest = path[len(prefix):]
                if "/" in rest:
                    dirs.add(rest.split("/")[0])
                elif mode in ("100644", "100755"):
                    files.add(rest)
                else:
                    raise Unmeasurable(f"{path}: a link or submodule, not a file")
        return sorted(files), sorted(dirs)

    def exists(self, rel: str) -> bool:
        return rel in self.entries or rel in self.dirs

    def read(self, rel: str) -> str:
        if rel not in self.entries:
            raise Unmeasurable(f"{rel}: missing")
        mode, oid = self.entries[rel]
        if mode not in ("100644", "100755"):
            raise Unmeasurable(f"{rel}: a link or submodule, not a file")
        if oid not in self.blobs:
            self._load([oid])
        return _decode(self.blobs[oid], rel)


# --------------------------------------------------------------------------- reading


def _json(tree, rel: str):
    try:
        return json.loads(tree.read(rel))
    except ValueError as err:
        raise Unmeasurable(f"{rel}: not JSON: {err}") from None


def _list(data, key: str, rel: str) -> list:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise Unmeasurable(f"{rel}: no list '{key}'")
    return data[key]


def _ids(values, where: str) -> list[str]:
    ids = list(values)
    if any(not isinstance(i, str) for i in ids):
        raise Unmeasurable(f"{where}: an item has no identity")
    seen = set()
    for i in ids:
        if i in seen:
            raise Unmeasurable(f"{where}: two items have the identity {i!r}")
        seen.add(i)
    return sorted(ids)


def _named(items: list, field: str, where: str) -> list[str]:
    if any(not isinstance(e, dict) for e in items):
        raise Unmeasurable(f"{where}: an item is not an object")
    return _ids((e.get(field) for e in items), where)


def _objects(items: list, field: str, where: str) -> list:
    """Items that are counted, not told apart: each must still be an object with its field."""
    if any(not isinstance(e, dict) or not isinstance(e.get(field), str) for e in items):
        raise Unmeasurable(f"{where}: an item that is not an object with a '{field}'")
    return items


def _content_ids(items: list, field: str, where: str) -> list[str]:
    """Items with no name of their own, told apart by their whole content: a changed item is one taken away
    and one added."""
    _objects(items, field, where)
    return _ids((hashlib.sha256(json.dumps(e, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
                 for e in items), where)


def _vector_id(entry):
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        for field in ("name", "path", "hex"):
            if isinstance(entry.get(field), str):
                return entry[field]
    return None


def _markdown(text: str, rel: str) -> list[tuple[str, bool]]:
    """Each line, and whether it is inside a fenced block. An HTML comment can hide a row from a reader while
    a parser counts it, so a parsed file with one is unreadable."""
    if "<!--" in text:
        raise Unmeasurable(f"{rel}: holds an HTML comment, which could hide what is counted")
    out, fence = [], None
    for line in text.split("\n"):
        m = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence is None and m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
            out.append((line, True))
            fence = m.group(1)  # closed only by the same character, at least as many, with nothing after
            continue
        if fence is not None and m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence) and not m.group(2).strip():
            out.append((line, True))
            fence = None
            continue
        if fence is None:
            # Outside code, Markdown that can hide a line from a reader while this tool reads it, or end a section
            # this tool does not see end, makes the file unreadable: an HTML block, a link reference definition
            # (whose title can hold lines), a heading indented by one to three spaces, and a setext underline.
            if re.match(r"^ {0,3}<[A-Za-z/!?]", line) or re.match(r"^ {0,3}\[[^\]]+\]:", line) \
                    or re.match(r"^ {1,3}#{1,6}(\s|$)", line) or (out and out[-1][0].strip() and not out[-1][0].lstrip().startswith("|")
                                                              and re.match(r"^ {0,3}(=+|-+)\s*$", line)):
                raise Unmeasurable(f"{rel}: Markdown this tool does not read (an HTML block, a link reference definition, "
                                   f"an indented or underlined heading): {line[:40]!r}")
        out.append((line, fence is not None))
    return out


def _section(text: str, heading: str, rel: str) -> list[str]:
    """The lines under a '## ' heading, up to the next heading of that level or above."""
    lines = text.split("\n")
    if lines.count(heading) != 1:
        raise Unmeasurable(f"{rel}: heading {heading!r} not found exactly once")
    body = []
    for line in lines[lines.index(heading) + 1:]:
        if re.match(r"^#{1,2} ", line):
            break
        if "<!--" in line or re.match(r"^\s*(`{3,}|~{3,})", line):
            raise Unmeasurable(f"{rel}: under {heading!r}, an HTML comment or a fenced block")
        body.append(line)
    return body


def _table_rows(text: str, header_start: str, rel: str, many: bool = False) -> list[list[str]]:
    """Cells of the data rows of the table whose header line starts with header_start: exactly one such
    table, or with many, at least one, all read."""
    marked = _markdown(text, rel)
    lines = [line for line, _ in marked]
    if any(fenced and line.lstrip().startswith("|") for line, fenced in marked):
        raise Unmeasurable(f"{rel}: a table row inside a fenced block")
    starts = [i for i, line in enumerate(lines) if line.startswith(header_start)]
    if not starts or (len(starts) > 1 and not many):
        raise Unmeasurable(f"{rel}: not {'at least' if many else 'exactly'} one table whose header starts {header_start!r}")
    rows = []
    for i in starts:
        if i + 1 >= len(lines) or not re.match(r"^\|(\s*:?-+:?\s*\|)+\s*$", lines[i + 1]):
            raise Unmeasurable(f"{rel}: a table {header_start!r} has no separator line")
        for row in lines[i + 2:]:
            if not row.startswith("|"):
                break
            rows.append([c.strip() for c in row.strip().strip("|").split("|")])
    return rows


def _check_list(tree, rel: str, name: str) -> set[str]:
    """The names in the list `name` of a tool, read from its source and never run."""
    try:
        module = ast.parse(tree.read(rel))
    except SyntaxError as err:
        raise Unmeasurable(f"{rel}: does not parse: {err}") from None
    # One binding, and nothing that changes it afterwards: otherwise the list read is not the list that runs.
    stores = [n for n in ast.walk(module) if isinstance(n, ast.Name) and n.id == name and not isinstance(n.ctx, ast.Load)]
    changed = [n for n in ast.walk(module) if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == name
                                               and n.attr in ("append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse"))
               or (isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == name
                   and not isinstance(n.ctx, ast.Load))]
    if len(stores) != 1 or changed:
        raise Unmeasurable(f"{rel}: {name} must be bound exactly once and never changed ({len(stores)} bindings, {len(changed)} changes)")
    # Read whole wherever it is read: a slice or an index (GAP_CHECKS[:0]) would run fewer checks than are counted.
    if any(isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == name for n in ast.walk(module)):
        raise Unmeasurable(f"{rel}: {name} is sliced or indexed where it is read, so the checks that run are not the ones counted")
    for node in module.body:
        if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets)
                and isinstance(node.value, (ast.List, ast.Tuple)) and all(isinstance(e, ast.Name) for e in node.value.elts)):
            return {e.id for e in node.value.elts}
    raise Unmeasurable(f"{rel}: no list {name} of check names")


def gap_checks_in_code(tree) -> set[str]:
    """The checks that exist: GAP_CHECKS of tools/check_repo.py and, where it exists, CHECKS of tools/check_docs.py."""
    found = _check_list(tree, "tools/check_repo.py", "GAP_CHECKS")
    if tree.exists("tools/check_docs.py"):
        found |= _check_list(tree, "tools/check_docs.py", "CHECKS")
    return found


# --------------------------------------------------------------------------- measuring


def measure(tree) -> list[dict]:
    """Every metric: name, value, whether it is ratcheted, its source and, if ratcheted, its items."""
    out: list[dict] = []

    def ratchet(name: str, items: dict, source: str) -> None:
        value = sum(len(v) if isinstance(v, list) else v for v in items.values())
        out.append({"name": name, "value": value, "ratchet": True, "source": source, "items": items})

    def shown(name: str, value: int, source: str) -> None:
        out.append({"name": name, "value": value, "ratchet": False, "source": source})

    # The kit: scenarios, by kind.
    files, kinds = tree.listing("conformance/kernel")
    if not kinds:
        raise Unmeasurable("conformance/kernel: no kinds of scenario")
    scenarios = {}
    for kind in kinds:
        names, _ = tree.listing(f"conformance/kernel/{kind}")
        scenarios[kind] = _ids([n[:-5] for n in names if n.endswith(".json")], f"conformance/kernel/{kind}")
        for name in scenarios[kind]:
            # A file that is not a scenario at all is not counted as one.
            _json(tree, f"conformance/kernel/{kind}/{name}.json")
    ratchet("kit.scenarios", scenarios, "conformance/kernel/<kind>/<name>.json (identity: kind and name)")
    for kind, ids in scenarios.items():
        shown(f"kit.scenarios.{kind}", len(ids), f"conformance/kernel/{kind}/*.json")

    # Vectors: the four files the kernels are judged with, and the tool-tree vectors apart.
    names, _ = tree.listing("conformance/vectors")
    stems = sorted(n[:-5] for n in names if n.endswith(".json"))
    unknown = [s for s in stems if s not in KERNEL_VECTOR_FILES + TOOL_TREE_VECTOR_FILES]
    if unknown or set(stems) != set(KERNEL_VECTOR_FILES + TOOL_TREE_VECTOR_FILES):
        raise Unmeasurable(f"conformance/vectors: expected exactly {', '.join(KERNEL_VECTOR_FILES + TOOL_TREE_VECTOR_FILES)}"
                           f" (.json), found {', '.join(stems) or 'none'}")
    per_file: dict[str, dict] = {}
    for stem in stems:
        rel = f"conformance/vectors/{stem}.json"
        data = _json(tree, rel)
        if not isinstance(data, dict):
            raise Unmeasurable(f"{rel}: not an object")
        groups = {}
        allowed = VECTOR_LISTS[stem]
        extra = sorted(k for k, v in data.items() if isinstance(v, list) and k not in allowed)
        missing = [k for k in allowed if not isinstance(data.get(k), list)]
        if extra or missing:
            raise Unmeasurable(f"{rel}: holds the lists {', '.join(allowed)} and no other "
                               f"(other: {', '.join(extra) or 'none'}; missing: {', '.join(missing) or 'none'})")
        for key in allowed:
            value = data[key]
            if any(not isinstance(e, (dict, str)) for e in value):
                raise Unmeasurable(f"{rel} '{key}': an item that is neither an object nor a string")
            ids = [_vector_id(e) for e in value]
            # Items with an identity are tracked one by one, however few; a list where any item has none, by count.
            groups[f"{stem}.json:{key}"] = (_ids(ids, f"{rel} '{key}'") if value and None not in ids else len(value))
        per_file[stem] = groups
    ratchet("kit.vectors", {g: v for s in KERNEL_VECTOR_FILES for g, v in per_file[s].items()},
            f"conformance/vectors/{{{','.join(KERNEL_VECTOR_FILES)}}}.json (accept, reject, reject_bytes, collisions)")
    ratchet("kit.tool_tree_vectors", per_file["tool-tree"], "conformance/vectors/tool-tree.json (accept, reject)")
    for stem in stems:
        shown(f"kit.vectors.{stem}", sum(len(v) if isinstance(v, list) else v for v in per_file[stem].values()),
              f"conformance/vectors/{stem}.json")

    # Ledger cases as the files list them (not the checks tools/run_ledger_cases.py makes of them).
    a, b = "conformance/ledger/cases.json", "conformance/ledger/more-damage.json"
    cases, more = _json(tree, a), _json(tree, b)
    if not isinstance(more.get("unlisted_kind"), dict):
        raise Unmeasurable(f"{b}: no 'unlisted_kind'")
    ratchet("kit.ledger_listed_cases", {
        "cases.json:append": _content_ids(_list(cases, "append", a), "kind", f"{a} 'append'"),
        "cases.json:damage": _named(_list(cases, "damage", a), "name", f"{a} 'damage'"),
        "more-damage.json:damage": _named(_list(more, "damage", b), "name", f"{b} 'damage'"),
        "more-damage.json:bad_requests": _named(_list(more, "bad_requests", b), "name", f"{b} 'bad_requests'"),
        "more-damage.json:unlisted_kind": 1,
    }, f"{a} (append, damage), {b} (damage, bad_requests, unlisted_kind)")

    rel = "conformance/provider/check-cases.json"
    # Many cases share a mode here, and a reason says nothing of what a case checks: each case is told apart by
    # its whole content, so a case cut down, or changed at all, is one taken away and one added.
    ratchet("kit.host_check_cases", {"cases": _content_ids(_list(_json(tree, rel), "cases", rel), "mode", rel)},
            f"{rel} (cases, identity: whole content)")
    rel = "conformance/provider/cases.json"
    ratchet("kit.session_cases", {"cases": _named(_list(_json(tree, rel), "cases", rel), "mode", rel)},
            f"{rel} (cases, identity: mode)")

    # Planted defects, read for their names only: a kernel is judged by planting them, not by this list.
    for kernel in ("kernel", "kernel2"):
        rel = f"{kernel}/defects.json"
        ratchet(f"planted_defects.{kernel}", {"defects": _named(_list(_json(tree, rel), "defects", rel), "name", rel)},
                f"{rel} (defects, identity: name)")

    # Claims.
    rel = "spec/CLAIMS.md"
    text = tree.read(rel)
    if any(fenced and re.match(r"^\| C\d+ \|", line) for line, fenced in _markdown(text, rel)):
        raise Unmeasurable(f"{rel}: a claim row inside a fenced block")
    runs, under = set(), False
    for line, fenced in _markdown(text, rel):
        if not fenced and re.match(r"^#{1,2}(\s|$)", line):
            under = re.sub(r"\s+#+\s*$", "", line.strip()) == "## Recorded runs"
        m = re.match(r"^### Run (\d+)\b", line)
        if m and under and not fenced:
            runs.add(m.group(1))
    by: dict[str, list[str]] = {"checked": [], "sampled_by_kit": [], "modelled_unchecked": [], "not_modelled": []}
    seen: list[str] = []
    section = ""
    for line in text.split("\n"):
        if line.startswith("## "):
            section = line
            continue
        m = re.match(r"^\| (C\d+) \|", line)
        if not m:
            continue
        cid = m.group(1)
        seen.append(cid)
        if section == "## Not yet modelled":
            by["not_modelled"].append(cid)
            continue
        status = line.strip().strip("|").split("|")[-1].strip()
        checked = re.match(r"^\*\*checked\*\*, run (\d+)$", status)
        if checked:
            if checked.group(1) not in runs:
                raise Unmeasurable(f"{rel}: {cid} is marked checked by run {checked.group(1)}, which is not under Recorded runs")
            by["checked"].append(cid)
        elif status == "sampled by the kit":
            by["sampled_by_kit"].append(cid)
        elif status == "modelled, unchecked":
            by["modelled_unchecked"].append(cid)
        else:
            raise Unmeasurable(f"{rel}: {cid} has a status this tool does not know: {status!r}")
    if not seen:
        raise Unmeasurable(f"{rel}: no claims found")
    ratchet("claims.total", {"claims": _ids(seen, rel)}, f"{rel} (rows '| C<n> |')")
    ratchet("claims.checked", {"claims": _ids(by["checked"], rel)}, f"{rel} (status '**checked**, run <n>', run recorded there)")
    shown("claims.unchecked", len(seen) - len(by["checked"]), f"{rel} (every other claim)")
    shown("claims.sampled_by_kit", len(by["sampled_by_kit"]), f"{rel} (status 'sampled by the kit')")
    shown("claims.modelled_unchecked", len(by["modelled_unchecked"]), f"{rel} (status 'modelled, unchecked')")
    shown("claims.not_modelled", len(by["not_modelled"]), f"{rel} (section 'Not yet modelled')")

    # Decisions.
    names, _ = tree.listing("decisions")
    records = [n for n in names if re.match(r"^[0-9].*\.md$", n)]
    if not records:
        raise Unmeasurable("decisions: no records")
    by_status = dict.fromkeys(DECISION_STATUSES, 0)
    for name in records:
        m = re.search(r"^status: (\S+)$", tree.read(f"decisions/{name}"), flags=re.M)
        if not m or m.group(1) not in by_status:
            raise Unmeasurable(f"decisions/{name}: status missing or not one of {', '.join(DECISION_STATUSES)}")
        by_status[m.group(1)] += 1
    ratchet("decisions.total", {"records": _ids([n[:-3] for n in records], "decisions")}, "decisions/[0-9]*.md")
    for status, n in by_status.items():
        shown(f"decisions.{status}", n, f"decisions/[0-9]*.md (status: {status})")

    # Gaps.
    rel = "conformance/README.md"
    bullets = 0
    for line in _section(tree.read(rel), "## Not yet in the kit", rel):
        if line.startswith("- "):
            bullets += 1
        elif line.strip():
            raise Unmeasurable(f"{rel}: under 'Not yet in the kit', a line that is not a '- ' item: {line[:60]!r}")
    shown("gaps.not_in_kit", bullets, f"{rel} (items under 'Not yet in the kit')")
    rel = "docs/gap-checks.md"
    text = tree.read(rel)
    in_code = gap_checks_in_code(tree)
    names = []
    for cells in _table_rows(text, "| Check |", rel, many=True):
        m = re.fullmatch(r"`(\w+)`", cells[0])
        if not m:
            raise Unmeasurable(f"{rel}: a row of the checks table does not name a check: {cells[0][:60]!r}")
        if m.group(1) not in in_code:
            raise Unmeasurable(f"{rel}: {m.group(1)} is listed, and neither GAP_CHECKS in tools/check_repo.py "
                               f"nor CHECKS in tools/check_docs.py has it")
        names.append(m.group(1))
    ratchet("gaps.gap_checks", {"checks": _ids(names, rel)}, f"{rel} (the 'Check' tables, each in GAP_CHECKS of tools/check_repo.py or CHECKS of tools/check_docs.py)")
    ratchet("gaps.tool_checks", {"tools": _ids([c[0] for c in _table_rows(text, "| Tool |", rel)], rel)},
            f"{rel} (the 'Tool' table, identity: first cell)")

    names = [m["name"] for m in out]
    for name in names:
        if names.count(name) > 1:
            raise Unmeasurable(f"two metrics would be called {name!r}")
        if not METRIC_NAME.fullmatch(name):
            raise Unmeasurable(f"a metric would be called {name!r}: names are lower case letters, digits, '_', '-' and '.'")
    return out


def as_json(metrics: list[dict], commit: str | None) -> dict:
    return {"format": FORMAT, "commit": commit,
            "metrics": {m["name"]: {k: v for k, v in m.items() if k != "name"} for m in metrics}}


# --------------------------------------------------------------------------- comparing


def read_baseline(path: pathlib.Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise BadBaseline(f"{path.name}: cannot be read as JSON: {err}") from None
    if not isinstance(data, dict) or data.get("format") != FORMAT or not isinstance(data.get("metrics"), dict):
        raise BadBaseline(f"{path.name}: not a {FORMAT} file")
    for name, m in data["metrics"].items():
        if (not isinstance(m, dict) or type(m.get("value")) is not int or type(m.get("ratchet")) is not bool
                or not METRIC_NAME.fullmatch(name)):
            raise BadBaseline(f"{path.name}: metric {name!r} has no integer value and boolean ratchet")
        items = m.get("items")
        if m["ratchet"] and (not isinstance(items, dict) or any(
                not (type(v) is int or (isinstance(v, list) and all(isinstance(i, str) for i in v))) for v in items.values())):
            raise BadBaseline(f"{path.name}: ratcheted metric {name!r} has no items")
    return data


def read_explanations(messages: str, known: set[str]) -> tuple[dict[str, str], list[str]]:
    """Explanations by metric, and the lines that look like one and are not well formed."""
    found: dict[str, str] = {}
    malformed: list[str] = []
    for raw in messages.split("\n"):
        line = raw.strip()
        if line.startswith(EXPLANATION_KEY):
            name, sep, reason = line[len(EXPLANATION_KEY):].strip().partition(":")
            name, reason = name.strip(), reason.strip()
            words = [w for w in reason.split() if re.search(r"\w", w)]
            if not sep or not METRIC_NAME.fullmatch(name):
                malformed.append(f"{line!r}: not 'Metrics-down: <metric>: <reason>'")
            elif name not in known:
                malformed.append(f"{line!r}: no metric is called {name!r}")
            elif len(words) < EXPLANATION_MIN_WORDS:
                malformed.append(f"{line!r}: the reason has {len(words)} words, at least {EXPLANATION_MIN_WORDS} are needed")
            else:
                found[name] = reason
        elif re.match(r"(?i)^\W*metrics?[-_ ]?down\b", line):
            malformed.append(f"{line!r}: looks like an explanation but does not start exactly with '{EXPLANATION_KEY}'")
    return found, malformed


def _taken(before: dict, after: dict | None) -> list[str]:
    """What a ratcheted metric lost: identities taken away, counts lowered, groups gone."""
    lost = []
    now = (after or {}).get("items") or {}
    for group, old in sorted(before.get("items", {}).items()):
        new = now.get(group)
        if new is None:
            lost.append(f"{group}: gone" + (f" ({len(old)} items)" if isinstance(old, list) else f" (count {old})"))
        elif isinstance(old, list) and isinstance(new, list):
            lost += [f"{printable(group)}: {printable(i)} taken away" for i in sorted(set(old) - set(new))]
        elif isinstance(old, list):
            lost.append(f"{group}: its items are no longer told apart (were {len(old)} with identities)")
        else:
            count = len(new) if isinstance(new, list) else new
            if count < old:
                lost.append(f"{group}: count {old} -> {count}")
    return lost


def compare(before_all: dict, after_all: dict, messages: str) -> tuple[list[dict], list[str], list[str], bool]:
    """Rows of the comparison, malformed explanation lines, unused explanations, and whether it failed."""
    before, after = before_all["metrics"], after_all["metrics"]
    explanations, malformed = read_explanations(messages, set(before) | set(after))
    used: set[str] = set()
    rows = []
    failed = False
    for name in list(after) + sorted(set(before) - set(after)):
        b, a = before.get(name), after.get(name)
        ratcheted = bool((b and b["ratchet"]) or (a and a["ratchet"]))
        row = {"name": name, "before": b["value"] if b else None, "now": a["value"] if a else None,
               "ratchet": ratcheted, "lost": []}
        problem = None
        if b and b["ratchet"] and a is None:
            problem, row["lost"] = "gone, was ratcheted", _taken(b, None)
        elif b and b["ratchet"] and not a["ratchet"]:
            problem = "no longer ratcheted"
        elif b and b["ratchet"]:
            row["lost"] = _taken(b, a)
            if row["lost"]:
                problem = "items taken away"
        if problem is None:
            row["verdict"] = "new" if b is None else ("gone" if a is None else "ok")
        else:
            failed = True
            if name in explanations:
                used.add(name)
                row["verdict"] = f"FAIL: {problem}; the author explains: {printable(explanations[name])}"
            else:
                row["verdict"] = f"FAIL: {problem}; no explanation in the change's commits"
        rows.append(row)
    unused = [f"{n}: {printable(r)}" for n, r in sorted(explanations.items()) if n not in used]
    return rows, malformed, unused, failed


# --------------------------------------------------------------------------- printing


def printable(text: str) -> str:
    """A fragment taken from the change (an identity, a reason): no line break or control character in it can
    start a line of its own, such as a forged result or a workflow command."""
    return re.sub(r"[\x00-\x1f\x7f\\]", lambda m: f"\\x{ord(m.group()):02x}", text)


def _ascii(text: str) -> str:
    return text.encode("ascii", "backslashreplace").decode("ascii")


def _cell(text: str) -> str:
    """Text from commit messages or files: keep it from breaking or styling a Markdown table."""
    return re.sub(r"([\\|`*_<>\[\]#])", r"\\\1", text)


def _change(b, a) -> str:
    if b is None or a is None:
        return ""
    d = a - b
    return f"+{d}" if d > 0 else str(d) if d < 0 else "0"


def table(metrics: list[dict], markdown: bool) -> str:
    if markdown:
        lines = ["| Metric | Value | Ratcheted | Source |", "|---|---:|---|---|"]
        lines += [f"| `{m['name']}` | {m['value']} | {'yes' if m['ratchet'] else 'shown only'} | {_cell(m['source'])} |" for m in metrics]
    else:
        w = max(len(m["name"]) for m in metrics)
        lines = [f"{'metric':<{w}}  {'value':>5}  {'rule':<7}  source"]
        lines += [f"{m['name']:<{w}}  {m['value']:>5}  {'ratchet' if m['ratchet'] else 'shown':<7}  {m['source']}" for m in metrics]
    return _ascii("\n".join(lines))


def comparison(title: str, rows, malformed, unused, failed, markdown: bool, judged: list[str] | None = None) -> str:
    """The table, what was taken away, the explanations, and one result line. `failed` is whether a ratcheted
    item was taken away; `judged` lists changes to how changes are judged, each a failure of its own."""
    lines = [title, ""]
    blank = lambda v: "" if v is None else v  # noqa: E731
    if markdown:
        lines += ["| Metric | Before | Now | Change | Ratcheted | Verdict |", "|---|---:|---:|---:|---|---|"]
        for r in rows:
            lines.append(f"| `{r['name']}` | {blank(r['before'])} | {blank(r['now'])} | {_change(r['before'], r['now'])} | "
                         f"{'yes' if r['ratchet'] else 'shown only'} | {_cell(r['verdict'])} |")
    else:
        w = max(len(r["name"]) for r in rows)
        lines.append(f"{'metric':<{w}}  {'before':>6}  {'now':>6}  {'change':>6}  {'rule':<7}  verdict")
        for r in rows:
            lines.append(f"{r['name']:<{w}}  {blank(r['before']):>6}  {blank(r['now']):>6}  {_change(r['before'], r['now']):>6}  "
                         f"{'ratchet' if r['ratchet'] else 'shown':<7}  {r['verdict']}")
    bullet = "- " if markdown else "  "
    esc = _cell if markdown else (lambda s: s)
    for r in rows:
        if r["lost"]:
            shown_ids = r["lost"][:SHOW_IDS]
            more = len(r["lost"]) - len(shown_ids)
            lines += ["", f"Taken from {r['name']}:"] + [bullet + esc(x) for x in shown_ids] + ([f"{bullet}and {more} more"] if more else [])
    if malformed:
        lines += ["", "Lines in the change's commits that are not well-formed explanations:"] + [bullet + esc(x) for x in malformed]
    if unused:
        lines += ["", "Explanations for a metric that lost nothing:"] + [bullet + esc(x) for x in unused]
    if judged:
        lines += ["", "Changes to how changes are judged:"] + [bullet + esc(printable(x)) for x in judged]
    reasons = (["a ratcheted item was taken away"] if failed else []) + (["the change changes how changes are judged"] if judged else [])
    lines += ["", f"Result: FAILED, {' and '.join(reasons)}. An explanation does not change this; the owner decides "
                  "whether to merge over it." if reasons else "Result: no ratcheted item was taken away, and how changes are "
                  "judged is unchanged." if judged is not None else "Result: no ratcheted item was taken away."]
    return _ascii("\n".join(lines))


# --------------------------------------------------------------------------- workflows


def mentions(text: str, name: str) -> bool:
    """Whether a workflow's text could give a job this id or name, read so as to fail closed: the name anywhere in
    the text, in comments and quotes too, or once spacing and line breaks are folded (a folded or quoted scalar)."""
    flat = " ".join(text.replace("\r\n", "\n").split())
    return name in text or name in flat or name in flat.replace('"', "").replace("'", "")


def escaped_names(text: str) -> bool:
    """A key or a name written with escapes: what it says cannot be told without a full YAML reader, so it fails."""
    return any(re.search(r"\\", line) and (re.match(r"\s*name\s*:", line) or re.match(r"\s*[\"'][^\"']*\\", line))
               for line in text.split("\n"))


def job_clashes(repo: pathlib.Path, head: str, own: str, names: set[str]) -> list[str]:
    """Other workflows of head that could define a job with one of names as its id or name. Fails closed: a workflow
    that mentions the name anywhere, or writes a key or name with escapes, is a clash."""
    tree = GitTree(repo, head)
    own = own.replace("\\", "/").removeprefix("./")
    paths = [p for p in tree.entries if re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", p) and p != own]
    out = [f"{p} mentions {n!r}, which {own} uses as a job id or name: a required check of that name could be passed by it"
           for p in sorted(paths) for n in sorted(names) if mentions(tree.read(p), n)]
    out += [f"{p} writes a job key or name with escapes, which this guard cannot read; write it plainly"
            for p in sorted(paths) if escaped_names(tree.read(p))]
    return out


def judge_changes(base, head) -> list[str]:
    """A change to the tool or its workflows changes how changes are judged, now or at the next step."""
    return [f"{path} changes how changes are judged; the owner merges over this failure"
            for path in JUDGE_FILES if base.entries.get(path) != head.entries.get(path)]


def run_blocks(text: str) -> str:
    """The text of every run: block of a workflow, comments left out."""
    out, indent = [], None
    for line in text.split("\n"):
        stripped = line.lstrip()
        here = len(line) - len(stripped)
        if indent is not None and stripped and here <= indent:
            indent = None
        m = re.match(r"(-\s+)?run:\s*(.*)$", stripped)
        if m:
            indent = here
            out.append(m.group(2))
        elif indent is not None and not stripped.startswith("#"):
            out.append(stripped)
    return "\n".join(out)


def workflow_problems(text: str) -> list[str]:
    """The gate runs on pull_request_target, with main's workflow and a token. It is safe only while
    nothing from the pull request is checked out or run, the token can only read, and the tool that
    judges comes from main (or, for a push, from the commit before it). This is advisory: it reads the
    text for known ways of breaking that, and a determined edit can get past it. A change to the
    workflow itself always fails the gate (judge_changes)."""
    text = text.replace("\r\n", "\n")
    found = []
    trigger = text.split("\njobs:")[0]
    runs = run_blocks(text)
    if "pull_request_target:" not in trigger:
        found.append("is not triggered by pull_request_target, so a pull request would be judged by its own copy")
    if re.search(r"^\s+pull_request:", trigger, flags=re.M):
        found.append("is also triggered by pull_request, which runs the pull request's own copy under the same job name")
    for use in re.findall(r"uses: (\S+)", text):
        if not re.search(r"@[0-9a-f]{40}$", use):
            found.append(f"action {use} is not pinned to a commit")
    if "self-hosted" in text:
        found.append("names a self-hosted runner")
    if not re.search(r"^permissions:\n  contents: read\n(?!  )", text, flags=re.M):
        found.append("does not limit the token to 'contents: read'")
    if re.search(r"^\s+[\w-]+:\s*write\b", text, flags=re.M) or "secrets." in text:
        found.append("gives the token write access, or uses a secret")
    if re.search(r"ref:\s*\$\{\{[^}]*(pull_request\.head|head_ref)", text):
        found.append("checks out the pull request's head")
    if "persist-credentials: false" not in text:
        found.append("keeps credentials in the checkout")
    if re.search(r"^\s+(ref|repository):", text, flags=re.M):
        found.append("tells the checkout which ref or repository to take: it must take main's commit only")
    shas = re.findall(r"^\s+BOOTSTRAP_BEFORE:\s*(\S+)\s*$", text, flags=re.M)
    if len(shas) != 1 or not re.fullmatch(r"[0-9a-f]{40}", shas[0]) \
            or runs.count('if git merge-base --is-ancestor "$TOOL_REV" "$BOOTSTRAP_BEFORE"; then') != 1 \
            or runs.count("BOOTSTRAP_BEFORE") != 1 or len(re.findall(r"\bexit 0\b", runs)) != 1:
        found.append("lets a change pass unjudged other than when the trusted revision is no later than BOOTSTRAP_BEFORE, "
                     "one full commit id set once in env")
    if any(re.search(r"\bpython3?(?! -I)\s", line) for line in text.split("\n") if not line.lstrip().startswith("#")):
        found.append("runs Python without -I, so a file in the working directory could be imported")
    if re.search(r"refs/pull/[^\s'\"]*/merge|merge_commit_sha", text):
        found.append("uses the pull request's merge commit, which holds its code")
    if re.search(r"\bgit\b[^\n]*?\s(checkout|switch|restore|reset|worktree|stash|apply|am|merge|pull|rebase|cherry-pick"
                 r"|read-tree|checkout-index|update-index|clone|archive)(?![\w-])", runs):
        found.append("changes the checked-out files with git: nothing of the change may reach the working tree")
    if re.search(r"\|\s*(bash|sh|zsh|dash|python3?|perl|ruby|node|xargs|tar)\b|\b(eval|source|tar)\b|^\s*\.\s", runs, flags=re.M):
        found.append("pipes into a shell or interpreter, evaluates text, or unpacks files: nothing of the change may run")
    if re.search(r"\bpython3?\s+-I\s+(?!\"\$TOOL\")", runs):
        found.append("runs Python on something other than \"$TOOL\", the tool taken from the trusted revision")
    shows = re.findall(r"git show (\S+)", runs)
    if not shows or any(s != '"$TOOL_REV:tools/metrics.py"' for s in shows):
        found.append("takes the tool from somewhere other than \"$TOOL_REV:tools/metrics.py\"")
    if sorted(set(re.findall(r"TOOL_REV=(\S+)", runs))) != ['"$MAIN_NOW"', '"$PUSH_BEFORE"']:
        found.append("sets TOOL_REV to something other than main now (pull request) or the commit before (push)")
    if "MAIN_NOW: ${{ github.sha }}" not in text or "PUSH_BEFORE: ${{ github.event.before }}" not in text:
        found.append("does not take MAIN_NOW from github.sha and PUSH_BEFORE from github.event.before")
    if "cancel-in-progress: ${{ github.event_name == 'pull_request_target' }}" not in text:
        found.append("may cancel the judging of a push to main")
    if re.search(r"github\.event\.pull_request\.(title|body|head\.ref|head\.label)|github\.head_ref", runs) or re.search(r"\$\{\{", runs):
        found.append("puts an expression into a run: block; values must come through env:")
    return found


# --------------------------------------------------------------------------- self-test

# The metrics that must be ratcheted. Kept here, apart from measure(), so that a ratchet taken away
# there is seen.
EXPECTED_RATCHETED = {
    "kit.scenarios", "kit.vectors", "kit.tool_tree_vectors", "kit.ledger_listed_cases", "kit.host_check_cases",
    "kit.session_cases", "planted_defects.kernel", "planted_defects.kernel2", "claims.total", "claims.checked",
    "decisions.total", "gaps.gap_checks", "gaps.tool_checks",
}

# Faults planted in this file. The self-test of each faulty copy must fail.
MUTANTS = [
    ("the ledger count ignores bad_requests",
     '"more-damage.json:bad_requests": _named(_list(more, "bad_requests", b), "name", f"{b} \'bad_requests\'"),', ""),
    ("vectors count only accept lists", "        for key in allowed:\n            value = data[key]", "        for key in allowed[:1]:\n            value = data[key]"),
    ("scenarios skip a kind", "    for kind in kinds:\n        names, _ = tree.listing", "    for kind in kinds[1:]:\n        names, _ = tree.listing"),
    ("a ratchet removed", 'ratchet("gaps.tool_checks", {"tools": _ids([c[0] for c in _table_rows(text, "| Tool |", rel)], rel)},',
     'shown("gaps.tool_checks", len([c[0] for c in _table_rows(text, "| Tool |", rel)]),'),
    ("ratchets compare counts, not identities",
     '            lost += [f"{printable(group)}: {printable(i)} taken away" for i in sorted(set(old) - set(new))]',
     '            lost += [f"{group}: count" for _ in range(len(old) - len(new))]'),
    ("a list of identities turned into a count is no loss",
     '            lost.append(f"{group}: its items are no longer told apart (were {len(old)} with identities)")', "            pass"),
    ("small lists are counted, not told apart", "if value and None not in ids else len(value))",
     "if value and None not in ids and len(ids) > 3 else len(value))"),
    ("an explanation turns a failure green", "            failed = True\n            if name in explanations:",
     "            failed = name not in explanations\n            if name in explanations:"),
    ("a change to the tool or its workflows is not judged",
     "for path in JUDGE_FILES if base.entries.get(path) != head.entries.get(path)]", "for path in JUDGE_FILES if False]"),
    ("duplicate identities are accepted", "        if i in seen:\n            raise", "        if False:\n            raise"),
    ("a stray line under 'Not yet in the kit' is accepted", "        elif line.strip():\n            raise", "        elif False:\n            raise"),
    ("a heading found twice is accepted", "    if lines.count(heading) != 1:", "    if lines.count(heading) < 1:"),
    ("HTML comments are accepted", '    if "<!--" in text:\n        raise', "    if False:\n        raise"),
    ("claim rows in a fenced block are counted", "    if any(fenced and re.match(", "    if False and any(fenced and re.match("),
    ("listed gap checks are not looked up in GAP_CHECKS", "        if m.group(1) not in in_code:", "        if False:"),
    ("a check list bound twice is accepted", "    if len(stores) != 1 or changed:", "    if False:"),
    ("vector files may hold any lists", "        if extra or missing:", "        if False:"),
    ("vector items of any type are accepted", "            if any(not isinstance(e, (dict, str)) for e in value):", "            if False:"),
    ("counted items need not be objects",
     "    if any(not isinstance(e, dict) or not isinstance(e.get(field), str) for e in items):", "    if False:"),
    ("metric names are matched as a prefix", "        if not METRIC_NAME.fullmatch(name):\n            raise Unmeasurable(f\"a metric would be called",
     "        if not METRIC_NAME.match(name):\n            raise Unmeasurable(f\"a metric would be called"),
    ("a link read from git is followed",
     '        if mode not in ("100644", "100755"):\n            raise Unmeasurable(f"{rel}: a link or submodule, not a file")\n        if oid',
     '        if False:\n            raise Unmeasurable(f"{rel}: a link or submodule, not a file")\n        if oid'),
    ("a link in a folder on disk is followed", "            if entry.is_symlink():\n                raise", "            if False:\n                raise"),
    ("identities are printed raw", "{printable(i)} taken away", "{i} taken away"),
    ("error messages are printed raw", "    print(_ascii(printable(message)), file=sys.stderr)", "    print(_ascii(message), file=sys.stderr)"),
    ("a crash reads as a failed ratchet", "        return 2\n\n\ndef complain(", "        return 1\n\n\ndef complain("),
    ("job ids are not compared, only names", "        if indent == job_indent and m:\n            found.add(m.group(2))",
     "        if False and indent == job_indent and m:\n            found.add(m.group(2))"),
    ("the jobs guard reads .yml only", 're.fullmatch(r"\\.github/workflows/[^/]+\\.ya?ml", p) and p != own]',
     're.fullmatch(r"\\.github/workflows/[^/]+\\.yml", p) and p != own]'),
    ("the jobs guard compares the gate with itself", "and p != own]", "]"),
    ("the workflow guard ignores Python without -I", 'if any(re.search(r"\\bpython3?(?! -I)\\s", line)', 'if False and any(re.search(r"\\bpython3?(?! -I)\\s", line)'),
    ("the workflow guard ignores write permissions and secrets",
     'if re.search(r"^\\s+[\\w-]+:\\s*write\\b", text, flags=re.M) or "secrets." in text:', "if False:"),
    ("the workflow guard ignores self-hosted runners", 'if "self-hosted" in text:', "if False:"),
    ("the workflow guard misses git with options before the command", 'r"\\bgit\\b[^\\n]*?\\s(checkout|', 'r"\\bgit\\s+(checkout|'),
    ("the workflow guard misses pipes into a shell", 'if re.search(r"\\|\\s*(bash|', 'if False and re.search(r"\\|\\s*(bash|'),
]

# Unsafe edits of the gate workflow. The guard must notice each.
UNSAFE_WORKFLOW_EDITS = [
    ('python3 -I "$TOOL" --repo', 'python3 "$TOOL" --repo'),
    ('python3 -I "$TOOL" --repo', 'python3 -I tools/metrics.py --repo'),
    ("fetch-depth: 0", "fetch-depth: 0\n          ref: ${{ github.event.pull_request.head.sha }}"),
    ("fetch-depth: 0", "fetch-depth: 0\n          ref: refs/pull/${{ github.event.pull_request.number }}/head"),
    ("fetch-depth: 0", "fetch-depth: 0\n          repository: ${{ github.event.pull_request.head.repo.full_name }}"),
    ("contents: read", "contents: write"),
    ("    runs-on: ubuntu-26.04\n", "    runs-on: ubuntu-26.04\n    permissions:\n      checks: write\n"),
    ("          MAIN_NOW: ${{ github.sha }}\n", "          MAIN_NOW: ${{ github.sha }}\n          TOKEN: ${{ secrets.PAT }}\n"),
    ("runs-on: ubuntu-26.04", "runs-on: [self-hosted, linux]"),
    ("persist-credentials: false", "persist-credentials: true"),
    ("refs/pull/$PR_NUMBER/head:", "refs/pull/$PR_NUMBER/merge:"),
    ("PR_HEAD: ${{ github.event.pull_request.head.sha }}", "PR_HEAD: ${{ github.event.pull_request.merge_commit_sha }}"),
    ("MAIN_NOW: ${{ github.sha }}", "MAIN_NOW: ${{ github.event.pull_request.head.sha }}"),
    ('git show "$TOOL_REV:tools/metrics.py"', 'git show "$HEAD:tools/metrics.py"'),
    ('TOOL_REV="$MAIN_NOW"', 'TOOL_REV="$HEAD"'),
    ('TOOL_REV="$PUSH_BEFORE"', 'TOOL_REV="$MAIN_NOW"'),
    ("set -uo pipefail\n", 'set -uo pipefail\n          git checkout --quiet --detach "$HEAD"\n'),
    ("set -uo pipefail\n", 'set -uo pipefail\n          git -c advice.detachedHead=false checkout "$HEAD"\n'),
    ("set -uo pipefail\n", 'set -uo pipefail\n          git worktree add "$RUNNER_TEMP/pr" "$HEAD"\n'),
    ("set -uo pipefail\n", 'set -uo pipefail\n          git read-tree -u --reset "$HEAD"\n'),
    ("set -uo pipefail\n", 'set -uo pipefail\n          git cat-file -p "$HEAD:run.sh" | bash\n'),
    ("set -uo pipefail\n", 'set -uo pipefail\n          git archive "$HEAD" | tar -x\n'),
    ("set -uo pipefail\n", 'set -uo pipefail\n          eval "$(cat "$RUNNER_TEMP/x")"\n'),
    ("set -uo pipefail\n", 'set -uo pipefail\n          echo "${{ github.event.pull_request.title }}"\n'),
    ("set -uo pipefail\n", 'set -uo pipefail\n          echo "${{ github.head_ref }}"\n'),
    ("  pull_request_target:", "  pull_request:\n  pull_request_target:"),
    ("  pull_request_target:", "  pull_request:"),
    ("cancel-in-progress: ${{ github.event_name == 'pull_request_target' }}", "cancel-in-progress: true"),
    ("@3d3c42e5aac5ba805825da76410c181273ba90b1", "@v7"),
    ('--is-ancestor "$TOOL_REV" "$BOOTSTRAP_BEFORE"; then', '--is-ancestor "$TOOL_REV" "$HEAD"; then'),
    ('--is-ancestor "$TOOL_REV" "$BOOTSTRAP_BEFORE"; then',
     '--is-ancestor "$TOOL_REV" "$BOOTSTRAP_BEFORE" || git cat-file -e "$HEAD:tools/metrics.py"; then'),
    ("BOOTSTRAP_BEFORE: {BOOTSTRAP}", "BOOTSTRAP_BEFORE: main"),
    ("          BOOTSTRAP_BEFORE: {BOOTSTRAP}\n",
     "          BOOTSTRAP_BEFORE: {BOOTSTRAP}\n          BOOTSTRAP_BEFORE: 0000000000000000000000000000000000000000\n"),
    ('say "PROBLEM cannot judge: $TOOL_REV has no tools/metrics.py."\n            exit 1',
     'say "PROBLEM cannot judge: $TOOL_REV has no tools/metrics.py."\n            exit 0'),
]


def self_test(mutants: bool) -> int:
    """Plant changes in copies of the sources and require each to be judged as stated, through the CLI."""
    results: list[tuple[str, bool, str]] = []
    skipped: list[str] = []
    me = pathlib.Path(__file__).resolve()

    def record(label: str, ok: bool, detail: str = "") -> None:
        results.append((label, ok, detail))

    with tempfile.TemporaryDirectory(prefix="dodona-metrics-") as tmp:
        tmpdir = pathlib.Path(tmp)
        counter = [0]

        def fresh(name: str) -> pathlib.Path:
            counter[0] += 1
            return tmpdir / f"{name}{counter[0]}"

        def copy(extra: tuple[str, ...] = ()) -> pathlib.Path:
            dest = fresh("r")
            for rel in SOURCES + list(extra):
                src = ROOT / rel
                if rel in OPTIONAL_SOURCES and not src.exists():
                    continue
                if src.is_dir():
                    shutil.copytree(src, dest / rel, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
                else:
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest / rel)
            return dest

        def cli(*args: str, tool: pathlib.Path = me, cwd: pathlib.Path | None = None) -> tuple[int, str]:
            proc = subprocess.run([sys.executable, "-I", str(tool), *args], capture_output=True, cwd=cwd,
                                  text=True, encoding="ascii", errors="replace")
            return proc.returncode, proc.stdout + proc.stderr

        def check(label: str, code: int, out: str, expect: int, must_say: str | None = None,
                  fails: str | None = None, markdown: bool = False) -> None:
            ok = code == expect and (must_say is None or must_say in out)
            if fails is not None:
                row = f"| `{fails}` |" if markdown else fails + " "
                ok = ok and any(line.startswith(row) and "FAIL:" in line for line in out.split("\n"))
            record(label, ok, f"exit {code}, expected {expect}" + (f", output must say {must_say!r}" if must_say else "")
                   + (f", the row of {fails} must fail" if fails else "") + ("" if ok else "\n" + out))

        base_root = copy()
        code, text = cli("--root", str(base_root), "--json", "--commit", "0" * 40)
        if code != 0:
            print("self-test: the unchanged copy could not be measured:\n" + text)
            return 2
        baseline = json.loads(text)
        base_file = tmpdir / "baseline.json"
        base_file.write_text(json.dumps(baseline), encoding="utf-8")
        ratcheted = sorted(n for n, m in baseline["metrics"].items() if m["ratchet"])
        shown = sorted(n for n, m in baseline["metrics"].items() if not m["ratchet"])
        record("the ratcheted metrics are exactly the expected ones", set(ratcheted) == EXPECTED_RATCHETED,
               f"missing {sorted(EXPECTED_RATCHETED - set(ratcheted))}, unexpected {sorted(set(ratcheted) - EXPECTED_RATCHETED)}")

        def judge(label: str, root: pathlib.Path, expect: int, messages: str = "", against: dict | None = None,
                  must_say: str | None = None, fails: str | None = None, markdown: bool = False) -> None:
            bf = base_file
            if against is not None:
                bf = fresh("b").with_suffix(".json")
                bf.write_text(json.dumps(against), encoding="utf-8")
            mf = fresh("m").with_suffix(".txt")
            mf.write_text(messages, encoding="utf-8")
            code, out = cli("--root", str(root), "--compare", str(bf), "--messages", str(mf), *(["--markdown"] if markdown else []))
            check(label, code, out, expect, must_say, fails, markdown)

        def planted(edit) -> pathlib.Path:
            root = copy()
            edit(root)
            return root

        def append(root, rel: str, text: str) -> None:
            path = pathlib.Path(root) / rel
            path.write_text(path.read_text(encoding="utf-8") + text, encoding="utf-8")

        def replace_once(root: pathlib.Path, rel: str, old: str, new: str) -> None:
            path = root / rel
            text = path.read_text(encoding="utf-8")
            if old not in text:
                raise SystemExit(f"self-test: cannot plant: {old!r} not in {rel}")
            path.write_text(text.replace(old, new, 1), encoding="utf-8")

        def edit_json(root: pathlib.Path, rel: str, change) -> None:
            path = root / rel
            data = json.loads(path.read_text(encoding="utf-8"))
            change(data)
            path.write_text(json.dumps(data), encoding="utf-8")

        def drop_lines(root: pathlib.Path, rel: str, start: str) -> None:
            path = root / rel
            lines = path.read_text(encoding="utf-8").split("\n")
            kept = [l for l in lines if not l.startswith(start)]
            if len(kept) == len(lines):
                raise SystemExit(f"self-test: cannot plant: no line starts {start!r} in {rel}")
            path.write_text("\n".join(kept), encoding="utf-8")

        good = "the scenario tested a rule the contract no longer has"

        # Controls: nothing changed, items added, and shown numbers that went down all pass.
        judge("control: nothing changed", base_root, 0)
        def add_scenario(r):
            src = sorted((r / "conformance/kernel/evidence").glob("*.json"))[0]
            shutil.copyfile(src, src.with_name("zz_planted_copy.json"))
        judge("control: a scenario added", planted(add_scenario), 0)
        judge("control: an item of 'Not yet in the kit' removed (shown only)",
              planted(lambda r: drop_lines(r, "conformance/README.md", "- What happens when a ticket name")), 0)
        judge("control: a decision accepted (status counts are shown only)",
              planted(lambda r: replace_once(r, "decisions/0001-decisions-are-nodes.md", "status: proposed", "status: accepted")), 0)

        # A scenario removed from each kind.
        for kind in sorted(p.name for p in (base_root / "conformance/kernel").iterdir() if p.is_dir()):
            def drop(r, kind=kind):
                sorted((r / "conformance/kernel" / kind).glob("*.json"))[0].unlink()
            judge(f"a scenario removed from {kind}", planted(drop), 1, fails="kit.scenarios", must_say=f"{kind}: ")
        def rename_scenario(r):
            p = sorted((r / "conformance/kernel/acts").glob("*.json"))[0]
            p.rename(p.with_name("zz_renamed.json"))
        judge("a scenario renamed: one taken away though the count is the same", planted(rename_scenario), 1, fails="kit.scenarios")

        # Explanations are shown and never pass a change.
        no_scenario = planted(lambda r: sorted((r / "conformance/kernel/evidence").glob("*.json"))[0].unlink())
        judge("a scenario removed, no explanation", no_scenario, 1, fails="kit.scenarios", must_say="no explanation")
        judge("a scenario removed, a well-formed explanation still fails", no_scenario, 1,
              f"Remove a wrong scenario\n\nMetrics-down: kit.scenarios: {good}\n", fails="kit.scenarios", must_say="the author explains")
        judge("a scenario removed, explanation of five words is shown as malformed", no_scenario, 1,
              "Metrics-down: kit.scenarios: the scenario was simply wrong\n", must_say="5 words")
        judge("a scenario removed, explanation with no reason", no_scenario, 1, "Metrics-down: kit.scenarios\n", must_say="not well-formed")
        judge("a scenario removed, explanation for another metric", no_scenario, 1, f"Metrics-down: claims.checked: {good}\n",
              must_say="lost nothing")
        judge("a scenario removed, explanation for an unknown metric", no_scenario, 1, f"Metrics-down: kit.scenario: {good}\n",
              must_say="no metric is called")
        judge("a scenario removed, key misspelt", no_scenario, 1, f"metrics-down: kit.scenarios: {good}\n", must_say="looks like")
        judge("a scenario removed, as Markdown", no_scenario, 1, fails="kit.scenarios", markdown=True)
        judge("an explanation holding a pipe and a backtick, as Markdown", no_scenario, 1,
              "Metrics-down: kit.scenarios: the scenario | judged `a` rule the contract dropped\n", markdown=True,
              must_say="the scenario \\| judged \\`a\\` rule")

        # A claim un-checked.
        unchecked = planted(lambda r: replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| modelled, unchecked |"))
        judge("a claim un-checked", unchecked, 1, fails="claims.checked", must_say="claims: C1 taken away")

        # Every list each ratchet reads from.
        vectors = [("conformance/vectors/canonical.json", k, "kit.vectors") for k in ("accept", "reject")]
        vectors += [("conformance/vectors/core-key.json", k, "kit.vectors") for k in ("accept", "reject")]
        vectors += [("conformance/vectors/core-key-more.json", k, "kit.vectors") for k in ("accept", "reject")]
        vectors += [("conformance/vectors/paths.json", k, "kit.vectors") for k in VECTOR_LISTS["paths"]]
        vectors += [("conformance/vectors/tool-tree.json", k, "kit.tool_tree_vectors") for k in ("accept", "reject")]
        lists = vectors + [
            ("conformance/ledger/cases.json", "append", "kit.ledger_listed_cases"),
            ("conformance/ledger/cases.json", "damage", "kit.ledger_listed_cases"),
            ("conformance/ledger/more-damage.json", "damage", "kit.ledger_listed_cases"),
            ("conformance/ledger/more-damage.json", "bad_requests", "kit.ledger_listed_cases"),
            ("conformance/provider/check-cases.json", "cases", "kit.host_check_cases"),
            ("conformance/provider/cases.json", "cases", "kit.session_cases"),
            ("kernel/defects.json", "defects", "planted_defects.kernel"),
            ("kernel2/defects.json", "defects", "planted_defects.kernel2"),
        ]
        for rel, key, metric in lists:
            judge(f"an item removed from '{key}' in {rel}", planted(lambda r, rel=rel, key=key: edit_json(r, rel, lambda d: d[key].pop(0))),
                  1, fails=metric)
        judge("the unlisted kind removed from the ledger cases: unreadable",
              planted(lambda r: edit_json(r, "conformance/ledger/more-damage.json", lambda d: d.pop("unlisted_kind"))), 2)
        judge("a gap check row removed", planted(lambda r: drop_lines(r, "docs/gap-checks.md", "| `gap_readme_counts` |")), 1,
              fails="gaps.gap_checks")
        judge("a tool check row removed", planted(lambda r: drop_lines(r, "docs/gap-checks.md", "| `tools/check_examples.py` |")), 1,
              fails="gaps.tool_checks")
        def docs_checks(r, listed: str, defined: str | None):
            p = r / "docs/gap-checks.md"
            p.write_text(p.read_text(encoding="utf-8") + f"\n## More\n\n| Check | The gap behind it |\n|---|---|\n| `{listed}` | x |\n",
                         encoding="utf-8")
            if defined is not None:
                (r / "tools/check_docs.py").write_text(f"def {defined}():\n    pass\n\n\nCHECKS = [{defined}]\n", encoding="utf-8")
        judge("control: a second checks table naming a check of tools/check_docs.py",
              planted(lambda r: docs_checks(r, "docs_planted", "docs_planted")), 0)
        judge("a second checks table whose check is gone", planted(lambda r: docs_checks(r, "docs_planted", "docs_planted")), 1,
              against=json.loads(json.dumps(baseline, default=list).replace('"gap_readme_counts"', '"gap_readme_counts", "docs_gone"')),
              fails="gaps.gap_checks")
        judge("unreadable: a second checks table naming a check that exists nowhere",
              planted(lambda r: docs_checks(r, "docs_nowhere", None)), 2)
        judge("unreadable: tools/check_docs.py without a list CHECKS",
              planted(lambda r: (docs_checks(r, "docs_planted", "docs_planted"),
                                 (r / "tools/check_docs.py").write_text("CHECK = []\n", encoding="utf-8"))), 2)
        judge("a decision record removed", planted(lambda r: (r / "decisions/0001-decisions-are-nodes.md").unlink()), 1,
              fails="decisions.total")
        judge("a claim removed from the table", planted(lambda r: drop_lines(r, "spec/CLAIMS.md", "| C11 |")), 1, fails="claims.total")
        judge("a claim renumbered", planted(lambda r: replace_once(r, "spec/CLAIMS.md", "| C11 |", "| C99 |")), 1, fails="claims.total")
        judge("a decision record renamed", planted(lambda r: (r / "decisions/0001-decisions-are-nodes.md").rename(
            r / "decisions/0001-decisions-are-first-class.md")), 1, fails="decisions.total")

        # An item renamed in every list that has identities, the count unchanged, however short the list.
        def renamed(entry, first=()):
            if isinstance(entry, str):
                return entry + "-renamed"
            for field in (*first, "name", "path", "hex", "mode"):
                if isinstance(entry.get(field), str):
                    return dict(entry, **{field: entry[field] + ("00" if field == "hex" else "-renamed")})
            raise SystemExit(f"self-test: cannot rename {entry!r}")
        for rel, key, metric in lists:
            first = ("why",) if rel.endswith("check-cases.json") else ("kind",) if key == "append" else ()  # any field changes a content identity
            judge(f"an item renamed in '{key}' in {rel}",
                  planted(lambda r, rel=rel, key=key, first=first: edit_json(r, rel, lambda d: d[key].__setitem__(0, renamed(d[key][0], first)))),
                  1, fails=metric, must_say="taken away")
        # A real case swapped for one that tests nothing keeps every count.
        for rel, key, metric, junk in (("conformance/provider/check-cases.json", "cases", "kit.host_check_cases", {"mode": "x", "why": "x"}),
                                       ("conformance/provider/check-cases.json", "cases", "kit.host_check_cases", "keep-why"),
                                       ("conformance/ledger/cases.json", "append", "kit.ledger_listed_cases", {"kind": "x"})):
            judge(f"a real item in '{key}' of {rel} swapped for one that tests nothing" + (", keeping its reason" if junk == "keep-why" else ""),
                  planted(lambda r, rel=rel, key=key, junk=junk: edit_json(r, rel, lambda d: (
                      d[key].append({"mode": "x", "why": d[key][0]["why"]} if junk == "keep-why" else junk), d[key].pop(0)))),
                  1, fails=metric, must_say="taken away")
        judge("a named vector replaced by one with no identity",
              planted(lambda r: edit_json(r, "conformance/vectors/canonical.json", lambda d: d["accept"].__setitem__(0, {"value": 1}))),
              1, fails="kit.vectors", must_say="no longer told apart")
        judge("control: a scenario copied byte for byte under a new name (adds, takes nothing)", planted(add_scenario), 0)
        judge("control: the Recorded runs heading with a closing sequence, as Markdown allows",
              planted(lambda r: replace_once(r, "spec/CLAIMS.md", "\n## Recorded runs\n", "\n## Recorded runs ##\n")), 0)

        # What cannot be read is never counted as zero, and duplicates have no identity.
        unreadable = [
            ("'Not yet in the kit' heading renamed", lambda r: replace_once(r, "conformance/README.md", "## Not yet in the kit", "## Not in the kit yet")),
            ("a line under 'Not yet in the kit' that is not an item",
             lambda r: replace_once(r, "conformance/README.md", "\n- What happens when a ticket name", "\nWhat happens when a ticket name")),
            ("a heading inside 'Not yet in the kit'",
             lambda r: replace_once(r, "conformance/README.md", "\n- What happens when a ticket name", "\n### More\n- What happens when a ticket name")),
            ("a claim checked by a run that is not recorded", lambda r: replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| **checked**, run 99 |")),
            ("a claim checked by a run whose heading is outside Recorded runs",
             lambda r: (replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| **checked**, run 99 |"), replace_once(r, "spec/CLAIMS.md", "\n## Not yet modelled", "\n### Run 99: a lookalike\n\n## Not yet modelled"))),
            ("a claim checked by a run whose heading is in a fenced block",
             lambda r: (replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| **checked**, run 99 |"), append(r, "spec/CLAIMS.md", "\n```\n### Run 99: fenced\n```\n"))),
            ("a claim checked by a run whose heading is in a fence closed only by a longer one",
             lambda r: (replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| **checked**, run 99 |"), append(r, "spec/CLAIMS.md", "\n````\n```\n### Run 99: still fenced\n```\n````\n"))),
            ("a claim checked by a run whose heading follows a level-1 heading",
             lambda r: (replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| **checked**, run 99 |"), append(r, "spec/CLAIMS.md", "\n# Appendix\n\n### Run 99: not a recorded run\n"))),
            ("a claim checked by a run under a Recorded runs heading that is fenced",
             lambda r: (replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| **checked**, run 99 |"), replace_once(r, "spec/CLAIMS.md", "\n## Not yet modelled", "\n```\n## Recorded runs\n```\n### Run 99: a lookalike\n\n## Not yet modelled"))),
            ("an HTML comment inside a line of text",
             lambda r: append(r, "spec/CLAIMS.md", "\nA note <!-- that hides this -->\n")),
            ("a claim row hidden in a link reference title",
             lambda r: replace_once(r, "spec/CLAIMS.md", "\n| C11 |", '\n[c11]: /x "\n| C11 |')),
            ("a claim row hidden in an HTML block",
             lambda r: replace_once(r, "spec/CLAIMS.md", "\n| C11 |", '\n<div title="\n| C11 |')),
            ("a heading indented by a space",
             lambda r: append(r, "spec/CLAIMS.md", "\n ## Unrelated notes\n")),
            ("a heading written by underlining it",
             lambda r: append(r, "spec/CLAIMS.md", "\nUnrelated notes\n---------------\n")),
            ("a claim checked by a run whose heading is in a fence closed by a line with text after it",
             lambda r: (replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| **checked**, run 99 |"),
                        append(r, "spec/CLAIMS.md", "\n```\n``` not a close\n### Run 99: still fenced\n```\n"))),
            ("a scenario that is not JSON",
             lambda r: (r / "conformance/kernel/evidence/nothing_ran.json").write_text("not json", encoding="utf-8")),
            ("a claim with an unknown status", lambda r: replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| checked |")),
            ("a claim listed twice", lambda r: replace_once(r, "spec/CLAIMS.md", "| C2 |", "| C1 |")),
            ("a decision with an unknown status",
             lambda r: replace_once(r, "decisions/0001-decisions-are-nodes.md", "status: proposed", "status: approved")),
            ("a defect name used twice", lambda r: edit_json(r, "kernel/defects.json", lambda d: d["defects"].append(d["defects"][0]))),
            ("a session mode used twice", lambda r: edit_json(r, "conformance/provider/cases.json", lambda d: d["cases"].append(d["cases"][0]))),
            ("a vector name used twice", lambda r: edit_json(r, "conformance/vectors/canonical.json", lambda d: d["accept"].append(d["accept"][0]))),
            ("a vector list of an unknown kind", lambda r: edit_json(r, "conformance/vectors/canonical.json", lambda d: d.update(extra=[1]))),
            ("a vector file this tool does not know",
             lambda r: shutil.copyfile(r / "conformance/vectors/paths.json", r / "conformance/vectors/paths2.json")),
            ("a scenario kind whose name cannot be a metric",
             lambda r: shutil.copytree(r / "conformance/kernel/acts", r / "conformance/kernel/More_Acts")),
            ("a listed gap check that tools/check_repo.py does not have",
             lambda r: replace_once(r, "docs/gap-checks.md", "| `gap_readme_counts` |", "| `gap_readme_count` |")),
            ("a gap check gone from GAP_CHECKS and still listed",
             lambda r: replace_once(r, "tools/check_repo.py", "gap_readme_counts, gap_claims", "gap_claims")),
            ("a gap check listed twice",
             lambda r: replace_once(r, "docs/gap-checks.md", "| `gap_claims_name_real_properties` |", "| `gap_readme_counts` |")),
            ("tools/check_repo.py that does not parse", lambda r: (r / "tools/check_repo.py").write_text("GAP_CHECKS = [\n", encoding="utf-8")),
            ("a defects file that is not JSON", lambda r: (r / "kernel/defects.json").write_text("{", encoding="utf-8")),
            ("a claims file that is not UTF-8", lambda r: (r / "spec/CLAIMS.md").write_bytes(b"\xff\xfe| C1 |")),
            ("'Not yet in the kit' found twice",
             lambda r: (r / "conformance/README.md").write_text((r / "conformance/README.md").read_text(encoding="utf-8")
                                                               + "\n## Not yet in the kit\n\n- more\n", encoding="utf-8")),
            ("an HTML comment under 'Not yet in the kit'",
             lambda r: replace_once(r, "conformance/README.md", "\n- What happens when a ticket name", "\n- <!-- hidden --> What happens when a ticket name")),
            ("a claim row wrapped in an HTML comment",
             lambda r: replace_once(r, "spec/CLAIMS.md", "| C11 |", "<!--\n| C11 |")),
            ("a claim row inside a fenced block",
             lambda r: replace_once(r, "spec/CLAIMS.md", "\n| C11 |", "\n```\n| C11 |")),
            # A fenced block that holds only a row of a new claim: nothing else about the file changes.
            ("a new claim row inside a closed fenced block",
             lambda r: replace_once(r, "spec/CLAIMS.md", "\n| C11 |", "\n```\n| C998 | planted | not modelled |\n```\n| C11 |")),
            ("a gap-checks table inside a fenced block",
             lambda r: replace_once(r, "docs/gap-checks.md", "\n| Check |", "\n```\n| Check |")),
            ("an HTML comment in docs/gap-checks.md",
             lambda r: replace_once(r, "docs/gap-checks.md", "| `gap_readme_counts` |", "<!-- | `gap_readme_counts` |")),
            ("GAP_CHECKS bound a second time",
             lambda r: (r / "tools/check_repo.py").write_text((r / "tools/check_repo.py").read_text(encoding="utf-8")
                                                             + "\nGAP_CHECKS = []\n", encoding="utf-8")),
            ("GAP_CHECKS sliced where it runs",
             lambda r: replace_once(r, "tools/check_repo.py", "check_indexes] + GAP_CHECKS:", "check_indexes] + GAP_CHECKS[:0]:")),
            ("GAP_CHECKS changed after it is bound",
             lambda r: (r / "tools/check_repo.py").write_text((r / "tools/check_repo.py").read_text(encoding="utf-8")
                                                             + "\nGAP_CHECKS.clear()\n", encoding="utf-8")),
            ("a vector list this file may not hold",
             lambda r: edit_json(r, "conformance/vectors/canonical.json", lambda d: d.update(collisions=[{"name": "x"}]))),
            ("a vector list missing", lambda r: edit_json(r, "conformance/vectors/canonical.json", lambda d: d.pop("reject"))),
            ("a vector that is neither an object nor a string",
             lambda r: edit_json(r, "conformance/vectors/canonical.json", lambda d: d["accept"].append(7))),
            ("a ledger append that is not an object",
             lambda r: edit_json(r, "conformance/ledger/cases.json", lambda d: d["append"].__setitem__(0, None))),
            ("a host check case with no mode",
             lambda r: edit_json(r, "conformance/provider/check-cases.json", lambda d: d["cases"].__setitem__(0, {}))),
        ]
        for label, edit in unreadable:
            judge(f"unreadable: {label}", planted(edit), 2)
        judge("unreadable: earlier file has the wrong format", base_root, 2, against={"format": "other", "metrics": {}})
        bad = json.loads(json.dumps(baseline))
        bad["metrics"]["kit.scenarios"]["value"] = "150"
        judge("unreadable: earlier value that is not an integer", base_root, 2, against=bad)
        bad = json.loads(json.dumps(baseline))
        del bad["metrics"]["kit.scenarios"]["items"]
        judge("unreadable: earlier ratcheted metric with no items", base_root, 2, against=bad)

        # Every ratchet can go red on every one of its groups, and nothing shown only can.
        for name in ratcheted:
            for group, value in baseline["metrics"][name]["items"].items():
                more = json.loads(json.dumps(baseline))
                more["metrics"][name]["items"][group] = value + ["zz-planted"] if isinstance(value, list) else value + 1
                more["metrics"][name]["value"] += 1
                judge(f"ratchet {name} [{group}]: one item more before", base_root, 1, against=more, fails=name)
        for name in shown:
            more = json.loads(json.dumps(baseline))
            more["metrics"][name]["value"] += 1
            judge(f"shown {name}: one lower than before is no failure", base_root, 0, against=more)
        gone = json.loads(json.dumps(baseline))
        gone["metrics"]["kit.planted_gone"] = {"value": 1, "ratchet": True, "source": "x", "items": {"x": ["a"]}}
        judge("a ratcheted metric that is gone", base_root, 1, against=gone, must_say="gone, was ratcheted")
        gone["metrics"]["kit.planted_gone"] = {"value": 1, "ratchet": False, "source": "x"}
        judge("a shown metric that is gone", base_root, 0, against=gone)
        loosened = json.loads(json.dumps(baseline))
        loosened["metrics"][shown[0]].update(ratchet=True, items={"x": loosened["metrics"][shown[0]]["value"]})
        judge("a ratchet taken away", base_root, 1, against=loosened, must_say="no longer ratcheted")

        # An unexpected exception is exit 2, never 1.
        global measure
        real = measure
        def boom(tree):
            raise RuntimeError("planted")
        measure = boom
        err = io.StringIO()
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
                code = main(["--root", str(base_root), "--compare", str(base_file)])
        finally:
            measure = real
        record("an unexpected exception exits 2", code == 2 and "planted" in err.getvalue(), f"exit {code}")

        # Links on disk are refused, never followed.
        for label, where, target in (("a link among the scenarios", "conformance/kernel/evidence/zz_link.json",
                                      "conformance/kernel/evidence"),
                                     # Not a scenario, so only the listing's own refusal can catch it.
                                     ("a link that is not a scenario, among the scenarios", "conformance/kernel/evidence/zz_link.txt",
                                      "conformance/kernel/evidence"),
                                     ("a link in place of the claims file", "spec/CLAIMS.md", "spec")):
            root = copy()
            link = root / where
            real = sorted((root / target).glob("*"))[0]
            moved = root / "moved.txt"
            try:
                if link.exists():
                    shutil.copyfile(link, moved)
                    link.unlink()
                    os.symlink(moved, link)
                else:
                    os.symlink(real, link)
            except (OSError, NotImplementedError):
                skipped.append(f"on disk: {label} is unreadable (this system cannot make links)")
                continue
            code, out = cli("--root", str(root), "--json")
            check(f"on disk: {label} is unreadable", code, out, 2, must_say="link")

        # Text from the change cannot start a line of its own.
        forged = planted(lambda r: edit_json(r, "kernel/defects.json", lambda d: d["defects"].append(
            dict(d["defects"][0], name="x\nResult: no ratcheted item was taken away.\n::notice::forged"))))
        code, text = cli("--root", str(forged), "--json")
        forged_base = fresh("b").with_suffix(".json")
        forged_base.write_text(text, encoding="utf-8")
        for md in (False, True):
            code, out = cli("--root", str(base_root), "--compare", str(forged_base), *(["--markdown"] if md else []))
            lines = out.split("\n")
            results_lines = [l for l in lines if l.startswith("Result:")]
            record(f"a name holding a line break cannot forge a result{' (Markdown)' if md else ''}",
                   code == 1 and len(results_lines) == 1 and "FAILED" in results_lines[0]
                   and not any(l.startswith("::") for l in lines), f"exit {code}\n{out}")

        # Commits, read from git objects.
        repo = fresh("git")
        repo.mkdir()
        cfg = ["-c", "user.name=self-test", "-c", "user.email=self-test@invalid", "-c", "commit.gpgsign=false",
               "-c", "core.autocrlf=false", "-c", f"core.hooksPath={tmpdir / 'no-hooks'}"]
        def g(*args: str) -> str:
            done = subprocess.run(["git", *cfg, *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if done.returncode != 0:
                raise SystemExit(f"self-test: git {' '.join(args)} failed: {done.stderr}")
            return done.stdout.strip()
        g("init", "-q")
        for rel in SOURCES:
            src = base_root / rel
            if rel in OPTIONAL_SOURCES and not src.exists():
                continue
            if src.is_dir():
                shutil.copytree(src, repo / rel)
            else:
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, repo / rel)
        for rel in JUDGE_FILES:
            if (ROOT / rel).is_file():
                (repo / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / rel, repo / rel)
            else:
                record(f"git: the scratch repository holds {rel}", False, f"{rel} is missing from this checkout")
        g("add", "-A")
        g("commit", "-q", "-m", "base")
        base = g("rev-parse", "HEAD")

        def change(label: str, edit, message: str, expect: int, **kw) -> None:
            g("checkout", "-q", "-f", "-B", f"case{counter[0]}", base)
            g("clean", "-q", "-f", "-d")
            edit(repo)
            g("add", "-A")
            g("commit", "-q", "--allow-empty", "-m", message)
            code, out = cli("--repo", str(repo), "--base", base, "--head", g("rev-parse", "HEAD"))
            check(f"git: {label}", code, out, expect, **kw)
            counter[0] += 1

        change("nothing changed", lambda r: None, "nothing", 0)
        change("a scenario renamed", rename_scenario, "rename", 1, fails="kit.scenarios", must_say="acts: ")
        change("a tool-tree vector removed",
               lambda r: edit_json(r, "conformance/vectors/tool-tree.json", lambda d: d["reject"].pop()), "x", 1, fails="kit.tool_tree_vectors")
        change("an explanation in the commit is shown and the change still fails",
               lambda r: sorted((r / "conformance/kernel/evidence").glob("*.json"))[0].unlink(),
               f"Drop a scenario\n\nMetrics-down: kit.scenarios: {good}", 1, must_say="the author explains")
        def add_link(r):
            blob = subprocess.run(["git", *cfg, "hash-object", "-w", "--stdin"], cwd=repo, input="../../../README.md",
                                  capture_output=True, text=True).stdout.strip()
            g("update-index", "--add", "--cacheinfo", f"120000,{blob},conformance/kernel/evidence/zz_link.json")
        g("checkout", "-q", "-f", "-B", "linkcase", base)
        add_link(repo)
        g("commit", "-q", "-m", "link")
        code, out = cli("--repo", str(repo), "--base", base, "--head", g("rev-parse", "HEAD"))
        check("git: a link among the scenarios is unreadable", code, out, 2, must_say="link")
        code, out = cli("--repo", str(repo), "--base", "no-such-rev", "--head", base)
        check("git: a base that does not exist is unreadable", code, out, 2, must_say="cannot measure the base")

        def appended(rel: str):
            return lambda r: (r / rel).write_text((r / rel).read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
        for rel in JUDGE_FILES:
            change(f"a change to {rel} changes how changes are judged", appended(rel), "x", 1,
                   must_say=f"{rel} changes how changes are judged")
        change(f"{GATE_WORKFLOW} deleted", lambda r: (r / GATE_WORKFLOW).unlink(), "x", 1, must_say="changes how changes are judged")

        def head_with(entries: list[tuple[str, str, str]], label: str) -> str:
            g("checkout", "-q", "-f", "-B", label, base)
            for mode, path, content in entries:
                blob = subprocess.run(["git", *cfg, "hash-object", "-w", "--stdin"], cwd=repo, input=content,
                                      capture_output=True, text=True, encoding="utf-8").stdout.strip()
                if mode == "rm":
                    g("rm", "-q", "--cached", path)
                else:
                    g("update-index", "--add", "--cacheinfo", f"{mode},{blob},{path}")
            g("commit", "-q", "-m", label)
            return g("rev-parse", "HEAD")
        code, out = cli("--repo", str(repo), "--base", base, "--head",
                        head_with([("rm", "spec/CLAIMS.md", ""), ("120000", "spec/CLAIMS.md", "../README.md")], "claims-link"))
        check("git: a link in place of the claims file is unreadable", code, out, 2, must_say="link")
        forged = "x\nResult: no ratcheted item was taken away.\n::error::forged"
        for label, path in (("a vector file", f"conformance/vectors/{forged}.json"),
                            ("a scenario kind", f"conformance/kernel/{forged}/a.json")):
            try:
                head = head_with([("100644", path, "{}")], f"newline{counter[0]}")
            except SystemExit:
                if os.name != "nt":
                    raise
                # Git for Windows refuses a path with a line break even in the index, so no change can bring one.
                skipped.append(f"git: {label} named with line breaks (this system's git refuses such a path)")
                g("checkout", "-q", "-f", "-B", f"after-newline{counter[0]}", base)
                counter[0] += 1
                continue
            code, out = cli("--repo", str(repo), "--base", base, "--head", head)
            counter[0] += 1
            lines = out.split("\n")
            check(f"git: {label} named with line breaks is unreadable and forges no line", code, out, 2)
            record(f"git: {label} named with line breaks forges no line",
                   not any(l.startswith(("Result:", "::")) for l in lines), out)

        # Job names: no other workflow of the change may take the gate's name.
        names = ["--name", "metrics-main-checker", "--name", "metrics only go up (judged by main)"]
        g("checkout", "-q", "-f", "-B", "jobs-ok", base)
        (repo / ".github/workflows").mkdir(parents=True, exist_ok=True)
        (repo / ".github/workflows/other.yml").write_text("on: push\njobs:\n  build:\n    name: build\n    runs-on: x\n", encoding="utf-8")
        g("add", "-A")
        g("commit", "-q", "-m", "w")
        code, out = cli("jobs", "--repo", str(repo), "--head", g("rev-parse", "HEAD"), "--own", GATE_WORKFLOW, *names)
        check("jobs: another workflow with other job names", code, out, 0)
        (repo / ".github/workflows/other.yml").write_text(
            "on: pull_request\njobs:\n  fake:\n    name: metrics only go up (judged by main)\n    runs-on: x\n", encoding="utf-8")
        g("add", "-A")
        g("commit", "-q", "-m", "w2")
        code, out = cli("jobs", "--repo", str(repo), "--head", g("rev-parse", "HEAD"), "--own", GATE_WORKFLOW, *names)
        check("jobs: another workflow taking the gate's job name", code, out, 1, must_say="other.yml")
        g("rm", "-q", "--cached", ".github/workflows/other.yml")
        (repo / ".github/workflows/other.yml").unlink()
        (repo / ".github/workflows/other.yaml").write_text(
            "on: pull_request\njobs:\n  fake:\n    name: metrics only go up (judged by main)\n    runs-on: x\n", encoding="utf-8")
        g("add", "-A")
        g("commit", "-q", "-m", "w3")
        code, out = cli("jobs", "--repo", str(repo), "--head", g("rev-parse", "HEAD"), "--own", GATE_WORKFLOW, *names)
        check("jobs: a .yaml workflow taking the gate's job name", code, out, 1, must_say="other.yaml")
        (repo / ".github/workflows/other.yaml").write_text(
            "on: pull_request\njobs:\n  metrics-main-checker:\n    name: something else\n    runs-on: x\n", encoding="utf-8")
        g("add", "-A")
        g("commit", "-q", "-m", "w4")
        code, out = cli("jobs", "--repo", str(repo), "--head", g("rev-parse", "HEAD"), "--own", GATE_WORKFLOW, *names)
        check("jobs: another workflow taking the gate's job id", code, out, 1, must_say="'metrics-main-checker'")
        code, out = cli("jobs", "--repo", str(repo), "--head", base, "--own", GATE_WORKFLOW, *names)
        check("jobs: the gate's own workflow is not a clash with itself", code, out, 0)

        # The gate workflow: safe as it is, and each unsafe edit noticed.
        wf_path = ROOT / GATE_WORKFLOW
        wf = wf_path.read_text(encoding="utf-8").replace("\r\n", "\n") if wf_path.is_file() else ""
        record("the gate workflow passes its guard", bool(wf) and not workflow_problems(wf), "; ".join(workflow_problems(wf)) if wf else "missing")
        # The bootstrap commit is written in the workflow only; the edits take it from there.
        sha = (re.findall(r"^\s+BOOTSTRAP_BEFORE:\s*(\S+)\s*$", wf, flags=re.M) or ["(none)"])[0]
        for old, new in UNSAFE_WORKFLOW_EDITS:
            old, new = old.replace("{BOOTSTRAP}", sha), new.replace("{BOOTSTRAP}", sha)
            ok = old in wf and bool(workflow_problems(wf.replace(old, new, 1)))
            record(f"the workflow guard notices {new.strip()[:70]!r}", ok, "cannot plant" if old not in wf else "not noticed")

        # Faults planted in this tool must each make its self-test fail.
        if mutants:
            source = me.read_text(encoding="utf-8")
            # The faults are planted in the code, never in the list of faults itself.
            start = source.index("\nMUTANTS = [")
            end = source.index("\n]\n", start) + 3
            head, block, tail = source[:start], source[start:end], source[end:]
            jobs = []
            # A mutant whose only catching plants could not run on this system is listed as not run, never as caught.
            needs = {"error messages are printed raw": "named with line breaks"}
            for label, old, new in MUTANTS:
                if label in needs and any(needs[label] in item for item in skipped):
                    skipped.append(f"mutant '{label}': the plants that catch it cannot run on this system")
                    continue
                if (head + tail).count(old) != 1:
                    record(f"mutant '{label}' can be planted", False, f"{old!r} is not in the tool exactly once")
                    continue
                mutated = head.replace(old, new, 1) + block + tail if old in head else head + block + tail.replace(old, new, 1)
                root = copy(extra=(GATE_WORKFLOW, SELF_TEST_WORKFLOW))
                (root / "tools").mkdir(exist_ok=True)
                (root / "tools/metrics.py").write_text(mutated, encoding="utf-8")
                jobs.append((label, root / "tools/metrics.py"))
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                done = list(pool.map(lambda j: (j[0], cli("self-test", "--no-mutants", tool=j[1])), jobs))
            for label, (code, out) in done:
                # Caught means the self-test judged and failed (1), not that the mutated tool crashed (2).
                record(f"mutant '{label}' is caught by the self-test", code == 1 and "planted changes judged as expected" in out,
                       f"its self-test exited {code}")

    failed = [r for r in results if not r[1]]
    for label, ok, detail in results:
        print(_ascii(f"{'ok  ' if ok else 'FAIL'}  {label}" + ("" if ok else f": {detail}")))
    for label in skipped:
        print(_ascii(f"SKIP  {label}"))
    print(f"\n{len(results) - len(failed)} of {len(results)} planted changes judged as expected"
          + (f"; {len(skipped)} not run on this system (listed as SKIP)" if skipped else ""))
    return 1 if failed else 0


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", nargs="?", choices=["self-test", "jobs", "workflow-check"])
    parser.add_argument("file", nargs="?", help="with workflow-check: the workflow file")
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    parser.add_argument("--rev", help="measure this commit, from git objects, instead of the working tree")
    parser.add_argument("--base", help="with --head: the commit to compare from")
    parser.add_argument("--head", help="with --base: the commit to compare to; with jobs: the commit whose workflows are read")
    parser.add_argument("--repo", default=".", help="the git repository for --rev, --base, --head and jobs")
    parser.add_argument("--compare", metavar="FILE", help="compare the measured tree with an earlier --json output")
    parser.add_argument("--messages", metavar="FILE", help="with --compare: commit messages to read explanations from")
    parser.add_argument("--markdown", action="store_true", help="print tables as Markdown")
    parser.add_argument("--commit", metavar="SHA", help="the commit measured, recorded in --json output")
    parser.add_argument("--root", metavar="DIR", default=str(ROOT), help="the folder to measure")
    parser.add_argument("--own", help="with jobs: the workflow whose job names no other may use")
    parser.add_argument("--name", action="append", default=[], help="with jobs: a job id or name (may be repeated)")
    parser.add_argument("--no-mutants", action="store_true", help="with self-test: do not plant faults in this tool")
    args = parser.parse_args(argv)

    if args.mode == "self-test":
        # A self-test that stops on its own error has judged nothing: that is 2, never 1, so a fault that
        # only breaks the tool is not counted as caught.
        try:
            return self_test(not args.no_mutants)
        except SystemExit as stop:
            if isinstance(stop.code, int):
                raise
            print(_ascii(printable(str(stop.code))), file=sys.stderr)
            return 2
        except Exception as err:  # noqa: BLE001
            print(_ascii(printable(f"self-test stopped: {type(err).__name__}: {err}")), file=sys.stderr)
            return 2
    try:
        return run(args)
    except Exception as err:  # noqa: BLE001 - a crash must never read as "a ratchet went down" (exit 1)
        complain(f"cannot measure: unexpected {type(err).__name__}: {err}")
        return 2


def complain(message: str) -> None:
    print(_ascii(printable(message)), file=sys.stderr)


def run(args) -> int:
    repo = pathlib.Path(args.repo)
    if args.mode == "workflow-check":
        if not args.file:
            print("workflow-check needs a file", file=sys.stderr)
            return 2
        problems = workflow_problems(pathlib.Path(args.file).read_text(encoding="utf-8"))
        for p in problems:
            print(_ascii(printable(f"PROBLEM {args.file}: {p}")))
        print("workflow guard:", "FAILED" if problems else "safe")
        return 1 if problems else 0
    if args.mode == "jobs":
        if not (args.head and args.own and args.name):
            print("jobs needs --head, --own and --name", file=sys.stderr)
            return 2
        try:
            clashes = job_clashes(repo, args.head, args.own, set(args.name))
        except Unmeasurable as err:
            complain(f"cannot read the workflows: {err}")
            return 2
        for line in clashes:
            print(_ascii(printable(f"PROBLEM {line}")))
        print("job names:", "FAILED" if clashes else "no other workflow uses them")
        return 1 if clashes else 0

    if args.base or args.head:
        if not (args.base and args.head):
            print("--base and --head go together", file=sys.stderr)
            return 2
        try:
            base_tree = GitTree(repo, args.base)
            before = as_json(measure(base_tree), base_tree.commit)
        except Unmeasurable as err:
            complain(f"cannot measure the base {args.base}: {err}")
            return 2
        try:
            head_tree = GitTree(repo, args.head)
            after = as_json(measure(head_tree), head_tree.commit)
            messages = git(repo, "log", "--format=%B", f"{base_tree.commit}..{head_tree.commit}").decode("utf-8", "replace")
        except Unmeasurable as err:
            complain(f"cannot measure the change {args.head}: {err}")
            return 2
        rows, malformed, unused, failed = compare(before, after, messages)
        judged = judge_changes(base_tree, head_tree)
        title = (f"Metrics of `{head_tree.commit}` compared with `{base_tree.commit}`. Explanations are read from the "
                 f"commits in between." if args.markdown else f"metrics of {head_tree.commit} compared with {base_tree.commit}")
        print(comparison(title, rows, malformed, unused, failed, args.markdown, judged))
        return 1 if failed or judged else 0

    try:
        tree = GitTree(repo, args.rev) if args.rev else DirTree(pathlib.Path(args.root))
        metrics = measure(tree)
    except Unmeasurable as err:
        complain(f"cannot measure: {err}")
        return 2
    if args.json:
        print(json.dumps(as_json(metrics, args.commit or getattr(tree, "commit", None)), indent=2))
        return 0
    if not args.compare:
        print(table(metrics, args.markdown))
        return 0
    try:
        old = read_baseline(pathlib.Path(args.compare))
        messages = pathlib.Path(args.messages).read_text(encoding="utf-8") if args.messages else ""
    except BadBaseline as err:
        complain(f"cannot compare: {err}")
        return 2
    except OSError as err:
        complain(f"cannot read the commit messages: {err}")
        return 2
    rows, malformed, unused, failed = compare(old, as_json(metrics, None), messages)
    print(comparison(f"compared with the metrics of {old.get('commit') or 'an unknown commit'}", rows, malformed, unused,
                     failed, args.markdown))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
