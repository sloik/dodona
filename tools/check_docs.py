"""Checks that the documents still describe the code. Stage-0 helper (decision 0023).

    python tools/check_docs.py                                          # every repository-wide check
    python tools/check_docs.py self-test                                # plant a fault for each check; each must fail
    python tools/check_docs.py diff --base REV [--head REV] [--pr-body FILE] [--repo DIR]
    python tools/check_docs.py pins-only --base REV --head REV [--repo DIR]   # exit 0 if only pinned versions changed
    python tools/check_docs.py jobs --head REV --own WORKFLOW --name NAME... [--repo DIR]   # no other workflow may use these job names

The usual way documents go wrong here is quiet: code changes and the text that
describes it does not. The repository-wide checks compare what the code and
data say with what the documents say, in both directions where both can be
read: command-line flags, the tool list, the decision index, the protocol and
kit indexes, counts, links and the paths and decision numbers the documents
name. Each is listed, with the gap behind it, in docs/gap-checks.md.

`diff` judges a change. docs/doc-map.toml says which documents describe which
files. A change to a file under a rule needs a change of substance to one of
that rule's documents in the same change, or a line in a commit message of
the change saying why none is needed:

    Docs-unchanged: <rule id>: <why no document has to change, in a sentence>

Only a line that starts exactly so is a waiver. It is the author's own word,
and it is printed as such for whoever reviews the change. A change is judged
by the map on its base, so it cannot loosen the rule it is judged by; a file
new to the map must be bound by a rule the change brings, and an exemption or
known drift the change adds fails it. `pins-only` says whether a change
touches nothing but workflow lines pinning actions and runner images.
With --pr-body, the description of a pull request must also say what was
verified and what was not. Without --head, the working tree is judged,
including files not yet committed.

`self-test` plants, in a copy held in memory, a fault each check exists to
catch, and requires the check to report it; it also judges a small throwaway
repository end to end with git. A check that cannot fail is not a check.

Exit status: 0 if nothing is wrong, 1 if something is, 2 if the check could
not run (no base, no git). Exit status 2 is never a pass.
"""
from __future__ import annotations

import argparse
import ast
import functools
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAP_FILE = "docs/doc-map.toml"
WAIVER = re.compile(r"^Docs-unchanged: ([a-z0-9][a-z0-9-]*): (.+)$")
MIN_REASON_CHARS, MIN_REASON_WORDS = 40, 6
# The files that decide how a change is judged. A change to any of them, or to a [[rule]] of the map,
# fails the change that makes it: nothing else stops a change from loosening what judges it, as the owner
# opens the pull requests and a code-owner review therefore never applies.
JUDGING_FILES = ("tools/check_docs.py", ".github/workflows/docs.yml", ".github/CODEOWNERS")
JUDGING = "changes how changes are judged; the owner merges over this failure"
TOOL_DIRS = ("tools/", "providers/", "conformance/", ".github/site/")
SKIPPED_PARTS = {".git", "__pycache__", "target", "node_modules"}


class CannotRun(Exception):
    """The check could not be carried out. Never reported as a pass."""


# ---------------------------------------------------------------------------
# The repository as the checks see it: a list of files and their text, with an
# overlay so the self-test can plant faults without touching the disk.


def _listed_files(root: pathlib.Path) -> list[str]:
    try:
        done = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z", "-c", "-o", "--exclude-standard"],
                              cwd=root, capture_output=True)
    except OSError:
        done = None
    if done is not None and done.returncode == 0:
        names = {n for n in done.stdout.decode("utf-8").split("\0") if n}
        return sorted(n for n in names if (root / n).is_file() and not SKIPPED_PARTS & set(n.split("/")))
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")
                  if p.is_file() and not SKIPPED_PARTS & set(p.relative_to(root).parts))


class Repo:
    def __init__(self, root: pathlib.Path, files: list[str] | None = None, overlay: dict | None = None,
                 cache: dict | None = None):
        self.root = root
        self._base = files if files is not None else _listed_files(root)
        self.overlay = overlay or {}
        self._cache = cache if cache is not None else {}
        gone = {p for p, t in self.overlay.items() if t is None}
        added = {p for p, t in self.overlay.items() if t is not None}
        self.files = sorted((set(self._base) - gone) | added)
        self._set = set(self.files)
        self._dirs = {"/".join(f.split("/")[:i]) for f in self.files for i in range(1, f.count("/") + 1)}

    def read(self, rel: str) -> str:
        if rel in self.overlay:
            if self.overlay[rel] is None:
                raise FileNotFoundError(rel)
            return self.overlay[rel]
        if rel not in self._cache:
            self._cache[rel] = (self.root / rel).read_bytes().decode("utf-8").replace("\r\n", "\n")
        return self._cache[rel]

    def exists(self, rel: str) -> bool:
        rel = rel.rstrip("/")
        return rel in self._set or rel in self._dirs

    def is_dir(self, rel: str) -> bool:
        return rel.rstrip("/") in self._dirs

    def changed(self, edits: dict) -> "Repo":
        return Repo(self.root, self._base, {**self.overlay, **edits}, self._cache)

    def glob(self, pattern: str) -> list[str]:
        rx = glob_rx(pattern)
        return [f for f in self.files if rx.fullmatch(f)]

    def markdown(self) -> list[str]:
        return [f for f in self.files if f.endswith(".md")]


