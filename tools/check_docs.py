"""Checks that the documents still describe the code. Stage-0 helper (decision 0023).

    python tools/check_docs.py                                          # every repository-wide check
    python tools/check_docs.py self-test                                # plant a fault for each check; each must fail
    python tools/check_docs.py diff --base REV [--head REV] [--pr-body FILE]

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

That line is the author's own word, and it is printed as such for whoever
reviews the change. A change is judged by the rules on its base, so it cannot
loosen the rule it is judged by; a new file is judged by the rules it brings.
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


class Cli:
    def __init__(self):
        self.flags: dict[str | None, set[str]] = {None: set()}
        self.subcommands: set[str] = set()
        self.unreadable: list[str] = []
        self.runnable = False


def read_cli(source: str) -> Cli:
    cli = Cli()
    tree = ast.parse(source)
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
        doc = ast.get_docstring(ast.parse(source)) or ""
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
                if span.split("/")[0] not in tops and not repo.exists(own):
                    continue  # not a path in this repository, e.g. `run.poll` or `vendor/family`
                checked += 1
                if repo.exists(span) or repo.exists(own):
                    continue
                if span in absent:
                    mentioned.add(span)
                    continue
                problems.append(f"{doc}:{number}: names `{span}`, which does not exist. If it is meant not to exist yet, "
                                f"add it to [[absent]] in {MAP_FILE} with the reason")
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


def waivers(messages: list[str]) -> tuple[dict[str, str], list[str]]:
    found, problems = {}, []
    for message in messages:
        for line in message.replace("\r\n", "\n").split("\n"):
            line = line.strip()
            if not re.match(r"(?i)docs[- _]?unchanged", line):
                continue
            m = WAIVER.fullmatch(line)
            if not m:
                problems.append(f"waiver line {line!r} is not `Docs-unchanged: <rule id>: <reason>`")
                continue
            reason = m.group(2).strip()
            if len(reason) < MIN_REASON_CHARS or len(reason.split()) < MIN_REASON_WORDS:
                problems.append(f"waiver for rule {m.group(1)} gives too short a reason ({reason!r}): "
                                f"say in at least {MIN_REASON_WORDS} words why no document has to change")
                continue
            found[m.group(1)] = reason
    return found, problems


def report_problems(body: str) -> list[str]:
    """A pull request description must say what was verified and what was not (AGENTS.md rule 4)."""
    body = re.sub(r"<!--.*?-->", "", body.replace("\r\n", "\n"), flags=re.S)
    problems = []
    for heading in ("## Verified", "## Not verified"):
        m = re.search(rf"^{heading}[ \t]*\n(.*?)(?=^#{{1,2}} |\Z)", body, flags=re.M | re.S)
        content = m.group(1).strip() if m else ""
        if not m:
            problems.append(f"the pull request description has no '{heading}' section")
        elif len(content.split()) < 2 or re.fullmatch(r"(?i)[\s*_-]*(todo|tbd|n/?a|-|\.\.\.)[\s*_.-]*", content):
            problems.append(f"the '{heading}' section of the pull request description says nothing: "
                            "name each check that ran to completion, or say what did not run or was not finished, and why")
    return problems


def judge_change(changed: list[tuple[str, str]], docs_changed: set[str], messages: list[str],
                 base_map: dict | None, head_map: dict, decisions: dict[str, list[str]] | None = None
                 ) -> tuple[list[str], list[str]]:
    """The rule for a change. `changed` is (status, path) with status A, M or D; `docs_changed` the
    documents whose substance changed. Returns problems and notes. Pure: no git, no files."""
    problems, notes = [], []
    given, bad = waivers(messages)
    problems += bad
    known = {r["id"] for m in (base_map, head_map) if m for r in m["rule"]}
    for rid in sorted(set(given) - known):
        problems.append(f"waiver names rule {rid!r}, which {MAP_FILE} does not have")
    triggered: dict[str, tuple[dict, list[str]]] = {}
    for status, path in sorted(changed, key=lambda c: c[1]):
        if path.endswith(".md"):
            continue
        found = (map_entry(base_map, path) if base_map else []) or map_entry(head_map, path)
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
            problems.append(f"rule {rid}: {shown} changed, and none of {', '.join(entry['docs'])} did. Update the one that "
                            f"describes this change, or, if none needs to, add to a commit message the line "
                            f"`Docs-unchanged: {rid}: <why, in a sentence>`")
    for rid in sorted(set(given) & known - set(triggered)):
        problems.append(f"waiver names rule {rid}, and nothing that rule covers changed")
    if base_map is not None and base_map != head_map:
        for kind in ("rule", "exempt", "absent", "known"):
            before = {json.dumps(e, sort_keys=True) for e in base_map[kind]}
            after = {json.dumps(e, sort_keys=True) for e in head_map[kind]}
            for e in sorted(after - before):
                notes.append(f"{MAP_FILE}: this change adds or alters [[{kind}]] {e}; it applies after merge, review it")
            for e in sorted(before - after):
                notes.append(f"{MAP_FILE}: this change removes or alters [[{kind}]] {e}; it applies after merge, review it")
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


def diff(root: pathlib.Path, base: str, head: str | None, pr_body: str | None,
         env: dict | None = None) -> tuple[list[str], list[str]]:
    for rev in (base, head):
        if rev is not None and (not rev.strip() or re.fullmatch(r"0+", rev)):
            raise CannotRun(f"no usable revision given ({rev!r})")
    head_rev = head or "HEAD"

    def git(root, *args):  # noqa: F811 - the module's git, with this call's environment
        return globals()["git"](root, *args, env=env)

    git(root, "rev-parse", "--verify", "--quiet", base + "^{commit}")
    git(root, "rev-parse", "--verify", "--quiet", head_rev + "^{commit}")
    merge_base = git(root, "merge-base", base, head_rev).decode().strip()
    if not merge_base:
        raise CannotRun(f"{base} and {head_rev} have no common ancestor")
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

    docs_changed = {p for _, p in changed if p.endswith(".md") and substance(at(merge_base, p)) != substance(at(head, p))}
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
    problems, notes = judge_change(changed, docs_changed, messages, base_map, head_map, decisions)
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
        ("waived with too short a reason", "too short a reason", (host, set(), ["Docs-unchanged: host: typo"], doc_map, doc_map)),
        ("waived for a rule that does not exist", "'nosuchrule', which",
         (host, {host_docs[0]}, [f"Docs-unchanged: nosuchrule: {reason}"], doc_map, doc_map)),
        ("waived for a rule nothing triggered", "rule encoding, and nothing that rule covers changed",
         (host, {host_docs[0]}, [f"Docs-unchanged: encoding: {reason}"], doc_map, doc_map)),
        ("a waiver line written wrongly", "is not `Docs-unchanged: <rule id>: <reason>`",
         (host, set(), [f"Docs-Unchanged host because {reason}"], doc_map, doc_map)),
        ("a new file no rule covers", "newdir/tool.py: no rule", ([("A", "newdir/tool.py")], set(), [], doc_map, doc_map)),
        ("an exemption added in the same change", missing, (host, set(), [], doc_map, exempting)),
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
            except CannotRun:
                pass
    except CannotRun as err:
        problems.append(f"self-test: the end-to-end case could not run: {err}")


def self_test(repo: Repo | None = None) -> list[str]:
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
                              ("Fixes a typo.", False)):
        if (not report_problems(body)) != should_pass:
            problems.append(f"self-test: the pull request report rule gave the wrong answer for {body!r}")
    if substance("a  b\r\nc\n") != substance("a b\nc") or substance("a b") == substance("a c"):
        problems.append("self-test: the comparison of document substance is wrong")
    _git_case(problems)
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command")
    sub.add_parser("self-test")
    one = sub.add_parser("diff")
    one.add_argument("--base", required=True, help="the branch or commit the change is to be merged into")
    one.add_argument("--head", help="the commit to judge; the working tree if left out")
    one.add_argument("--pr-body", type=pathlib.Path, help="a file holding the pull request's description")
    args = ap.parse_args()
    if args.command == "self-test":
        found, notes = self_test(), []
    elif args.command == "diff":
        try:
            body = args.pr_body.read_text(encoding="utf-8") if args.pr_body else None
            found, notes = diff(ROOT, args.base, args.head, body)
        except (CannotRun, OSError) as err:
            print(f"COULD NOT RUN {err}")
            print("documents and code: not judged")
            return 2
    else:
        found, notes = repo_problems(), []
    for kind, lines in (("NOTE", notes), ("PROBLEM", found)):
        for line in lines:  # text from commit messages is printed; it must not read as a command to a CI runner
            print(kind, re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "?", line).replace("::", ": :"))
    print("documents and code:", "FAILED" if found else "agree")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
