#!/usr/bin/env python3
"""How complete and how well checked dodona is, in numbers read from its own files.

Every number is counted from a file in this repository that a reader can open, and each
names that file. Nothing here runs a kernel, a model or a checker, and no number says that
what a file states is true: a claim marked checked is counted as marked checked.

    python tools/metrics.py                    the numbers, as a table
    python tools/metrics.py --json             the numbers, as JSON
    python tools/metrics.py --compare FILE     the change against an earlier --json output;
                                               exits 1 if a ratcheted number went down
                                               without a waiver (see docs/metrics.md)
    python tools/metrics.py self-test          plants changes and requires each to be judged right

Options: --markdown (tables for a job summary), --messages FILE (commit messages to read
waivers from, with --compare), --commit SHA (recorded in --json output), --root DIR.

Exit codes: 0 fine, 1 a ratcheted number went down without a valid waiver, 2 something could
not be measured or the earlier file could not be read. A file that is missing or does not
read as expected is never counted as zero.

Standard library only; standard output is ASCII so it prints on any console.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

FORMAT = "dodona-metrics/1"
ROOT = pathlib.Path(__file__).resolve().parent.parent

# The files the numbers are read from. The self-test copies exactly these.
SOURCES = [
    "conformance/kernel",
    "conformance/vectors",
    "conformance/ledger",
    "conformance/provider/cases.json",
    "conformance/provider/check-cases.json",
    "conformance/README.md",
    "kernel/defects.json",
    "kernel2/defects.json",
    "spec/CLAIMS.md",
    "decisions",
    "docs/gap-checks.md",
]

DECISION_STATUSES = ("proposed", "accepted", "superseded", "rejected")  # decisions/README.md
WAIVER_KEY = "Metrics-down:"
WAIVER_MIN_WORDS = 6
METRIC_NAME = re.compile(r"^[a-z0-9_]+(\.[a-z0-9_-]+)*$")


class Unmeasurable(Exception):
    """A source is missing or does not read the way this tool expects."""


class BadBaseline(Exception):
    """The earlier metrics file cannot be read."""


# --------------------------------------------------------------------------- reading


def _text(root: pathlib.Path, rel: str) -> str:
    path = root / rel
    if not path.is_file():
        raise Unmeasurable(f"{rel}: missing")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as err:
        raise Unmeasurable(f"{rel}: not UTF-8: {err}") from None


def _json(root: pathlib.Path, rel: str):
    try:
        return json.loads(_text(root, rel))
    except ValueError as err:
        raise Unmeasurable(f"{rel}: not JSON: {err}") from None


def _list(data, key: str, rel: str) -> list:
    if not isinstance(data, dict) or not isinstance(data.get(key), list):
        raise Unmeasurable(f"{rel}: no list '{key}'")
    return data[key]


def _section(text: str, heading: str, rel: str) -> str:
    """The body under a '## ' heading, up to the next heading of that level or the end."""
    lines = text.splitlines()
    try:
        start = lines.index(heading)
    except ValueError:
        raise Unmeasurable(f"{rel}: heading {heading!r} not found") from None
    body = []
    for line in lines[start + 1:]:
        if line.startswith("## ") or line.startswith("# "):
            break
        body.append(line)
    return "\n".join(body)


def _table_rows(text: str, header_start: str, rel: str) -> list[str]:
    """Data rows of the first table whose header line starts with header_start."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(header_start):
            if i + 1 >= len(lines) or not re.match(r"^\|(\s*:?-+:?\s*\|)+\s*$", lines[i + 1]):
                raise Unmeasurable(f"{rel}: table {header_start!r} has no separator line")
            rows = []
            for row in lines[i + 2:]:
                if not row.startswith("|"):
                    break
                rows.append(row)
            return rows
    raise Unmeasurable(f"{rel}: no table whose header starts {header_start!r}")


# --------------------------------------------------------------------------- measuring