@functools.lru_cache(maxsize=None)
def glob_rx(pattern: str) -> re.Pattern:
    """`**` is any run of characters, `*` any run within one path segment, `?` one character, `[0-9]` one of a set."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        elif pattern[i] == "[" and "]" in pattern[i + 1:]:
            end = pattern.index("]", i + 1)
            out, i = out + "[" + pattern[i + 1:end].replace("\\", "\\\\") + "]", end + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out)


# ---------------------------------------------------------------------------
# Reading Markdown: code fences and code spans are kept apart from prose.

FENCE = re.compile(r"^(```|~~~)")


def prose_lines(text: str):
    """Lines outside fenced code blocks, with their numbers."""
    inside = False
    for number, line in enumerate(text.split("\n"), 1):
        if FENCE.match(line.lstrip()):
            inside = not inside
            continue
        if not inside:
            yield number, line


def fenced_lines(text: str):
    inside = False
    for number, line in enumerate(text.split("\n"), 1):
        if FENCE.match(line.lstrip()):
            inside = not inside
            continue
        if inside:
            yield number, line


def code_spans(line: str) -> list[str]:
    return re.findall(r"`([^`\n]+)`", line)


def without_code_spans(line: str) -> str:
    return re.sub(r"`[^`\n]*`", "", line)


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading).strip().lower()
    text = re.sub(r"[^\w\- ]", "", text.replace("`", ""))
    return text.replace(" ", "-")


def anchors(text: str) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for _, line in prose_lines(text):
        m = re.match(r"#{1,6} +(.*?)\s*#*\s*$", line)
        if m:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else f"{s}-{n}")
        for name in re.findall(r'<a (?:name|id)="([^"]+)"', line):
            out.add(name)
    return out


def table_rows(text: str, heading: str | None = None) -> list[list[str]]:
    """Rows of the tables in the section under `heading` (or the whole text), header and rule left out."""
    if heading is not None:
        start = text.find("\n" + heading + "\n")
        if start < 0:
            return []
        rest = text[start + len(heading) + 2:]
        level = heading.split(" ")[0]
        stop = re.search(rf"^#{{1,{len(level)}}} ", rest, flags=re.M)
        text = rest[: stop.start()] if stop else rest
    rows, at = [], 0  # at: position of a line within its table, 0 outside one
    for line in text.split("\n"):
        at = at + 1 if line.startswith("|") else 0
        if at > 2:  # the first line of a table is its header, the second its rule
            rows.append([c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))])
    return rows


def front_matter(text: str) -> dict:
    """The small subset of YAML the decision records use: `key: value` and lists of `  - item`."""
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    fields: dict = {}
    key = None
    for line in text[4:end].split("\n"):
        m = re.match(r"^([a-z_]+):\s*(.*)$", line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            fields[key] = [] if value in ("", "[]") else value.strip('"')
        elif key and re.match(r"^\s+- ", line):
            if not isinstance(fields[key], list):
                fields[key] = []
            fields[key].append(line.split("- ", 1)[1].strip().strip('"'))
    return fields


# ---------------------------------------------------------------------------
# The command-line interface of a Python tool, read from its source without
# running it, and the usage lines its docstring shows.


@functools.lru_cache(maxsize=None)
def _parse(source: str) -> ast.Module:
    return ast.parse(source)


class Cli:
    def __init__(self):
        self.flags: dict[str | None, set[str]] = {None: set()}
        self.subcommands: set[str] = set()
        self.unreadable: list[str] = []
        self.runnable = False


@functools.lru_cache(maxsize=None)
def read_cli(source: str) -> Cli:
    """Cached by the text, as the self-test reads the same sources many times; the result is never changed."""
    cli = Cli()
    tree = _parse(source)
    parsers: dict[str, str] = {}
    loops: dict[str, list[str]] = {}

    def strings(node) -> list[str] | None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left, right = strings(node.left), strings(node.right)
            if left is not None and right is not None:
                return [a + b for a in left for b in right]
        if isinstance(node, ast.Name) and node.id in loops:
            return loops[node.id]
        return None

    def is_argv(node) -> bool:
        return (isinstance(node, ast.Attribute) and node.attr == "argv"
                and isinstance(node.value, ast.Name) and node.value.id == "sys")

    def visit(node):
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and isinstance(node.iter, (ast.Tuple, ast.List)):
            values = [strings(e) for e in node.iter.elts]
            if all(v is not None and len(v) == 1 for v in values):
                loops[node.target.id] = [v[0] for v in values]
                for child in node.body:
                    visit(child)
                del loops[node.target.id]
                return
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) \
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__":
            cli.runnable = True
        if is_argv(node):
            cli.runnable = True
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "add_parser":
            names = strings(node.value.args[0]) if node.value.args else None
            if names and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                parsers[node.targets[0].id] = names[0]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_parser":
                names = strings(node.args[0]) if node.args else None
                if names is None:
                    cli.unreadable.append(f"line {node.lineno}: a subcommand whose name cannot be read without running the tool")
                else:
                    cli.subcommands.update(names)
            elif node.func.attr == "add_argument" and node.args:
                owner = node.func.value.id if isinstance(node.func.value, ast.Name) else None
                sub = parsers.get(owner)
                names = [strings(a) for a in node.args]
                if any(n is None for n in names):
                    cli.unreadable.append(f"line {node.lineno}: an argument whose name cannot be read without running the tool")
                else:
                    flat = [s for n in names for s in n]
                    if flat and flat[0].startswith("-"):
                        cli.flags.setdefault(sub, set()).update(s for s in flat if s.startswith("--"))
                    else:
                        for kw in node.keywords:
                            if kw.arg == "choices" and isinstance(kw.value, (ast.List, ast.Tuple)):
                                cli.subcommands.update(s for e in kw.value.elts for s in (strings(e) or []))
            elif node.func.attr == "index" and is_argv(node.func.value) and node.args:
                found = strings(node.args[0])
                if found:
                    cli.flags[None].update(f for f in found if f.startswith("--") and f != "--")
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], (ast.In, ast.NotIn)) \
                and is_argv(node.comparators[0]):
            found = strings(node.left)
            if found:
                cli.flags[None].update(f for f in found if f.startswith("--") and f != "--")
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return cli


FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")


def command_words(text: str) -> tuple[str | None, set[str]]:
    """The first word and the flags of a command line, up to `--`, a comment or the end of a code span."""
    text = re.split(r"\s#\s", " " + text + " ", maxsplit=1)[0]
    words = text.split()
    if "--" in words:
        words = words[: words.index("--")]
    first = words[0] if words and re.fullmatch(r"[a-z][a-z0-9-]*", words[0]) else None
    return first, set(FLAG.findall(" ".join(words)))


def usage_lines(doc: str, name: str) -> list[str]:
    """The lines of a docstring that show how the tool is started, joined with their continuation lines."""
    out: list[str] = []
    lines = doc.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        words = line.split()
        if len(words) >= 2 and words[0] in ("python", "python3") and words[1].split("/")[-1] == name:
            indent = len(line) - len(line.lstrip())
            joined = " ".join(words[2:])
            i += 1
            while i < len(lines) and lines[i].strip() and len(lines[i]) - len(lines[i].lstrip()) > indent:
                joined += " " + lines[i].strip()
                i += 1
            out.append(joined)
            continue
        i += 1
    return out


def tool_files(repo: Repo) -> list[str]:
    return [f for f in repo.files if f.endswith(".py") and f.startswith(TOOL_DIRS)]


# ---------------------------------------------------------------------------
# The repository-wide checks. Each returns a list of problems.


def load_map(text: str) -> dict:
    data = tomllib.loads(text)
    return {kind: data.get(kind, []) for kind in ("rule", "exempt", "absent", "known")}


def map_entry(doc_map: dict, path: str) -> list[tuple[str, dict]]:
    found = []
    for kind in ("rule", "exempt"):
        for entry in doc_map[kind]:
            if any(glob_rx(p).fullmatch(path) for p in entry.get("code" if kind == "rule" else "paths", [])):
                found.append((kind, entry))
    return found


def docs_map_covers_every_file(repo: Repo) -> list[str]:
    """New code could be added that no document is bound to, and nothing would ask for one."""
    problems = []
    try:
        doc_map = load_map(repo.read(MAP_FILE))
    except (FileNotFoundError, tomllib.TOMLDecodeError) as err:
        return [f"{MAP_FILE}: cannot be read: {err}"]
    ids = [r.get("id") for r in doc_map["rule"]]
    for rule in doc_map["rule"]:
        rid = rule.get("id")
        if not isinstance(rid, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]*", rid):
            problems.append(f"{MAP_FILE}: a rule has no id of lowercase letters, digits and dashes: {rid!r}")
        if ids.count(rid) > 1:
            problems.append(f"{MAP_FILE}: rule id {rid} is used twice")
        if not rule.get("why", "").strip():
            problems.append(f"{MAP_FILE}: rule {rid} does not say why these documents describe this code")
        if not rule.get("docs"):
            problems.append(f"{MAP_FILE}: rule {rid} names no document")
        for doc in rule.get("docs", []):
            if not doc.endswith(".md") or not repo.exists(doc):
                problems.append(f"{MAP_FILE}: rule {rid} names {doc}, which is not a Markdown file in the repository")
        for pattern in rule.get("code", []):
            if not repo.glob(pattern):
                problems.append(f"{MAP_FILE}: rule {rid}: pattern {pattern} matches no file; remove it or fix it")
    for entry in doc_map["exempt"]:
        if len(entry.get("why", "").split()) < 4:
            problems.append(f"{MAP_FILE}: the exemption of {entry.get('paths')} does not say why")
        for pattern in entry.get("paths", []):
            if not repo.glob(pattern):
                problems.append(f"{MAP_FILE}: exempt pattern {pattern} matches no file; remove it")
    for path in repo.files:
        if path.endswith(".md"):
            continue
        found = map_entry(doc_map, path)
        if not found:
            problems.append(f"{path}: no rule in {MAP_FILE} names the documents that describe it, and it is not exempt. "
                            "Add it to the rule of the documents that describe it, or add a rule")
        elif len(found) > 1:
            names = ", ".join(e.get("id", "exempt") if k == "rule" else "exempt" for k, e in found)
            problems.append(f"{path}: matched by more than one entry of {MAP_FILE} ({names}); one file, one entry")
    return problems


def docs_usage_matches_the_parser(repo: Repo) -> list[str]:
    """A tool gained a flag and its usage line did not, or the usage line kept a flag the tool no longer has."""
    problems = []
    for path in tool_files(repo):
        source = repo.read(path)
        try:
            cli = read_cli(source)
        except SyntaxError:
            continue  # reported by check_repo.py's gap_every_tool_compiles
        name = path.split("/")[-1]
        for why in cli.unreadable:
            problems.append(f"{path}: {why}; write it as a literal so the documents can be checked against it")
        if not cli.runnable:
            continue
        doc = ast.get_docstring(_parse(source)) or ""
        usage = usage_lines(doc, name)
        if not usage:
            problems.append(f"{path}: it can be run, and its docstring has no line showing how (`python {path} ...`)")
            continue
        documented: dict[str | None, set[str]] = {}
        for line in usage:
            first, flags = command_words(line)
            sub = first if first in cli.subcommands else None
            if cli.subcommands and first and first not in cli.subcommands:
                problems.append(f"{path}: its usage shows subcommand {first!r}, which the tool does not have")
            documented.setdefault(sub, set()).update(flags)
        every_documented = set().union(*documented.values())
        for sub in sorted(cli.subcommands):
            if sub not in documented:
                problems.append(f"{path}: subcommand {sub!r} is not shown in its usage lines")
        for sub, flags in sorted(cli.flags.items(), key=lambda kv: kv[0] or ""):
            seen = every_documented if sub is None else documented.get(sub, set())
            for flag in sorted(flags - seen):
                where = f" {sub}" if sub else ""
                problems.append(f"{path}: flag {flag} of `{name}{where}` is not shown in its usage lines")
        for sub, flags in documented.items():
            known = cli.flags[None] | (cli.flags.get(sub, set()) if sub else set().union(*cli.flags.values()))
            for flag in sorted(flags - known):
                problems.append(f"{path}: its usage shows flag {flag}{' for ' + sub if sub else ''}, which the tool does not define")
    return problems


TOOL_REF = re.compile(r"(?<![\w./-])((?:tools|providers|conformance|\.github)/[\w./-]*?\.py)\b(.*)")


def command_references(repo: Repo):
    """(file, line number, tool path, the rest of the command) for every tool named in code in the documents or a workflow."""
    for doc in repo.markdown():
        text = repo.read(doc)
        pieces = [(n, span) for n, line in prose_lines(text) for span in code_spans(line)]
        pieces += list(fenced_lines(text))
        for number, piece in pieces:
            for m in TOOL_REF.finditer(piece):
                yield doc, number, m.group(1), m.group(2)
    for wf in repo.glob(".github/workflows/*.yml"):
        for number, line in enumerate(repo.read(wf).split("\n"), 1):
            if line.lstrip().startswith("#"):
                continue  # a comment, in prose
            for m in TOOL_REF.finditer(line):
                yield wf, number, m.group(1), m.group(2)


def docs_commands_name_real_flags(repo: Repo) -> list[str]:
    """Documents and workflows showed a tool started with a flag or subcommand it does not have, or a tool that is gone."""
    problems, clis = [], {}
    for where, number, tool, rest in command_references(repo):
        if not repo.exists(tool):
            problems.append(f"{where}:{number}: names {tool}, which does not exist")
            continue
        if tool not in clis:
            clis[tool] = read_cli(repo.read(tool))
        cli = clis[tool]
        rest = re.split(r"[`|;&<>)]|\$\{\{", rest, maxsplit=1)[0]
        first, flags = command_words(rest)
        if cli.subcommands and first and first not in cli.subcommands:
            problems.append(f"{where}:{number}: `{tool} {first}`: the tool has no subcommand {first!r} (it has {', '.join(sorted(cli.subcommands))})")
        known = set().union(*cli.flags.values())
        for flag in sorted(flags - known):
            problems.append(f"{where}:{number}: `{tool} {flag}`: the tool has no flag {flag}")
    return problems


def docs_every_tool_is_listed(repo: Repo) -> list[str]:
    """A tool can be added that no document names, and a removed one can stay listed."""
    problems = []
    try:
        text = repo.read("tools/README.md")
    except FileNotFoundError:
        return ["tools/README.md is missing: it lists every tool with what it is for"]
    listed = {}
    for cells in table_rows(text):
        m = re.fullmatch(r"\[`?([\w.-]+\.py)`?\]\(([\w.-]+\.py)\)", cells[0]) if cells else None
        if not m or m.group(1) != m.group(2):
            problems.append(f"tools/README.md: row {cells!r} is not `| [name.py](name.py) | what it is for |`")
            continue
        if m.group(1) in listed:
            problems.append(f"tools/README.md lists {m.group(1)} twice")
        listed[m.group(1)] = cells[1] if len(cells) > 1 else ""
    present = {f.split("/")[-1] for f in repo.glob("tools/*.py")}
    for name in sorted(present - set(listed)):
        problems.append(f"tools/README.md does not list tools/{name}: add a row saying what it is for")
    for name in sorted(set(listed) - present):
        problems.append(f"tools/README.md lists {name}, which is not in tools/")
    for name, what in sorted(listed.items()):
        if len(what.split()) < 3:
            problems.append(f"tools/README.md: the row of {name} does not say what it is for")
    return problems


DECISION_REF = re.compile(r"\b[Dd]ecisions? (\d{4})\b|\bdecisions/(\d{4})-")


def docs_decision_index_matches_the_records(repo: Repo) -> list[str]:
    """The decision index, the records' headers, their headings and what amends what drifted apart."""
    problems = []
    records = {f.split("/")[-1][:4]: f for f in repo.glob("decisions/[0-9][0-9][0-9][0-9]-*.md")}
    index = repo.read("decisions/README.md")
    rows = table_rows(index, "## Index")
    if not rows:
        return ["decisions/README.md: the table under '## Index' is missing"]
    seen = set()
    fields_of = {num: front_matter(repo.read(path)) for num, path in records.items()}
    for cells in rows:
        m = re.fullmatch(r"\[(\d{4})\]\(((\d{4})-[\w-]+\.md)\)", cells[0])
        if not m or len(cells) != 3 or m.group(1) != m.group(3):
            problems.append(f"decisions/README.md: index row {cells!r} is not `| [NNNN](NNNN-name.md) | title | status |`")
            continue
        num = m.group(1)
        if num in seen:
            problems.append(f"decisions/README.md lists {num} twice")
        seen.add(num)
        if num not in records or records[num] != "decisions/" + m.group(2):
            problems.append(f"decisions/README.md: row {num} links to {m.group(2)}, which is not a decision record")
            continue
        fields = fields_of[num]
        if cells[1] != fields.get("title"):
            problems.append(f"decisions/README.md: the title of {num} reads {cells[1]!r}; the record's header says {fields.get('title')!r}")
        status = fields.get("status", "") + (", owner direction" if fields.get("direction") == "owner" else "")
        if cells[2] != status:
            problems.append(f"decisions/README.md: the status of {num} reads {cells[2]!r}; the record's header gives {status!r}"
                            " (status, then ', owner direction' when the header has `direction: owner`)")
    for num in sorted(set(records) - seen):
        problems.append(f"decisions/README.md: the index has no row for {records[num]}")
    for num, path in sorted(records.items()):
        text, fields = repo.read(path), fields_of[num]
        heading = re.search(r"^# (\d{4})\. (.+)$", text, flags=re.M)
        if not heading or heading.group(1) != num or heading.group(2) != fields.get("title"):
            problems.append(f"{path}: the heading must be '# {num}. ' followed by the title in the header")
        for key, verb in (("amends", "amended"), ("supersedes", "superseded")):
            for other in fields.get(key, []):
                target = records.get(other)
                if target is None:
                    problems.append(f"{path}: {key} {other}, which is not a decision record")
                    continue
                if path.split("/")[-1] not in repo.read(target):
                    problems.append(f"{target}: is {verb} by {num} ({path}) and does not link to it")
                if key == "supersedes" and fields_of[other].get("status") != "superseded":
                    problems.append(f"{target}: is superseded by {num} and its status is {fields_of[other].get('status')}")
        for governed in fields.get("governs", []):
            if not repo.exists(governed):
                problems.append(f"{path}: governs {governed}, which does not exist")
    for path in repo.files:
        if not path.endswith((".md", ".py", ".yml", ".json", ".toml")):
            continue
        for number, line in enumerate(repo.read(path).split("\n"), 1):
            for m in DECISION_REF.finditer(line):
                num = m.group(1) or m.group(2)
                if num not in records:
                    problems.append(f"{path}:{number}: names decision {num}, which does not exist")
    return problems


