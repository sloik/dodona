"""Read dodona's intent files, and write the criteria table each one shows. Stage-0 helper (decision 0028).

    python tools/intents.py --write   # rewrite each intent's table from its front matter
    python tools/intents.py --check   # fail unless every intent file can be read one way only

An intent's criteria are data, kept in its front matter as one JSON line:

    criteria: [{"id": "1", "words": "...", "gate": "hard", "checks": ["*/design*"], "checked_by": "..."}]

A deferred criterion also says what is to be observed and within how many days of delivery
(decision 0018): "condition" and "limit_days". No other criterion has them.

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
PLAIN = re.compile(r"[A-Za-z0-9 .,;:'()/+?%-]+")
# What a pattern naming checks may hold.
PATTERN = re.compile(r"[A-Za-z0-9_*?/.-]+")
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


# GitHub shows :name: as an emoji, so plain text may not hold one.
EMOJI = re.compile(r":[A-Za-z0-9_+-]+:")


def plain(text) -> bool:
    """Text that Markdown and HTML render as itself: allowed characters only, the whole of it (no line feed slips
    past the end), and no emoji code."""
    return isinstance(text, str) and PLAIN.fullmatch(text) is not None and not EMOJI.search(text)


def no_repeats(pairs: list) -> dict:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise Unreadable("the criteria line names a field twice in one criterion")
    return dict(pairs)


def criteria_of(fields: dict) -> list[dict]:
    try:
        items = json.loads(fields.get("criteria", "[]"), object_pairs_hook=no_repeats)
    except ValueError as err:
        raise Unreadable(f"the criteria line is not JSON: {err}") from None
    if not isinstance(items, list) or not items:
        raise Unreadable("the criteria line must be a list with at least one criterion")
    seen = set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {"id", "words", "gate", "checks", "checked_by", "condition", "limit_days"}:
            raise Unreadable("each criterion has only id, words, gate, checks, checked_by, condition and limit_days")
        ident, words, gate = item.get("id"), item.get("words"), item.get("gate")
        if not (isinstance(ident, str) and ident.isascii() and ident.isdigit()) or ident in seen:
            raise Unreadable(f"criterion id {ident!r} is not a new number written in plain digits")
        seen.add(ident)
        if gate not in GATES:
            raise Unreadable(f"criterion {ident} has gate {gate!r}; it must be exactly hard, soft or deferred")
        if not plain(words):
            raise Unreadable(f"criterion {ident}: its words must be plain text (letters, digits, spaces, . , ; : ' ( ) / + ? % -)")
        checks = item.get("checks", [])
        if not isinstance(checks, list) or not all(isinstance(c, str) and PATTERN.fullmatch(c) for c in checks):
            raise Unreadable(f"criterion {ident}: checks must be a list of name patterns")
        note = item.get("checked_by", "")
        if not isinstance(note, str) or (note and not plain(note)):
            raise Unreadable(f"criterion {ident}: checked_by must be plain text")
        if gate == "deferred":
            condition, days = item.get("condition"), item.get("limit_days")
            if not plain(condition) or condition != condition.strip() or not any(ch.isalpha() for ch in condition):
                raise Unreadable(f"criterion {ident} is deferred: its condition, what is to be observed, must be given in plain text, with words, and no space at either end")
            if type(days) is not int or days < 1:
                raise Unreadable(f"criterion {ident} is deferred: limit_days must be a whole number of days, at least 1")
        elif "condition" in item or "limit_days" in item:
            raise Unreadable(f"criterion {ident} is not deferred, so it has no condition or limit_days")
    return items


def shown_checks(item: dict) -> str:
    """The Checked by cell: exactly the patterns that are read, then the note, which is only a note."""
    patterns = item.get("checks", [])
    cell = ("checks named " + ", ".join(f"`{p}`" for p in patterns)) if patterns else "nothing a kernel reads yet"
    return cell + (f". {item['checked_by']}" if item.get("checked_by") else "")


def shown_observation(item: dict) -> str:
    """The Observed cell of a deferred criterion: the limit first, in a fixed form, then what is to be observed.
    It has a column of its own, so nothing in the note can be taken for it."""
    if item.get("gate") != "deferred":
        return ""
    return f"within {item.get('limit_days')} days of delivery: {item.get('condition')}"


def table(items: list[dict]) -> str:
    rows = ["| # | Criterion | Gate | Checked by | Observed after delivery |", "|---|---|---|---|---|"]
    rows += [f"| {c['id']} | {c['words']} | {c['gate']} | {shown_checks(c)} | {shown_observation(c)} |" for c in items]
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
    problems = check_all(paths, "--write" in sys.argv)
    for problem in problems:
        print(problem)
    print(json.dumps({"intents": len(paths), "readable": len(paths) - len(problems)}))
    return 1 if problems else 0


def check_all(paths: list[pathlib.Path], rewrite: bool = False) -> list[str]:
    """Why each of these intent files cannot be read one way only; empty when all can. Two files with one id
    cannot: which of them a reader takes would depend on the order it lists them in."""
    problems, seen = [], {}
    for path in paths:
        try:
            if rewrite:
                write(path)
            fields, _, _ = read(path)
            ident = fields.get("id", "").strip('"')
            if ident in seen:
                raise Unreadable(f"its id {ident} is also the id of {seen[ident]}")
            seen[ident] = path.name
        except Unreadable as err:
            problems.append(f"{path.name} cannot be read one way only: {err}")
    return problems


if __name__ == "__main__":
    sys.exit(main())