def measure(root: pathlib.Path) -> list[dict]:
    """Every metric: name, value, whether it is ratcheted, and the file it is read from."""
    out: list[dict] = []

    def add(name: str, value: int, ratchet: bool, source: str) -> None:
        out.append({"name": name, "value": value, "ratchet": ratchet, "source": source})

    # The kit.
    kit = root / "conformance" / "kernel"
    if not kit.is_dir():
        raise Unmeasurable("conformance/kernel: missing")
    kinds = sorted(p for p in kit.iterdir() if p.is_dir())
    per_kind = {p.name: len(list(p.glob("*.json"))) for p in kinds}
    add("kit.scenarios", sum(per_kind.values()), True, "conformance/kernel/*/*.json")
    for kind, n in per_kind.items():
        add(f"kit.scenarios.{kind}", n, False, f"conformance/kernel/{kind}/*.json")

    vectors_dir = root / "conformance" / "vectors"
    files = sorted(vectors_dir.glob("*.json")) if vectors_dir.is_dir() else []
    if not files:
        raise Unmeasurable("conformance/vectors: no vector files")
    total = 0
    for path in files:
        rel = f"conformance/vectors/{path.name}"
        data = _json(root, rel)
        lists = [v for v in data.values() if isinstance(v, list)] if isinstance(data, dict) else []
        if not lists:
            raise Unmeasurable(f"{rel}: no lists of vectors")
        n = sum(len(v) for v in lists)
        total += n
        add(f"kit.vectors.{path.stem}", n, False, f"{rel} (every top-level list)")
    add("kit.vectors", total, True, "conformance/vectors/*.json (every top-level list)")

    cases = _json(root, "conformance/ledger/cases.json")
    more = _json(root, "conformance/ledger/more-damage.json")
    ledger = (len(_list(cases, "append", "conformance/ledger/cases.json"))
              + len(_list(cases, "damage", "conformance/ledger/cases.json"))
              + len(_list(more, "damage", "conformance/ledger/more-damage.json"))
              + len(_list(more, "bad_requests", "conformance/ledger/more-damage.json")))
    if not isinstance(more.get("unlisted_kind"), dict):
        raise Unmeasurable("conformance/ledger/more-damage.json: no 'unlisted_kind'")
    ledger += 1
    add("kit.ledger_cases", ledger, True,
        "conformance/ledger/cases.json (append, damage), more-damage.json (damage, bad_requests, unlisted_kind)")

    rel = "conformance/provider/check-cases.json"
    add("kit.host_check_cases", len(_list(_json(root, rel), "cases", rel)), True, f"{rel} (cases)")
    rel = "conformance/provider/cases.json"
    add("kit.session_cases", len(_list(_json(root, rel), "cases", rel)), True, f"{rel} (cases)")

    # Planted defects, counted only.
    for kernel in ("kernel", "kernel2"):
        rel = f"{kernel}/defects.json"
        add(f"planted_defects.{kernel}", len(_list(_json(root, rel), "defects", rel)), True, f"{rel} (defects)")

    # Claims.
    rel = "spec/CLAIMS.md"
    text = _text(root, rel)
    runs = set(re.findall(r"^### Run (\d+)\b", text, flags=re.M))
    counts = {"checked": 0, "sampled_by_kit": 0, "modelled_unchecked": 0, "not_modelled": 0}
    seen: set[str] = set()
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line
            continue
        m = re.match(r"^\| (C\d+) \|", line)
        if not m:
            continue
        cid = m.group(1)
        if cid in seen:
            raise Unmeasurable(f"{rel}: claim {cid} is listed twice")
        seen.add(cid)
        if section == "## Not yet modelled":
            counts["not_modelled"] += 1
            continue
        status = line.strip().strip("|").split("|")[-1].strip()
        checked = re.match(r"^\*\*checked\*\*, run (\d+)$", status)
        if checked:
            if checked.group(1) not in runs:
                raise Unmeasurable(f"{rel}: {cid} is marked checked by run {checked.group(1)}, which is not under Recorded runs")
            counts["checked"] += 1
        elif status == "sampled by the kit":
            counts["sampled_by_kit"] += 1
        elif status == "modelled, unchecked":
            counts["modelled_unchecked"] += 1
        else:
            raise Unmeasurable(f"{rel}: {cid} has a status this tool does not know: {status!r}")
    if not seen:
        raise Unmeasurable(f"{rel}: no claims found")
    add("claims.total", len(seen), True, f"{rel} (rows '| C<n> |')")
    add("claims.checked", counts["checked"], True, f"{rel} (status '**checked**, run <n>', run recorded there)")
    add("claims.unchecked", len(seen) - counts["checked"], False, f"{rel} (every other claim)")
    add("claims.sampled_by_kit", counts["sampled_by_kit"], False, f"{rel} (status 'sampled by the kit')")
    add("claims.modelled_unchecked", counts["modelled_unchecked"], False, f"{rel} (status 'modelled, unchecked')")
    add("claims.not_modelled", counts["not_modelled"], False, f"{rel} (section 'Not yet modelled')")

    # Decisions.
    records = sorted((root / "decisions").glob("[0-9]*.md"))
    by_status = dict.fromkeys(DECISION_STATUSES, 0)
    for path in records:
        m = re.search(r"^status: (\S+)$", _text(root, f"decisions/{path.name}"), flags=re.M)
        if not m or m.group(1) not in by_status:
            raise Unmeasurable(f"decisions/{path.name}: status missing or not one of {', '.join(DECISION_STATUSES)}")
        by_status[m.group(1)] += 1
    if not records:
        raise Unmeasurable("decisions: no records")
    add("decisions.total", len(records), True, "decisions/[0-9]*.md")
    for status, n in by_status.items():
        add(f"decisions.{status}", n, False, f"decisions/[0-9]*.md (status: {status})")

    # Gaps.
    rel = "conformance/README.md"
    body = _section(_text(root, rel), "## Not yet in the kit", rel)
    add("gaps.not_in_kit", sum(1 for line in body.splitlines() if line.startswith("- ")), False,
        f"{rel} (bullets under 'Not yet in the kit')")
    rel = "docs/gap-checks.md"
    text = _text(root, rel)
    rows = _table_rows(text, "| Check |", rel)
    for row in rows:
        if not re.match(r"^\| `\w+` \|", row):
            raise Unmeasurable(f"{rel}: a row of the checks table does not start with a check name: {row[:60]!r}")
    add("gaps.gap_checks", len(rows), True, f"{rel} (rows of the 'Check' table)")
    rows = _table_rows(text, "| Tool |", rel)
    add("gaps.tool_checks", len(rows), True, f"{rel} (rows of the 'Tool' table)")

    names = [m["name"] for m in out]
    for name in names:
        if names.count(name) > 1:
            raise Unmeasurable(f"two metrics would be called {name!r}")
        if not METRIC_NAME.match(name):
            raise Unmeasurable(f"a metric would be called {name!r}: names are lower case letters, digits, '_', '-' and '.'")
    return out