LINK = re.compile(r"\]\(([^)\s]+)\)")


def docs_links_and_anchors_resolve(repo: Repo) -> list[str]:
    """A heading was renamed and the links to it went on pointing at nothing; GitHub shows no error for that."""
    problems, checked = [], 0
    cache: dict[str, set[str]] = {}
    for doc in repo.markdown():
        text = repo.read(doc)
        for number, line in prose_lines(text):
            for target in LINK.findall(without_code_spans(line)):
                if re.match(r"[a-z][a-z0-9+.-]*:", target) or "#" not in target:
                    continue
                file, anchor = target.split("#", 1)
                path = doc if not file else os.path.normpath(os.path.join(os.path.dirname(doc), file)).replace(os.sep, "/")
                if not path.endswith(".md") or not repo.exists(path) or repo.is_dir(path):
                    continue
                if path not in cache:
                    cache[path] = anchors(repo.read(path))
                checked += 1
                if anchor not in cache[path]:
                    problems.append(f"{doc}:{number}: links to {target}, and {path} has no heading with that anchor")
    if checked == 0:
        problems.append("no link to a heading was found to check; the reader of links is broken")
    return problems


PATHLIKE = re.compile(r"[\w.-]+(?:/[\w.-]+)+/?")


def docs_named_paths_exist(repo: Repo) -> list[str]:
    """A document named a file in code type that had been moved or deleted."""
    problems, checked = [], 0
    tops = {f.split("/")[0] for f in repo.files}
    try:
        absent = {a["path"]: a for a in load_map(repo.read(MAP_FILE))["absent"]}
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        absent = {}
    mentioned = set()
    for doc in repo.markdown():
        here = os.path.dirname(doc)
        for number, line in prose_lines(repo.read(doc)):
            for span in code_spans(line):
                if not PATHLIKE.fullmatch(span):
                    continue
                own = os.path.normpath(os.path.join(here, span)).replace(os.sep, "/") if here else span
                file_like = re.search(r"\.(py|md|json|toml|ya?ml|tla|cfg|rs|js)$", span) is not None
                if span.split("/")[0] not in tops and not repo.exists(own) and not file_like:
                    continue  # not a path in this repository, e.g. `run.poll` or `vendor/family`
                checked += 1
                if repo.exists(span) or repo.exists(own):
                    continue
                if span in absent:
                    mentioned.add(span)
                    continue
                problems.append(f"{doc}:{number}: names `{span}`, which does not exist. Name a path that exists; if it is meant not to "
                                f"exist yet, the owner lists it under [[absent]] in {MAP_FILE}, with the reason, in a change of its own")
    for path, entry in sorted(absent.items()):
        if repo.exists(path):
            problems.append(f"{MAP_FILE}: {path} is listed as absent but now exists; remove the entry")
        elif path not in mentioned:
            problems.append(f"{MAP_FILE}: {path} is listed as absent but no document names it; remove the entry")
        if len(entry.get("why", "").split()) < 4:
            problems.append(f"{MAP_FILE}: the absent path {path} does not say why it is absent")
    if checked == 0:
        problems.append("no path in code type was found to check; the reader is broken")
    return problems


def docs_protocol_matches_the_schemas(repo: Repo) -> list[str]:
    """A schema, a capability, a kind of message or an error code could be added without the contract documents knowing."""
    problems = []
    readme = repo.read("protocol/README.md")
    guide = repo.read("docs/writing-a-provider.md")
    listed = set()
    for cells in table_rows(readme, "## Schemas"):
        m = re.fullmatch(r"\[([\w.-]+\.schema\.json)\]\(\1\)", cells[0])
        if not m:
            problems.append(f"protocol/README.md: Schemas row {cells[0]!r} is not `[name.schema.json](name.schema.json)`")
            continue
        listed.add(m.group(1))
    present = {f.split("/")[-1] for f in repo.glob("protocol/*.schema.json")}
    for name in sorted(present - listed):
        problems.append(f"protocol/README.md: the Schemas table does not list protocol/{name}")
    for name in sorted(listed - present):
        problems.append(f"protocol/README.md: the Schemas table lists {name}, which is not in protocol/")
    for doc in repo.glob("protocol/*.md"):
        name = doc.split("/")[-1]
        if name != "README.md" and f"]({name}" not in readme:
            problems.append(f"protocol/README.md does not link to {name}")
    common = json.loads(repo.read("protocol/common.schema.json"))["$defs"]
    capabilities = set(common["capability"]["enum"])
    in_table = set()
    for cells in table_rows(readme, "## Capabilities"):
        m = re.fullmatch(r"`([a-z]+\.[a-z]+)`", cells[0])
        if m:
            in_table.add(m.group(1))
        else:
            problems.append(f"protocol/README.md: Capabilities row {cells[0]!r} does not name one capability in code type")
    for cap in sorted(capabilities - in_table):
        problems.append(f"protocol/README.md: the Capabilities table has no row for {cap}, which common.schema.json lists")
    for cap in sorted(in_table - capabilities):
        problems.append(f"protocol/README.md: the Capabilities table has {cap}, which common.schema.json does not list")
    messages = json.loads(repo.read("protocol/messages.schema.json"))
    defs = messages["$defs"]
    for cap in sorted(capabilities):
        for side in ("req", "res"):
            if f"{side}_{cap.replace('.', '_')}" not in defs:
                problems.append(f"protocol/messages.schema.json has no {side}_{cap.replace('.', '_')} for capability {cap}")
    for ref in messages.get("oneOf", []):
        kind = defs[ref["$ref"].split("/")[-1]]["properties"]["type"]["const"]
        if not re.search(rf'"type":\s*"{re.escape(kind)}"', guide):
            problems.append(f"docs/writing-a-provider.md has no worked example of a {kind!r} message, which messages.schema.json defines")
    for code in defs["error"]["properties"]["code"]["enum"]:
        if f"`{code}`" not in guide and f"`{code}`" not in readme:
            problems.append(f"error code {code} is in messages.schema.json and neither protocol/README.md nor docs/writing-a-provider.md explains it")
    return problems


def docs_kit_index_matches_the_kit(repo: Repo) -> list[str]:
    """Files were added to the conformance kit that its index did not list, and a kind of scenario had no rules written."""
    problems = []
    readme = repo.read("conformance/README.md")
    listed = set()
    for cells in table_rows(readme, "## What is here"):
        names = re.findall(r"`([^`]+)`", cells[0])
        if not names:
            problems.append(f"conformance/README.md: 'What is here' row {cells[0]!r} names no path in code type")
        listed.update(names)
    present = set()
    for f in repo.files:
        parts = f.split("/")
        if parts[0] != "conformance" or len(parts) < 3:
            continue
        if parts[1] == "kernel" and len(parts) >= 4:
            present.add(f"kernel/{parts[2]}/")
        else:
            present.add("/".join(parts[1:3]))
    for name in sorted(present - listed):
        problems.append(f"conformance/README.md: 'What is here' does not list `{name}`")
    for name in sorted(listed - present):
        problems.append(f"conformance/README.md: 'What is here' lists `{name}`, which is not in conformance/")
    kinds = {p.split("/")[1] for p in present if p.startswith("kernel/") and p.endswith("/")}
    headings = set(re.findall(r"^### (\w+) scenarios$", readme, flags=re.M))
    for kind in sorted(kinds):
        if kind.capitalize() not in headings:
            problems.append(f"conformance/README.md has no '### {kind.capitalize()} scenarios' section for conformance/kernel/{kind}/")
    for heading in sorted(headings):
        if heading.lower() not in kinds:
            problems.append(f"conformance/README.md has a '### {heading} scenarios' section and no conformance/kernel/{heading.lower()}/")
    return problems


NUMBER_WORDS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen "
                                           "fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}


def docs_counts_match_the_repository(repo: Repo) -> list[str]:
    """Counts in the README and the list of models went stale when scenarios, vectors or models were added."""
    problems = []
    readme = repo.read("README.md")
    scenarios = len(repo.glob("conformance/kernel/*/*.json"))
    vectors = 0
    for name in ("canonical", "paths", "core-key", "core-key-more"):
        data = json.loads(repo.read(f"conformance/vectors/{name}.json"))
        vectors += sum(len(v) for v in data.values() if isinstance(v, list))
    models = sorted(f.split("/")[1] for f in repo.glob("spec/*/expected.json"))
    for pattern, want, what in ((r"(\d+) scenarios", scenarios, "scenarios in conformance/kernel/"),
                                (r"(\d+) encoding, path and key vectors", vectors, "canonical, path and core-key vectors"),
                                (r"(\w+) formal models", len(models), "models with an expected.json in spec/")):
        m = re.search(pattern, readme)
        got = None if not m else int(m.group(1)) if m.group(1).isdigit() else NUMBER_WORDS.get(m.group(1).lower())
        if got != want:
            problems.append(f"README.md: says {m.group(0) if m else 'nothing matching ' + repr(pattern)}; there are {want} {what}")
    spec_readme = repo.read("spec/README.md")
    rows = {re.sub(r"\]\(.*", "", c[0]).strip("[").split("/")[0] for c in table_rows(spec_readme) if c and c[0].startswith("[")}
    for model in models:
        if model not in rows:
            problems.append(f"spec/README.md: the table of models has no row for spec/{model}/")
    for row in sorted(rows - set(models)):
        problems.append(f"spec/README.md: the table of models has a row for {row}/, which has no expected.json")
    return problems


