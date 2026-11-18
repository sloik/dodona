"""Read dodona's intent files, and write the criteria table each one shows. Stage-0 helper (decision 0028).

    python tools/intents.py --write   # rewrite each intent's table from its front matter
    python tools/intents.py --check   # fail unless every intent file can be read one way only

An intent's criteria are data, kept in its front matter as one JSON line:

    criteria: [{"id": "1", "words": "...", "gate": "hard", "checks": ["*/design*"], "checked_by": "..."}]

That line is the only thing a reader takes the criteria from. The table under
"## Criteria" is written from it by this tool, so what a person sees on
GitHub is what is read. A file is refused when anything else in it could be
taken for a criterion: any other table, an HTML table, a code block, a
blockquote, a hidden comment, or a table that is not exactly the one this
tool writes. Two reviews found that a free-form table could always be written
so that a person and the reader saw different things; this removes the choice.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
GATES = ("hard", "soft", "deferred")
# What a criterion's words and note may hold: plain text that Markdown and HTML render as itself.
PLAIN = re.compile(r"^[A-Za-z0-9 .,;:'()/+?%-]+$")
# What a pattern naming checks may hold.
PATTERN = re.compile(r"^[A-Za-z0-9_*?/.-]+$")
# Characters that make Markdown or HTML render something other than the text: tags, entities,
# tables, emphasis, code, links, escapes. None may appear outside the written table.
MARKUP = set("<>&|*_`[]\\")
BEGIN = "<!-- criteria: written by tools/intents.py from the front matter; do not edit -->"
END = "<!-- end of criteria -->"


class Unreadable(Exception):
    """The intent file could be read more than one way."""


def front(text: str) -> tuple[dict, str]:
    """The front matter as plain `key: value` lines, and the body after it."""
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise Unreadable("it does not start with front matter between two lines of ---")
    head, body = text[4:].split("\n---\n", 1)
    if any(line.rstrip() in ("---", "...") or line.strip().startswith("---") for line in text.splitlines()[1:]
           if line != "---"):
        raise Unreadable("a line looks like the end of the front matter but is not exactly ---")
    fields: dict[str, str] = {}
    for line in head.splitlines():
        # Every line of the front matter is a plain key and value, or a plain item of a list. Nothing
        # else may sit there, because nothing else is read and a page could still show it.
        if re.fullmatch(r"  - [A-Za-z0-9_./-]+", line):
            continue
        match = re.fullmatch(r"([a-z_]+): (.*)", line) or re.fullmatch(r"([a-z_]+):", line)
        if not match:
            raise Unreadable(f"a front-matter line is not a plain key and value: {line[:40]!r}")
        key, value = match.group(1), (match.group(2) if match.lastindex == 2 else "")
        if key in fields:
            raise Unreadable(f"the front matter names {key!r} twice")
        if key != "criteria" and not re.fullmatch(r"[A-Za-z0-9 .,;:'\"()/+?%-]*", value):
            raise Unreadable(f"the front-matter value of {key!r} is not plain text")
        fields[key] = value
    return fields, body


def criteria_of(fields: dict) -> list[dict]:
    try:
        items = json.loads(fields.get("criteria", "[]"))
    except ValueError as err:
        raise Unreadable(f"the criteria line is not JSON: {err}") from None
    if not isinstance(items, list) or not items:
        raise Unreadable("the criteria line must be a list with at least one criterion")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {"id", "words", "gate", "checks", "checked_by"}:
            raise Unreadable("each criterion has only id, words, gate, checks and checked_by")
        ident, words, gate = item.get("id"), item.get("words"), item.get("gate")
        if not (isinstance(ident, str) and ident.isascii() and ident.isdigit()) or ident in seen:
            raise Unreadable(f"criterion id {ident!r} is not a new number written in plain digits")
        seen.add(ident)
        if gate not in GATES:
            raise Unreadable(f"criterion {ident} has gate {gate!r}; it must be exactly hard, soft or deferred")
        if not isinstance(words, str) or not PLAIN.match(words):
            raise Unreadable(f"criterion {ident}: its words must be plain text (letters, digits, spaces, . , ; : ' ( ) / + ? % -)")
        checks = item.get("checks", [])
        if not isinstance(checks, list) or not all(isinstance(c, str) and PATTERN.match(c) for c in checks):
            raise Unreadable(f"criterion {ident}: checks must be a list of name patterns")
        note = item.get("checked_by", "")
        if not isinstance(note, str) or (note and not PLAIN.match(note)):
            raise Unreadable(f"criterion {ident}: checked_by must be plain text")
    return items


def shown_checks(item: dict) -> str:
    """The Checked by cell: exactly the patterns that are read, then the note, which is only a note."""
    patterns = item.get("checks", [])
    cell = ("checks named " + ", ".join(f"`{p}`" for p in patterns)) if patterns else "nothing a kernel reads yet"
    return cell + (f". {item['checked_by']}" if item.get("checked_by") else "")


def table(items: list[dict]) -> str:
    rows = ["| # | Criterion | Gate | Checked by |", "|---|---|---|---|"]
    rows += [f"| {c['id']} | {c['words']} | {c['gate']} | {shown_checks(c)} |" for c in items]
    return "\n".join([BEGIN] + rows + [END])


def read(path: pathlib.Path) -> tuple[dict, list[dict], str]:
    """The front matter, the criteria, and the whole text; or Unreadable."""
    text = path.read_text(encoding="utf-8")
    fields, body = front(text)
    items = criteria_of(fields)
    if body.count(BEGIN) != 1 or body.count(END) != 1:
        raise Unreadable("the body must hold the written criteria table exactly once")
    shown = body[body.index(BEGIN): body.index(END) + len(END)]
    if shown != table(items):
        raise Unreadable("the criteria table is not the one the front matter gives; run tools/intents.py --write")
    rest = body.replace(shown, "")
    # Outside the written table the body is plain prose: no character that Markdown or HTML would
    # turn into anything else. An allowlist, because two reviews kept finding new markup that did.
    found = sorted(MARKUP & set(rest))
    if found:
        raise Unreadable(f"outside the written table it uses {''.join(found)!r}, which could make a page show something other than what is read")
    if any(not (line.isprintable() or line == "") for line in rest.splitlines()):
        raise Unreadable("outside the written table it has a character that does not print")
    if re.search(r"(?m)^ {4,}\S|^\t", rest) or re.search(r"(?m)^\s*(```|~~~)", rest):
        raise Unreadable("it has a code block")
    return fields, items, text


def write(path: pathlib.Path) -> bool:
    text = path.read_text(encoding="utf-8")
    fields, body = front(text)
    made = table(criteria_of(fields))
    if BEGIN in body and END in body:
        new_body = body[: body.index(BEGIN)] + made + body[body.index(END) + len(END):]
    else:
        raise Unreadable("no written criteria table to replace")
    head = text[: len(text) - len(body)]
    if head + new_body != text:
        path.write_text(head + new_body, encoding="utf-8")
        return True
    return False


def main() -> int:
    paths = sorted((ROOT / "intents").glob("[0-9]*.md"))
    failed = 0
    for path in paths:
        try:
            if "--write" in sys.argv:
                write(path)
            read(path)
        except Unreadable as err:
            failed += 1
            print(f"{path.relative_to(ROOT)} cannot be read one way only: {err}")
    print(json.dumps({"intents": len(paths), "readable": len(paths) - failed}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