def as_json(metrics: list[dict], commit: str | None) -> dict:
    return {
        "format": FORMAT,
        "commit": commit,
        "metrics": {m["name"]: {"value": m["value"], "ratchet": m["ratchet"], "source": m["source"]} for m in metrics},
    }


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
                or not METRIC_NAME.match(name)):
            raise BadBaseline(f"{path.name}: metric {name!r} has no integer value and boolean ratchet")
    return data


def read_waivers(messages: str, known: set[str]) -> tuple[dict[str, str], list[str]]:
    """Valid waivers by metric, and the lines that look like a waiver and are not one."""
    waivers: dict[str, str] = {}
    refused: list[str] = []
    for raw in messages.splitlines():
        line = raw.strip()
        if line.startswith(WAIVER_KEY):
            rest = line[len(WAIVER_KEY):].strip()
            name, sep, reason = rest.partition(":")
            name, reason = name.strip(), reason.strip()
            words = [w for w in reason.split() if re.search(r"\w", w)]
            if not sep or not METRIC_NAME.match(name):
                refused.append(f"{line!r}: not 'Metrics-down: <metric>: <reason>'")
            elif name not in known:
                refused.append(f"{line!r}: no metric is called {name!r}")
            elif len(words) < WAIVER_MIN_WORDS:
                refused.append(f"{line!r}: the reason has {len(words)} words, at least {WAIVER_MIN_WORDS} are needed")
            else:
                waivers[name] = reason
        elif re.match(r"(?i)^\W*metrics?[-_ ]?down\b", line):
            refused.append(f"{line!r}: looks like a waiver but does not start exactly with '{WAIVER_KEY}'")
    return waivers, refused