def docs_every_check_is_listed(repo: Repo) -> list[str]:
    """A check whose reason is lost gets deleted by mistake."""
    listed = repo.read("docs/gap-checks.md")
    return [f"docs/gap-checks.md does not list `{c.__name__}`" for c in CHECKS if f"`{c.__name__}`" not in listed]


CHECKS = [docs_map_covers_every_file, docs_usage_matches_the_parser, docs_commands_name_real_flags,
          docs_every_tool_is_listed, docs_decision_index_matches_the_records, docs_links_and_anchors_resolve,
          docs_named_paths_exist, docs_protocol_matches_the_schemas, docs_kit_index_matches_the_kit,
          docs_counts_match_the_repository, docs_every_check_is_listed]


def known_drift(repo: Repo) -> list[dict]:
    try:
        return load_map(repo.read(MAP_FILE))["known"]
    except (FileNotFoundError, tomllib.TOMLDecodeError):
        return []


def run_check(check, repo: Repo, seen: set | None = None) -> list[str]:
    """What a check finds, less drift listed in [[known]] of the map with the reason it cannot be fixed now."""
    try:
        found = check(repo)
    except (OSError, KeyError, ValueError, IndexError, TypeError) as err:
        return [f"could not run: {type(err).__name__}: {err}"]
    known = {k.get("problem") for k in known_drift(repo) if k.get("check") == check.__name__}
    if seen is not None:
        seen.update((check.__name__, p) for p in found if p in known)
    return [p for p in found if p not in known]


def repo_problems(repo: Repo | None = None) -> list[str]:
    repo = repo or Repo(ROOT)
    out, seen = [], set()
    for check in CHECKS:
        out += [f"[{check.__name__}] {p}" for p in run_check(check, repo, seen)]
    for entry in known_drift(repo):
        if (entry.get("check"), entry.get("problem")) not in seen:
            out.append(f"[known] {MAP_FILE}: known drift {entry.get('problem')!r} no longer happens; remove the entry")
        if len(entry.get("why", "").split()) < 8:
            out.append(f"[known] {MAP_FILE}: known drift {entry.get('problem')!r} does not say why it cannot be fixed now")
    return out


# ---------------------------------------------------------------------------
# Judging a change.


def substance(text: str | None) -> str:
    """What is left of a text once spacing and line endings are ignored."""
    return " ".join((text or "").split())


def waivers(messages: list[str]) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Waiver lines: only a line that starts exactly `Docs-unchanged:` is one. Returns the accepted
    waivers, the refused ones (rule id, why refused) and lines that start so and cannot be read.
    A refused or unreadable waiver matters only where a rule needs one; history keeps old mistakes."""
    found, refused, unreadable = {}, {}, []
    for message in messages:
        for line in message.replace("\r\n", "\n").split("\n"):
            if not line.startswith("Docs-unchanged:"):
                continue
            line = line.strip()
            m = WAIVER.fullmatch(line)
            if not m:
                unreadable.append(line)
                continue
            reason = m.group(2).strip()
            if len(reason) < MIN_REASON_CHARS or len(reason.split()) < MIN_REASON_WORDS:
                refused[m.group(1)] = (f"its reason ({reason!r}) is too short: say in at least {MIN_REASON_WORDS} words "
                                       "why no document has to change")
                continue
            found[m.group(1)] = reason
    return found, refused, unreadable


def report_problems(body: str) -> list[str]:
    """A pull request description must say what was verified and what was not (AGENTS.md rule 4)."""
    body = re.sub(r"<!--.*?-->", "", body.replace("\r\n", "\n"), flags=re.S)
    body = re.sub(r"^(```|~~~).*?^\1[^\n]*$", "", body, flags=re.M | re.S)  # a heading in a code block is not one
    problems = []
    for heading in ("## Verified", "## Not verified"):
        m = re.search(rf"^{heading}[ \t]*\n(.*?)(?=^#{{1,2}} |\Z)", body, flags=re.M | re.S)
        content = m.group(1).strip() if m else ""
        if not m:
            problems.append(f"the pull request description has no '{heading}' section")
        elif not re.search(r"\w", content) or re.fullmatch(r"(?i)[\s*_>-]*(todo|tbd|tbc|fixme|xxx|n/?a|\.\.\.|…)[\s*_.!:-]*", content):
            problems.append(f"the '{heading}' section of the pull request description says nothing: "
                            "name each check that ran to completion, or say what did not run or was not finished, and why")
    return problems


def judge_change(changed: list[tuple[str, str]], docs_changed: set[str], messages: list[str],
                 base_map: dict | None, head_map: dict, decisions: dict[str, list[str]] | None = None,
                 head_files: list[str] | None = None) -> tuple[list[str], list[str]]:
    """The rule for a change. `changed` is (status, path) with status A, M or D; `docs_changed` the
    documents whose substance changed. Returns problems and notes. Pure: no git, no files."""
    problems, notes = [], []
    given, refused, unreadable = waivers(messages)
    for line in unreadable:
        notes.append(f"ignored: {line!r} starts like a waiver and is not `Docs-unchanged: <rule id>: <reason>`")
    known = {r["id"] for m in (base_map, head_map) if m for r in m["rule"]}
    for rid in sorted((set(given) | set(refused)) - known):
        notes.append(f"ignored: a waiver names rule {rid!r}, which {MAP_FILE} does not have")
    if base_map is None:
        notes.append(f"the base has no {MAP_FILE}: this change is judged by the map it brings, which a reviewer must read")
    for path in sorted({p for _, p in changed} & set(JUDGING_FILES)):
        problems.append(f"{path}: this change {JUDGING}")
    triggered: dict[str, tuple[dict, list[str]]] = {}
    for status, path in sorted(changed, key=lambda c: c[1]):
        if path.endswith(".md"):
            continue
        found = map_entry(base_map, path) if base_map else []
        if not found:
            found = map_entry(head_map, path)
            if found and found[0][0] == "exempt" and base_map is not None:
                problems.append(f"{path}: the base's {MAP_FILE} does not cover it, and this change exempts it. A file "
                                "new to the map must be bound to a [[rule]]; an exemption is the owner's to merge")
                continue
        if not found:
            if status == "D":
                notes.append(f"{path} was deleted and no rule names it")
            else:
                problems.append(f"{path}: no rule in {MAP_FILE} names the documents that describe it, and it is not exempt")
            continue
        kind, entry = found[0]
        if kind == "exempt":
            continue
        triggered.setdefault(entry["id"], (entry, []))[1].append(path)
    for rid, (entry, paths) in sorted(triggered.items()):
        touched = sorted(set(entry["docs"]) & docs_changed)
        shown = ", ".join(paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")
        if touched:
            notes.append(f"rule {rid}: {shown} changed, and so did {', '.join(touched)}")
        elif rid in given:
            notes.append(f"rule {rid}: {shown} changed with no change to {', '.join(entry['docs'])}. "
                         f"Waived on the author's own word, for the reviewer to judge: {given[rid]}")
        else:
            why = f" The waiver for it was refused: {refused[rid]}." if rid in refused else ""
            problems.append(f"rule {rid}: {shown} changed, and none of {', '.join(entry['docs'])} did. Update the one that "
                            f"describes this change, or, if none needs to, add to a commit message the line "
                            f"`Docs-unchanged: {rid}: <why, in a sentence>`.{why}")
    for rid in sorted((set(given) | set(refused)) & known - set(triggered)):
        notes.append(f"unused: a waiver names rule {rid}, and nothing that rule covers changed")
    if base_map is not None and base_map != head_map:
        for kind in ("rule", "exempt", "absent", "known"):
            before = {json.dumps(e, sort_keys=True) for e in base_map[kind]}
            after = {json.dumps(e, sort_keys=True) for e in head_map[kind]}
            # What an exemption or known drift excuses is its paths or its problem; rewording its reason is not new.
            excused = {"exempt": lambda e: {(p,) for p in e.get("paths", [])},
                       "absent": lambda e: {(e.get("path"),)},
                       "known": lambda e: {(e.get("check"), e.get("problem"))}}.get(kind)
            excused_before = set().union(*(excused(e) for e in base_map[kind])) if excused else set()
            if kind == "exempt" and head_files is not None:
                # Judged by effect: an exemption is new where it exempts a file the base's map did not.
                newly = [f for f in head_files if any(k == "exempt" for k, _ in map_entry(head_map, f))
                         and not any(k == "exempt" for k, _ in map_entry(base_map, f))]
                if newly:
                    problems.append(f"{MAP_FILE}: this change exempts {', '.join(newly[:5])}"
                                    + (f" and {len(newly) - 5} more" if len(newly) > 5 else "")
                                    + ", which its base's map does not. An exemption added by the change it excuses is "
                                    "granting yourself an exception (AGENTS.md rule 8): the owner adds it, in a change of its own "
                                    "or by merging over this failure")
                excused = None
            for e in sorted(after - before):
                if excused and excused(json.loads(e)) - excused_before:
                    problems.append(f"{MAP_FILE}: this change adds or alters [[{kind}]] {e}. An exemption, absent path or known "
                                    "drift added by the change it excuses is granting yourself an exception (AGENTS.md rule 8): "
                                    "the owner adds it, in a change of its own or by merging over this failure")
                elif kind == "rule":
                    problems.append(f"{MAP_FILE}: this change adds or alters [[rule]] {e}: it {JUDGING}")
                else:
                    notes.append(f"{MAP_FILE}: this change adds or alters [[{kind}]] {e}; review it")
            for e in sorted(before - after):
                if kind == "rule":
                    problems.append(f"{MAP_FILE}: this change removes or alters [[rule]] {e}: it {JUDGING}")
                else:
                    notes.append(f"{MAP_FILE}: this change removes or alters [[{kind}]] {e}; "
                                 "files the base's entry covers are still judged by it here")
    for num, governed in sorted((decisions or {}).items()):
        hit = sorted({p for _, p in changed for g in governed if not p.endswith(".md")
                      and (p == g.rstrip("/") or (g.endswith("/") and p.startswith(g)))})
        if hit:
            notes.append(f"decision {num} governs {', '.join(hit[:3])}: check that it still holds")
    return problems, notes


def git(root: pathlib.Path, *args: str, ok_codes=(0,), env: dict | None = None) -> bytes:
    try:
        done = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=root, capture_output=True, env=env)
    except OSError as err:
        raise CannotRun(f"git could not be started: {err}") from err
    if done.returncode not in ok_codes:
        raise CannotRun(f"git {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


USES_LINE = re.compile(r"(\s*(?:-\s+)?uses:\s*)([\w.-]+/[\w./-]+)@([\w.-]+)(\s+#\s*[\w. -]+)?\s*")
RUNNER_LINE = re.compile(r"(\s*(?:-\s+)?(?:runs-on|os):\s*|\s*if:\s*matrix\.os\s*==\s*')"
                         r"(ubuntu|windows|macos)-([0-9][0-9.]*)('?)\s*")


def _same_pin(old: str, new: str) -> bool:
    """Whether two lines pin the same thing at another version: the same action from the same owner
    and repository with only its ref and version comment changed, or the same kind of runner of the same
    system with only its version changed."""
    a, b = USES_LINE.fullmatch(old), USES_LINE.fullmatch(new)
    if a and b:
        # The new version is a full commit, never a branch or tag that can move after review.
        return a.group(1) == b.group(1) and a.group(2) == b.group(2) and not a.group(2).startswith(".") \
            and re.fullmatch(r"[0-9a-f]{40}", b.group(3)) is not None
    a, b = RUNNER_LINE.fullmatch(old), RUNNER_LINE.fullmatch(new)
    return bool(a and b) and (a.group(1), a.group(2), a.group(4)) == (b.group(1), b.group(2), b.group(4))


def pin_lines_only(paths: list[str], patch: str) -> bool:
    """Whether a change only moves pinned versions in workflows: what an automatic update of pinned
    versions changes, and nothing a document describes. Each removed line must be replaced, in the same
    place, by one line pinning the same thing at another version; no line is only added or only removed."""
    if not paths or any(not re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", p) for p in paths):
        return False
    hunks: list[tuple[list[str], list[str]]] = []
    with_hunks: set[str] = set()
    current = None
    header = False  # between a file's `diff` line and its first hunk, where `---` and `+++` name the file
    for line in patch.replace("\r\n", "\n").split("\n"):
        if line.startswith("diff --git a/"):
            rest = line[len("diff --git a/"):]
            half = (len(rest) - 3) // 2  # without renames both names are the same: a/P b/P
            if rest[half:half + 3] != " b/" or rest[:half] != rest[half + 3:]:
                return False
            current, header = rest[:half], True
        elif line.startswith(("diff ", "Binary files ", "GIT binary patch")):
            return False  # another kind of diff, or bytes no line can show
        elif line.startswith("@@"):
            if current is None:
                return False
            header = False
            with_hunks.add(current)
            hunks.append(([], []))
        elif header:
            if line.startswith(("new file", "deleted file", "rename", "similarity", "old mode", "new mode", "copy ")):
                return False
        elif line[:1] in ("+", "-"):
            if not hunks:
                return False
            hunks[-1][0 if line[0] == "-" else 1].append(line[1:])
    if set(paths) != with_hunks:
        return False  # every changed file must show its change as lines
    return bool(hunks) and all(len(old) == len(new) and old and all(_same_pin(o, n) for o, n in zip(old, new))
                               for old, new in hunks)


def workflow_jobs(text: str) -> set[str]:
    """The ids and names of a workflow's jobs, read from the block under its top-level `jobs:`. A required
    check is matched by name, so these are what another workflow could take over. A name GitHub would
    compute (one holding `${{`) or one written as a block (`>` or `|`) is kept as written, so that
    job_clashes can treat it as able to be anything its fixed parts allow."""
    found, inside, job_indent, key_indent, pending = set(), False, None, None, None
    for line in text.replace("\r\n", "\n").split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if pending is not None and (indent == 0 or not inside):
            found.add(pending)
            pending = None
        if indent == 0:
            inside = re.fullmatch(r"([\"']?)jobs\1\s*:\s*(#.*)?", line.rstrip()) is not None
            job_indent = key_indent = None
            continue
        if not inside:
            continue
        if job_indent is None:
            job_indent = indent
        if indent == job_indent:
            m = re.fullmatch(r"\s*([\"']?)([^\"':#]+)\1\s*:\s*(#.*)?", line)
            if m:
                found.add(m.group(2).strip())
            key_indent = None
            continue
        if key_indent is None:
            key_indent = indent
        if pending is not None:
            # A plain or quoted name may go on over the next, deeper lines: it cannot be read here.
            found.add(">" if indent > key_indent and not re.match(r"\s*[\w\"'-]+\s*:", line) else pending)
            pending = None
        m = re.fullmatch(r"\s*([\"']?)name\1\s*:\s*(.*)", line)
        if indent == key_indent and m:
            value = m.group(2).strip()
            if value[:1] in ("\"", "'"):
                end = value.find(value[0], 1)
                value = value[1:end] if end > 0 else ">"
            else:
                value = re.split(r"\s#", value, maxsplit=1)[0].strip()
            pending = value
    if pending is not None:
        found.add(pending)
    return found


def could_be(written: str, name: str) -> bool:
    """Whether a job name as written could be shown as `name`: exactly, or, when GitHub computes it or it is
    a block, by any text in the places it does not fix."""
    if written.startswith((">", "|")):
        return True
    if "${{" not in written:
        # GitHub adds a matrix job's values after a plain name, in brackets.
        return written == name or name.startswith(written + " (")
    parts = re.split(r"\$\{\{.*?\}\}", written)
    return re.fullmatch(".*".join(re.escape(p) for p in parts), name, flags=re.S) is not None


WRITES_STATUS = re.compile(r"""\b(checks|statuses)["']?\s*:\s*["']?write\b|\bwrite-all\b""")
# YAML this check does not read: anchors, aliases, tags and merge keys can carry a name or a permission anywhere.
UNREAD_YAML = re.compile(r"""(^|[\s\[{,:-])&[\w-]+|(:|-|\[|\{|,)\s*\*[\w-]+|!!|(:\s*)![\w]|<<\s*:""", re.M)


def job_clashes(workflows: dict[str, str], own: str, names: set[str]) -> list[str]:
    """Other workflows that define a job that could be shown under one of `names`, or whose token could post a
    check or a status of any name. The repository's default token can only read, so a workflow needs one of
    these permissions written out to post one."""
    found = []
    for path, text in sorted(workflows.items()):
        if path == own:
            continue
        for written in sorted(workflow_jobs(text)):
            for name in sorted(names):
                if could_be(written, name):
                    found.append(f"{path} defines a job {written!r} that could be shown as {name!r}, as {own} names its job: "
                                 "a required check of that name could be passed by it")
        if WRITES_STATUS.search(text):
            found.append(f"{path} gives its token permission to post checks or statuses: it could post one named as {own}'s job")
        if UNREAD_YAML.search(text):
            found.append(f"{path} uses YAML anchors, aliases, tags or merge keys, which this check does not read: "
                         "a job name or a permission could hide in them")
    return found


def head_workflows(root: pathlib.Path, head: str) -> dict[str, str]:
    listing = git(root, "ls-tree", "-r", "--name-only", "-z", head, ".github/workflows/").decode("utf-8").split("\0")
    return {p: git(root, "show", f"{head}:{p}").decode("utf-8", "replace") for p in listing
            if re.fullmatch(r"\.github/workflows/[^/]+\.ya?ml", p)}


def pins_only(root: pathlib.Path, base: str, head: str, env: dict | None = None) -> bool:
    merge_base = git(root, "merge-base", base, head, env=env).decode().strip()
    names = git(root, "diff", "--no-renames", "--name-only", "-z", merge_base, head, env=env).decode("utf-8").split("\0")
    patch = git(root, "diff", "--no-renames", "-U0", "--no-color", merge_base, head, env=env).decode("utf-8", "replace")
    return pin_lines_only([n for n in names if n], patch)


def diff(root: pathlib.Path, base: str, head: str | None, pr_body: str | None,
         env: dict | None = None) -> tuple[list[str], list[str]]:
    for rev in (base, head):
        if rev is not None and (not rev.strip() or re.fullmatch(r"0+", rev)):
            raise CannotRun(f"no usable revision given ({rev!r})")
    head_rev = head or "HEAD"

    def git(root, *args):  # noqa: F811 - the module's git, with this call's environment
        return globals()["git"](root, *args, env=env)

    for rev, what in ((base, "base"), (head_rev, "head")):
        try:
            git(root, "rev-parse", "--verify", "--quiet", rev + "^{commit}")
        except CannotRun:
            raise CannotRun(f"the {what} {rev} is not in this repository's history. If the branch was force-pushed, "
                            "the commits it replaced are gone and the change cannot be judged: judge it by hand") from None
    try:
        merge_base = git(root, "merge-base", base, head_rev).decode().strip()
    except CannotRun:
        merge_base = ""
    if not merge_base:
        raise CannotRun(f"{base} and {head_rev} have no common ancestor, so there is no change to judge")
    names = git(root, "diff", "--no-renames", "--name-status", "-z", merge_base, *([head] if head else []))
    fields = names.decode("utf-8").split("\0")
    changed = [(fields[i][0], fields[i + 1]) for i in range(0, len(fields) - 1, 2)]
    if head is None:
        extra = git(root, "ls-files", "-z", "-o", "--exclude-standard").decode("utf-8").split("\0")
        changed += [("A", n) for n in extra if n]

    def at(rev: str | None, path: str) -> str | None:
        if rev is None:
            p = root / path
            return p.read_bytes().decode("utf-8", "replace") if p.is_file() else None
        out = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, env=env)
        return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None

    # A document deleted or renamed away is not a document brought up to date: it must still be there.
    def regular_at_head(path: str) -> bool:
        if head is None:
            p = root / path
            return p.is_file() and not p.is_symlink()
        listed = git(root, "ls-tree", head_rev, "--", path).decode("utf-8", "replace").split()
        return bool(listed) and listed[0] in ("100644", "100755")

    # A document deleted, renamed away, emptied or replaced by a link is not a document brought up to date.
    docs_changed = {p for _, p in changed if p.endswith(".md") and at(head, p) is not None and regular_at_head(p)
                    and substance(at(head, p)).strip() and substance(at(merge_base, p)) != substance(at(head, p))}
    log = git(root, "log", "--format=%B%x00", f"{merge_base}..{head_rev}").decode("utf-8", "replace")
    messages = [m for m in log.split("\0") if m.strip()]
    head_text = at(head, MAP_FILE)
    if head_text is None:
        raise CannotRun(f"{MAP_FILE} does not exist in the change")
    base_text = at(base, MAP_FILE)
    try:
        head_map = load_map(head_text)
        base_map = load_map(base_text) if base_text is not None else None
    except tomllib.TOMLDecodeError as err:
        raise CannotRun(f"{MAP_FILE} cannot be read: {err}") from err
    decisions = {}
    head_repo = Repo(root) if head is None else None
    listing = git(root, "ls-tree", "-r", "--name-only", "-z", head_rev, "decisions/").decode("utf-8").split("\0")
    for path in listing:
        if re.fullmatch(r"decisions/\d{4}-[\w-]+\.md", path or ""):
            text = head_repo.read(path) if head_repo and head_repo.exists(path) else at(head_rev, path)
            decisions[path.split("/")[1][:4]] = front_matter(text or "").get("governs", [])
    head_files = [f for f in git(root, "ls-tree", "-r", "--name-only", "-z", head_rev).decode("utf-8").split("\0") if f]
    if head is None:
        head_files = Repo(root).files
    problems, notes = judge_change(changed, docs_changed, messages, base_map, head_map, decisions, head_files)
    if pr_body is not None:
        problems += report_problems(pr_body)
    return problems, notes