def compare(old: dict, now: list[dict], messages: str) -> tuple[list[dict], list[str], list[str], bool]:
    """Rows of the comparison, refused waiver lines, unused waivers, and whether it failed."""
    before = old["metrics"]
    after = {m["name"]: m for m in now}
    waivers, refused = read_waivers(messages, set(before) | set(after))
    used: set[str] = set()
    rows = []
    failed = False
    for name in [m["name"] for m in now] + sorted(set(before) - set(after)):
        b, a = before.get(name), after.get(name)
        ratchet = bool((b and b["ratchet"]) or (a and a["ratchet"]))
        row = {"name": name, "before": b["value"] if b else None, "now": a["value"] if a else None, "ratchet": ratchet}
        problem = None
        if b and b["ratchet"] and a is None:
            problem = "gone, was ratcheted"
        elif b and b["ratchet"] and not a["ratchet"]:
            problem = "no longer ratcheted"
        elif b and ratchet and a["value"] < b["value"]:
            problem = "went down"
        if problem is None:
            row["verdict"] = "new" if b is None else ("gone" if a is None else "ok")
        elif name in waivers:
            used.add(name)
            row["verdict"] = f"{problem}; allowed by waiver: {waivers[name]}"
        else:
            failed = True
            row["verdict"] = f"FAIL: {problem}, no waiver"
        rows.append(row)
    unused = [f"{n}: {r}" for n, r in sorted(waivers.items()) if n not in used]
    return rows, refused, unused, failed


# --------------------------------------------------------------------------- printing


def _ascii(text: str) -> str:
    return text.encode("ascii", "replace").decode("ascii")


def _cell(text: str) -> str:
    """Waiver text comes from commit messages: keep it from breaking or styling a Markdown table."""
    return re.sub(r"([\\|`*_<>\[\]])", r"\\\1", text)


def _change(b, a) -> str:
    if b is None or a is None:
        return ""
    d = a - b
    return f"+{d}" if d > 0 else str(d) if d < 0 else "0"


def table(metrics: list[dict], markdown: bool) -> str:
    if markdown:
        lines = ["| Metric | Value | Ratcheted | Source |", "|---|---:|---|---|"]
        lines += [f"| `{m['name']}` | {m['value']} | {'yes' if m['ratchet'] else 'shown only'} | {m['source']} |" for m in metrics]
    else:
        w = max(len(m["name"]) for m in metrics)
        lines = [f"{'metric':<{w}}  {'value':>5}  {'rule':<10}  source"]
        lines += [f"{m['name']:<{w}}  {m['value']:>5}  {'ratchet' if m['ratchet'] else 'shown':<10}  {m['source']}" for m in metrics]
    return _ascii("\n".join(lines))


def comparison(old: dict, rows, refused, unused, failed, markdown: bool) -> str:
    base = old.get("commit") or "unknown commit"
    lines = []
    if markdown:
        lines.append(f"Compared with the metrics of `{base}`.\n")
        lines += ["| Metric | Before | Now | Change | Ratcheted | Verdict |", "|---|---:|---:|---:|---|---|"]
        for r in rows:
            lines.append(f"| `{r['name']}` | {'' if r['before'] is None else r['before']} | {'' if r['now'] is None else r['now']} | "
                         f"{_change(r['before'], r['now'])} | {'yes' if r['ratchet'] else 'shown only'} | {_cell(r['verdict'])} |")
        refused = [_cell(x) for x in refused]
        unused = [_cell(x) for x in unused]
    else:
        lines.append(f"compared with the metrics of {base}")
        w = max(len(r["name"]) for r in rows)
        lines.append(f"{'metric':<{w}}  {'before':>6}  {'now':>6}  {'change':>6}  {'rule':<7}  verdict")
        for r in rows:
            lines.append(f"{r['name']:<{w}}  {'' if r['before'] is None else r['before']:>6}  {'' if r['now'] is None else r['now']:>6}  "
                         f"{_change(r['before'], r['now']):>6}  {'ratchet' if r['ratchet'] else 'shown':<7}  {r['verdict']}")
    bullet = "- " if markdown else "  "
    if refused:
        lines += ["", "Lines refused as waivers (they allow nothing):"] + [bullet + x for x in refused]
    if unused:
        lines += ["", "Waivers for a number that did not go down (they allow nothing):"] + [bullet + x for x in unused]
    lines += ["", "Result: a ratcheted number went down without a valid waiver." if failed
              else "Result: no ratcheted number went down without a valid waiver."]
    return _ascii("\n".join(lines))


# --------------------------------------------------------------------------- self-test


def self_test() -> int:
    """Plant changes in a copy of the sources and require each to be judged as stated, through the CLI."""
    results: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory(prefix="dodona-metrics-") as tmp:
        tmpdir = pathlib.Path(tmp)
        counter = [0]

        def copy() -> pathlib.Path:
            counter[0] += 1
            dest = tmpdir / f"r{counter[0]}"
            for rel in SOURCES:
                src = ROOT / rel
                if src.is_dir():
                    shutil.copytree(src, dest / rel, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
                else:
                    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest / rel)
            return dest

        def cli(*args: str) -> tuple[int, str]:
            proc = subprocess.run([sys.executable, "-I", str(pathlib.Path(__file__).resolve()), *args],
                                  capture_output=True, text=True, encoding="ascii", errors="replace")
            return proc.returncode, proc.stdout + proc.stderr

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

        def judge(label: str, root: pathlib.Path, expect: int, messages: str = "", against: dict | None = None,
                  must_say: str | None = None, fails: str | None = None, markdown: bool = False) -> None:
            bf = base_file
            if against is not None:
                counter[0] += 1
                bf = tmpdir / f"b{counter[0]}.json"
                bf.write_text(json.dumps(against), encoding="utf-8")
            counter[0] += 1
            mf = tmpdir / f"m{counter[0]}.txt"
            mf.write_text(messages, encoding="utf-8")
            code, out = cli("--root", str(root), "--compare", str(bf), "--messages", str(mf), *(["--markdown"] if markdown else []))
            ok = code == expect and (must_say is None or must_say in out)
            if fails is not None:
                # The row of that metric itself must carry the failure.
                row = f"| `{fails}` |" if markdown else fails + " "
                ok = ok and any(line.startswith(row) and "FAIL:" in line for line in out.splitlines())
            results.append((label, ok, f"exit {code}, expected {expect}" + (f", output must say {must_say!r}" if must_say else "")
                            + (f", the row of {fails} must fail" if fails else "")
                            + ("" if ok else "\n" + out)))

        def planted(edit) -> pathlib.Path:
            root = copy()
            edit(root)
            return root

        def replace_once(root: pathlib.Path, rel: str, old: str, new: str) -> None:
            path = root / rel
            text = path.read_text(encoding="utf-8")
            if old not in text:
                raise SystemExit(f"self-test: cannot plant: {old!r} not in {rel}")
            path.write_text(text.replace(old, new, 1), encoding="utf-8")

        def drop_list_item(root: pathlib.Path, rel: str, key: str) -> None:
            path = root / rel
            data = json.loads(path.read_text(encoding="utf-8"))
            data[key].pop()
            path.write_text(json.dumps(data), encoding="utf-8")

        good = "the scenario tested a rule the contract no longer has"

        # Controls: nothing changed, numbers that went up, and shown numbers that went down are all green.
        judge("control: nothing changed", base_root, 0)
        def add_scenario(r):
            src = sorted((r / "conformance/kernel/evidence").glob("*.json"))[0]
            shutil.copyfile(src, src.with_name("zz_planted_copy.json"))
        judge("control: a scenario added", planted(add_scenario), 0)
        judge("control: an item of 'Not yet in the kit' removed (shown only)",
              planted(lambda r: replace_once(r, "conformance/README.md", "\n- What happens when a ticket name", "\nWhat happens when a ticket name")), 0)
        judge("control: a decision accepted (status counts are shown only)",
              planted(lambda r: replace_once(r, "decisions/0001-decisions-are-nodes.md", "status: proposed", "status: accepted")), 0)

        # A scenario removed, with every kind of waiver.
        def drop_scenario(r):
            sorted((r / "conformance/kernel/evidence").glob("*.json"))[0].unlink()
        no_scenario = planted(drop_scenario)
        judge("a scenario removed, no waiver", no_scenario, 1, fails="kit.scenarios")
        judge("a scenario removed, valid waiver", no_scenario, 0,
              f"Remove a wrong scenario\n\nMetrics-down: kit.scenarios: {good}\n", must_say="allowed by waiver")
        judge("a scenario removed, waiver among other commits' text", no_scenario, 0,
              f"First commit\n\nbody\n\nSecond commit\n\n  Metrics-down: kit.scenarios: {good}\nClaude-Session: x\n")
        judge("a scenario removed, waiver reason of five words", no_scenario, 1,
              "Metrics-down: kit.scenarios: the scenario was simply wrong\n", must_say="5 words")
        judge("a scenario removed, waiver with no reason", no_scenario, 1, "Metrics-down: kit.scenarios\n", must_say="refused")
        judge("a scenario removed, waiver for another metric", no_scenario, 1, f"Metrics-down: claims.checked: {good}\n",
              must_say="did not go down")
        judge("a scenario removed, waiver for an unknown metric", no_scenario, 1, f"Metrics-down: kit.scenario: {good}\n",
              must_say="no metric is called")
        judge("a scenario removed, waiver key misspelt", no_scenario, 1, f"metrics-down: kit.scenarios: {good}\n",
              must_say="looks like a waiver")

        judge("a scenario removed, no waiver, as Markdown", no_scenario, 1, fails="kit.scenarios", markdown=True)
        judge("a scenario removed, waiver with a pipe and a backtick, as Markdown", no_scenario, 0,
              "Metrics-down: kit.scenarios: the scenario | judged `a` rule the contract dropped\n", markdown=True,
              must_say="the scenario \\| judged \\`a\\` rule")

        # A claim un-checked: the checked count is ratcheted, the unchecked count only shown.
        unchecked = planted(lambda r: replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| modelled, unchecked |"))
        judge("a claim un-checked, no waiver", unchecked, 1, fails="claims.checked")
        judge("a claim un-checked, valid waiver", unchecked, 0,
              "Metrics-down: claims.checked: the model changed and the claim awaits a new run\n")

        # Other planted drops in files.
        judge("a planted defect removed from the first kernel", planted(lambda r: drop_list_item(r, "kernel/defects.json", "defects")), 1,
              fails="planted_defects.kernel")
        judge("a planted defect removed from the second kernel", planted(lambda r: drop_list_item(r, "kernel2/defects.json", "defects")), 1,
              fails="planted_defects.kernel2")
        judge("a vector removed", planted(lambda r: drop_list_item(r, "conformance/vectors/canonical.json", "accept")), 1,
              fails="kit.vectors")
        judge("a ledger case removed", planted(lambda r: drop_list_item(r, "conformance/ledger/more-damage.json", "damage")), 1,
              fails="kit.ledger_cases")
        judge("a host check case removed", planted(lambda r: drop_list_item(r, "conformance/provider/check-cases.json", "cases")), 1,
              fails="kit.host_check_cases")
        judge("a session case removed", planted(lambda r: drop_list_item(r, "conformance/provider/cases.json", "cases")), 1,
              fails="kit.session_cases")
        def drop_gap_row(r):
            p = r / "docs/gap-checks.md"
            p.write_text("\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if not l.startswith("| `gap_readme_counts` |")) + "\n",
                         encoding="utf-8")
        judge("a gap check row removed", planted(drop_gap_row), 1, fails="gaps.gap_checks")
        judge("a decision record removed", planted(lambda r: (r / "decisions/0001-decisions-are-nodes.md").unlink()), 1,
              fails="decisions.total")
        def drop_claim_row(r):
            p = r / "spec/CLAIMS.md"
            p.write_text("\n".join(l for l in p.read_text(encoding="utf-8").splitlines() if not l.startswith("| C11 |")) + "\n",
                         encoding="utf-8")
        judge("a claim removed from the table", planted(drop_claim_row), 1, fails="claims.total")

        # What cannot be read is never counted as zero.
        judge("unreadable: 'Not yet in the kit' heading renamed",
              planted(lambda r: replace_once(r, "conformance/README.md", "## Not yet in the kit", "## Not in the kit yet")), 2)
        judge("unreadable: a claim checked by a run that is not recorded",
              planted(lambda r: replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| **checked**, run 99 |")), 2)
        judge("unreadable: a claim with an unknown status",
              planted(lambda r: replace_once(r, "spec/CLAIMS.md", "| **checked**, run 9 |", "| checked |")), 2)
        judge("unreadable: a decision with an unknown status",
              planted(lambda r: replace_once(r, "decisions/0001-decisions-are-nodes.md", "status: proposed", "status: approved")), 2)
        def upper_vectors(r):
            shutil.copyfile(r / "conformance/vectors/paths.json", r / "conformance/vectors/Paths2.json")
        judge("unreadable: a vectors file whose name cannot be a metric", planted(upper_vectors), 2, must_say="cannot measure")
        judge("unreadable: a claims file that is not UTF-8",
              planted(lambda r: (r / "spec/CLAIMS.md").write_bytes(b"\xff\xfe| C1 |")), 2, must_say="not UTF-8")
        judge("unreadable: defects file is not JSON",
              planted(lambda r: (r / "kernel/defects.json").write_text("{", encoding="utf-8")), 2)
        judge("unreadable: earlier file has the wrong format", base_root, 2, against={"format": "other", "metrics": {}})
        bad = json.loads(json.dumps(baseline))
        bad["metrics"]["kit.scenarios"]["value"] = "150"
        judge("unreadable: earlier file has a value that is not an integer", base_root, 2, against=bad)

        # Every ratchet can go red, and nothing shown only can.
        for name in ratcheted:
            higher = json.loads(json.dumps(baseline))
            higher["metrics"][name]["value"] += 1
            judge(f"ratchet {name}: one lower than before", base_root, 1, against=higher, fails=name)
        for name in shown:
            higher = json.loads(json.dumps(baseline))
            higher["metrics"][name]["value"] += 1
            judge(f"shown {name}: one lower than before is no failure", base_root, 0, against=higher)
        gone = json.loads(json.dumps(baseline))
        gone["metrics"]["kit.vectors.planted_gone"] = {"value": 3, "ratchet": True, "source": "x"}
        judge("a ratcheted metric that is gone", base_root, 1, against=gone, must_say="gone, was ratcheted")
        judge("a ratcheted metric that is gone, with a waiver", base_root, 0, against=gone,
              messages=f"Metrics-down: kit.vectors.planted_gone: {good}\n")
        gone_shown = json.loads(json.dumps(baseline))
        gone_shown["metrics"]["kit.vectors.planted_gone"] = {"value": 3, "ratchet": False, "source": "x"}
        judge("a shown metric that is gone", base_root, 0, against=gone_shown)
        loosened = json.loads(json.dumps(baseline))
        loosened["metrics"][shown[0]]["ratchet"] = True
        judge("a ratchet taken away", base_root, 1, against=loosened, must_say="no longer ratcheted")

    failed = [r for r in results if not r[1]]
    for label, ok, detail in results:
        print(_ascii(f"{'ok  ' if ok else 'FAIL'}  {label}" + ("" if ok else f": {detail}")))
    print(f"\n{len(results) - len(failed)} of {len(results)} planted changes judged as expected "
          f"({len(ratcheted)} ratcheted metrics, each seen to go red)")
    return 1 if failed else 0


# --------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", nargs="?", choices=["self-test"])
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    parser.add_argument("--compare", metavar="FILE", help="compare with an earlier --json output")
    parser.add_argument("--messages", metavar="FILE", help="commit messages to read waivers from (with --compare)")
    parser.add_argument("--markdown", action="store_true", help="print tables as Markdown")
    parser.add_argument("--commit", metavar="SHA", help="the commit measured, recorded in --json output")
    parser.add_argument("--root", metavar="DIR", default=str(ROOT), help="the repository to measure")
    args = parser.parse_args(argv)

    if args.mode == "self-test":
        return self_test()
    try:
        return run(args)
    except Exception as err:  # noqa: BLE001 - a crash must never read as "a ratchet went down" (exit 1)
        print(_ascii(f"cannot measure: unexpected {type(err).__name__}: {err}"), file=sys.stderr)
        return 2


def run(args) -> int:
    try:
        metrics = measure(pathlib.Path(args.root))
    except Unmeasurable as err:
        print(_ascii(f"cannot measure: {err}"), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(as_json(metrics, args.commit), indent=2))
        return 0
    if not args.compare:
        print(table(metrics, args.markdown))
        return 0
    try:
        old = read_baseline(pathlib.Path(args.compare))
        messages = pathlib.Path(args.messages).read_text(encoding="utf-8") if args.messages else ""
    except BadBaseline as err:
        print(_ascii(f"cannot compare: {err}"), file=sys.stderr)
        return 2
    except OSError as err:
        print(_ascii(f"cannot read the commit messages: {err}"), file=sys.stderr)
        return 2
    rows, refused, unused, failed = compare(old, metrics, messages)
    print(comparison(old, rows, refused, unused, failed, args.markdown))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