# ---------------------------------------------------------------------------
# The self-test: every check must be seen to fail.


def _edit(repo: Repo, path: str, old: str, new: str) -> dict:
    text = repo.read(path)
    if old not in text:
        raise AssertionError(f"self-test: {path} no longer contains {old!r}; update the planted fault")
    return {path: text.replace(old, new, 1)}


def planted_faults(repo: Repo) -> list[tuple[object, str, dict]]:
    """(check, what is planted, the edit). Each edit is made to the real files, in memory."""
    first_tool = repo.glob("tools/host.py")[0]
    return [
        (docs_map_covers_every_file, "a new tool no rule covers", {"tools/new_helper.py": '"""x"""\n'}),
        (docs_map_covers_every_file, "a rule naming a document that does not exist",
         _edit(repo, MAP_FILE, 'docs = ["conformance/README.md"', 'docs = ["conformance/MISSING.md"')),
        (docs_map_covers_every_file, "a rule whose pattern matches nothing",
         _edit(repo, MAP_FILE, '"tools/host.py"', '"tools/host.py", "tools/no_such_tool.py"')),
        (docs_usage_matches_the_parser, "a new flag the usage line does not show",
         _edit(repo, "tools/status.py", 'ap.add_argument("--json", action="store_true")',
               'ap.add_argument("--json", action="store_true")\n    ap.add_argument("--since")')),
        (docs_usage_matches_the_parser, "a flag removed from the parser and still shown",
         _edit(repo, "tools/status.py", 'ap.add_argument("--json", action="store_true")', 'pass')),
        (docs_usage_matches_the_parser, "a new subcommand the usage lines do not show",
         _edit(repo, first_tool, 'two = sub.add_parser("conclude")', 'sub.add_parser("replan")\n    two = sub.add_parser("conclude")')),
        (docs_usage_matches_the_parser, "a flag built at run time",
         _edit(repo, "tools/status.py", 'ap.add_argument("--json", action="store_true")',
               'ap.add_argument("--" + str(len("json")), action="store_true")')),
        (docs_commands_name_real_flags, "a workflow using a flag the tool does not have",
         _edit(repo, ".github/workflows/checks.yml", "tools/kernel_differential.py --rounds", "tools/kernel_differential.py --round")),
        (docs_commands_name_real_flags, "a document naming a subcommand the tool does not have",
         {"docs/probe.md": "Run `tools/host.py replan --out x` first.\n"}),
        (docs_commands_name_real_flags, "a document naming a tool that is gone",
         {"docs/probe.md": "Run `python tools/gone_tool.py` first.\n"}),
        (docs_every_tool_is_listed, "a tool with no row", {"tools/new_helper.py": '"""x"""\n'}),
        (docs_every_tool_is_listed, "a row for a tool that is gone", {"tools/keep.py": None}),
        (docs_decision_index_matches_the_records, "an index title that differs from the record",
         _edit(repo, "decisions/README.md", "| Decisions are first-class nodes |", "| Decisions are nodes |")),
        (docs_decision_index_matches_the_records, "an owner-direction record shown without it",
         _edit(repo, "decisions/README.md", "| Decisions are first-class nodes | proposed, owner direction |",
               "| Decisions are first-class nodes | proposed |")),
        (docs_decision_index_matches_the_records, "an amended record that does not link back",
         _edit(repo, "decisions/0024-separation-is-graded-not-enforced.md",
               "0031-an-agreement-after-a-real-change-keeps-its-grade-up-to-a-limit.md", "0031.md")),
        (docs_decision_index_matches_the_records, "a governed path that does not exist",
         _edit(repo, "decisions/0026-the-first-host-and-status-are-stage-0-helpers.md", "  - tools/host.py\n", "  - tools/hosts.py\n")),
        (docs_decision_index_matches_the_records, "a mention of a decision that does not exist",
         {"docs/probe.md": "As decision " + "0999 says.\n"}),  # split so this line does not name it
        (docs_links_and_anchors_resolve, "a heading renamed under its links",
         _edit(repo, "ARCHITECTURE.md", "## 6. Reproducibility", "## 6. Reproducing results")),
        (docs_named_paths_exist, "a document naming a file that is gone", {"docs/probe.md": "See `tools/gone_tool.py`.\n"}),
        (docs_named_paths_exist, "an absent path that now exists", {"records/owner.ledger": "x\n"}),
        (docs_named_paths_exist, "a file under a top-level directory that is gone",
         {"docs/probe.md": "See `olddir/tool.py`.\n"}),
        (docs_protocol_matches_the_schemas, "a schema the table does not list", {"protocol/new.schema.json": "{}\n"}),
        (docs_protocol_matches_the_schemas, "a capability with no row",
         _edit(repo, "protocol/common.schema.json", '"store.blob"', '"store.blob", "store.list"')),
        (docs_protocol_matches_the_schemas, "a message kind with no worked example",
         _edit(repo, "docs/writing-a-provider.md", '{"type":"shutdown"}', '{"type": "stop"}')),
        (docs_kit_index_matches_the_kit, "a kit file the index does not list", {"conformance/vectors/new.json": "{}\n"}),
        (docs_kit_index_matches_the_kit, "a kind of scenario with no section",
         _edit(repo, "conformance/README.md", "### Acts scenarios", "### Act scenarios")),
        (docs_counts_match_the_repository, "a scenario added and not counted",
         {"conformance/kernel/acts/zz-probe.json": "{}\n"}),
        (docs_counts_match_the_repository, "a model added and not counted",
         {"spec/probe/expected.json": '{"cases": []}\n'}),
        (docs_every_check_is_listed, "a check missing from docs/gap-checks.md",
         _edit(repo, "docs/gap-checks.md", "`docs_counts_match_the_repository`", "`docs_counts`")),
    ]


# What each planted fault must be reported as, so that a check cannot pass the self-test by failing
# for some other reason.
EXPECTED = {
    "a new tool no rule covers": "tools/new_helper.py: no rule",
    "a rule naming a document that does not exist": "names conformance/MISSING.md",
    "a rule whose pattern matches nothing": "pattern tools/no_such_tool.py matches no file",
    "a new flag the usage line does not show": "flag --since of `status.py` is not shown",
    "a flag removed from the parser and still shown": "shows flag --json, which the tool does not define",
    "a new subcommand the usage lines do not show": "subcommand 'replan' is not shown",
    "a flag built at run time": "cannot be read without running the tool",
    "a workflow using a flag the tool does not have": "checks.yml:",
    "a document naming a subcommand the tool does not have": "has no subcommand 'replan'",
    "a document naming a tool that is gone": "names tools/gone_tool.py, which does not exist",
    "a tool with no row": "does not list tools/new_helper.py",
    "a row for a tool that is gone": "lists keep.py, which is not in tools/",
    "an index title that differs from the record": "the title of 0001 reads",
    "an owner-direction record shown without it": "the status of 0001 reads 'proposed'",
    "an amended record that does not link back": "is amended by 0031",
    "a governed path that does not exist": "governs tools/hosts.py",
    "a mention of a decision that does not exist": "names decision " "0999",  # split so this line does not name it
    "a heading renamed under its links": "#6-reproducibility",
    "a document naming a file that is gone": "names `tools/gone_tool.py`",
    "an absent path that now exists": "records/owner.ledger is listed as absent but now exists",
    "a file under a top-level directory that is gone": "names `olddir/tool.py`",
    "a schema the table does not list": "does not list protocol/new.schema.json",
    "a capability with no row": "no row for store.list",
    "a message kind with no worked example": "worked example of a 'shutdown' message",
    "a kit file the index does not list": "does not list `vectors/new.json`",
    "a kind of scenario with no section": "no '### Acts scenarios' section",
    "a scenario added and not counted": "scenarios in conformance/kernel/",
    "a model added and not counted": "models with an expected.json in spec/",
    "a check missing from docs/gap-checks.md": "does not list `docs_counts_match_the_repository`",
}


def _diff_cases(doc_map: dict) -> list[tuple[str, str | None, tuple]]:
    """(what, None if it must pass or what it must be reported as, arguments of judge_change)."""
    reason = "only a comment was reworded, and no behaviour or flag changed at all"
    host_docs = next(r for r in doc_map["rule"] if "tools/host.py" in r["code"])["docs"]
    exempting = {**doc_map, "rule": [r for r in doc_map["rule"] if "tools/host.py" not in r["code"]],
                 "exempt": doc_map["exempt"] + [{"paths": ["tools/host.py"], "why": "planted by the self-test"}]}
    host = [("M", "tools/host.py")]
    missing = "rule host: tools/host.py changed, and none of"
    return [
        ("code changed, no document", missing, (host, set(), [], doc_map, doc_map)),
        ("code changed with its document", None, (host, {host_docs[0]}, [], doc_map, doc_map)),
        ("code changed, an unrelated document", missing, (host, {"CONTRIBUTING.md"}, [], doc_map, doc_map)),
        ("code changed, waived with a reason", None, (host, set(), [f"Fix\n\nDocs-unchanged: host: {reason}\n"], doc_map, doc_map)),
        ("waived with too short a reason", "is too short", (host, set(), ["Docs-unchanged: host: typo"], doc_map, doc_map)),
        ("waived for a rule that does not exist", None,
         (host, {host_docs[0]}, [f"Docs-unchanged: nosuchrule: {reason}"], doc_map, doc_map)),
        ("waived for a rule nothing triggered", None,
         (host, {host_docs[0]}, [f"Docs-unchanged: encoding: {reason}"], doc_map, doc_map)),
        ("a waiver for a rule that does not exist does not waive another", missing,
         (host, set(), [f"Docs-unchanged: hosts: {reason}"], doc_map, doc_map)),
        ("a waiver line written wrongly", missing, (host, set(), [f"Docs-Unchanged host because {reason}"], doc_map, doc_map)),
        ("a waiver not at the start of its line", missing, (host, set(), [f"see: Docs-unchanged: host: {reason}"], doc_map, doc_map)),
        ("old mistakes in history, where no waiver is needed", None,
         ([("M", "README.md")], {"README.md"}, ["Docs-unchanged: host: typo", "Docs unchanged on purpose",
                                                "Docs-unchanged: host"], doc_map, doc_map)),
        ("a new file no rule covers", "newdir/tool.py: no rule", ([("A", "newdir/tool.py")], set(), [], doc_map, doc_map)),
        ("an exemption added in the same change", missing, (host, set(), [], doc_map, exempting)),
        ("a new file exempted by the change that adds it", "this change exempts it",
         ([("A", "newdir/tool.py")], set(), [], doc_map,
          {**doc_map, "exempt": doc_map["exempt"] + [{"paths": ["newdir/*"], "why": "planted by the self-test"}]})),
        ("an exemption's reason reworded", None,
         ([("M", "README.md")], {"README.md"}, [], doc_map,
          {**doc_map, "exempt": [{**e, "why": e["why"] + " Reworded."} for e in doc_map["exempt"]]})),
        ("an exemption narrowed, judged by the files it exempts", None,
         ([("M", "README.md")], {"README.md"}, [], doc_map,
          {**doc_map, "exempt": [{**e, "paths": [p for p in e["paths"] if not p.endswith(".exit")]} for e in doc_map["exempt"]]},
          None, ["spec/runs/r/a.txt", "spec/runs/r/a.exit", "tools/host.py"])),
        ("an exemption widened, judged by the files it exempts", "this change exempts tools/host.py",
         ([("M", "README.md")], {"README.md"}, [], doc_map,
          {**doc_map, "exempt": [{**e, "paths": e["paths"] + ["tools/h*.py"]} for e in doc_map["exempt"]]},
          None, ["spec/runs/r/a.txt", "tools/host.py"])),
        ("the checker changed", "tools/check_docs.py: this change changes how changes are judged",
         ([("M", "tools/check_docs.py")], {"docs/gap-checks.md"}, [], doc_map, doc_map)),
        ("the workflow that runs the checker changed", ".github/workflows/docs.yml: this change changes how",
         ([("M", ".github/workflows/docs.yml")], {"docs/gap-checks.md"}, [], doc_map, doc_map)),
        ("a rule added", "adds or alters [[rule]]",
         ([("M", "README.md")], {"README.md"}, [], doc_map,
          {**doc_map, "rule": doc_map["rule"] + [{"id": "probe", "code": ["newdir/*"], "docs": ["README.md"], "why": "x"}]})),
        ("a rule removed", "removes or alters [[rule]]",
         ([("M", "README.md")], {"README.md"}, [], doc_map,
          {**doc_map, "rule": [r for r in doc_map["rule"] if r["id"] != "encoding"]})),
        ("a rule's documents changed", "alters [[rule]]",
         ([("M", "README.md")], {"README.md"}, [], doc_map,
          {**doc_map, "rule": [{**r, "docs": r["docs"] + ["README.md"]} if r["id"] == "host" else r for r in doc_map["rule"]]})),
        ("an absent path added by the change that names it", "adds or alters [[absent]]",
         ([("M", "README.md")], {"README.md"}, [], doc_map,
          {**doc_map, "absent": doc_map["absent"] + [{"path": "tools/gone.py", "why": "planted by the self-test"}]})),
        ("known drift added by the change it excuses", "adds or alters [[known]]",
         ([("M", "README.md")], {"README.md"}, [], doc_map,
          {**doc_map, "known": doc_map["known"] + [{"check": "x", "problem": "y", "why": "planted by the self-test"}]})),
        ("a rule of the change applies to a file new to it", "rule probe: newdir/tool.py changed",
         ([("A", "newdir/tool.py")], set(), [], doc_map,
          {**doc_map, "rule": doc_map["rule"] + [{"id": "probe", "code": ["newdir/*.py"], "docs": ["README.md"], "why": "x"}]})),
        ("a document alone", None, ([("M", "README.md")], {"README.md"}, [], doc_map, doc_map)),
    ]


def _git_case(problems: list[str]) -> None:
    """A throwaway repository judged end to end, through git."""
    if not shutil.which("git"):
        problems.append("self-test: git is not available, so the end-to-end case could not run (this is not a pass)")
        return
    # Nothing of the caller's git environment reaches the throwaway repository: run from a hook or
    # `rebase --exec`, GIT_DIR or GIT_INDEX_FILE would otherwise point these commands at the real one.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
                "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1"})

    def judge(*args):
        return diff(*args, env=env)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)

            def run(*args):
                git(root, "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false",
                    "-c", f"core.hooksPath={root / 'no-hooks'}", *args, env=env)

            def write(rel, text):
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                (root / rel).write_bytes(text.encode("utf-8"))

            run("init", "-q", "-b", "main")
            write(MAP_FILE, '[[rule]]\nid = "a"\ncode = ["src/a.py"]\ndocs = ["docs/a.md"]\nwhy = "the guide describes it"\n')
            write("src/a.py", "x = 1\n")
            write("docs/a.md", "# A\n\nx is one.\n")
            run("add", "-A")
            run("commit", "-q", "-m", "start")
            base = git(root, "rev-parse", "HEAD", env=env).decode().strip()
            run("checkout", "-q", "-b", "work")
            write("src/a.py", "x = 2\n")
            write("docs/a.md", "# A\r\n\r\nx is one.\r\n")  # only line endings: not a change of substance
            run("add", "-A")
            run("commit", "-q", "-m", "change x")
            found, _ = judge(root, base, "HEAD", None)
            if not any("rule a:" in p for p in found):
                problems.append(f"self-test: a code change with only line endings changed in its document passed end to end: {found}")
            run("checkout", "-q", "-b", "gone", base)
            write("src/a.py", "x = 3\n")
            (root / "docs" / "a.md").unlink()
            run("add", "-A")
            run("commit", "-q", "-m", "change x, delete its guide")
            found, _ = judge(root, base, "HEAD", None)
            if not any("rule a:" in p for p in found):
                problems.append(f"self-test: a code change whose document was deleted passed as if the document were updated: {found}")
            for how in ("emptied", "replaced by a link"):
                run("checkout", "-q", "-B", "gone", base)
                write("src/a.py", "x = 4\n")
                (root / "docs" / "a.md").unlink()
                if how == "emptied":
                    write("docs/a.md", "")
                else:
                    try:
                        os.symlink("../README", root / "docs" / "a.md")
                    except (OSError, NotImplementedError):
                        continue  # this system cannot make links; the emptied case still runs
                run("add", "-A")
                run("commit", "-q", "-m", f"change x, guide {how}")
                found, _ = judge(root, base, "HEAD", None)
                if not any("rule a:" in p for p in found):
                    problems.append(f"self-test: a code change whose document was {how} passed as if the document were updated: {found}")
            run("checkout", "-q", "work")
            write("docs/a.md", "# A\n\nx is two.\n")
            found, _ = judge(root, base, None, "## Verified\n\nself-test ran.\n\n## Not verified\n\nnothing else here.\n")
            if found:
                problems.append(f"self-test: an uncommitted document change in the working tree was not seen: {found}")
            run("checkout", "-q", "--", "docs/a.md")
            run("commit", "-q", "--allow-empty", "-m", "x\n\nDocs-unchanged: a: the value is internal and no document states it anywhere")
            found, notes = judge(root, base, "HEAD", "no sections")
            if [p for p in found if "rule a" in p] or not any("author's own word" in n for n in notes):
                problems.append(f"self-test: a waiver in a commit message was not honoured and shown: {found} {notes}")
            if not any("Verified" in p for p in found):
                problems.append("self-test: a pull request description without its report passed")
            try:
                judge(root, "0" * 40, "HEAD", None)
                problems.append("self-test: a base of zeros was judged instead of refused")
            except CannotRun as err:
                if "no usable revision" not in str(err):
                    problems.append(f"self-test: a base of zeros was refused without saying so: {err}")
            try:
                judge(root, "1" * 40, "HEAD", None)
                problems.append("self-test: a base missing from the history (a force-push) was judged instead of refused")
            except CannotRun as err:
                if "not in this repository's history" not in str(err):
                    problems.append(f"self-test: a base missing from the history was refused without saying so: {err}")
            # A change that moves its own file from a rule to an exemption is still judged by the base's rule.
            run("checkout", "-q", "-b", "loosen", base)
            write(MAP_FILE, '[[exempt]]\npaths = ["src/a.py"]\nwhy = "the change exempts its own file"\n')
            write("src/a.py", "x = 3\n")
            run("add", "-A")
            run("commit", "-q", "-m", "exempt a")
            found, _ = judge(root, base, "HEAD", None)
            if not any("rule a:" in p for p in found):
                problems.append(f"self-test: a change was judged by the map it brings, not by its base's: {found}")
            # Only lines pinning actions and runner images: what an automatic update changes.
            run("checkout", "-q", "-b", "pins", base)
            workflow = ".github/workflows/w.yml"
            write(workflow, "jobs:\n  a:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: a/b@1111 # v1\n      - run: x\n")
            run("add", "-A")
            run("commit", "-q", "-m", "workflow")
            pinned = git(root, "rev-parse", "HEAD", env=env).decode().strip()
            write(workflow, "jobs:\n  a:\n    runs-on: ubuntu-26.04\n    steps:\n      - uses: a/b@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb # v2\n      - run: x\n")
            run("commit", "-q", "-am", "bump")
            if not pins_only(root, pinned, "HEAD", env=env):
                problems.append("self-test: a change of pinned versions only was not recognised as one")
            write(workflow, "jobs:\n  a:\n    runs-on: ubuntu-26.04\n    steps:\n      - uses: a/b@2222 # v2\n      - run: y\n")
            run("commit", "-q", "-am", "more")
            if pins_only(root, pinned, "HEAD", env=env):
                problems.append("self-test: a change of a command was taken for a change of pinned versions")
    except CannotRun as err:
        problems.append(f"self-test: the end-to-end case could not run: {err}")


def self_test(repo: Repo | None = None, with_git: bool = True) -> list[str]:
    """With with_git False the end-to-end case, which starts git some forty times, is left out:
    tools/check_repo.py runs the rest, and CI runs the whole self-test as a step of its own."""
    repo = repo or Repo(ROOT)
    problems = []
    for check in CHECKS:
        if run_check(check, repo):
            problems.append(f"self-test: {check.__name__} is not clean on the repository as it is, so a planted fault proves nothing")
    try:
        faults = planted_faults(repo)
    except AssertionError as err:
        return problems + [str(err)]
    for check, what, edit in faults:
        planted = repo.changed(edit)
        if all(repo.exists(p) and planted.exists(p) and planted.read(p) == repo.read(p) for p in edit):
            problems.append(f"self-test: planting {what!r} changed nothing")
            continue
        found = run_check(check, planted)
        if what not in EXPECTED or not any(EXPECTED[what] in p for p in found):
            problems.append(f"self-test: {check.__name__} did not report {what} as {EXPECTED.get(what)!r}; it gave {found or 'nothing'}")
    gone = repo.changed({MAP_FILE: repo.read(MAP_FILE) + '\n[[known]]\ncheck = "docs_every_tool_is_listed"\n'
                         'problem = "tools/README.md lists nothing.py, which is not in tools/"\n'
                         'why = "planted by the self-test: drift that does not happen must not be listed"\n'})
    if not any(p.startswith("[known]") for p in repo_problems(gone)):
        problems.append("self-test: a [[known]] entry for drift that does not happen was not reported")
    tested = {c for c, _, _ in faults}
    for check in CHECKS:
        if check not in tested:
            problems.append(f"self-test: {check.__name__} has no planted fault")
    doc_map = load_map(repo.read(MAP_FILE))
    for what, expect, args in _diff_cases(doc_map):
        found, _ = judge_change(*args)
        if (expect is None and found) or (expect is not None and not any(expect in p for p in found)):
            problems.append(f"self-test: diff case {what!r} gave {found or 'a pass'}, not {expect or 'a pass'}")
    for body, should_pass in (("## Verified\n\nRan tools/check_repo.py to the end: passed.\n\n## Not verified\n\nThe model checks did not run.\n", True),
                              ("## Verified\n\n<!-- what ran -->\n\n## Not verified\n\nNothing.\n", False),
                              ("## Verified\n\nTODO\n\n## Not verified\n\nThe model checks.\n", False),
                              ("## Verified\n\nRan tools/check_repo.py: passed.\n\n## Not verified\n\nNothing.\n", True),
                              ("## Verified\n\nRan tools/check_repo.py: passed.\n\n## Not verified\n\nNone\n", True),
                              ("## Verified\n\nTBD.\n\n## Not verified\n\nNone\n", False),
                              ("## Verified\n\n## Not verified\n\nNone\n", False),
                              ("Fixes a typo.\n\n```\n## Verified\n\nall of it\n\n## Not verified\n\nnone\n```\n", False),
                              ("Fixes a typo.", False)):
        if (not report_problems(body)) != should_pass:
            problems.append(f"self-test: the pull request report rule gave the wrong answer for {body!r}")
    wf = [".github/workflows/checks.yml"]

    def h(body: str, path: str = wf[0], extra: str = "") -> str:  # a file's diff header, then its hunks
        return f"diff --git a/{path} b/{path}\n{extra}index 1..2 100644\n--- a/{path}\n+++ b/{path}\n" + body

    bump = "@@ -1 +1 @@\n-      - uses: a/b@1111 # v1\n+      - uses: a/b@bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb # v2\n"
    other = ".github/workflows/models.yml"
    for what, paths, patch, want in (
            ("an action's ref and version comment", wf, h(bump), True),
            ("runner versions in a matrix and a condition", wf,
             h("@@ -3 +3 @@\n-          - os: ubuntu-24.04\n+          - os: ubuntu-26.04\n"
               "@@ -9 +9 @@\n-        if: matrix.os == 'ubuntu-24.04'\n+        if: matrix.os == 'ubuntu-26.04'\n"), True),
            ("pins in two workflows", wf + [other], h(bump) + h(bump, other), True),
            ("a new step using an action", wf, h("@@ -4,0 +5 @@\n+      - uses: a/b@2222 # v2\n"), False),
            ("the action of another owner", wf, h("@@ -1 +1 @@\n-      - uses: a/b@1111\n+      - uses: evil/b@2222\n"), False),
            ("one system for another", wf, h("@@ -2 +2 @@\n-    runs-on: ubuntu-24.04\n+    runs-on: windows-2025\n"), False),
            ("a deleted condition", wf, h("@@ -9 +8,0 @@\n-        if: matrix.os == 'ubuntu-24.04'\n"), False),
            ("a self-hosted runner", wf, h("@@ -2 +2 @@\n-    runs-on: ubuntu-24.04\n+    runs-on: self-hosted\n"), False),
            ("a local action", wf, h("@@ -1 +1 @@\n-      - uses: ./act@1\n+      - uses: ./act@2\n"), False),
            ("a runner from an expression", wf, h("@@ -2 +2 @@\n-    runs-on: ubuntu-24.04\n+    runs-on: ${{ inputs.os }}\n"), False),
            ("a command", wf, h("@@ -7 +7 @@\n-        run: python3 tools/check_repo.py\n+        run: true\n"), False),
            ("a changed indentation", wf, h("@@ -1 +1 @@\n-      - uses: a/b@1111 # v1\n+        - uses: a/b@2222 # v2\n"), False),
            ("a mode change beside a pin bump", wf, h(bump, extra="old mode 100644\nnew mode 100755\n"), False),
            ("a changed file with no lines shown", wf + [other], h(bump) + h("", other), False),
            ("a binary file", wf, f"diff --git a/{wf[0]} b/{wf[0]}\nindex 1..2 100644\nBinary files a/{wf[0]} and b/{wf[0]} differ\n", False),
            ("hunks with no file header", wf, bump, False),
            ("a binary note after a pin bump", wf, h(bump) + f"Binary files a/{wf[0]} and b/{wf[0]} differ\n", False),
            ("a removed line that reads like a file header", wf, h("@@ -1,2 +1 @@\n----\n-      - uses: a/b@1\n+      - uses: a/b@2\n"), False),
            ("a file outside the workflows", wf + ["tools/host.py"], h(bump), False),
            ("a ref that is a branch, which can move", wf, h("@@ -1 +1 @@\n-      - uses: a/b@1111 # v1\n+      - uses: a/b@main\n"), False),
            ("a short commit", wf, h("@@ -1 +1 @@\n-      - uses: a/b@1111 # v1\n+      - uses: a/b@2222 # v2\n"), False),
            ("a pin in the docs workflow too, as one update moves every copy", wf + [".github/workflows/docs.yml"],
             h(bump) + h(bump, ".github/workflows/docs.yml"), True),
            ("nothing", wf, "", False)):
        if pin_lines_only(paths, patch) != want:
            problems.append(f"self-test: pin_lines_only takes {what} for {'a' if not want else 'no'} change of pinned versions only")
    own = ".github/workflows/docs.yml"
    workflows = {p: repo.read(p) for p in repo.glob(".github/workflows/*.yml")}
    names = workflow_jobs(workflows.get(own, ""))
    if len(names) < 2 or job_clashes(workflows, own, names):
        problems.append(f"self-test: the docs job's id and name are not both read, or another workflow already uses them: {sorted(names)}")
    for what, edit in (("the same job name", lambda s, n: s.replace("  checks:\n", f"  checks:\n    name: {n}\n", 1)),
                       ("the same job id", lambda s, n: s.replace("  checks:\n", f"  {n}:\n", 1)),
                       ("the same name, quoted, with a comment after jobs", lambda s, n: s.replace("jobs:\n", "jobs: # all\n", 1).replace("  checks:\n", f"  checks:\n    name: \"{n}\"\n", 1)),
                       ("the same name in a job indented four spaces", lambda s, n: s.replace("jobs:\n", f"jobs:\n    other:\n        name: {n}\n        runs-on: x\n", 1)),
                       ("a name GitHub computes", lambda s, n: s.replace("  checks:\n", "  checks:\n    name: ${{ 'x' }}\n", 1)),
                       ("a name with a matrix value in it", lambda s, n: s.replace("  checks:\n", f"  checks:\n    name: {n.split(' ')[0]} ${{{{ matrix.w }}}}\n", 1)),
                       ("a name written as a block", lambda s, n: s.replace("  checks:\n", "  checks:\n    name: >-\n      x\n", 1)),
                       ("a token that can post statuses", lambda s, n: s.replace("jobs:\n", "permissions:\n  statuses: write\njobs:\n", 1)),
                       ("a quoted permission to post checks", lambda s, n: s.replace("  checks:\n", "  checks:\n    permissions:\n      checks: 'write'\n", 1)),
                       ("a name over two lines", lambda s, n: s.replace("  checks:\n", f"  checks:\n    name: {n[:9]}\n      {n[9:]}\n", 1)),
                       ("a name with a comment holding a quote", lambda s, n: s.replace("  checks:\n", f"  checks:\n    name: {n} # it's\n", 1)),
                       ("a plain name GitHub extends with matrix values", lambda s, n: s.replace("  checks:\n", f"  checks:\n    name: {n.split(' (')[0]}\n", 1)),
                       ("a name from an anchor", lambda s, n: s.replace("  checks:\n", f"  checks:\n    env:\n      N: &n x\n    name: *n\n", 1))):
        for name in sorted(names):
            if " " in name and what.endswith("id") or " " not in name and what.endswith("name") \
                    or " " not in name and what.startswith(("the same name", "a name", "a plain name")):
                continue
            planted = {**workflows, ".github/workflows/checks.yml": edit(workflows[".github/workflows/checks.yml"], name)}
            if not job_clashes(planted, own, names):
                problems.append(f"self-test: another workflow with {what} as the docs job was not noticed")
    for raw, shown in (("a\nPROBLEM forged", "a\\nPROBLEM forged"), ("a\r::error::x", "a\\r: :error: :x"), ("a\x1b[2Kb", "a?[2Kb")):
        if printable(raw) != shown:
            problems.append(f"self-test: output text {raw!r} is printed as {printable(raw)!r}, not {shown!r}")
    if substance("a  b\r\nc\n") != substance("a b\nc") or substance("a b") == substance("a c"):
        problems.append("self-test: the comparison of document substance is wrong")
    if with_git:
        _git_case(problems)
    return problems


def printable(line: str) -> str:
    """Text from commit messages is printed: it must stay on its line and not read as a command to a CI runner."""
    line = line.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "?", line).replace("::", ": :")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("self-test")
    one = sub.add_parser("diff")
    one.add_argument("--base", required=True, help="the branch or commit the change is to be merged into")
    one.add_argument("--head", help="the commit to judge; the working tree if left out")
    one.add_argument("--pr-body", type=pathlib.Path, help="a file holding the pull request's description")
    one.add_argument("--repo", type=pathlib.Path, default=ROOT,
                     help="the repository to judge; by default the one this file is in. CI runs the base's copy of "
                          "this file on the change, so that a change cannot loosen the checker that judges it")
    three = sub.add_parser("jobs")
    three.add_argument("--head", required=True)
    three.add_argument("--own", required=True, help="the workflow whose jobs no other may share")
    three.add_argument("--name", action="append", required=True, help="a job id or name it uses (may be repeated)")
    three.add_argument("--repo", type=pathlib.Path, default=ROOT)
    two = sub.add_parser("pins-only")
    two.add_argument("--base", required=True)
    two.add_argument("--head", required=True)
    two.add_argument("--repo", type=pathlib.Path, default=ROOT)
    args = ap.parse_args()
    if args.command == "self-test":
        found, notes = self_test(), []
    elif args.command == "jobs":
        try:
            clashes = job_clashes(head_workflows(args.repo.resolve(), args.head), args.own, set(args.name))
        except CannotRun as err:
            print(f"COULD NOT RUN {err}")
            return 2
        for line in clashes:
            print("PROBLEM", printable(line))
        print("job names:", "FAILED" if clashes else "no other workflow uses them")
        return 1 if clashes else 0
    elif args.command == "pins-only":
        try:
            only = pins_only(args.repo.resolve(), args.base, args.head)
        except CannotRun as err:
            print(f"COULD NOT RUN {err}")
            return 2
        print("the change touches only lines pinning actions and runner images" if only
              else "the change touches more than pinned versions")
        return 0 if only else 1
    elif args.command == "diff":
        try:
            body = args.pr_body.read_text(encoding="utf-8") if args.pr_body else None
            found, notes = diff(args.repo.resolve(), args.base, args.head, body)
        except (CannotRun, OSError) as err:
            print(f"COULD NOT RUN {err}")
            print("documents and code: not judged")
            return 2
    else:
        found, notes = repo_problems(), []
    for kind, lines in (("NOTE", notes), ("PROBLEM", found)):
        for line in lines:
            print(kind, printable(line))
    print("documents and code:", "FAILED" if found else "agree")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
