"""Checks of this repository that need no model checker and run on any platform.

    python tools/check_repo.py

Stage-0 helper (decision 0023): disposable, to be replaced by dodona itself.
Exit status is 0 only if every check passed.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
from functools import cache
import io
import hashlib
import json
import pathlib
import os
import tempfile
import subprocess
import re
import sys
import tomllib
import types
import unittest
import zipfile
from unittest import mock
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_models  # noqa: E402
import kit_adequacy  # noqa: E402
import pathcheck  # noqa: E402
import run_attest_check  # noqa: E402
import run_check_cases  # noqa: E402
import run_harness_check  # noqa: E402
harness = run_harness_check.harness
import run_input_cases  # noqa: E402
import run_key_vectors  # noqa: E402
import run_kit  # noqa: E402
import run_ledger_cases  # noqa: E402
import run_path_vectors  # noqa: E402
import run_provider_cases  # noqa: E402
import run_run_cases  # noqa: E402
import run_status_cases  # noqa: E402
import run_vectors  # noqa: E402

problems: list[str] = []

SKIPPED_PARTS = {".git", "__pycache__", "target", "node_modules"}


def repo_files(pattern: str = "**/*"):
    """Files that belong to the repository: not version control data, caches or build output."""
    return [p for p in sorted(ROOT.glob(pattern))
            if p.is_file() and not SKIPPED_PARTS & set(p.relative_to(ROOT).parts)]



def check_json_and_toml() -> None:
    for path in repo_files("**/*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except ValueError as err:
            problems.append(f"{path.relative_to(ROOT).as_posix()}: not valid JSON: {err}")
    for path in sorted(ROOT.glob("*.toml")):
        try:
            tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as err:
            problems.append(f"{path.name}: not valid TOML: {err}")


def check_links() -> None:
    link = re.compile(r"\]\(([^)#\s]+)(#[^)]*)?\)")
    for path in repo_files("**/*.md"):
        for target, _ in link.findall(path.read_text(encoding="utf-8")):
            if re.match(r"[a-z]+://", target):
                continue
            if not (path.parent / target).exists():
                problems.append(f"{path.relative_to(ROOT).as_posix()}: broken link to {target}")


def check_line_endings() -> None:
    for path in repo_files():
        if "conformance" in path.parts:
            continue
        if path.suffix in {".md", ".json", ".toml", ".tla", ".cfg", ".py", ".yml", ".rs"}:
            data = path.read_bytes()
            if b"\r\n" in data:
                problems.append(f"{path.relative_to(ROOT).as_posix()}: has CRLF line endings")
            if data.startswith(b"\xef\xbb\xbf"):
                problems.append(f"{path.relative_to(ROOT).as_posix()}: starts with a byte-order mark")


def check_model_cases() -> None:
    for expected in sorted(ROOT.glob("spec/*/expected.json")):
        spec = json.loads(expected.read_text(encoding="utf-8"))
        listed = {c["config"] for c in spec["cases"]}
        present = {p.name for p in expected.parent.glob("*.cfg")} - {"dump.cfg"}  # writes out states; judged by check_states
        for name in sorted(listed - present):
            problems.append(f"{expected.parent.name}: {name} is listed but missing")
        for name in sorted(present - listed):
            problems.append(f"{expected.parent.name}: {name} exists but has no expected outcome")
        for case in spec["cases"]:
            if case["expect"] in ("violation", "temporal-violation") and "of" not in case:
                problems.append(f"{expected.parent.name}: {case['config']} expects a violation of nothing")
            root = case.get("model", spec["model"])
            if not (expected.parent / root).exists():
                problems.append(f"{expected.parent.name}: root module {root} is missing")


def check_claims_match_runs() -> None:
    """A claim may be marked checked only while a recorded run still matches the model files."""
    claims = (ROOT / "spec" / "CLAIMS.md").read_text(encoding="utf-8")
    index = json.loads((ROOT / "spec" / "runs" / "index.json").read_text(encoding="utf-8"))
    current = {}
    for run in index["runs"]:
        folder = ROOT / "spec" / run["model"]
        current[run["id"]] = all(
            (folder / name).exists()
            and hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest
            for name, digest in run["files"].items()
        ) and all(
            (ROOT / name).exists() and hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
            for name, digest in run.get("other_files", {}).items()
        ) and (ROOT / "spec" / "runs" / run["outputs"]).is_dir()
    # A run supports claims only if it was recorded against the expected outcomes too, every file
    # it kept is hashed in the index, and its saved output, judged again by the provider's own
    # judge, still matches every case listed. A run of the kernel over every state ("kind":
    # "dump") has no cases; its outputs are hashed, and what they show is judged by the run that
    # reads them. A run replaced by a later one ("superseded_by") supports nothing.
    sys.path.insert(0, str(ROOT / "providers" / "tlc"))
    from judge import judge  # noqa: E402

    needed = {n for run in index["runs"] for n in run.get("needs", [])}
    for run in index["runs"]:
        rid = run["id"]
        if run.get("superseded_by"):
            current[rid] = False
            continue
        if not current[rid] or not (run["claims"] or rid in needed):
            continue
        out = ROOT / "spec" / "runs" / run["outputs"]

        def refuse(why: str) -> None:
            problems.append(f"spec/runs/index.json: run {rid} cannot support its claims: {why}")
            current[rid] = False

        kept = {f.name for f in out.iterdir() if f.is_file()}
        digests = run.get("outputs_sha256")
        if not isinstance(digests, dict) or set(digests) != kept:
            refuse("the hash of every output file it kept is not listed")
            continue
        if any(hashlib.sha256((out / n).read_bytes()).hexdigest() != d for n, d in digests.items()):
            refuse("an output file is not the one recorded")
            continue
        if run.get("kind") == "dump":
            continue
        if "expected.json" not in run["files"]:
            refuse("expected.json is not among the files it was run on")
            continue
        cases = json.loads((ROOT / "spec" / run["model"] / "expected.json").read_text(encoding="utf-8"))["cases"]
        unhashed = [c["config"] for c in cases if c["config"] not in run["files"]]
        if unhashed:
            refuse(f"configurations {unhashed} are not among the files it was run on")
            continue
        listed = {c["config"].removesuffix(".cfg") + ext for c in cases for ext in (".txt", ".exit")}
        if kept != listed:
            refuse(f"its outputs {sorted(kept ^ listed)} do not match the cases in expected.json")
            continue
        for case in cases:
            name = case["config"].removesuffix(".cfg")
            try:
                code = int((out / f"{name}.exit").read_text(encoding="ascii").strip())
            except (ValueError, UnicodeDecodeError):
                refuse(f"{name}.exit does not hold an exit code")
                break
            verdict = judge(case, code, (out / f"{name}.txt").read_text(encoding="utf-8", errors="replace"))
            if not verdict["match"]:
                refuse(f"the saved output of {name} shows {verdict['outcome']}, not what expected.json says")
                break
    supported = set()
    for run in index["runs"]:
        if current[run["id"]] and all(current.get(n) for n in run.get("needs", [])):
            supported.update(run["claims"])
    for row in re.findall(r"^\| (C\d+) \|.*\*\*checked\*\*.*$", claims, flags=re.M):
        if row not in supported:
            problems.append(f"spec/CLAIMS.md marks {row} as checked, but no recorded run matches the current model files")


def check_indexes() -> None:
    for folder in ("decisions", "intents"):
        index = (ROOT / folder / "README.md").read_text(encoding="utf-8")
        for path in sorted((ROOT / folder).glob("[0-9]*.md")):
            if f"({path.name})" not in index:
                problems.append(f"{folder}/README.md does not list {path.name}")


# ---------------------------------------------------------------------------
# Gap checks. Each one exists because a gap was found once, by a review or by
# a mistake. The rule (AGENTS.md): a gap that is found becomes a check here.
# docs/gap-checks.md lists each check with the gap behind it.


def _claims_rows() -> list[tuple[str, str]]:
    text = (ROOT / "spec" / "CLAIMS.md").read_text(encoding="utf-8")
    return [(m.group(1), m.group(0)) for m in re.finditer(r"^\| (C\d+) \|.*$", text, flags=re.M)]


def gap_readme_counts() -> None:
    """The README once said 9 claims were checked after a model change left 6."""
    rows = _claims_rows()
    checked = sum(1 for _, row in rows if "**checked**" in row)
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"\| \*\*Checked so far\*\* \| (\d+) of (\d+) design claims", readme)
    if not m:
        problems.append("README.md: the 'Checked so far' line is missing or reworded")
    elif (int(m.group(1)), int(m.group(2))) != (checked, len(rows)):
        problems.append(f"README.md says {m.group(1)} of {m.group(2)} claims checked; CLAIMS.md has {checked} of {len(rows)}")
    decisions = len(list((ROOT / "decisions").glob("[0-9]*.md")))
    m = re.search(r"(\d+) proposed decisions", readme)
    if not m or int(m.group(1)) != decisions:
        problems.append(f"README.md decision count does not match the {decisions} records in decisions/")
    counts = []
    for name in ("kernel/defects.json", "kernel2/defects.json"):
        data = json.loads((ROOT / name).read_text(encoding="utf-8"))
        counts.append(len(data["defects"] if isinstance(data, dict) else data))
    m = re.search(r"(\d+) planted defects, (\d+) in one kernel and (\d+) in the other", readme)
    if not m or [int(m.group(2)), int(m.group(3))] != counts or int(m.group(1)) != sum(counts):
        problems.append(f"README.md: the planted-defect counts must say {sum(counts)}, {counts[0]} in one kernel and {counts[1]} in the other")
    claims = (ROOT / "spec" / "CLAIMS.md").read_text(encoding="utf-8")
    if f"{counts[0]} in the first kernel and {counts[1]} in the second" not in claims:
        problems.append(f"spec/CLAIMS.md C20: the counts must say {counts[0]} in the first kernel and {counts[1]} in the second")
    ids = [cid for cid, _ in rows]
    if len(ids) != len(set(ids)):
        problems.append("spec/CLAIMS.md lists a claim id twice")


def gap_kit_shown_claims_are_exercised() -> None:
    """A claim could be listed as shown by the kit while nothing ran the tool that shows it."""
    text = (ROOT / "spec" / "CLAIMS.md").read_text(encoding="utf-8")
    start = text.find("## Shown by the conformance kit")
    if start < 0:
        problems.append("spec/CLAIMS.md: the section of claims shown by the kit is missing")
        return
    section = text[start:].split("\n## ")[0]
    workflow = (ROOT / ".github" / "workflows" / "checks.yml").read_text(encoding="utf-8")
    for row in re.findall(r"^\| C\d+ \|.*$", section, flags=re.M):
        cells = [c.strip() for c in row.strip("|").split("|")]
        tools = re.findall(r"`(tools/\w+\.py)`", cells[3])
        if not tools:
            problems.append(f"spec/CLAIMS.md {cells[0]}: no tool is named as exercising it")
        for tool in tools:
            if not (ROOT / tool).exists():
                problems.append(f"spec/CLAIMS.md {cells[0]}: {tool} does not exist")
            elif tool not in workflow:
                problems.append(f"spec/CLAIMS.md {cells[0]}: {tool} is not run by .github/workflows/checks.yml")
        if "**checked**" in row or not cells[-1].startswith("sampled"):
            problems.append(f"spec/CLAIMS.md {cells[0]}: a claim shown by the kit must be marked sampled, never checked")


def gap_kit_judge_hides_the_answers() -> None:
    """The kit judge sent each scenario to the kernel whole; a program that echoed the expected results passed all of them."""
    asked = run_kit.question({"kind": "k", "claim": "C0", "covers": ["x"], "why": "w", "steps": [{"do": {"a": 1}, "expect": {"b": 2}}]})
    if "expect" in json.dumps(asked) or any(k in asked for k in ("claim", "covers", "why")):
        problems.append("tools/run_kit.py shows the kernel the expected results or the notes about a scenario")


def gap_generated_kit_files_are_current() -> None:
    """Kit files with hashes and keyed check values are generated; an edit by hand, or to the generator alone, would leave them wrong."""
    other = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_wrong_types.py"), "--check"], capture_output=True, text=True)
    if other.returncode != 0:
        problems.append("the wrong-type scenarios differ from what tools/gen_wrong_types.py writes: " + (other.stdout + other.stderr).strip()[-200:])
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_kit_vectors.py"), "--check"], capture_output=True, text=True)
    if done.returncode != 0:
        problems.append("the generated kit files differ from what tools/gen_kit_vectors.py writes: " + (done.stdout + done.stderr).strip()[-200:])


def gap_driver_refuses_outside_the_queue() -> None:
    """The file that starts the model checker could be run by hand on any machine. It must refuse before reading anything."""
    driver = ROOT / ".github" / "site" / "batch_driver.py"
    with tempfile.TemporaryDirectory() as tmp:
        for extra in ({}, {"TLA_QUEUE_JOB": "0123456789abcdef0123456789abcdef"}):
            env = {k: v for k, v in os.environ.items() if k != "TLA_QUEUE_JOB"} | extra
            done = subprocess.run([sys.executable, "-I", str(driver), "no-such-manifest.json"], cwd=tmp, env=env, capture_output=True)
            if done.returncode != 78 or os.listdir(tmp):
                problems.append(".github/site/batch_driver.py did not refuse to run outside a job of the queue"
                                + (" when given a made-up job marker" if extra else ""))


def gap_an_unfinished_job_proves_nothing() -> None:
    """Results were once recorded from a job the queue had stopped part of the way, and a tool nobody measured looked the same as one not yet pinned."""
    import host
    cases = [({"reachable": False, "complete": False}, [], [], "unavailable"),
             ({"reachable": True, "complete": False}, [], [], "job-incomplete"),
             ({"reachable": True}, [], [], "job-incomplete"),
             ({"reachable": True, "complete": True}, ["java"], [], "tool-unmeasured"),
             ({"reachable": True, "complete": True}, [], ["java"], "tool-mismatch"),
             ({"reachable": True, "complete": True}, [], [], None)]
    for runs, unmeasured, mismatched, want in cases:
        if host.proves_nothing(runs, unmeasured, mismatched) != want:
            problems.append(f"tools/host.py: a job with {runs}, unmeasured {unmeasured}, mismatched {mismatched} must give {want}")
    # The queue can mark a job failed after every file is written. Files alone must not be enough.
    fake = ("import sys, json, pathlib\n"
            "dest, code, marker = pathlib.Path(sys.argv[1]) / 'out', int(sys.argv[2]), sys.argv[3] == 'marker'\n"
            "(dest / 'm').mkdir(parents=True)\n"
            "(dest / 'm' / 'c.txt').write_text('x'); (dest / 'm' / 'c.exit').write_text('0')\n"
            "(dest / 'measured.json').write_text(json.dumps({'/j': 'aa', '/t': 'bb'}))\n"
            "if marker: (dest / 'complete.json').write_text(json.dumps({'cases': ['m/c']}))\n"
            "sys.exit(code)\n")
    for code, marker, want in ((0, "marker", True), (75, "marker", False), (0, "none", False)):
        with tempfile.TemporaryDirectory() as tmp:
            script = pathlib.Path(tmp) / "fake_queue.py"
            script.write_text(fake, encoding="utf-8")
            bundle = pathlib.Path(tmp) / "bundle"
            bundle.mkdir()
            site = {"tool_files": {"java/bin/java": "/j", "tla2tools/tla2tools.jar": "/t"},
                    "batch_command": [sys.executable, str(script), "{dest}", str(code), marker]}
            with contextlib.redirect_stdout(io.StringIO()):
                job = host.send_job(site, bundle, [{"name": "m/c", "cwd": ".", "argv": ["x"]}])
            if job["complete"] is not want:
                problems.append(f"tools/host.py: a job whose queue client exits {code} with end marker {marker} must count as complete={want}")
    models = (ROOT / "tools" / "check_models.py").read_text(encoding="utf-8")
    if "host.send_job" not in models or "subprocess.run" in models:
        problems.append("tools/check_models.py must send jobs only through tools/host.py and start nothing itself")
    workflow = (ROOT / ".github" / "workflows" / "models.yml").read_text(encoding="utf-8")
    if "check_models.py --replay" in workflow or "check_models.py --runs" not in workflow:
        problems.append(".github/workflows/models.yml must judge with --runs, which refuses an unfinished job; --replay is for looking only")
    driver = (ROOT / ".github" / "site" / "batch_driver.py").read_text(encoding="utf-8")
    if not (driver.find("measured.json") < driver.find("subprocess.run(case") < driver.find("complete.json")):
        problems.append(".github/site/batch_driver.py must measure its tools before the first case and write its marker after the last")


def gap_tool_tree_digest_matches_its_vectors() -> None:
    """How a tool tree's digest is computed was unwritten, so a lock could not have been checked by anyone else."""
    import tooltree
    vectors = json.loads((ROOT / "conformance" / "vectors" / "tool-tree.json").read_text(encoding="utf-8"))
    for item in vectors["accept"]:
        try:
            got = tooltree.digest(item["items"])
        except tooltree.Unusable as err:
            got = f"refused: {err}"
        if got != item["digest"]:
            problems.append(f"tool-tree vectors: '{item['name']}' must have digest {item['digest']}, the reference gives {got}")
    for item in vectors["reject"]:
        try:
            problems.append(f"tool-tree vectors: '{item['name']}' must be refused, the reference gives {tooltree.digest(item['items'])}")
        except tooltree.Unusable as err:
            if str(err) != item["reason"]:
                problems.append(f"tool-tree vectors: '{item['name']}' must be refused as {item['reason']}, not {err}")
    if len(vectors["accept"]) < 5 or len(vectors["reject"]) < 5:
        problems.append("tool-tree vectors: too few to mean anything")


def gap_tool_tree_refuses_an_incomplete_listing() -> None:
    """A review denied the listing of one directory inside a tree: the reference walked past it without a word
    and printed a digest for the rest. A listing that misses part of the tree must be refused, not digested."""
    import runpy
    import tooltree
    real_scandir, real_read_bytes = os.scandir, pathlib.Path.read_bytes

    def denying(name: str):
        def scandir(path="."):
            if not isinstance(path, int) and os.path.basename(os.fspath(path)) == name:
                raise PermissionError(13, "denied by the repository check", os.fspath(path))
            return real_scandir(path)
        return scandir

    def refusing(name: str):
        def read_bytes(self):
            if self.name == name:
                raise PermissionError(13, "denied by the repository check", str(self))
            return real_read_bytes(self)
        return read_bytes

    def outcome(root: pathlib.Path) -> str:
        try:
            return f"the digest {tooltree.digest(tooltree.listing(root))}"
        except tooltree.Unusable as err:
            return f"refused: {err}"
        except OSError as err:
            return f"an unhandled {type(err).__name__}"

    def command(root: pathlib.Path) -> str:
        out, argv = io.StringIO(), sys.argv
        try:
            sys.argv = ["tooltree.py", str(root)]
            with contextlib.redirect_stdout(out):
                runpy.run_path(str(ROOT / "tools" / "tooltree.py"), run_name="__main__")
            code = 0
        except SystemExit as stop:
            code = stop.code
        except Exception as err:  # an error the command line lets escape, Unusable included
            code = f"an unhandled {type(err).__name__}"
        finally:
            sys.argv = argv
        return f"exit {code}, printing {out.getvalue().strip()}"

    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp) / "tree"
        (root / "sub").mkdir(parents=True)
        contents = {"top.txt": b"top", "sub/inner.txt": b"inner"}
        for path, data in contents.items():
            (root / path).write_bytes(data)
        whole = [{"path": p, "kind": "file", "identity": "sha256:" + hashlib.sha256(d).hexdigest()} for p, d in contents.items()]
        # The controls: a tree read in full keeps its digest, and a directory that is not there is still an empty tree.
        if outcome(root) != f"the digest {tooltree.digest(whole)}":
            problems.append(f"tools/tooltree.py gives a tree it can read in full {outcome(root)}, not the digest of its two files")
        if outcome(root / "missing") != "refused: empty":
            problems.append(f"tools/tooltree.py gives a directory that does not exist {outcome(root / 'missing')}, not refused: empty")
        for name, patch in (("a child directory it may not list", mock.patch("os.scandir", denying("sub"))),
                            ("a root directory it may not list", mock.patch("os.scandir", denying("tree"))),
                            ("a file it may not read", mock.patch.object(pathlib.Path, "read_bytes", refusing("inner.txt")))):
            with patch:
                got, shown = outcome(root), command(root)
            if got != "refused: unreadable":
                problems.append(f"tools/tooltree.py: a tree with {name} must be refused as unreadable; the reference gives {got}")
            if shown != 'exit 1, printing {"refused": "unreadable"}':
                problems.append(f"tools/tooltree.py: a tree with {name} must be refused as unreadable on its command line; it gives {shown}")


def gap_thin_coverage_is_shown() -> None:
    """Counting the floor over a whole tree lets a child be delivered with fewer hard gates of its own
    than policy demands (decision 0030). The owner chose to keep that rule and see where it happens."""
    import status
    hard = {"words": "w", "gate": "hard", "checked_by": []}
    soft = {"words": "w", "gate": "soft", "checked_by": []}
    tree = {"r": {"children": ["a", "b"], "criteria": {"1": hard, "2": hard}},
            "a": {"children": [], "criteria": {"1": hard}},
            "b": {"children": [], "criteria": {"1": hard, "2": hard, "3": soft}}}
    where = status.coverage(tree, 2)
    if where["thinnest"] != {"r": "a"}:
        problems.append(f"status.coverage names {where['thinnest']} as the thinnest intent, not a")
    flagged = sorted(i for i, x in where["intents"].items() if x["floor_met_only_over_tree"])
    if flagged != ["a"]:
        problems.append(f"status.coverage marks {flagged} as meeting the floor only over the tree, not a alone")
    report = {"project": {"status": "open"}, "obligations": {}, "coverage": where,
              "intents": {i: {"status": "delivered", "gates": {"hard": 1, "soft": 0, "deferred": 0, "deferred_open": 0},
                              "score": {"met": 1, "of": 1}, "shown": {}, "exceptions": {},
                              "separation": {"weakest": "self", "act": "x", "apart_or_better": 0, "of": 0}} for i in tree}}
    text = status.render(report, False, 0, "")
    if "thinnest in tree r: intent a" not in text or "met only over tree r" not in text:
        problems.append("the status report does not show where a tree's hard gates are thin")


def gap_every_tool_compiles() -> None:
    """A syntax error in the status command reached the branch because nothing ran that file."""
    for path in sorted(list((ROOT / "tools").glob("*.py")) + list((ROOT / "providers").rglob("*.py"))
                       + list((ROOT / "conformance").rglob("*.py")) + repo_files(".github/**/*.py")):
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")  # checks syntax, writes nothing
        except SyntaxError as err:
            problems.append(f"{path.relative_to(ROOT)} does not compile: line {err.lineno}: {err.msg}")


def gap_an_intent_reads_one_way_only() -> None:
    """Free-form criteria tables could always be written so that a person and the reader saw different things,
    and results written by hand into the owner's ledger counted as passed."""
    import intents
    problems_before = len(problems)  # noqa: F841
    try:
        for path in sorted((ROOT / "intents").glob("[0-9]*.md")):
            intents.read(path)
    except intents.Unreadable as err:
        problems.append(f"intents: {err}")
    sample = sorted((ROOT / "intents").glob("[0-9]*.md"))[0].read_text(encoding="utf-8")
    fields, body = intents.front(sample)
    head = sample[: len(sample) - len(body)]
    shown = body[body.index(intents.BEGIN): body.index(intents.END) + len(intents.END)]
    tampered = {
        "an extra row outside the table": body + "\n|  | Every release is signed | hard | nobody |\n",
        "a table in a blockquote": body + "\n> | 9 | x | hard | y |\n",
        "an HTML table": body + "\n<table><tr><td>9</td><td>hard</td></tr></table>\n",
        "a code block": body + "\n```\n| 9 | x | hard | y |\n```\n",
        "a hidden comment": body + "\n<!-- x -->\n",
        "the table wrapped in an attribute": body.replace(shown, '<p title="\n' + shown + '\n">'),
        "a table without leading bars": body + "\nNo. | Criterion | Gate | Checked by\n:-|-|-|-\n2 | Runs on Windows | hard | x\n",
        "an entity": body + "\nA &lt;b&gt; tag\n",
        "a second closer with a trailing space": body + "\n--- \n",
        "markup in the front matter": None,
        "a hand-edited table": body.replace(shown, shown.replace("| hard |", "| soft |", 1)) if "| hard |" in shown else body + "|",
    }
    with tempfile.TemporaryDirectory() as tmp:
        for name, new_body in tampered.items():
            path = pathlib.Path(tmp) / "0001-probe.md"
            if new_body is None:
                path.write_text(sample.replace("\ntitle: ", "\ntitle: <details> ", 1), encoding="utf-8")
            else:
                path.write_text(head + new_body, encoding="utf-8")
            try:
                intents.read(path)
                problems.append(f"tools/intents.py reads an intent with {name} without refusing it")
            except intents.Unreadable:
                pass
        for field, bad in (("words", "Runs</td><td>hard</td></tr><tr><td colspan=4>"), ("checks", ["a|b"]), ("checked_by", "*emphasis*")):
            items = json.loads(fields["criteria"])
            items[0][field] = bad
            changed = sample.replace(fields["criteria"], json.dumps(items))
            old_table = changed[changed.index(intents.BEGIN): changed.index(intents.END) + len(intents.END)]
            path = pathlib.Path(tmp) / "0001-probe.md"
            try:
                path.write_text(changed.replace(old_table, intents.table(items)), encoding="utf-8")
                intents.read(path)
                problems.append(f"tools/intents.py accepts a criterion whose {field} is {bad!r}")
            except intents.Unreadable:
                pass
        for bad in ('"Hard"', '"hard\\u200b"'):
            path = pathlib.Path(tmp) / "0001-probe.md"
            changed = sample.replace('"gate": "hard"', f'"gate": {bad}', 1)
            items = json.loads(intents.front(changed)[0]["criteria"])
            old_table = changed[changed.index(intents.BEGIN): changed.index(intents.END) + len(intents.END)]
            path.write_text(changed.replace(old_table, intents.table(items)), encoding="utf-8")  # only the gate rule can refuse it
            try:
                intents.read(path)
                problems.append(f"tools/intents.py accepts a gate written {bad}")
            except intents.Unreadable:
                pass
        # A deferred gate says what is observed and within how many days (decision 0018); no other gate does.
        items = json.loads(fields["criteria"])
        deferred = next(i for i, c in enumerate(items) if c["gate"] == "deferred")
        other = next(i for i, c in enumerate(items) if c["gate"] != "deferred")
        for name, change in (("a deferred criterion without its condition", lambda c: c[deferred].pop("condition")),
                             ("a deferred criterion without its limit", lambda c: c[deferred].pop("limit_days")),
                             ("a limit of 0 days", lambda c: c[deferred].update(limit_days=0)),
                             ("a limit written as text", lambda c: c[deferred].update(limit_days="30")),
                             ("a limit written with a fractional part", lambda c: c[deferred].update(limit_days=30.0)),
                             ("a limit that is true", lambda c: c[deferred].update(limit_days=True)),
                             ("a condition with markup", lambda c: c[deferred].update(condition="<b>seen</b>")),
                             ("a condition of spaces", lambda c: c[deferred].update(condition=" ")),
                             ("a condition with a space at its end", lambda c: c[deferred].update(condition="seen ")),
                             ("a condition without a word", lambda c: c[deferred].update(condition="1 2")),
                             ("a note ending in a line feed", lambda c: c[deferred].update(checked_by="seen\n")),
                             ("words ending in a line feed", lambda c: c[deferred].update(words="seen\n")),
                             ("an emoji code in a condition", lambda c: c[deferred].update(condition="seen :100: times")),
                             ("a criterion that is not deferred with a condition", lambda c: c[other].update(condition="seen")),
                             ("a criterion that is not deferred with a limit", lambda c: c[other].update(limit_days=1)),
                             ("a soft criterion with a condition and a limit", lambda c: c[other].update(gate="soft", condition="seen", limit_days=1))):
            changed_items = json.loads(fields["criteria"])
            change(changed_items)
            path = pathlib.Path(tmp) / "0001-probe.md"
            changed = sample.replace(fields["criteria"], json.dumps(changed_items))
            old_table = changed[changed.index(intents.BEGIN): changed.index(intents.END) + len(intents.END)]
            try:
                path.write_text(changed.replace(old_table, intents.table(changed_items)), encoding="utf-8")
                intents.read(path)
                problems.append(f"tools/intents.py accepts {name}")
            except intents.Unreadable:
                pass
        # A field named twice in one criterion: json keeps the last, a person may read the first.
        path = pathlib.Path(tmp) / "0001-probe.md"
        doubled = fields["criteria"].replace('"gate": "deferred"', '"gate": "hard", "gate": "deferred"', 1)
        path.write_text(sample.replace(fields["criteria"], doubled), encoding="utf-8")
        try:
            intents.read(path)
            problems.append("tools/intents.py accepts a criterion that names a field twice")
        except intents.Unreadable:
            pass
        # The front matter: keys no reader takes, a key twice, and an id or parent spelled another way.
        for name, old, new in (("a front-matter key given twice", "\ntitle: ", "\ntitle: Another\ntitle: "),
                               ("a key no reader takes, named like a criterion's field", "\ntitle: ", "\nlimit_days: 400\ntitle: "),
                               ("an id in single quotes", 'id: "0001"', "id: '0001'"),
                               ("an id with a space after it", 'id: "0001"', 'id: "0001" '),
                               ("an id without quotes", 'id: "0001"', "id: 1"),
                               ("an id that is not the file's number", 'id: "0001"', 'id: "0009"'),
                               ("a parent in single quotes", 'parent: ""', "parent: ''")):
            path.write_text(sample.replace(old, new, 1), encoding="utf-8")
            try:
                intents.read(path)
                problems.append(f"tools/intents.py accepts {name}")
            except intents.Unreadable:
                pass
        # An id of another form in a file named to match it: only the rule on how an id is written refuses it.
        short = pathlib.Path(tmp) / "1-probe.md"
        short.write_text(sample.replace('id: "0001"', 'id: "1"', 1), encoding="utf-8")
        try:
            intents.read(short)
            problems.append("tools/intents.py accepts an id that is not four digits")
        except intents.Unreadable:
            pass
        # Plain text that states a deadline of its own, says nothing, or is a time (which must still be read).
        for name, change, refused in (("words of a space", lambda c: c[deferred].update(words=" "), True),
                                      ("words with a space at the end", lambda c: c[deferred].update(words="seen "), True),
                                      ("a note without a word", lambda c: c[deferred].update(checked_by="1 2"), True),
                                      ("an emoji code followed by a digit", lambda c: c[deferred].update(condition="seen :x:1 times"), True),
                                      ("words with a number of days, which a hard criterion may state", lambda c: c[other].update(words="Logs are kept for 30 days"), False),
                                      ("a note holding a time, which is not an emoji", lambda c: c[deferred].update(checked_by="Runs at 02:00:00 in CI"), False)):
            changed_items = json.loads(fields["criteria"])
            change(changed_items)
            changed = sample.replace(fields["criteria"], json.dumps(changed_items))
            old_table = changed[changed.index(intents.BEGIN): changed.index(intents.END) + len(intents.END)]
            path.write_text(changed.replace(old_table, intents.table(changed_items)), encoding="utf-8")
            try:
                intents.read(path)
                if refused:
                    problems.append(f"tools/intents.py accepts {name}")
            except intents.Unreadable as err:
                if not refused:
                    problems.append(f"tools/intents.py refuses {name}: {err}")
        # Two files with one id: which one counts would depend on the order they are listed in.
        twin = pathlib.Path(tmp) / "0001-twin.md"
        twin.write_text(sample, encoding="utf-8")
        path.write_text(sample, encoding="utf-8")
        if not intents.check_all([path, twin]):
            problems.append("tools/intents.py accepts two intent files with one id")
    # What the owner confirms shows each deferred criterion's observation and limit, in its own column, and the
    # limit is one policy allows.
    import tomllib
    longest = tomllib.loads((ROOT / "policy.toml").read_text(encoding="utf-8")).get("gates", {}).get("max_deferred_days")
    for path in sorted((ROOT / "intents").glob("[0-9]*.md")):
        try:
            _, items, text = intents.read(path)
        except intents.Unreadable:
            continue
        for c in items:
            if c["gate"] != "deferred":
                continue
            row = f"| {c['id']} | {c['words']} | deferred | {intents.shown_checks(c)} | within {c['limit_days']} days of delivery: {c['condition']} |"
            if row not in text:
                problems.append(f"{path.name}: criterion {c['id']}'s observation and limit are not shown in a column of their own")
            if isinstance(longest, int) and c["limit_days"] > longest:
                problems.append(f"{path.name}: criterion {c['id']} has a limit of {c['limit_days']} days; policy.toml allows at most {longest}")
    import confirm
    shown = "\n".join(confirm.observation_lines({"gate": "deferred", "condition": "seen on a probe", "limit_days": 120},
                                                {"gates": {"max_deferred_days": 90}}))
    if "seen on a probe" not in shown or "120" not in shown or "longer than policy allows" not in shown:
        problems.append("tools/confirm.py must show each deferred criterion's observation and limit, and warn of a limit above policy, "
                        f"before the owner agrees: {shown!r}")
    import status
    with tempfile.TemporaryDirectory() as tmp:
        sample = sorted((ROOT / "intents").glob("[0-9]*.md"))[0]
        for name in (sample.name, sample.name[:5] + "twin.md"):
            (pathlib.Path(tmp) / name).write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            status.read_intents([], pathlib.Path(tmp))
            problems.append("tools/status.py reports a status when two intent files have one id")
        except SystemExit:
            pass
    source = (ROOT / "tools" / "status.py").read_text(encoding="utf-8")
    if 'e.get("kind") == "act"' not in source or "OWNER_LEDGER.resolve()" not in source:
        problems.append("tools/status.py must read only acts from the owner's ledger, and compare ledger paths after resolving them")


def gap_runner_versions_agree() -> None:
    """A version bump that touches one runner line and not the others leaves steps that run only on a named
    system matching nothing, and those steps then skip without a word. Every workflow uses one Ubuntu
    version, and every condition on a named system names one its file's matrix actually has."""
    versions: dict[str, list[str]] = {}
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for found in re.findall(r"ubuntu-\d+\.\d+", text):
            versions.setdefault(found, []).append(path.name)
        offered = set(re.findall(r"(?m)^\s*-?\s*os:\s*([\w.-]+)", text))
        for named in re.findall(r"matrix\.os\s*==\s*'([^']+)'", text):
            if named not in offered:
                problems.append(f".github/workflows/{path.name}: a step runs only on {named!r}, which no job there offers, so it never runs")
    if len(versions) > 1:
        problems.append("the workflows use more than one Ubuntu version (" + "; ".join(f"{v} in {', '.join(sorted(set(f)))}" for v, f in sorted(versions.items()))
                        + "): change them all together, as an update to one is easy to miss")


def gap_reuse_is_decided_by_a_kernel_and_checked() -> None:
    """Every run used to start from nothing. Reuse must come from the kept ledger through a kernel, and a run must still fail when a check has no passing result."""
    workflow = (ROOT / ".github" / "workflows" / "models.yml").read_text(encoding="utf-8")
    commands = run_blocks(workflow)
    for needed, why in (("model_request.py prepare-policy", "the plan must validate the push policy"),
                        ("model_request.py dump-plan", "the site must plan state dumps separately"),
                        ("model_request.py run", "the native request must use the protected policy and kept ledger"),
                        ("out/seed/dodona-kernel run", "what runs must be decided by a kernel from the kept ledger"),
                        ("--plan plan.json --dumps", "collect must send only the state dumps the plan says"),
                        ("model_request.py status", "status must read the ledger under the same protected policy"),
                        ("node kernel2/dodona-kernel2.js status", "the other kernel must read the native ledger"),
                        ("model_results.py", "keeping a ledger requires all current passes and the raw case proof"),
                        ("check_transcript.py out/model-transcript.json out/runs/transcript-collect.json",
                         "the native and dump provider transcripts must both validate"),
                        ("tools/keep.py finish", "only the gated result is prepared for reuse"),
                        ("--status success", "only a successful run's ledger may be the starting point"),
                        ("--event push", "only a run a push started may be the starting point, never a pull request's"),
                        ('.head_repository.full_name', "the starting point must be a run of this repository, not a fork's"),
                        ("--branch main", "only a ledger kept on main may be the starting point")):
        if needed not in commands:
            problems.append(f".github/workflows/models.yml: {why} ({needed!r} is missing)")
    keep_receipt = workflow.find("name: dodona-kept")
    if keep_receipt < 0 or any(workflow.find(gate) < 0 or workflow.find(gate) > keep_receipt for gate in
                               ("model_results.py", "check_transcript.py out/model-transcript.json", "tools/keep.py finish")):
        problems.append(".github/workflows/models.yml: the kept artifact must follow the native result and transcript gates")
    import keep
    with tempfile.TemporaryDirectory() as tmp:
        report = pathlib.Path(tmp) / "status.json"
        for checks, want in (({"a": {"status": "passed"}}, 0), ({"a": {"status": "passed"}, "b": {"status": "unknown"}}, 1),
                             ({"a": {"status": "failed"}}, 1), ({}, 1)):
            report.write_text(json.dumps({"obligations": checks}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()):
                got = keep.require_passed(argparse.Namespace(status=report))
            if got != want:
                problems.append(f"tools/keep.py require-passed gives {got} for {checks}; it must give {want}")


def gap_one_reader_of_checker_output() -> None:
    """The provider and the older model tool each had their own reading of the checker's output and could have disagreed."""
    provider = (ROOT / "providers" / "tlc" / "provider.py").read_text(encoding="utf-8")
    older = (ROOT / "tools" / "check_models.py").read_text(encoding="utf-8")
    for name, text in (("providers/tlc/provider.py", provider), ("tools/check_models.py", older)):
        if "from judge import" not in text or "is violated" in text:
            problems.append(f"{name} must take its reading of the checker's output from providers/tlc/judge.py and hold no copy")


def gap_claims_name_real_properties() -> None:
    """A claim pointed at properties and defect cases that did not exist."""
    text = (ROOT / "spec" / "CLAIMS.md").read_text(encoding="utf-8")
    for section in re.split(r"^## ", text, flags=re.M):
        m = re.match(r"Modelled in `(\w+)/(\w+)\.tla`", section)
        if not m:
            continue
        model = (ROOT / "spec" / m.group(1) / f"{m.group(2)}.tla").read_text(encoding="utf-8")
        table = section.split("\n## ")[0]
        for row in re.findall(r"^\| C\d+ \|.*$", table, flags=re.M):
            cells = [c.strip() for c in row.strip("|").split("|")]
            for prop in re.findall(r"`(\w+)`", cells[3]):
                if not re.search(rf"^{prop}\b.*==", model, flags=re.M):
                    problems.append(f"spec/CLAIMS.md {cells[0]}: property {prop} is not defined in {m.group(2)}.tla")


def gap_every_property_has_a_defect() -> None:
    """A property was once listed with no planted defect, so it could not be seen to fail."""
    for expected in sorted(ROOT.glob("spec/*/expected.json")):
        spec = json.loads(expected.read_text(encoding="utf-8"))
        guarded = {c["of"] for c in spec["cases"] if c["expect"] in ("violation", "temporal-violation")}
        for case in spec["cases"]:
            if case["expect"] != "no-violation":
                continue
            cfg = (expected.parent / case["config"]).read_text(encoding="utf-8")
            for line in cfg.splitlines():
                if line.startswith(("INVARIANT", "PROPERTY")):
                    for prop in line.split()[1:]:
                        if prop not in guarded and prop != "TypeOK" and not prop.startswith("Never"):
                            problems.append(f"{expected.parent.name}: {prop} is checked in {case['config']} but no case shows it can fail")


def gap_decisions_are_well_formed() -> None:
    """Decisions were marked accepted that the owner had not read; one lacked a falsifier."""
    allowed = {"proposed", "accepted", "superseded", "rejected"}
    for path in sorted((ROOT / "decisions").glob("[0-9]*.md")):
        text = path.read_text(encoding="utf-8")
        m = re.search(r"^status: (\w+)$", text, flags=re.M)
        if not m or m.group(1) not in allowed:
            problems.append(f"decisions/{path.name}: status is missing or not one of {sorted(allowed)}")
        for heading in ("## Context", "## Decision", "## What would show this wrong"):
            if heading not in text:
                problems.append(f"decisions/{path.name}: no '{heading}' section")
        if not re.search(rf'^id: "{path.name[:4]}"$', text, flags=re.M):
            problems.append(f"decisions/{path.name}: id does not match the file name")


def gap_vocabulary_is_the_same_everywhere() -> None:
    """Capability and level names drifted between the schema and the prose."""
    common = json.loads((ROOT / "protocol" / "common.schema.json").read_text(encoding="utf-8"))["$defs"]
    prose = "".join((ROOT / f).read_text(encoding="utf-8") for f in ("ARCHITECTURE.md", "MODEL.md", "protocol/README.md"))
    for cap in common["capability"]["enum"]:
        if f"`{cap}`" not in prose:
            problems.append(f"capability {cap} is in the schema but not described in the documents")
    for cap in set(re.findall(r"`([a-z]+\.[a-z]+)`", prose)):
        if cap.split(".")[0] in {"intent", "decision", "definition", "artifact", "obligation", "conformance", "run", "tool", "store"}:
            if cap not in common["capability"]["enum"] and cap not in {"run.poll", "run.cancel"}:
                problems.append(f"capability {cap} is described in the documents but not in the schema")
    model = (ROOT / "MODEL.md").read_text(encoding="utf-8")
    for key in ("separation", "assurance", "gate", "verdict", "status"):
        for value in common[key]["enum"]:
            explained = f"`{value}`" in model or f"`{value}`" in prose
            if key == "gate":  # gates are written as plain words in the tables
                explained = re.search(rf"\b{value}\b", model, flags=re.I) is not None
            if not explained:
                problems.append(f"{key} value {value} is in the schema but not explained in the documents")


def gap_nothing_private_or_unportable() -> None:
    """The repository is public and must run on three platforms."""
    private = re.compile(r"/Users/|/home/[a-z]|\bC:\\\\Users")
    for path in repo_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith("spec/runs/"):
            continue
        if path.suffix in {".sh", ".bat", ".cmd", ".ps1"}:
            problems.append(f"{rel}: shell scripts are not allowed (decision 0009)")
        if path.suffix in {".md", ".json", ".toml", ".py", ".yml", ".tla", ".cfg", ".rs"} and rel != "tools/check_repo.py":
            if private.search(path.read_text(encoding="utf-8", errors="replace")):
                problems.append(f"{rel}: contains a private or absolute path")


def gap_owner_rule_review_is_exact() -> None:
    """An approval cannot move with a new head, merge base or map."""
    import check_docs

    review = getattr(check_docs, "owner_rule_review", None)
    if review is None:
        problems.append("check_docs.py: the protected owner's exact map review cannot be applied")
        return
    parent, head = "1" * 40, "2" * 40
    before, after = "previous rules", "reviewed rules"
    digest = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
    approvals = {(parent, head, digest(before), digest(after)): "0037"}
    inputs = (parent, head, before, before, after)
    if review(approvals, *inputs) != "0037":
        problems.append("check_docs.py: the exact approved map review was refused")
    for position, unapproved in enumerate(("3" * 40, "4" * 40, "old map", "new main map", "edited map")):
        changed = list(inputs)
        changed[position] = unapproved
        if review(approvals, *changed) is not None:
            problems.append(f"check_docs.py: an owner review carried across changed input {position + 1}")
    if review(approvals, parent, None, before, before, after) is not None:
        problems.append("check_docs.py: an owner review accepted a working tree")

    base_map = {"rule": [], "exempt": [], "absent": [], "known": []}
    rule = {"id": "probe", "code": ["newdir/tool.py"], "docs": ["README.md"], "why": "explains the tool"}
    head_map = {**base_map, "rule": [rule]}
    changed = [("A", "newdir/tool.py")]
    reviewed = {"rule_review": "0040"}
    rejected, _ = check_docs.judge_change(changed, {"README.md"}, [], base_map, head_map)
    passed, notes = check_docs.judge_change(changed, {"README.md"}, [], base_map, head_map, **reviewed)
    if len(rejected) != 1 or not rejected[0].endswith(check_docs.JUDGING) or passed or not any("owner review 0040" in n for n in notes):
        problems.append("check_docs.py: the owner review did not resolve only the rule-change diagnostic")
    for extra_changes, docs, proposed_map, expected in (
        ([], set(), head_map, "rule probe:"),
        ([("M", "tools/check_docs.py")], {"README.md"}, head_map, f"tools/check_docs.py: this change {check_docs.JUDGING}"),
        ([("M", "decisions/owner-approvals/0040-documentation-bindings.md")], {"README.md"}, head_map,
         f"decisions/owner-approvals/0040-documentation-bindings.md: this change {check_docs.JUDGING}"),
        ([], {"README.md"}, {**head_map, "exempt": [{"paths": ["legacy/*"], "why": "new exception"}]}, "adds or alters [[exempt]]"),
        ([], {"README.md"}, {**head_map, "known": [{"check": "probe", "problem": "new drift"}]}, "adds or alters [[known]]"),
    ):
        found, _ = check_docs.judge_change(changed + extra_changes, docs, [], base_map, proposed_map, **reviewed)
        if not any(expected in problem for problem in found):
            problems.append(f"check_docs.py: an owner review hid {expected!r}")


def action_ref_problem(use, local_refs: set[str]) -> str | None:
    if not isinstance(use, str) or not use.strip():
        return "action reference must be text"
    use = use.strip()
    if use.startswith(("./", ".\\")):
        if use not in local_refs:
            return f"local action or workflow {use!r} is outside the audited inventory"
    elif not re.search(r"@[0-9a-f]{40}$", use):
        return f"action {use!r} is not pinned to a commit"
    return None


def action_step_problems(steps, local_refs: set[str], owner: str) -> list[str]:
    if not isinstance(steps, list):
        return [f"{owner}: steps is not a list"]
    found = []
    for number, step in enumerate(steps, 1):
        location = f"{owner} step {number}"
        if not isinstance(step, dict):
            found.append(f"{location}: not a mapping")
            continue
        if "uses" not in step:
            continue
        use = step["uses"]
        pin_problem = action_ref_problem(use, local_refs)
        if pin_problem:
            found.append(f"{location}: {pin_problem}")
        if not isinstance(use, str) or use.strip().partition("@")[0].casefold() != "actions/checkout":
            continue
        inputs = step.get("with")
        if not isinstance(inputs, dict):
            inputs = {}
        values = [value for key, value in inputs.items()
                  if isinstance(key, str) and key.casefold() == "persist-credentials"]
        credential = values[0] if len(values) == 1 else None
        if credential is not False and (not isinstance(credential, str) or credential.strip().casefold() != "false"):
            found.append(f"{location}: a checkout that does not set persist-credentials: false in its with mapping")
    return found


def workflow_action_problems(data, text: str, local_workflows: set[str], local_actions: set[str]) -> tuple[dict[str, dict], list[str]]:
    jobs = workflow_jobs(data)
    triggers = data.get("on", {})
    if isinstance(triggers, str):
        triggers = [triggers]
    if not isinstance(triggers, (dict, list)) or not all(isinstance(event, str) for event in triggers):
        raise ValueError("workflow events are not named")
    events = {event.casefold() for event in triggers}
    found = []
    if "workflow_run" in events:
        found.append("is started by workflow_run, which runs with the base's token on another run's outcome")
    if "self-hosted" in text:
        trigger = text.split("jobs:", 1)[0]
        if "pull_request" in trigger or events & {"pull_request", "pull_request_target"}:
            found.append("runs on a self-hosted runner and is triggered by pull requests")
        if "github.ref == 'refs/heads/main'" not in text or "github.repository == 'sloik/dodona'" not in text:
            found.append("self-hosted job is not restricted to this repository's main branch")
    if "permissions" not in data:
        found.append("no explicit permissions")
    found.extend(pull_request_target_problems(text, "pull_request_target" in events))
    for job_id, job in jobs.items():
        if "uses" in job:
            pin_problem = action_ref_problem(job["uses"], local_workflows)
            if pin_problem:
                found.append(f"job {job_id}: {pin_problem}")
        found.extend(action_step_problems(job.get("steps", []), local_actions, f"job {job_id}"))
    return jobs, found


def job_can_report_check(job_id: str, job: dict, context: str) -> bool:
    name = job.get("name", "").strip() or job_id
    if could_claim_check(name, context):
        return True
    # GitHub can append matrix values to a job name. The values may be computed.
    strategy = job.get("strategy", {})
    base, separator, values = context.rpartition(" (")
    return (isinstance(strategy, dict) and "matrix" in strategy and bool(separator)
            and values.endswith(")") and could_claim_check(name, base))


def required_check_problems(
    workflows: dict[str, dict[str, dict]], composites: dict[str, list[tuple[str, object]]],
    required_checks: frozenset[str],
) -> list[str]:
    """Follow the local workflow and composite graph from each required check."""
    found, jobs, actions = [], set(), set()
    for context in sorted(required_checks):
        roots = {(file, job_id) for file, contents in workflows.items() for job_id, job in contents.items()
                 if job_can_report_check(job_id, job, context)}
        if not roots:
            found.append(f"required check {context!r}: no matching workflow job")
        jobs.update(roots)

    def check_steps(steps, owner):
        if not isinstance(steps, list):
            return  # The Actions YAML check reports malformed steps.
        for number, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                continue
            if "continue-on-error" in step:
                found.append(f"{owner} step {number}: continue-on-error is forbidden behind a required check")
            use = step.get("uses")
            if isinstance(use, str) and use.strip() in composites:
                actions.add(use.strip())

    seen_jobs = set()
    while jobs:
        location = jobs.pop()
        if location in seen_jobs:
            continue
        seen_jobs.add(location)
        file, job_id = location
        job = workflows[file][job_id]
        owner = f"{file}: job {job_id}"
        if "continue-on-error" in job:
            found.append(f"{owner}: continue-on-error is forbidden behind a required check")
        check_steps(job.get("steps", []), owner)
        needs = job.get("needs", [])
        if isinstance(needs, str):
            needs = [needs]
        if not isinstance(needs, list) or not all(isinstance(need, str) for need in needs):
            found.append(f"{owner}: needs must name jobs behind a required check")
        else:
            for dependency in needs:
                if dependency in workflows[file]:
                    jobs.add((file, dependency))
                else:
                    found.append(f"{owner}: unknown needed job {dependency!r}")
        if "uses" in job:
            use = job["uses"]
            local = use.strip()[2:] if isinstance(use, str) and use.strip().startswith("./") else None
            if local in workflows:
                jobs.update((local, nested_id) for nested_id in workflows[local])
            else:
                found.append(f"{owner}: cannot audit the required reusable workflow {use!r}")

    seen_actions = set()
    while actions:
        call = actions.pop()
        if call in seen_actions:
            continue
        seen_actions.add(call)
        for file, steps in composites[call]:
            check_steps(steps, f"{file}: composite")
    return sorted(found)


def github_action_problems(root: pathlib.Path, required_checks: frozenset[str] = frozenset()) -> list[str]:
    import check_docs
    try:
        reader = pinned_workflow_reader()
    except (OSError, ValueError, zipfile.BadZipFile, check_docs.CannotRun) as err:
        return [f"workflow YAML reader: {err}"]
    workflows = {path for path in root.glob(".github/workflows/*") if path.suffix in (".yml", ".yaml") and path.is_file()}
    actions = {path for path in root.glob(".github/actions/**/action.*")
               if path.name in ("action.yml", "action.yaml") and path.is_file()}
    workflow_refs = {"./" + path.relative_to(root).as_posix() for path in workflows}
    action_refs = {"./" + path.parent.relative_to(root).as_posix() for path in actions}
    workflow_jobs_by_file = {}
    composites = {}
    found = []
    for path in sorted(workflows | actions):
        name = path.relative_to(root).as_posix()
        try:
            if path.is_symlink():
                raise ValueError("workflow or action manifest is a symlink")
            text = path.read_text(encoding="utf-8")
            data = reader().load(text)
            if path in workflows:
                jobs, errors = workflow_action_problems(data, text, workflow_refs, action_refs)
                workflow_jobs_by_file[name] = jobs
            else:
                runs = data.get("runs") if isinstance(data, dict) else None
                if not isinstance(runs, dict) or not isinstance(runs.get("using"), str):
                    raise ValueError("action manifest needs a named runs.using")
                errors = []
                if runs["using"].casefold() == "composite":
                    steps = runs.get("steps")
                    errors = action_step_problems(steps, action_refs, "composite")
                    ref = "./" + path.parent.relative_to(root).as_posix()
                    composites.setdefault(ref, []).append((name, steps))
        except Exception as err:  # noqa: BLE001 - unreadable action YAML cannot pass the guard
            found.append(f"{name}: cannot read Actions YAML ({err})")
        else:
            found.extend(f"{name}: {error}" for error in errors)
    found.extend(required_check_problems(workflow_jobs_by_file, composites, required_checks))
    return found


def github_action_controls() -> list[str]:
    """Check both file discovery and the input seen by the action."""
    checkout = "actions/checkout@" + "a" * 40

    def workflow(steps, event="push"):
        return ("permissions: {contents: read}\n"
                f"on: {event}\n"
                "jobs:\n  fixture:\n    runs-on: ubuntu-26.04\n" + steps)

    def composite(steps):
        return "name: Fixture\ndescription: A local checker fixture\nruns:\n  using: composite\n" + steps

    actions = ".github/actions/"
    workflows = ".github/workflows/"
    bad = {
        workflows + "plain.yml": workflow(f"    steps:\n      - uses: {checkout}\n"),
        workflows + "target.yml": workflow(
            f"    steps: [{{uses: {checkout}, with: {{persist-credentials: true}}}}]\n", "pull_request_target"),
        workflows + "expression.yml": workflow(
            f"    steps: [{{uses: {checkout}, with: {{persist-credentials: '${{{{ inputs.persist }}}}'}}}}]\n"),
        workflows + "quoted.yml": workflow(f'    steps:\n      - uses: "{checkout}"\n'),
        workflows + "folded.yml": workflow(f"    steps:\n      - uses: >-\n          {checkout}\n"),
        workflows + "case.yml": workflow(f"    steps:\n      - uses: {checkout.replace('actions/checkout', 'Actions/Checkout')}\n"),
        workflows + "flow.yml": workflow(f"    steps: [{{uses: {checkout}}}]\n"),
        workflows + "env.yml": workflow(f"    steps:\n      - uses: {checkout}\n        env:\n          persist-credentials: false\n"),
        workflows + "misplaced.yml": workflow(f'    steps:\n      - uses: {checkout}\n        with: {{note: "persist-credentials: false"}}\n'),
        workflows + "extension.yaml": workflow(f"    steps:\n      - uses: {checkout}\n"),
        workflows + "ambiguous.yaml": workflow(f"    steps: [{{uses: {checkout}, with: {{persist-credentials: false, Persist-Credentials: true}}}}]\n"),
        actions + "nested/missing/action.yml": composite(f"  steps: [{{uses: {checkout}}}]\n"),
        actions + "nested/missing-yaml/action.yaml": composite(f"  steps: [{{uses: {checkout}}}]\n"),
    }
    other = {
        workflows + "outside.yaml": (workflow("    steps: [{uses: ./outside}]\n"), "outside the audited inventory"),
        workflows + "windows-local.yaml": (
            workflow(f"    steps: [{{uses: '.{chr(92)}outside@{'a' * 40}'}}]\n"), "outside the audited inventory"),
        workflows + "unreadable.yaml": ("jobs: [", "cannot read Actions YAML"),
        actions + "unpinned/action.yaml": (
            composite("  steps: [{uses: actions/checkout@main, with: {persist-credentials: false}}]\n"), "not pinned to a commit"),
        workflows + "event.yaml": (workflow("    steps: [{run: echo example}]\n",
                                            '{"workflow\\u005frun": {workflows: [Other], types: [completed]}}'), "started by workflow_run"),
    }
    good = {
        workflows + "safe.yml": workflow(
            f'    steps: [{{uses: "{checkout}", with: {{persist-credentials: "false"}}}}]\n', "pull_request_target"),
        workflows + "local.yaml": workflow("    steps: [{uses: ./.github/actions/nested/good}]\n"),
        actions + "nested/good/action.yaml": composite(
            f"  steps:\n    - uses: >-\n        {checkout}\n      with: {{persist-credentials: false}}\n"),
        workflows + "shell-text.yml": workflow("    steps:\n      - run: |\n          echo 'uses: actions/checkout@main'\n"),
    }
    with tempfile.TemporaryDirectory(prefix="dodona-action-controls-") as directory:
        root = pathlib.Path(directory)
        for file, text in {**bad, **good, **{path: text for path, (text, _) in other.items()}}.items():
            path = root / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        found = github_action_problems(root)
    missing = [f"the action guard missed {file}" for file in bad
               if not any(error.startswith(file + ":") and "does not set persist-credentials: false" in error for error in found)]
    missing.extend(f"the action guard missed {file}" for file, (_, why) in other.items()
                   if not any(error.startswith(file + ":") and why in error for error in found))
    missing.extend(f"the action guard refused valid {file}" for file in good
                   if any(error.startswith(file + ":") for error in found))
    return missing


# Effective main-ruleset contexts. Keep this offline snapshot in sync with the ruleset.
REQUIRED_CHECK_NAMES = frozenset({
    "checks (linux)", "checks (macos)", "checks (windows)",
    "planted defects (first kernel)", "planted defects (second kernel)", "lint",
})


def required_job_controls() -> list[str]:
    workflows = ".github/workflows/"
    actions = ".github/actions/"
    files = {
        workflows + "required.yaml": """permissions: {contents: read}
on: pull_request
jobs:
  gate:
    name: checks (${{ matrix.system }})
    strategy: {matrix: {system: [linux]}}
    runs-on: ubuntu-26.04
    needs: [bridge, missing-job]
    continue-on-error: true
    steps: [{run: echo gate}]
  bridge:
    runs-on: ubuntu-26.04
    needs: [leaf, local-call, remote-call]
    steps: [{uses: ./.github/actions/outer}]
  leaf:
    runs-on: ubuntu-26.04
    steps: [{run: exit 1, "continue-on-\\u0065rror": '${{ github.event_name == "push" }}'}]
  local-call:
    uses: ./.github/workflows/local.yaml
  remote-call:
    uses: other/project/.github/workflows/remote.yml@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  optional:
    runs-on: ubuntu-26.04
    continue-on-error: true
    steps: [{uses: ./.github/actions/optional}]
  fallback:
    strategy: {matrix: {version: [modern]}}
    runs-on: ubuntu-26.04
    continue-on-error: true
    steps: [{run: echo check}]
""",
        workflows + "local.yaml": """permissions: {contents: read}
on: workflow_call
jobs:
  nested:
    runs-on: ubuntu-26.04
    steps: [{run: exit 1, continue-on-error: true}]
""",
        actions + "outer/action.yml": """runs:
  using: composite
  steps: [{uses: ./.github/actions/inner}]
""",
        actions + "inner/action.yaml": """runs:
  using: composite
  steps: [{run: exit 1, shell: bash, continue-on-error: true}]
""",
        actions + "optional/action.yml": """runs:
  using: composite
  steps: [{run: exit 1, shell: bash, continue-on-error: true}]
""",
    }
    with tempfile.TemporaryDirectory(prefix="dodona-required-controls-") as directory:
        root = pathlib.Path(directory)
        for name, source in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source, encoding="utf-8")
        found = github_action_problems(root, frozenset({"checks (linux)", "fallback (modern)", "absent check"}))

    expected = (
        ("required.yaml: job gate", "continue-on-error"),
        ("required.yaml: job leaf step 1", "continue-on-error"),
        ("required.yaml: job fallback", "continue-on-error"),
        ("local.yaml: job nested step 1", "continue-on-error"),
        ("inner/action.yaml: composite step 1", "continue-on-error"),
        ("required.yaml: job remote-call", "cannot audit the required reusable workflow"),
        ("required.yaml: job gate", "unknown needed job"),
        ("required check 'absent check'", "no matching workflow job"),
    )
    missing = [f"the required-check guard missed {location} ({reason})" for location, reason in expected
               if not any(location in error and reason in error for error in found)]
    if any("job optional" in error or "optional/action.yml" in error for error in found):
        missing.append("the required-check guard treated an unrelated job or action as required")
    return missing


def gap_workflows_are_safe() -> None:
    """Check protected workflow execution, pinned actions and checkout credentials."""
    problems.extend(github_action_problems(ROOT, REQUIRED_CHECK_NAMES))
    problems.extend(github_action_controls())
    problems.extend(required_job_controls())
    # The guard must be seen to fail: each unsafe edit of the workflow that uses pull_request_target is planted.
    docs = ROOT / ".github" / "workflows" / "docs.yml"
    text = docs.read_text(encoding="utf-8") if docs.exists() else ""
    for old, new in (("python3 -I tools/check_docs.py diff", "python3 tools/check_docs.py diff"),
                     ("fetch-depth: 0", "fetch-depth: 0\n          ref: ${{ github.event.pull_request.head.sha }}"),
                     ("contents: read", "contents: write"),
                     ("refs/pull/$PR_NUMBER/head:", "refs/pull/$PR_NUMBER/merge:"),
                     ("PR_HEAD: ${{ github.event.pull_request.head.sha }}", "PR_HEAD: ${{ github.event.pull_request.merge_commit_sha }}"),
                     ('git checkout --quiet --detach "$BASE"', 'git checkout --quiet --detach "$HEAD"'),
                     ('git checkout --quiet --detach "$BASE"', 'git worktree add "$RUNNER_TEMP/pr" "$HEAD"'),
                     ('git checkout --quiet --detach "$BASE"', 'git switch --detach "$HEAD"'),
                     ("run: |\n", 'run: |\n          echo "${{ github.event.pull_request.title }}"\n'),
                     ("run: |\n", 'run: |\n          echo "${{ github.head_ref }}"\n')):
        if "pull_request_target" in text and (old not in text or not pull_request_target_problems(text.replace(old, new, 1))):
            problems.append(f".github/workflows/docs.yml: the pull_request_target guard does not notice {new.strip()!r}")


def pinned_workflow_reader():
    """Verify the pure YAML wheel before unpacking it outside the checkout."""
    pins = [line.strip() for line in (ROOT / ".github/yaml-reader.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    pin = re.fullmatch(r"(\.github/vendor/[A-Za-z0-9_.-]+\.whl)\s+--hash=sha256:([0-9a-f]{64})", pins[0]) if len(pins) == 1 else None
    if pin is None:
        raise ValueError("expected one pinned workflow YAML wheel")
    wheel = ROOT / pin[1]
    if wheel.is_symlink():
        raise ValueError("workflow YAML wheel must be a regular file")
    data = wheel.read_bytes()
    if hashlib.sha256(data).hexdigest() != pin[2]:
        raise ValueError("workflow YAML wheel does not match its SHA-256 pin")
    _, reader = load_workflow_wheel(data)
    return reader


@cache
def load_workflow_wheel(data: bytes):
    import check_docs
    unpacked = tempfile.TemporaryDirectory(prefix="dodona-yaml-reader-")
    root = pathlib.Path(unpacked.name)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as wheel:
            wheel.extractall(root)
        # A regular parent package keeps ambient ruamel installations from shadowing this wheel.
        (root / "ruamel" / "__init__.py").touch()
        sys.path.insert(0, str(root))
        try:
            check_docs._yaml_reader()
        finally:
            sys.path.remove(str(root))
        if root not in pathlib.Path(sys.modules["ruamel.yaml"].__file__).parents:
            raise ValueError("workflow YAML parser was loaded from outside the pinned wheel")
    except BaseException:
        unpacked.cleanup()
        raise
    # Hold the temporary directory for the same lifetime as the cached parser factory.
    return unpacked, check_docs._yaml_reader

def workflow_jobs(data) -> dict[str, dict]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), dict):
        raise ValueError("jobs is not a mapping")
    jobs = data["jobs"]
    for job_id, job in jobs.items():
        if not isinstance(job_id, str) or not isinstance(job, dict):
            raise ValueError(f"job {job_id!r} is not a named mapping")
        if "name" in job and not isinstance(job["name"], str):
            raise ValueError(f"job {job_id!r} has a name that is not text")
    return jobs


def could_claim_check(name: str, expected: str) -> bool:
    """Preserve literal text and treat each Actions expression as an unknown string."""
    # An Actions string uses single quotes and escapes them by doubling them.
    expression = r"\$\{\{(?:[^'}]|\}(?!\})|'(?:[^']|'')*+')*+\}\}"
    parts = re.split(expression, name.strip().casefold())
    if any("${{" in part for part in parts):
        return True  # An unreadable expression cannot clear the name.
    return re.fullmatch(".*".join(map(re.escape, parts)), expected.casefold()) is not None

def lint_result_step_problems(steps, needs: set[str]) -> list[str]:
    """Check the Bash step that turns every needed job's result into the required verdict."""
    missing_step = ["lint-all must have one unconditional Bash step with result bindings and a run block"]
    if not isinstance(steps, list) or len(steps) != 1 or not isinstance(steps[0], dict):
        return missing_step
    step = steps[0]
    environment, script = step.get("env"), step.get("run")
    if (step.keys() - {"name", "shell", "env", "run"} or step.get("shell") != "bash"
            or not isinstance(environment, dict) or not isinstance(script, str)):
        return missing_step

    bindings = {}
    for variable, binding in environment.items():
        if not isinstance(variable, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", variable):
            return ["lint-all step environment has an invalid variable name"]
        source = re.fullmatch(r"\s*\$\{\{\s*needs\.([A-Za-z0-9_-]+)\.result\s*\}\}\s*", binding) if isinstance(binding, str) else None
        if source is None:
            return ["lint-all step environment must bind variables directly to needed job results"]
        bindings[variable] = source[1]
    if set(bindings.values()) != needs or len(bindings) != len(needs):
        return ["lint-all must bind one distinct variable to each needed job's result"]

    if "${{" in script:
        return ["lint-all must put workflow expressions in its result bindings, outside the Bash script"]
    # Bash splits commands at LF, while str.splitlines also splits Unicode separators.
    lines = (line.strip(" \t") for line in script.split("\n"))
    commands = [line for line in lines if line and not line.startswith("#")]
    if commands and re.fullmatch(r'echo "[A-Za-z0-9_$.,: -]*"', commands[0]):
        commands = commands[1:]
    tests = {f'test "${variable}" = success' for variable in bindings}
    if len(commands) != len(tests) or set(commands) != tests:
        return ["lint-all must test each bound result for success with no other commands"]
    return []


def lint_aggregate_problems(jobs: dict[str, dict]) -> list[str]:
    """The ruleset requires `lint`; every lint job must contribute its result."""
    if "lint-all" not in jobs:
        return ["has no job lint-all"]
    aggregate = jobs["lint-all"]
    found = []
    for job_id, job in jobs.items():
        steps = job.get("steps", [])
        if "continue-on-error" in job or (isinstance(steps, list)
                and any(isinstance(step, dict) and "continue-on-error" in step for step in steps)):
            found.append(f"{job_id}: continue-on-error is forbidden on lint jobs and steps")

    listed = aggregate.get("needs", [])
    if isinstance(listed, str):
        listed = [listed]
    if not isinstance(listed, list) or not all(isinstance(job_id, str) for job_id in listed):
        return found + ["lint-all needs must name jobs"]
    needs = set(listed)
    if not needs:
        found.append("lint-all must need at least one lint job")
    if len(needs) != len(listed):
        found.append("lint-all names a needed job more than once")
    others = jobs.keys() - {"lint-all"}
    for job_id in sorted(others - needs):
        found.append(f"lint-all does not need the job {job_id}, so its failure blocks nothing")
    for job_id in sorted(needs - others):
        found.append(f"lint-all needs {job_id}, which is not another job")
    condition = aggregate.get("if")
    if not isinstance(condition, str) or not re.fullmatch(r"(\$\{\{\s*always\(\)\s*\}\}|always\(\))", condition.strip()):
        found.append("lint-all must run with if: always() so a failed job cannot skip it")
    strategy = aggregate.get("strategy", {})
    if aggregate.get("name") != "lint" or "uses" in aggregate or not isinstance(strategy, dict) or "matrix" in strategy:
        found.append("lint-all must produce one check named lint")
    found.extend(lint_result_step_problems(aggregate.get("steps"), needs))
    return found


def lint_aggregate_and_name_problems(workflows: dict[str, str]) -> list[str]:
    import check_docs
    try:
        reader = pinned_workflow_reader()
    except (OSError, ValueError, zipfile.BadZipFile, check_docs.CannotRun) as err:
        return [f"workflow YAML reader: {err}"]
    found = []
    if "lint.yml" not in workflows:
        found.append("lint.yml: missing required lint workflow")
    for path, text in sorted(workflows.items()):
        try:
            jobs = workflow_jobs(reader().load(text))
        except Exception as err:  # noqa: BLE001 - any unreadable workflow leaves the required name unjudged
            found.append(f"{path}: cannot read jobs as YAML ({err})")
            continue
        if path == "lint.yml":
            found.extend(f"{path}: {error}" for error in lint_aggregate_problems(jobs))
        for job_id, job in jobs.items():
            name = job.get("name", "").strip() or job_id
            if (path, job_id) != ("lint.yml", "lint-all") and could_claim_check(name, "lint"):
                found.append(f"{path}: job {job_id} ({name!r}) could claim the required lint name")
    return found



def ruff_f401_problem(config: str) -> str | None:
    lint = tomllib.loads(config).get("lint", {})

    def covers_f401(rules):
        return any(rule == "ALL" or "F401".startswith(rule) for rule in rules)

    selected = lint.get("select", ["F"]) + lint.get("extend-select", [])
    ignored = lint.get("ignore", []) + lint.get("extend-ignore", [])
    for setting in ("per-file-ignores", "extend-per-file-ignores"):
        for rules in lint.get(setting, {}).values():
            ignored.extend(rules)
    if not covers_f401(selected) or covers_f401(ignored):
        return "ruff F401 must stay enabled outside a source-line waiver"
    return None


def gap_ruff_f401_stays_enabled() -> None:
    """Keep unused-import coverage after retiring the metrics file waiver."""
    problem = ruff_f401_problem((ROOT / "ruff.toml").read_text(encoding="utf-8"))
    if problem:
        problems.append(problem)
    enabled = '[lint]\nselect = ["F"]\n'
    plants = (
        enabled.replace('"F"', '"E4"'),
        enabled + 'ignore = ["F4"]\n',
        enabled + '[lint.per-file-ignores]\n"tools/metrics.py" = ["F401"]\n',
    )
    if ruff_f401_problem(enabled) or not all(map(ruff_f401_problem, plants)):
        problems.append("the Ruff guard did not distinguish enabled F401 from its planted faults")


def eslint_scope_problem(config: str) -> str | None:
    redeclare = r"""['"]no-redeclare['"]\s*\]?\s*:\s*\[?\s*([^,}\]\r\n]+)"""
    declarations = re.findall(redeclare, config)
    if not declarations or any(value.strip() not in ("'error'", '"error"', "2") for value in declarations):
        return "ESLint no-redeclare must report an error without a file-wide override"
    return None


def gap_eslint_no_redeclare_stays_enabled() -> None:
    """Keep the duplicate declaration rule active after retiring its broad waiver."""
    config = (ROOT / "eslint.config.mjs").read_text(encoding="utf-8")
    problem = eslint_scope_problem(config)
    if problem:
        problems.append(problem)
    enabled = "const rules = {'no-redeclare': 'error'};"
    disabled = enabled + "const waived = {'no-redeclare': 'off'};"
    if eslint_scope_problem(enabled) or not eslint_scope_problem(disabled):
        problems.append("the lint scope check did not distinguish an error from a file-wide waiver")



def gap_eslint_uses_locked_install() -> None:
    """The hosted JavaScript lint must install and use the locked ESLint tree."""
    try:
        reader = pinned_workflow_reader()
        workflow = (ROOT / ".github/workflows/lint.yml").read_text(encoding="utf-8")
        steps = workflow_jobs(reader().load(workflow))["javascript"]["steps"]
        run_steps = [step for step in steps if "run" in step]
    except Exception as err:  # noqa: BLE001 - an unreadable lint job leaves its install unjudged
        problems.append(f"cannot read the JavaScript lint job: {err}")
    else:
        commands = [
            "npm ci --prefix .github/eslint --ignore-scripts --no-audit --no-fund",
            "node .github/eslint/node_modules/eslint/bin/eslint.js kernel2",
        ]
        if [step["run"] for step in run_steps] != commands or any("if" in step for step in run_steps):
            problems.append("JavaScript lint must install and use ESLint from the committed dependency lock")

    tooling = ROOT / ".github/eslint"
    try:
        manifest = json.loads((tooling / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((tooling / "package-lock.json").read_text(encoding="utf-8"))
        version = manifest["devDependencies"]["eslint"]
        packages = lock["packages"]
        locked_version = packages["node_modules/eslint"]["version"]
        locked_dependencies = packages[""]["devDependencies"]
        integrity = all(item.get("integrity") for name, item in packages.items() if name)
    except (OSError, KeyError, AttributeError, TypeError, ValueError) as err:
        problems.append(f"cannot read the ESLint dependency lock: {err}")
        return
    exact = isinstance(version, str) and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
    if not exact or locked_version != version or locked_dependencies != manifest["devDependencies"] or not integrity:
        problems.append("ESLint needs a matching exact version and integrity hashes in its dependency lock")

def clippy_lint_steps_problem(steps) -> str | None:
    run_steps = [step for step in steps if isinstance(step, dict) and isinstance(step.get("run"), str)]
    expected = "Rust lint must install a pinned Clippy and run it with warnings as errors"
    if len(run_steps) != 2 or any("if" in step for step in run_steps):
        return expected
    install, lint = (step["run"] for step in run_steps)
    pin = re.fullmatch(
        r"rustup toolchain install ([0-9]+\.[0-9]+\.[0-9]+) --profile minimal --component clippy --no-self-update",
        install,
    )
    if pin is None:
        return expected
    command = f"cargo +{pin[1]} clippy --locked --all-targets --manifest-path kernel/Cargo.toml -- -D warnings"
    return None if lint == command else expected


def gap_clippy_is_pinned_and_strict() -> None:
    """Rust lint uses the same exact toolchain and fatal warnings on every runner."""
    try:
        reader = pinned_workflow_reader()
        workflow = (ROOT / ".github/workflows/lint.yml").read_text(encoding="utf-8")
        steps = workflow_jobs(reader().load(workflow))["rust"]["steps"]
        problem = clippy_lint_steps_problem(steps)
    except Exception as err:  # noqa: BLE001 - an unreadable lint job leaves its compiler unjudged
        problem = f"cannot read the Rust lint job: {err}"
    if problem:
        problems.append(problem)

    install = "rustup toolchain install 1.2.3 --profile minimal --component clippy --no-self-update"
    lint = "cargo +1.2.3 clippy --locked --all-targets --manifest-path kernel/Cargo.toml -- -D warnings"
    plants = [
        [{"run": install.replace("1.2.3", "stable")}, {"run": lint}],
        [{"run": install}, {"run": lint.replace("+1.2.3", "+1.2.4")}],
        [{"run": install}, {"run": lint.removesuffix(" -- -D warnings")}],
        [{"run": install}, {"run": lint, "if": "false"}],
    ]
    if clippy_lint_steps_problem([{"run": install}, {"run": lint}]) or not all(map(clippy_lint_steps_problem, plants)):
        problems.append("the Clippy guard did not distinguish a pinned strict run from its planted faults")


def gap_lint_aggregate_needs_every_job() -> None:
    """A lint job left out of the needs of `lint`, the one the ruleset requires, could fail and block nothing."""
    workflows = {path.name: path.read_text(encoding="utf-8") for path in repo_files(".github/workflows/*")
                 if path.suffix in (".yml", ".yaml")}
    problems.extend(f".github/workflows/{error}" for error in lint_aggregate_and_name_problems(workflows))
    text = '''jobs:
  python-and-workflows:
    steps:
      - name: An ordinary lint step
        run: echo example
  javascript:
    name: lint (JavaScript)
    steps: [{run: echo example}]
  rust:
    steps: [{run: echo example}]
  lint-all:
    name: lint
    needs: [python-and-workflows, javascript, rust]
    if: ${{ always() }}
    steps:
      - name: Require successful completion of every lint job
        shell: bash
        env:
          PYTHON_AND_WORKFLOWS: ${{ needs.python-and-workflows.result }}
          JAVASCRIPT: ${{ needs.javascript.result }}
          RUST: ${{ needs.rust.result }}
        run: |
          echo "$PYTHON_AND_WORKFLOWS $JAVASCRIPT $RUST"
          test "$PYTHON_AND_WORKFLOWS" = success
          test "$JAVASCRIPT" = success
          test "$RUST" = success
'''
    fixture_problems = lint_aggregate_and_name_problems({"lint.yml": text})
    if fixture_problems:
        problems.append(f".github/workflows: the valid lint control failed: {fixture_problems}")
        return
    extra = "\n  planted:\n    name: lint (planted)\n    runs-on: ubuntu-26.04\n    steps:\n      - run: exit 1\n"
    for what, old, new in (("a job not in its needs", "\n  lint-all:\n", extra + "\n  lint-all:\n"),
                           ("if: always() removed", "    if: ${{ always() }}\n", ""),
                           ("a needed job dropped", "needs: [python-and-workflows, javascript, rust]", "needs: [python-and-workflows, javascript]"),
                           ("an ignored lint job failure", "  javascript:\n",
                            "  javascript:\n    continue-on-error: true\n"),
                           ("an ignored aggregate failure", "  lint-all:\n",
                            "  lint-all:\n    'continue-on-error': true\n"),
                           ("an ignored lint step failure", "      - name: An ordinary lint step\n",
                            '      - name: An ordinary lint step\n        "continue-on-error": true\n'),
                           ("a removed success test", '          test "$RUST" = success\n', ""),
                           ("a softened success test", '          test "$RUST" = success\n',
                            '          test "$RUST" = success || true\n'),
                           ("a test bound to the wrong job", "needs.rust.result", "needs.javascript.result"),
                           ("an aggregate script that disables exit on error", '          test "$PYTHON_AND_WORKFLOWS" = success\n',
                            '          set +e\n          test "$PYTHON_AND_WORKFLOWS" = success\n'),
                           ("a skipped aggregate step", "      - name: Require successful completion of every lint job\n",
                            "      - name: Require successful completion of every lint job\n        if: false\n"),
                           ("a custom aggregate shell", "        shell: bash\n", "        shell: sh {0}\n")):
        if old not in text or not lint_aggregate_and_name_problems({"lint.yml": text.replace(old, new, 1)}):
            problems.append(f".github/workflows/lint.yml: the lint aggregate guard does not notice {what}")


    insertion = "  javascript:\n"
    omitted = (
        "  planted: # still a job\n    runs-on: ubuntu-26.04\n    steps: [{run: exit 1}]\n",
        "  'planted':\n    runs-on: ubuntu-26.04\n    steps: [{run: exit 1}]\n",
        "  planted: &held\n    runs-on: ubuntu-26.04\n    steps: [{run: exit 1}]\n",
        "  planted: {runs-on: ubuntu-26.04, steps: [{run: exit 1}]}\n",
    )
    for form, job in zip(("commented", "quoted", "anchored", "flow"), omitted, strict=True):
        planted = text.replace(insertion, job + insertion, 1)
        if insertion not in text or not any("lint-all does not need the job planted" in error
                for error in lint_aggregate_and_name_problems({"lint.yml": planted})):
            problems.append(f".github/workflows/lint.yml: the lint aggregate guard missed an omitted {form} job")

    name_plants = (
        ("same workflow", {"lint.yml": text.replace("name: lint (JavaScript)", "name: lint", 1)}, "lint.yml"),
        (".yml workflow", {"another.yml": "jobs: {other: {name: lint}}"}, "another.yml"),
        (".yaml workflow", {"another.yaml": 'jobs: {other: {name: "lint"}}'}, "another.yaml"),
        ("fallback job ID", {"another.yaml": "jobs: {lint: {runs-on: ubuntu-26.04}}"}, "another.yaml"),
        ("computed name", {"another.yml": "jobs: {other: {name: '${{ matrix.name }}'}}"}, "another.yml"),
        ("computed name with a quoted brace", {"another.yaml": json.dumps({
            "jobs": {"other": {"name": "li${{ vars.VALUE || '}}' }}nt"}}})}, "another.yaml"),
    )
    for form, extra_workflows, path in name_plants:
        found = lint_aggregate_and_name_problems({"lint.yml": text, **extra_workflows})
        if not any(error.startswith(path + ":") and "could claim the required lint name" in error for error in found):
            problems.append(f".github/workflows: the lint guard missed a duplicate name in the {form}")

    distinct = {"jobs": {"other": {"name": "${{ vars.PREFIX }} build ${{ vars.SUFFIX }}"}}}
    if lint_aggregate_and_name_problems({"lint.yml": text, "another.yml": json.dumps(distinct)}):
        problems.append(".github/workflows: a computed name with distinct literal text was refused")

    only_aggregate = {"jobs": {"lint-all": {
        "name": "lint", "if": "always()", "steps": [{"shell": "bash", "env": {}, "run": 'echo "example"'}],
    }}}
    if not lint_aggregate_and_name_problems({"lint.yml": json.dumps(only_aggregate)}):
        problems.append(".github/workflows: the lint guard accepted an aggregate with no lint jobs")

    for ending in ("javascript: # a comment", "'javascript':", "javascript: &hold"):
        variant = text.replace("javascript:", ending, 1)
        if lint_aggregate_and_name_problems({"lint.yml": variant}):
            problems.append(f".github/workflows: a valid lint job restyled as {ending!r} was refused")

    # JSON flow style gives the same YAML values, including the newlines in the script.
    fixture = pinned_workflow_reader()().load(text)
    if lint_aggregate_and_name_problems({"lint.yml": json.dumps(fixture)}):
        problems.append(".github/workflows: the valid flow-style lint control was refused")
    step = fixture["jobs"]["lint-all"]["steps"][0]
    script = step["run"]
    step["run"] = script.rstrip("\n").replace("\n", "\u2028")
    if not any("test each bound result" in error for error in
               lint_aggregate_and_name_problems({"lint.yml": json.dumps(fixture)})):
        problems.append(".github/workflows: the lint guard accepted separators Bash does not treat as newlines")
    step["run"] = "# ${{ inputs.note }}\n" + script
    if not any("workflow expressions" in error for error in
               lint_aggregate_and_name_problems({"lint.yml": json.dumps(fixture)})):
        problems.append(".github/workflows: the lint guard accepted a workflow expression in a shell comment")


    # A regular ambient package can hide a namespace supplied by a ZIP archive.
    with tempfile.TemporaryDirectory(prefix="dodona-ambient-yaml-") as directory:
        ambient = pathlib.Path(directory) / "ruamel"
        ambient.mkdir()
        (ambient / "__init__.py").touch()
        probe = ("import sys\n"
                 "sys.path[:0] = sys.argv[1:3]\n"
                 "import check_repo\n"
                 "assert check_repo.pinned_workflow_reader()().load('jobs: {}') == {'jobs': {}}\n")
        ran = subprocess.run([sys.executable, "-I", "-c", probe, str(ROOT / "tools"), directory], capture_output=True)
        if ran.returncode:
            problems.append(".github/workflows: the pinned YAML reader did not load with an ambient ruamel package")


def pull_request_target_problems(text: str, enabled: bool = False) -> list[str]:
    """pull_request_target runs with the base's workflow and a token; it is safe only while nothing
    from the pull request is checked out or run, and the token can do no more than read."""
    if not enabled and "pull_request_target" not in text:
        return []
    found = []
    if re.search(r"ref:\s*\$\{\{[^}]*(pull_request\.head|head_ref)", text):
        found.append("checks out the pull request's head under pull_request_target")
    if re.search(r"^\s+\w[\w-]*:\s*write\b", text, flags=re.M) or "secrets." in text:
        found.append("gives the token write access, or uses a secret, under pull_request_target")
    if any(re.search(r"\bpython3?(?! -I)\s", line) for line in text.split("\n") if not line.lstrip().startswith("#")):
        found.append("runs Python without -I under pull_request_target, so a file in the working directory could be imported")
    if re.search(r"refs/pull/[^\s'\"]*/merge|merge_commit_sha", text):
        found.append("uses the pull request's merge commit under pull_request_target, which holds its code")
    runs = run_blocks(text)
    for cmd in re.findall(r"\bgit\s+(?:checkout|switch|worktree\s+add)\b[^\n;&|]*", runs):
        if cmd.split()[-1] != '"$BASE"':
            found.append(f"checks out something other than the base under pull_request_target: {cmd.strip()!r}")
    if re.search(r"github\.event\.pull_request\.(title|body|head\.ref|head\.label)|github\.head_ref", runs):
        found.append("puts text the pull request's author chose into a run: block under pull_request_target; pass it through env:")
    return found


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


def gap_run_refuses_ambiguous_write_paths() -> None:
    """The run refuses names that can alias another file on a system that drops a trailing dot or space."""
    import project_run
    control = {"ledger": "l/run.ledger", "ledgers": ["l/run.ledger"], "owner_ledger": "l/owner.ledger",
               "project": "project.json", "executor": ["fixture"], "transcript": "trace.json"}
    variants = ({"ledger": "l/owner.ledger.", "ledgers": ["l/owner.ledger."]},
                {"ledger": "l /run.ledger", "ledgers": ["l /run.ledger"]},
                {"owner_ledger": "l/run.ledger."}, {"transcript": "l/run.ledger "},
                {"ledgers": ["l/run.ledger", "trace.json."]}, {"project": "trace.json "})
    project_run.check_run_input(control)
    for changed in variants:
        try:
            project_run.check_run_input(control | changed)
        except project_run.Stop as err:
            if err.reason == "bad-input":
                continue
        problems.append(f"tools/project_run.py: must refuse ambiguous write paths in {changed}")


def gap_status_keeps_literal_obligation_names() -> None:
    """A name that is special to a language still needs a passing case in the project status kit."""
    path = ROOT / "conformance" / "project" / "cases.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    if not any(case.get("expect", {}).get("status", {}).get("obligations", {}).get("__proto__") == "passed"
               for case in spec["cases"]):
        problems.append("conformance/project/cases.json: no status case for a passed obligation named __proto__")


def gap_batch_wait_respects_site_and_run_limits() -> None:
    """A batch may need a longer wait without changing a run's description."""
    import project_run
    tree = mock.Mock()
    tree.proc.returncode = 0
    tree.proc.communicate.return_value = (b'{"ended":true,"reports":[]}\n', b"")
    for limits, floor, wanted in (({"wall_ms": 1_800_000}, 3_660_000, 3660),
                                  ({"wall_ms": 1_800_000}, 1, 1860),
                                  ({}, 3_660_000, 86_400)):
        run = {"limits": limits}
        batch = [{"number": 1, "run_key": "one", "run": run}]
        with mock.patch.object(project_run.host.Session, "_start", return_value=tree):
            try:
                project_run.run_batch(ROOT, ["executor"], batch, floor_ms=floor)
            except TypeError as err:
                problems.append(f"project run cannot take a site batch wait floor: {err}")
                return
        (sent,), kwargs = tree.proc.communicate.call_args
        if kwargs.get("timeout") != wanted or json.loads(sent)["runs"][0]["run"] != run:
            problems.append("a batch wait floor changed a run or failed to preserve the required wait")


def check_planted_defect_anchors(directory: str) -> None:
    kernel = ROOT / directory
    defects = json.loads((kernel / "defects.json").read_text(encoding="utf-8"))["defects"]
    sources: dict[str, str | None] = {}
    for defect in defects:
        file = defect["file"]
        if file not in sources:
            try:
                sources[file] = (kernel / file).read_bytes().decode("utf-8")
            except (OSError, UnicodeError):
                sources[file] = None
        source = sources[file]
        if source is None or defect["find"] not in source:
            problems.append(f"{directory}/defects.json: {defect['name']!r}: anchor absent from {directory}/{file}")


def gap_js_planted_defect_anchors_exist() -> None:
    """Every listed JavaScript defect needs source text its runner can replace."""
    check_planted_defect_anchors("kernel2")


def gap_rust_planted_defect_anchors_exist() -> None:
    """Every listed Rust defect needs source text its runner can replace."""
    check_planted_defect_anchors("kernel")


def gap_js_status_exercises_retained_ledger_work() -> None:
    """Keep the status work test in the unit suite used by every platform job."""
    tests = (ROOT / "kernel2" / "test.js").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "checks.yml").read_text(encoding="utf-8")
    if "test('status validates each ledger record once per report'" not in tests or \
            "node --test kernel2/test.js" not in run_blocks(workflow).splitlines():
        problems.append("keep the JavaScript status ledger work test in the platform unit suite")


def gap_site_executor_reports_measured_tool_keys() -> None:
    """Exercise tool reports with the site's fake queue."""
    tests = ROOT / ".github" / "site" / "test_kernel_executor.py"
    result = subprocess.run([sys.executable, str(tests), "KernelExecutor"], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        problems.append("site executor conformance failed: " + result.stderr.strip())


def gap_site_driver_applies_case_timeouts() -> None:
    """An individual case's limit is independent of the queue batch's limit."""
    tests = ROOT / ".github" / "site" / "test_kernel_executor.py"
    result = subprocess.run([sys.executable, str(tests), "BatchDriver"], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        problems.append("site driver conformance failed: " + result.stderr.strip())


def gap_site_model_requests_use_protected_policy() -> None:
    """A native request must use the validated policy from its protected checkout."""
    tests = ROOT / ".github" / "site" / "test_model_request.py"
    result = subprocess.run([sys.executable, str(tests)], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        problems.append("site model request conformance failed: " + result.stderr.strip())


def gap_native_model_results_need_raw_evidence() -> None:
    """A native result is accepted only with the exact case inventory and judged outputs."""
    tests = ROOT / ".github" / "site" / "test_model_results.py"
    result = subprocess.run([sys.executable, str(tests)], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        problems.append("site model result conformance failed: " + result.stderr.strip())


def gap_rust_defect_shards_cover_the_inventory() -> None:
    """Splitting the Rust job must still judge every listed defect exactly once."""
    import kit_adequacy
    select = getattr(kit_adequacy, "select_shard", None)
    if select is None:
        problems.append("kit_adequacy.py: the serial Rust defect inventory cannot be split across jobs")
        return
    inventory = list(range(19))
    try:
        selected = [select(inventory, index, 8) for index in range(8)]
        if selected != [inventory[index::8] for index in range(8)]:
            problems.append("kit_adequacy.py: the eight Rust shards must cover each defect once in manifest order")
        for index, count in [(-1, 8), (8, 8), (0, 0), (0, len(inventory) + 1)]:
            try:
                select(inventory, index, count)
            except ValueError:
                continue
            problems.append(f"kit_adequacy.py: accepted an invalid Rust shard {index} of {count}")
    except (TypeError, ValueError, IndexError) as err:
        problems.append(f"kit_adequacy.py: could not partition the Rust defects: {err}")


def gap_ledger_judge_keeps_held_lock_result() -> None:
    """A defective append may remove the judge's lock before the judge cleans up."""
    import run_ledger_cases
    for mode in ("intact", "removed", "changed"):
        output = io.StringIO()

        def answer(command, subcommand, request):
            ledger = pathlib.Path(request["ledger"])
            if subcommand != "ledger-append" or ledger.name != "held.ledger":
                return {}
            marker = ledger.with_suffix(".ledger.lock")
            if mode == "removed":
                marker.unlink()
                ledger.write_bytes(ledger.read_bytes() + b"wrong append")
                return {"appended": "wrong"}
            if mode == "changed":
                marker.write_bytes(b"replaced")
            return {"refused": "locked"}

        with contextlib.redirect_stdout(output), mock.patch.object(sys, "argv", ["judge", "--", "kernel"]), \
                mock.patch.object(run_ledger_cases, "ask", side_effect=answer), \
                mock.patch.object(subprocess, "Popen", return_value=mock.Mock(wait=lambda timeout: run_ledger_cases.WRITER_MISMATCH)):
            try:
                result = run_ledger_cases.main()
            except OSError as err:
                problems.append(f"ledger judge: held lock {mode} prevented a completed result: {type(err).__name__}")
                continue
        lines = output.getvalue().splitlines()
        prefix = "match    " if mode == "intact" else "MISMATCH "
        if result != 1 or not any(line.startswith(prefix + "a held lock refuses an append") for line in lines):
            problems.append(f"ledger judge: did not record the expected held lock result when {mode}")
        if not lines or json.loads(lines[-1]).get("all_matched") is not False:
            problems.append(f"ledger judge: did not complete its final tally with the held lock {mode}")


def gap_every_check_is_listed() -> None:
    """A gap check that nobody can find the reason for will be deleted by mistake."""
    listed = (ROOT / "docs" / "gap-checks.md").read_text(encoding="utf-8")
    for name in GAP_CHECKS:
        if f"`{name.__name__}`" not in listed:
            problems.append(f"docs/gap-checks.md does not list {name.__name__}")


def gap_path_check_matches_its_vectors() -> None:
    """The path rules were first only prose; nothing showed an implementation agreed with them."""
    vectors = json.loads((ROOT / "conformance" / "vectors" / "paths.json").read_text(encoding="utf-8"))
    for path in vectors["accept"]:
        got = pathcheck.check(path.encode("utf-8"))
        if got is not None:
            problems.append(f"path vectors: {path!r} must be accepted, the reference refuses it: {got}")
    for item in vectors["reject"]:
        got = pathcheck.check(item["path"].encode("utf-8", errors="surrogatepass"))
        if got != item["reason"]:
            problems.append(f"path vectors: {item['path']!r} must be refused as {item['reason']}, the reference says {got}")
    for item in vectors["reject_bytes"]:
        got = pathcheck.check(bytes.fromhex(item["hex"]))
        if got != item["reason"]:
            problems.append(f"path vectors: bytes {item['hex']} must be refused as {item['reason']}, the reference says {got}")
    for item in vectors["collisions"]:
        if bool(pathcheck.collisions(item["paths"])) != item["collide"]:
            problems.append(f"path vectors: collision case {item['name']!r} disagrees with the reference")


def run_path_vectors_with(answer_for_set) -> tuple[int, str]:
    """Run tools/run_path_vectors.py in this process against a mock kernel; no child process is started.

    The mock answers every single-path vector with its hand-written expectation and
    every set with answer_for_set(paths, collide), where collide is the vector's own flag.
    """
    vectors = json.loads((ROOT / "conformance" / "vectors" / "paths.json").read_text(encoding="utf-8"))
    singles = {path.encode("utf-8").hex(): {"accepted": True} for path in vectors["accept"]}
    for item in vectors["reject"]:
        singles[item["path"].encode("utf-8", errors="surrogatepass").hex()] = {"refused": item["reason"]}
    for item in vectors["reject_bytes"]:
        singles[item["hex"]] = {"refused": item["reason"]}
    sets = {tuple(item["paths"]): item["collide"] for item in vectors["collisions"]}

    def run(command: list[str], *, input: bytes, **kwargs) -> subprocess.CompletedProcess:
        payload = json.loads(input)
        if command[-1] == "one":
            answer = singles[payload["hex"]]
        else:
            pair = payload["paths"]
            answer = {"collisions": answer_for_set(pair, sets[tuple(pair)])}
        return subprocess.CompletedProcess(command, 0, json.dumps(answer).encode("utf-8"), b"")

    argv = ["run_path_vectors.py", "--", "mock-kernel", "one", "many"]
    with patch.object(run_path_vectors.subprocess, "run", side_effect=run), patch.object(sys, "argv", argv), \
            contextlib.redirect_stdout(io.StringIO()) as out:
        code = run_path_vectors.main()
    return code, out.getvalue()


def gap_path_vector_judge_is_strict() -> None:
    """The path-vector judge turned a kernel's collisions into a yes or no, so a truthy string or a pair naming unrelated paths passed."""
    vectors = json.loads((ROOT / "conformance" / "vectors" / "paths.json").read_text(encoding="utf-8"))
    positives = [item["name"] for item in vectors["collisions"] if item["collide"]]
    negatives = [item["name"] for item in vectors["collisions"] if not item["collide"]]
    unrelated = ["unrelated/1", "unrelated/2"]
    # Each false answer is given only where it is false; every other set gets its right answer.
    false_on_positives = {
        "a truthy string": lambda pair: "yes",
        "a pair naming unrelated paths": lambda pair: [unrelated],
        "one path of the pair and one unrelated": lambda pair: [[pair[0], unrelated[0]]],
        "the right pair and an unrelated pair": lambda pair: [pair, unrelated],
        "the same pair twice": lambda pair: [pair, pair],
        "the same pair twice in either order": lambda pair: [pair, pair[::-1]],
        "a pair of three": lambda pair: [pair + [pair[0]]],
        "a pair of one": lambda pair: [pair[:1]],
        "one path twice": lambda pair: [[pair[0], pair[0]]],
        "a pair that is not a list": lambda pair: [{"a": pair[0], "b": pair[1]}],
        "a pair that is a string": lambda pair: [" ".join(pair)],
        "an empty list": lambda pair: [],
    }
    false_on_negatives = {
        "zero": lambda pair: 0,
        "null": lambda pair: None,
        "an empty string": lambda pair: "",
        "false": lambda pair: False,
        "an empty object": lambda pair: {},
        "the vector's own pair": lambda pair: [pair],
    }
    malformed = {"a truthy string", "a pair of three", "a pair of one", "a pair that is not a list",
                 "a pair that is a string", "zero", "null", "an empty string", "false", "an empty object"}

    def require_fault(label: str, wrong, positive: bool) -> None:
        code, out = run_path_vectors_with(lambda pair, collide: wrong(pair) if collide == positive else ([pair] if collide else []))
        names = [f"collision case {name!a}" for name in (positives if positive else negatives)]
        unfinished = label in malformed
        mark = "UNFINISHED" if unfinished else "MISMATCH"
        summary = json.loads(out.splitlines()[-1])
        if (code != (2 if unfinished else 1) or summary["all_matched"]
                or summary["rejected"] != ([] if unfinished else names)
                or summary["unfinished"] != (len(names) if unfinished else 0)):
            problems.append(f"tools/run_path_vectors.py misclassifies {label}: {summary}")
        for name in names:
            if f"{mark} {name}: " not in out:
                problems.append(f"tools/run_path_vectors.py accepts or misclassifies {label} for {name}")

    for label, wrong in false_on_positives.items():
        require_fault(label, wrong, True)
    for label, wrong in false_on_negatives.items():
        require_fault(label, wrong, False)
    # Positive controls: a right answer, in either order, passes every vector.
    for label, right in {"the pair as given": lambda pair: [pair], "the pair reversed": lambda pair: [pair[::-1]]}.items():
        code, out = run_path_vectors_with(lambda pair, collide: right(pair) if collide else [])
        if code != 0 or "MISMATCH" in out or '"all_matched": true' not in out:
            problems.append(f"tools/run_path_vectors.py refuses a right answer ({label}): {out.strip()[-300:]}")


def gap_repository_paths_are_portable() -> None:
    """dodona's own files must pass dodona's own path rules."""
    paths = [p.relative_to(ROOT).as_posix() for p in repo_files()]
    for path in paths:
        reason = pathcheck.check(path.encode("utf-8"))
        if reason:
            problems.append(f"{path}: fails the path check: {reason}")
    for first, second in pathcheck.collisions(paths):
        problems.append(f"{first} and {second} differ only by case")


def gap_canonical_vectors_are_consistent() -> None:
    """A vector whose hash does not match its own text would be worse than no vector."""
    vectors = json.loads((ROOT / "conformance" / "vectors" / "canonical.json").read_text(encoding="utf-8"))
    for item in vectors["accept"]:
        if hashlib.sha256(item["canonical"].encode("utf-8")).hexdigest() != item["sha256"]:
            problems.append(f"canonical vectors: {item['name']!r} has a hash that is not the hash of its text")
        if json.loads(item["canonical"]) != item["value"]:
            problems.append(f"canonical vectors: {item['name']!r} has a text that does not decode to its value")


def gap_every_modelled_case_has_a_scenario() -> None:
    """A planted defect in a model is no use to a kernel unless a scenario carries it over."""
    kit = ROOT / "conformance" / "kernel"
    excused = set(json.loads((kit / "index.json").read_text(encoding="utf-8"))["not_covered"])
    covered: set[str] = set()
    for path in sorted(kit.glob("*/*.json")):
        scenario = json.loads(path.read_text(encoding="utf-8"))
        for key in ("kind", "name", "claim", "covers", "why", "steps"):
            if key not in scenario:
                problems.append(f"conformance/kernel/{path.parent.name}/{path.name}: no '{key}'")
        if scenario.get("name") != path.stem or scenario.get("kind") != path.parent.name:
            problems.append(f"conformance/kernel/{path.parent.name}/{path.name}: name or kind does not match its location")
        if not scenario.get("steps") or any("do" not in s or "expect" not in s for s in scenario.get("steps", [])):
            problems.append(f"conformance/kernel/{path.parent.name}/{path.name}: a step lacks 'do' or 'expect'")
        covered.update(scenario.get("covers", []))
    modelled = set()
    for expected in sorted(ROOT.glob("spec/*/expected.json")):
        for case in json.loads(expected.read_text(encoding="utf-8"))["cases"]:
            modelled.add(f"{expected.parent.name}/{case['config'].removesuffix('.cfg')}")
    for case in sorted(modelled - covered - excused):
        problems.append(f"model case {case} has no scenario in the conformance kit and no stated reason")
    for case in sorted((covered | excused) - modelled):
        problems.append(f"the conformance kit refers to model case {case}, which does not exist")
    for case in sorted(covered & excused):
        problems.append(f"model case {case} is both covered by a scenario and listed as not covered")


def gap_planner_keeps_artifact_and_depth_cases() -> None:
    """Keep the independent artifact plant and both reachability controls in the model inventory."""
    folder = ROOT / "spec/planner"
    model = json.loads((folder / "expected.json").read_text(encoding="utf-8"))
    cases = {case["config"]: (case["expect"], case["expect_exit"], case.get("of")) for case in model["cases"]}
    for config, property_name in (
        ("mutant_lookup_wrong_key.cfg", "TestUsesCurrentArtifact"),
        ("reach_test_with_competing_artifact.cfg", "NeverTestedCurrentWithCompetingArtifact"),
        ("reach_eight_steps.cfg", "NeverReachesEightSteps"),
    ):
        if cases.get(config) != ("violation", 12, property_name):
            problems.append(f"planner: {config} must show a violation of {property_name}")
    partitions = []
    for case in model["cases"]:
        if case["expect"] == "no-violation":
            config = folder / case["config"]
            if not config.is_file():
                continue
            text = config.read_text(encoding="utf-8")
            names = ("Granularity", "InitialShape", "FirstAction", "SecondAction")
            constants = dict(re.findall(r'^\s*(\w+)\s*=\s*"(\w+)"', text, re.M))
            partitions.append(tuple(constants.get(name) for name in names))
    required = {(granularity, shape, first, second)
                for granularity in ("definition", "file")
                for shape in ("chain", "diamond")
                for first in ("edit", "other")
                for second in (("any",) if granularity == "definition" else ("edit", "other"))}
    if set(partitions) != required or len(partitions) != len(required):
        problems.append("planner: the design must cover every initial shape and action partition for each granularity")


def gap_kit_judge_is_strict() -> None:
    """The kit's judge must not accept a kernel that says nothing, or the wrong number of things."""
    scenario = {"steps": [{"do": {}, "expect": {"o1": {"status": "passed"}}}]}
    cases = [("", False), ("{}", False), ('{"results": []}', False),
             ('{"results": [{"o1": {"status": "failed"}}]}', False),
             ('{"results": [{"o1": {}}]}', False),
             ('{"results": [{"o1": {"status": "passed"}}, {}]}', False),
             ('{"results": [{"o1": {"status": "passed", "extra": 1}}]}', True)]
    for output, should_match in cases:
        if (run_kit.judge(scenario, output) == []) != should_match:
            problems.append(f"kit judge: wrong answer for kernel output {output!r}")


def gap_status_report_names_policy_on_pass() -> None:
    """The status schema described a policy identity for a pass without requiring one."""
    schema = json.loads((ROOT / "protocol" / "status.schema.json").read_text(encoding="utf-8"))
    condition = {
        "if": {"properties": {"project": {"properties": {"status": {"const": "passed"}}}}},
        "then": {"properties": {"policy": {"required": ["identity"]}}},
    }
    if condition not in schema.get("allOf", []):
        problems.append("status.schema.json: a passed project must require policy.identity")


def _fits(value, schema: dict, defs: dict, where: str) -> None:
    """A small structural check of data against the subset of JSON Schema the policy schema uses."""
    if "$ref" in schema:
        name = schema["$ref"].split("/")[-1]
        target = defs.get(name)
        if target is None:
            return  # a reference into another schema file; vocabulary is checked elsewhere
        return _fits(value, target, defs, where)
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"policy.toml: {where} is {value!r}, not one of {schema['enum']}")
    kind = schema.get("type")
    wanted = {"object": dict, "array": list, "string": str, "integer": int, "boolean": bool}.get(kind)
    if wanted and (not isinstance(value, wanted) or (kind == "integer" and isinstance(value, bool))):
        problems.append(f"policy.toml: {where} should be {kind}")
        return
    if isinstance(value, dict):
        known = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"policy.toml: {where} lacks {key}")
        for key, item in value.items():
            if key in known:
                _fits(item, known[key], defs, f"{where}.{key}")
            elif not key.startswith("x-") and schema.get("additionalProperties") is False:
                problems.append(f"policy.toml: {where}.{key} is not a field the policy schema knows")
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for number, item in enumerate(value):
            _fits(item, schema["items"], defs, f"{where}[{number}]")


def gap_own_policy_fits_the_schema() -> None:
    """dodona's own policy file was first written with field names the schema did not have."""
    schema = json.loads((ROOT / "protocol" / "policy.schema.json").read_text(encoding="utf-8"))
    policy = tomllib.loads((ROOT / "policy.toml").read_text(encoding="utf-8"))
    _fits(policy, schema, schema.get("$defs", {}), "policy")


def gap_evidence_strength_follows_kind() -> None:
    """The evidence schema once described the strength rule without expressing it."""
    schema = json.loads((ROOT / "protocol" / "evidence-record.schema.json").read_text(encoding="utf-8"))
    conditions = schema.get("allOf", [])
    for kinds, requirement in (
        ({"enum": ["check", "conformance"]}, {"required": ["strength"]}),
        ({"const": "build"}, {"not": {"required": ["strength"]}}),
    ):
        if {"if": {"properties": {"kind": kinds}}, "then": requirement} not in conditions:
            problems.append(f"evidence-record.schema.json: no strength condition for {kinds}")


def gap_no_generated_files_are_tracked() -> None:
    """Compiled caches and installed dependency trees are generated files."""
    import shutil
    import subprocess
    if not shutil.which("git") or not (ROOT / ".git").exists():
        return
    listed = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    for path in listed:
        if "__pycache__" in path or path.endswith(".pyc") or path.startswith("kernel/target/") or "node_modules" in path.split("/"):
            problems.append(f"{path}: a generated file is under version control")


def gap_provider_cases_match_the_provider() -> None:
    """A case naming a mode the provider does not have would silently test the well-behaved path."""
    cases = json.loads((ROOT / "conformance" / "provider" / "cases.json").read_text(encoding="utf-8"))["cases"]
    source = (ROOT / "conformance" / "provider" / "misbehaving_provider.py").read_text(encoding="utf-8")
    modes = [c["mode"] for c in cases]
    if modes[:1] != ["well-behaved"]:
        problems.append("conformance/provider/cases.json: the first case must be the well-behaved control")
    for case in cases:
        if case["mode"] != "well-behaved" and f'"{case["mode"]}"' not in source:
            problems.append(f"conformance/provider/cases.json: mode {case['mode']} is not in the provider")
        if case["outcome"] == "error" and "reason" not in case:
            problems.append(f"conformance/provider/cases.json: {case['mode']} expects an error with no reason")
    if len(modes) != len(set(modes)):
        problems.append("conformance/provider/cases.json: a mode is listed twice")


def gap_enumeration_transcript_keeps_inputs() -> None:
    """Normalizing an obligation must not change the recorded provider result."""
    import host
    transcript = []
    provider = ROOT / "providers" / "tlc" / "provider.py"
    session = host.Session([sys.executable, str(provider)], ROOT, transcript)
    try:
        with mock.patch.object(host, "DECLARED_INPUTS", {}), mock.patch.object(host, "REFUSED_BY_PROVIDER", []):
            obligations, files = host.list_project(session, ROOT)
            declared = {o["name"]: [f["path"] for f in host.inputs_of(o, files)] for o in obligations}
    finally:
        session.close()
    replies = [entry["message"]["body"]["obligations"] for entry in transcript
               if entry["message"]["type"] == "result" and entry["message"]["capability"] == "obligation.enumerate"]
    if len(replies) != 1 or not declared or any(not paths for paths in declared.values()):
        problems.append("host: no nonempty enumeration result to check")
        return
    recorded = {o["name"]: o.get("inputs") for o in replies[0]}
    if recorded != declared:
        problems.append("host: the enumeration transcript lost or changed declared inputs")
    if any("inputs" in o for o in obligations):
        problems.append("host: declared inputs leaked into the internal obligation")


def gap_lock_platform_pins_are_unique() -> None:
    """A draft lock entry may only pin one digest per exact platform."""
    import check_examples
    problems.extend(check_examples.check_lock_platform_fixtures())


def gap_project_intent_criteria_have_a_schema() -> None:
    """The shape of the criteria in a project file differs from the provider's wire format."""
    if not (ROOT / "protocol/project-intent-criteria.schema.json").is_file():
        problems.append("project intent criteria have no schema")


def gap_documents_follow_the_code() -> None:
    """Code changed and the documents describing it did not. The checks live in tools/check_docs.py."""
    import check_docs
    repo = check_docs.Repo(ROOT)
    problems.extend("documents: " + p for p in check_docs.repo_problems(repo))
    problems.extend("documents: " + p for p in check_docs.self_test(repo, with_git=False))  # CI runs it whole


GAP_CHECKS = [check_claims_match_runs, gap_readme_counts, gap_claims_name_real_properties,
              gap_every_property_has_a_defect, gap_decisions_are_well_formed,
              gap_vocabulary_is_the_same_everywhere, gap_nothing_private_or_unportable,
              gap_workflows_are_safe, gap_lint_aggregate_needs_every_job, gap_ruff_f401_stays_enabled,
              gap_eslint_no_redeclare_stays_enabled,
              gap_eslint_uses_locked_install, gap_clippy_is_pinned_and_strict, gap_owner_rule_review_is_exact,
              gap_path_check_matches_its_vectors, gap_path_vector_judge_is_strict,
              gap_repository_paths_are_portable, gap_lock_platform_pins_are_unique, gap_canonical_vectors_are_consistent,
              gap_every_modelled_case_has_a_scenario, gap_planner_keeps_artifact_and_depth_cases, gap_kit_judge_is_strict,
              gap_own_policy_fits_the_schema, gap_evidence_strength_follows_kind, gap_no_generated_files_are_tracked,
              gap_provider_cases_match_the_provider, gap_enumeration_transcript_keeps_inputs,
              gap_js_planted_defect_anchors_exist, gap_rust_planted_defect_anchors_exist, gap_js_status_exercises_retained_ledger_work,
              gap_rust_defect_shards_cover_the_inventory, gap_site_executor_reports_measured_tool_keys, gap_ledger_judge_keeps_held_lock_result,
              gap_site_driver_applies_case_timeouts,
              gap_site_model_requests_use_protected_policy,
              gap_native_model_results_need_raw_evidence,
              gap_every_check_is_listed,
              gap_kit_shown_claims_are_exercised, gap_kit_judge_hides_the_answers, gap_generated_kit_files_are_current,
              gap_driver_refuses_outside_the_queue, gap_one_reader_of_checker_output,
              gap_an_unfinished_job_proves_nothing, gap_tool_tree_digest_matches_its_vectors,
              gap_tool_tree_refuses_an_incomplete_listing, gap_every_tool_compiles,
              gap_an_intent_reads_one_way_only, gap_runner_versions_agree,
              gap_reuse_is_decided_by_a_kernel_and_checked, gap_run_refuses_ambiguous_write_paths,
              gap_status_keeps_literal_obligation_names, gap_batch_wait_respects_site_and_run_limits,
              gap_thin_coverage_is_shown, gap_status_report_names_policy_on_pass,
              gap_project_intent_criteria_have_a_schema, gap_documents_follow_the_code]


class ToolPinTests(unittest.TestCase):
    """A tool pinned by a floor (the queue's Java) is accepted at that version or later, and only then."""

    pinned = {"java": {"name": "java", "file": "java/bin/java", "floor": "21.0.13", "sha256": None},
              "tla2tools": {"name": "tla2tools", "file": "t.jar", "sha256": "ab"}}
    measured = {"java/bin/java": "any", "t.jar": "ab"}

    def faults(self, version, measured=None):
        import host
        return host.tool_faults(self.pinned, measured or self.measured, {} if version is None else {"java/bin/java": version})

    def test_the_floor_and_later_are_accepted(self):
        for version in ("21.0.13", "21.0.13.1", "21.0.100", "21.1", "22", "25.0.1", "100.0.1"):
            self.assertEqual(self.faults(version), ([], []), version)

    def test_below_the_floor_is_a_mismatch(self):
        for version in ("21.0.12", "21.0.9", "21.0.1", "21"):  # compared as numbers: 9 is below 13
            self.assertEqual(self.faults(version), ([], ["java"]), version)

    def test_an_older_major_version_is_a_mismatch(self):
        for version in ("3.0", "20.0.2", "1.8.0"):
            self.assertEqual(self.faults(version), ([], ["java"]), version)

    def test_a_job_on_java_below_the_floor_proves_nothing(self):
        import host
        _, pinned = host.lock_tools()
        good = {"reachable": True, "complete": True,
                "measured": {t["file"]: (t["sha256"] or "x") for t in pinned.values()},
                "versions": {t["file"]: t["floor"] for t in pinned.values() if t.get("floor")}}
        self.assertIsNone(host.job_fault(good))
        for version in ("21.0.9", None, "20.0.2"):
            low = dict(good, versions={f: version for f in good["versions"]})
            self.assertEqual(host.job_fault(low), "tool-mismatch", version)

    def test_the_driver_reads_only_a_released_version_on_its_own_line(self):
        sys.path.insert(0, str(ROOT / ".github" / "site"))
        import batch_driver
        read = batch_driver.stated_version
        self.assertEqual(read(b'openjdk version "21.0.13" 2026-10-21 LTS\nOpenJDK Runtime Environment\n', 0), "21.0.13")
        self.assertEqual(read(b'java version "21.0.15"\n', 0), "21.0.15")
        self.assertIsNone(read(b'openjdk version "21.0.13-ea" 2026-10-21\n', 0))
        self.assertIsNone(read(b'openjdk version "21.0.13"\n', 1))
        self.assertEqual(read(b'Picked up JAVA_TOOL_OPTIONS: -Dx=version "99"\nopenjdk version "21.0.9"\n', 0), "21.0.9")

    def test_an_unreadable_or_missing_version_is_a_mismatch(self):
        for version in ("garbage", "", None, "21.0.13-ea", "v21.0.13", " 21.0.13"):
            self.assertEqual(self.faults(version), ([], ["java"]), version)

    def test_an_exact_pin_still_compares_its_digest(self):
        self.assertEqual(self.faults("21.0.13", {"java/bin/java": "any", "t.jar": "other"}), ([], ["tla2tools"]))

    def test_an_unmeasured_tool_is_unmeasured(self):
        self.assertEqual(self.faults("21.0.13", {"t.jar": "ab"})[0], ["java"])

    def test_the_key_holds_the_floor_not_the_build(self):
        import host
        self.assertEqual(host.floor_digest(self.pinned["java"]), host.floor_digest(dict(self.pinned["java"], sha256="x")))
        self.assertNotEqual(host.floor_digest(self.pinned["java"]), host.floor_digest(dict(self.pinned["java"], floor="21.0.14")))


class KitAdequacyTests(unittest.TestCase):
    """A planted defect is credited only for a repeatable rejection, never a broken judge."""

    def result(self, code, stdout="", stderr=""):
        return subprocess.CompletedProcess([], code, stdout, stderr)

    def rejected(self, case):
        summary = {"scenarios": 1, "matched": 0, "all_matched": False, "unfinished": 0, "rejected": [case]}
        return self.result(1, f"MISMATCH {case}\n{json.dumps(summary)}\n")

    def planted(self, *results):
        with patch.object(kit_adequacy.subprocess, "run", side_effect=[self.result(0), *results]):
            return kit_adequacy.passes_kit(ROOT / "kernel", "src/main.rs")

    def test_crashed_scenario_judge_ends_unfinished(self):
        traceback = "Traceback (most recent call last):\n"
        for stdout in ("", "MISMATCH plan/example\n", self.rejected("plan/example").stdout):
            with self.subTest(stdout=stdout):
                self.assertEqual(self.planted(self.result(1, stdout, traceback)), (False, ["scenario-judge unfinished"]))

    def test_scenario_rejection_must_repeat_on_the_same_case(self):
        first = self.rejected("plan/example")
        self.assertEqual(self.planted(first, first), (False, ["plan/example"]))
        self.assertEqual(self.planted(first, self.rejected("plan/other")), (False, ["scenario-judge unsteady"]))

    def test_scenario_environment_failure_has_no_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            folder = root / "conformance" / "kernel" / "plan"
            folder.mkdir(parents=True)
            (folder / "example.json").write_text('{"steps": [{"do": {}, "expect": {}}]}', encoding="utf-8")
            for failure in (OSError(errno.ENOSPC, "No space left on device"), FileNotFoundError(),
                            subprocess.TimeoutExpired("kernel", 60), self.result(-15)):
                with self.subTest(failure=failure), contextlib.redirect_stdout(io.StringIO()) as output, \
                        patch.object(run_kit, "ROOT", root), patch.object(run_kit.sys, "argv", ["run_kit.py", "--", "kernel"]), \
                        patch.object(run_kit.subprocess, "run", side_effect=[failure]):
                    self.assertEqual(run_kit.main(), 2)
                    summary = json.loads(output.getvalue().splitlines()[-1])
                    self.assertEqual((summary["unfinished"], summary["rejected"], summary["all_matched"]), (1, [], False))

    def test_auxiliary_judge_signal_and_usage_error_are_unfinished(self):
        for code in (-15, 2):
            with self.subTest(code=code), patch.object(kit_adequacy.subprocess, "run", return_value=self.result(code)):
                self.assertEqual(kit_adequacy.run_judge("harness", "run_harness_check.py", ["scenario"], ROOT / "kernel"), "unfinished")

    # The ledger judge ends with the scenarios' footer, its count under `checks` (issue 41).
    def ledger(self, code, rejected, unfinished=0, key="checks", all_matched=None, before=""):
        summary = {key: 40, "matched": 40 - len(rejected), "unfinished": unfinished, "rejected": rejected,
                   "all_matched": (not rejected and not unfinished) if all_matched is None else all_matched}
        lines = "".join(f"MISMATCH {case}: detail\n" for case in rejected)
        return self.result(code, before + lines + json.dumps(summary) + "\n")

    def after_scenarios(self, *results):
        passed = {"scenarios": 1, "matched": 1, "all_matched": True, "unfinished": 0, "rejected": []}
        return self.planted(self.result(0, json.dumps(passed) + "\n"), *results)

    def test_ledger_rejection_is_credited_with_the_checks_that_repeat(self):
        writer = "writer 0 gave up at entry 3: the kernel answered {}\n"
        both = ["torn", "two kernels appending at once lose nothing"]
        self.assertEqual(self.after_scenarios(self.ledger(1, ["torn"]), self.ledger(1, ["torn"])),
                         (False, ["ledger-judge: torn"]))
        self.assertEqual(self.after_scenarios(self.ledger(1, both, before=writer), self.ledger(1, ["torn"])),
                         (False, ["ledger-judge: torn"]))
        self.assertEqual(self.after_scenarios(self.ledger(1, both), self.ledger(1, both, before=writer)),
                         (False, [f"ledger-judge: {case}" for case in both]))

    def test_ledger_replay_on_another_check_or_unfinished_is_unsteady(self):
        first = self.ledger(1, ["torn"])
        for second in (self.ledger(1, ["swapped"]), self.ledger(0, []), self.ledger(2, ["torn"], unfinished=1),
                       self.result(1, "MISMATCH torn: detail\n")):
            with self.subTest(second=second.stdout):
                self.assertEqual(self.after_scenarios(first, second), (False, ["ledger-judge unsteady"]))

    def test_ledger_report_that_is_partial_malformed_or_contradictory_is_unfinished(self):
        torn = self.ledger(1, ["torn"])
        cases = {
            "unfinished_after_a_mismatch": self.ledger(2, ["torn"], unfinished=1),
            "unfinished_with_exit_1": self.ledger(1, ["torn"], unfinished=1),
            "no_footer": self.result(1, "MISMATCH torn: detail\n"),
            "scenario_key": self.ledger(1, ["torn"], key="scenarios"),
            "exit_1_all_matched": self.ledger(1, ["torn"], all_matched=True),
            "exit_0_with_rejection": self.ledger(0, ["torn"]),
            "exit_1_nothing_rejected": self.ledger(1, [], all_matched=False),
            "empty_name": self.ledger(1, [""]),
            "stderr": self.result(1, torn.stdout, "writer did not finish: OSError\n"),
            "signal": self.result(-15, torn.stdout),
        }
        for name, answer in cases.items():
            with self.subTest(name=name):
                self.assertEqual(self.after_scenarios(answer), (False, ["ledger-judge unfinished"]))

    def at_session(self, *results):
        return self.after_scenarios(self.ledger(0, []), self.key_report(0, []), self.attest_report(0, []),
                                    self.harness_report(0, []), self.input_report(0, []), *results)

    def at_host_check(self, *results):
        return self.at_session(self.case_report(0, []), *results)

    def at_status(self, *results):
        return self.at_host_check(self.host_check_report(0, []), *results)

    def at_untyped(self, *results):
        stand_in = ("stand-in", "stand_in.py", [])
        with patch.object(kit_adequacy, "JUDGES", (*kit_adequacy.JUDGES, stand_in)):
            return self.at_status(self.case_report(0, [], project=True), *results)

    def host_check_report(self, code, rejected, *, unfinished=0, **fields):
        report = {"cases": 132, "judged": 129, "skipped": 3, "matched": 129 - len(rejected) - unfinished,
                  "unfinished": unfinished, "rejected": rejected, "all_matched": not rejected and not unfinished}
        report.update(fields)
        return self.result(code, "".join(f"MISMATCH {name}: detail\n" for name in rejected) + json.dumps(report) + "\n")

    def test_host_check_replay_credits_the_exact_case_with_skips(self):
        name = "well-behaved (exited) [a05c3820fa457e37]"
        other = "well-behaved (timed-out) [d3f9eab0f80b830f]"
        first, second = self.host_check_report(1, [name, other]), self.host_check_report(1, [name])
        self.assertEqual(self.at_host_check(first, second), (False, [f"host-check-judge: {name}"]))

    def test_host_check_replay_rejects_old_unfinished_or_inconsistent_reports(self):
        name = "well-behaved (exited) [a05c3820fa457e37]"
        first = self.host_check_report(1, [name])
        for second in (self.host_check_report(1, [name + " "]), self.host_check_report(2, [], unfinished=1),
                       self.result(1, f"MISMATCH {name}\n")):
            with self.subTest(second=second.stdout):
                self.assertEqual(self.at_host_check(first, second), (False, ["host-check-judge unsteady"]))
        for bad in (self.host_check_report(1, [name, name]), self.host_check_report(1, [name], cases=131),
                    self.host_check_report(1, [name], skipped=True), self.host_check_report(1, [name], skipped=None),
                    self.result(1, f"MISMATCH {name}\n")):
            with self.subTest(first=bad.stdout):
                self.assertEqual(self.at_host_check(bad, bad), (False, ["host-check-judge unfinished"]))

    def case_report(self, code, rejected, *, project=False, unfinished=0, **fields):
        totals = {"cases": 252, "judged": 243, "skipped": 9} if project else {"cases": 22}
        total = totals.get("judged", totals["cases"])
        report = dict(totals, matched=total - len(rejected) - unfinished, rejected=rejected,
                      unfinished=unfinished, all_matched=not rejected and not unfinished)
        report.update(fields)
        return self.result(code, "".join(f"MISMATCH {name}: detail\n" for name in rejected) + json.dumps(report) + "\n")

    def test_provider_replay_credits_the_repeated_named_case(self):
        name = "wrong-id"
        self.assertEqual(self.at_session(self.case_report(1, [name, "garbage"]), self.case_report(1, [name])),
                         (False, [f"session-judge: {name}"]))

    def test_status_replay_credits_the_repeated_named_case_with_skips(self):
        name = "an empty ledger has a report"
        first = self.case_report(1, [name, "two ledgers are read in order"], project=True)
        second = self.case_report(1, [name], project=True)
        self.assertEqual(self.at_status(first, second), (False, [f"status-judge: {name}"]))

    def test_session_and_status_require_valid_exact_names_on_both_runs(self):
        for run, label, name in ((self.at_session, "session", "wrong-id"),
                                 (self.at_status, "status", "an empty ledger has a report")):
            project = label == "status"
            first = self.case_report(1, [name], project=project)
            for second in (self.case_report(1, [name + " "], project=project),
                           self.case_report(0, [], project=project),
                           self.case_report(2, [], project=project, unfinished=1),
                           self.result(1, f"MISMATCH {name}\n")):
                with self.subTest(judge=label, second=second.stdout):
                    self.assertEqual(run(first, second), (False, [f"{label}-judge unsteady"]))
            old_report = self.result(1, json.dumps({"cases": 22, "matched": 21, "all_matched": False}) + "\n")
            duplicate_field = self.result(1, first.stdout.replace('"unfinished": 0', '"unfinished": 1, "unfinished": 0'))
            for bad in (old_report, duplicate_field, self.case_report(1, [name, name], project=project),
                        self.case_report(1, [" "], project=project)):
                with self.subTest(judge=label, first=bad.stdout):
                    self.assertEqual(run(bad, bad), (False, [f"{label}-judge unfinished"]))

    def test_status_cases_must_equal_judged_plus_skipped(self):
        for bad in ({"cases": 251}, {"skipped": -1, "cases": 242}, {"judged": 243.0}, {"skipped": True}, {"skipped": None}):
            with self.subTest(bad=bad):
                answer = self.case_report(1, ["an empty ledger has a report"], project=True, **bad)
                self.assertEqual(self.at_status(answer, answer), (False, ["status-judge unfinished"]))

    def test_other_auxiliary_judges_keep_their_exit_status_treatment(self):
        failed = self.result(1, "MISMATCH stand-in\n")
        self.assertEqual(self.at_untyped(failed, self.result(0)), (False, ["stand-in-judge unsteady"]))

    def test_repeated_untyped_auxiliary_rejection_is_provisional_not_caught(self):
        # Two identical exits 1 that name no case may be one environment failure twice (issue 41).
        failed = self.result(1, "MISMATCH stand-in\n")
        self.assertEqual(self.at_untyped(failed, failed), (False, ["stand-in-judge provisional"]))

    # The harness judge ends with the same footer, its count under `cases`: seven kernel cases and the known-answer
    # control; it runs after the attest judge (issue 41).
    def harness_report(self, code, rejected, unfinished=0, key="cases"):
        summary = {key: 8, "matched": 8 - len(rejected) - unfinished, "unfinished": unfinished, "rejected": rejected,
                   "all_matched": not rejected and not unfinished}
        lines = "".join(f"MISMATCH {case}: the checker agreed; kernel says None, None\n" for case in rejected)
        return self.result(code, lines + json.dumps(summary) + "\n")

    def at_harness(self, *results):
        return self.after_scenarios(self.ledger(0, []), self.key_report(0, []), self.attest_report(0, []), *results)

    def test_harness_rejection_is_credited_with_the_cases_that_repeat(self):
        nods = "a checker that agrees with everything"
        both = [nods, "the same with no known cases"]
        self.assertEqual(self.at_harness(self.harness_report(1, both), self.harness_report(1, [nods])),
                         (False, [f"harness-judge: {nods}"]))

    def test_harness_replay_on_another_case_or_unfinished_is_unsteady(self):
        first = self.harness_report(1, ["a checker that agrees with everything"])
        for second in (self.harness_report(1, ["the same with no known cases"]), self.harness_report(0, []),
                       self.harness_report(2, [], unfinished=7), self.result(1, "MISMATCH harness\n")):
            with self.subTest(second=second.stdout):
                self.assertEqual(self.at_harness(first, second), (False, ["harness-judge unsteady"]))

    def test_harness_report_that_is_unfinished_or_of_the_old_shape_is_unfinished_even_when_it_repeats(self):
        # The old judge folded a kernel that did not finish into seven mismatches, and a failed known-answer control
        # into an eighth, under a seven-case footer with exit 1.
        old = self.result(1, "".join(f"MISMATCH case {n}: kernel says None, None\n" for n in range(7))
                          + "MISMATCH the known cases did not tell the real checker from the one that agrees with everything\n"
                          + json.dumps({"cases": 7, "matched": 0, "all_matched": False}) + "\n")
        rejected = self.harness_report(1, ["a checker that agrees with everything"])
        for answer in (old, self.harness_report(2, [], unfinished=7), self.harness_report(2, [], unfinished=1),
                       self.harness_report(2, ["a checker that agrees with everything"], unfinished=1),
                       self.result(1, "MISMATCH harness\n"), self.harness_report(1, ["a checker that agrees with everything"], key="vectors"),
                       self.result(-15, rejected.stdout), self.result(0), self.result(2),
                       self.result(1, rejected.stdout, "Traceback (most recent call last):\n")):
            with self.subTest(answer=answer.stdout):
                self.assertEqual(self.at_harness(answer, answer), (False, ["harness-judge unfinished"]))

    def test_a_named_witness_must_be_present_in_the_replayed_rejections(self):
        witness = "status-judge: a duplicate intent"
        for rejected, want in ((witness, 0), ("status-judge: another case", 1)):
            with self.subTest(rejected=rejected), tempfile.TemporaryDirectory() as tmp:
                root = pathlib.Path(tmp)
                kernel = root / "kernel"
                kernel.mkdir()
                (kernel / "fixture.rs").write_text("old", encoding="utf-8")
                defect = {"name": "duplicate", "file": "fixture.rs", "find": "old",
                          "replace": "planted", "witness": witness}
                (kernel / "defects.json").write_text(json.dumps({"defects": [defect]}), encoding="utf-8")
                results = [(True, []), (False, [rejected])]
                with patch.object(kit_adequacy, "ROOT", root), \
                        patch.object(kit_adequacy, "passes_kit", side_effect=results), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    status = kit_adequacy.main()
                self.assertEqual(status, want)
                summary = json.loads(output.getvalue().splitlines()[-1])
                self.assertEqual((summary["caught"], summary["all_caught"]), (int(want == 0), want == 0))

    def test_provisional_replay_leaves_the_batch_unfinished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            kernel = root / "kernel"
            kernel.mkdir()
            (kernel / "fixture.rs").write_text("old", encoding="utf-8")
            defects = [{"name": name, "file": "fixture.rs", "find": "old", "replace": "planted"}
                       for name in ("named", "untyped")]
            (kernel / "defects.json").write_text(json.dumps({"defects": defects}), encoding="utf-8")
            results = [(True, []), (False, ["plan/named"]), (False, ["stand-in-judge provisional"])]
            with patch.object(kit_adequacy, "ROOT", root), patch.object(kit_adequacy, "passes_kit", side_effect=results), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                status = kit_adequacy.main()
        self.assertEqual(status, 1)
        self.assertIn("PROVISIONAL untyped", output.getvalue())
        summary = json.loads(output.getvalue().splitlines()[-1])
        self.assertEqual(summary, {"defects": 2, "caught": 1, "unfinished": 1, "all_caught": False})

    # The core-key judge ends with the same footer, its count under `vectors`; it runs after the ledger judge (issue 41).
    def key_report(self, code, rejected, unfinished=0, key="vectors"):
        summary = {key: 23, "matched": 23 - len(rejected) - unfinished, "unfinished": unfinished, "rejected": rejected,
                   "all_matched": not rejected and not unfinished}
        lines = "".join(f"MISMATCH {case}: expected {{}}, got {{}}\n" for case in rejected)
        return self.result(code, lines + json.dumps(summary) + "\n")

    def at_key(self, *results):
        return self.after_scenarios(self.ledger(0, []), *results)

    def test_core_key_rejection_is_credited_with_the_vectors_that_repeat(self):
        both = ["unsorted closure", "platform field"]
        self.assertEqual(self.at_key(self.key_report(1, both), self.key_report(1, ["platform field"])),
                         (False, ["core-key-judge: platform field"]))

    def test_core_key_replay_on_another_vector_or_unfinished_is_unsteady(self):
        first = self.key_report(1, ["unsorted closure"])
        for second in (self.key_report(1, ["platform field"]), self.key_report(0, []), self.key_report(2, [], unfinished=1),
                       self.result(1, "MISMATCH unsorted closure: expected {}, got None\n")):
            with self.subTest(second=second.stdout):
                self.assertEqual(self.at_key(first, second), (False, ["core-key-judge unsteady"]))

    def test_core_key_report_that_is_unfinished_or_of_the_old_shape_is_unfinished(self):
        # The old judge turned a timeout into exit 1 with this footer; two of them in a row were credited as a catch.
        old = self.result(1, "MISMATCH unsorted closure: expected {}, got None\n"
                          + json.dumps({"vectors": 23, "matched": 0, "all_matched": False}) + "\n")
        for answer in (old, self.key_report(2, [], unfinished=23), self.key_report(2, ["unsorted closure"], unfinished=1),
                       self.result(1, "MISMATCH unsorted closure\n"), self.key_report(1, ["unsorted closure"], key="cases"),
                       self.result(-15, self.key_report(1, ["unsorted closure"]).stdout)):
            with self.subTest(answer=answer.stdout):
                self.assertEqual(self.at_key(answer, answer), (False, ["core-key-judge unfinished"]))

    # The attest judge ends with the same footer, its count under `cases`; it runs after the core-key judge (issue 41).
    def attest_report(self, code, rejected, unfinished=0, key="cases"):
        summary = {key: 7, "matched": 7 - len(rejected) - unfinished, "unfinished": unfinished, "rejected": rejected,
                   "all_matched": not rejected and not unfinished}
        lines = "".join(f"MISMATCH {case}: kernel says None, None; the signer's own check says True\n" for case in rejected)
        return self.result(code, lines + json.dumps(summary) + "\n")

    def at_attest(self, *results):
        return self.after_scenarios(self.ledger(0, []), self.key_report(0, []), *results)

    def test_attest_rejection_is_credited_with_the_cases_that_repeat(self):
        both = ["changed after signing", "one fact left uncovered"]
        self.assertEqual(self.at_attest(self.attest_report(1, both), self.attest_report(1, ["one fact left uncovered"])),
                         (False, ["attest-judge: one fact left uncovered"]))

    def test_attest_replay_on_another_case_or_unfinished_is_unsteady(self):
        first = self.attest_report(1, ["changed after signing"])
        for second in (self.attest_report(1, ["one fact left uncovered"]), self.attest_report(0, []),
                       self.attest_report(2, [], unfinished=7), self.result(1, "MISMATCH changed after signing: x\n")):
            with self.subTest(second=second.stdout):
                self.assertEqual(self.at_attest(first, second), (False, ["attest-judge unsteady"]))

    def test_attest_report_that_is_unfinished_or_of_the_old_shape_is_unfinished_even_when_it_repeats(self):
        # The old judge folded a kernel that could not start, timed out or was signalled into seven named kernel
        # mismatches and exit 1; a runner that reads the footer must not take that for a catch.
        old = self.result(1, "".join(f"MISMATCH case {n}: kernel says None, None\n" for n in range(7))
                          + json.dumps({"cases": 7, "matched": 0, "all_matched": False}) + "\n")
        rejected = self.attest_report(1, ["changed after signing"])
        for answer in (old, self.attest_report(2, [], unfinished=7), self.attest_report(2, ["changed after signing"], unfinished=1),
                       self.result(1, "MISMATCH changed after signing\n"), self.attest_report(1, ["changed after signing"], key="vectors"),
                       self.result(-15, rejected.stdout), self.result(0), self.result(2),
                       self.result(1, rejected.stdout, "Traceback (most recent call last):\n")):
            with self.subTest(answer=answer.stdout):
                self.assertEqual(self.at_attest(answer, answer), (False, ["attest-judge unfinished"]))

    # The strict-input judge ends with the same footer, its count under `cases`; it runs after the ledger, core-key,
    # attest and harness judges (issue 41).
    def input_report(self, code, rejected, unfinished=0, key="cases"):
        summary = {key: 6, "matched": 6 - len(rejected) - unfinished, "unfinished": unfinished, "rejected": rejected,
                   "all_matched": not rejected and not unfinished}
        return self.result(code, "".join(f"MISMATCH {case} (exit 0)\n" for case in rejected) + json.dumps(summary) + "\n")

    def at_input(self, *results):
        return self.after_scenarios(self.ledger(0, []), self.key_report(0, []), self.attest_report(0, []), self.harness_report(0, []), *results)

    def test_input_rejection_is_credited_with_the_cases_that_repeat(self):
        key = "a key repeated in one object is refused"
        self.assertEqual(self.at_input(self.input_report(1, [key]), self.input_report(1, [key])), (False, [f"input-judge: {key}"]))

    def test_input_replay_on_another_case_or_unfinished_is_unsteady(self):
        first = self.input_report(1, ["a key repeated in one object is refused"])
        for second in (self.input_report(1, ["a byte that is not UTF-8 is refused"]), self.input_report(0, []),
                       self.input_report(2, [], unfinished=1)):
            with self.subTest(second=second.stdout):
                self.assertEqual(self.at_input(first, second), (False, ["input-judge unsteady"]))

    def test_input_report_that_is_partial_or_unfinished_is_unfinished(self):
        key = "a key repeated in one object is refused"
        old = self.result(1, f"MISMATCH {key} (exit 0)\n" + json.dumps({"cases": 6, "matched": 5, "all_matched": False}) + "\n")
        for answer in (self.input_report(2, [key], unfinished=1), self.input_report(2, [], unfinished=1), old,
                       self.result(1, f"MISMATCH {key} (exit 0)\n"), self.input_report(1, [key], key="checks"),
                       self.result(-15, self.input_report(1, [key]).stdout)):
            with self.subTest(answer=answer.stdout):
                self.assertEqual(self.at_input(answer), (False, ["input-judge unfinished"]))

    def test_structured_judge_requires_integer_unfinished_count(self):
        for invalid in (False, 0.0):
            with self.subTest(unfinished=invalid):
                report = self.ledger(1, ["torn"], unfinished=invalid)
                verdict = self.after_scenarios(report, report)
                self.assertEqual(verdict, (False, ["ledger-judge unfinished"]))

    def test_a_batch_builds_into_its_own_copy(self):
        summary = {"scenarios": 1, "matched": 1, "all_matched": True, "unfinished": 0, "rejected": []}
        with tempfile.TemporaryDirectory() as tmp:
            copy = pathlib.Path(tmp) / "kernel"
            with patch.object(kit_adequacy, "JUDGES", ()), \
                    patch.object(kit_adequacy.subprocess, "run", side_effect=[self.result(0), self.result(0, json.dumps(summary))]) as run:
                self.assertEqual(kit_adequacy.passes_kit(copy), (True, []))
            build = run.call_args_list[0].args[0]
            self.assertIn("--target-dir", build)
            self.assertEqual(build[build.index("--target-dir") + 1], str(copy / "target"))


class FakeWriter:
    """A `--write` child as the ledger judge sees it; `code` is None while it runs."""

    def __init__(self, code):
        self.code, self.killed, self.reaped = code, False, False

    def poll(self):
        return self.code

    def wait(self, timeout=None):
        if self.code is None:
            raise subprocess.TimeoutExpired("writer", timeout)
        self.reaped = True
        return self.code

    def kill(self):
        self.killed, self.code = True, -9


class LedgerJudgeTests(unittest.TestCase):
    """The ledger judge names a completed wrong answer, and never reports a run that did not finish as one (issue 41)."""

    @staticmethod
    def kernel(stdout=b"{}", code=0):
        """A kernel that gives every request the same answer, without starting anything."""
        return lambda command, **kwargs: subprocess.CompletedProcess(command, code, stdout, b"")

    def judge(self, run, writers=(), *, output=None):
        argv = ["run_ledger_cases.py", "--", "kernel"]
        output = io.StringIO() if output is None else output
        with contextlib.redirect_stdout(output), patch.object(run_ledger_cases.sys, "argv", argv), \
                patch.object(run_ledger_cases.subprocess, "run", side_effect=run), \
                patch.object(run_ledger_cases.subprocess, "Popen", side_effect=list(writers)):
            code = run_ledger_cases.main()
        return code, json.loads(output.getvalue().splitlines()[-1])

    def assertUnfinished(self, code, summary, rejected=None):
        self.assertEqual((code, summary["unfinished"], summary["all_matched"]), (2, 1, False))
        if rejected is not None:
            self.assertEqual(summary["rejected"], rejected)

    def test_a_kernel_that_could_not_answer_leaves_the_run_unfinished(self):
        for failure in (OSError(errno.ENOSPC, "No space left on device"), FileNotFoundError(),
                        subprocess.TimeoutExpired("kernel", 60), subprocess.CompletedProcess(["kernel"], -15, b"", b""),
                        subprocess.CompletedProcess(["kernel"], 101, b"", b"panicked")):
            with self.subTest(failure=failure):
                self.assertUnfinished(*self.judge([failure]), rejected=[])

    def test_a_completed_wrong_answer_is_a_named_rejection(self):
        for stdout in (b"{}", b"[]", b"not json", b'{"entries": 5, "torn": false}', b'{"entries": ["x"], "torn": false}',
                       b'{"entries": [{"body": [1]}, {"body": {"writer": null}}], "torn": false}'):
            with self.subTest(stdout=stdout):
                code, summary = self.judge(self.kernel(stdout), [FakeWriter(run_ledger_cases.WRITER_MISMATCH), FakeWriter(0)])
                self.assertEqual((code, summary["unfinished"], summary["all_matched"]), (1, 0, False))
                rejected = summary["rejected"]
                self.assertIn("the file is byte for byte the reference file", rejected)
                self.assertIn("two kernels appending at once lose nothing", rejected)
                self.assertEqual(len(rejected), len(set(rejected)))
                self.assertEqual(summary["checks"], summary["matched"] + len(rejected))

    def test_a_mismatch_then_an_unfinished_answer_is_not_a_rejection(self):
        appends = len(json.loads((ROOT / "conformance" / "ledger" / "cases.json").read_text(encoding="utf-8"))["append"])
        answers = [subprocess.CompletedProcess(["kernel"], 0, b"{}", b"")] * (appends + 1) + [subprocess.TimeoutExpired("kernel", 60)]
        code, summary = self.judge(answers)
        self.assertUnfinished(code, summary)
        self.assertIn("the file is byte for byte the reference file", summary["rejected"])

    def test_a_writer_kernel_can_answer_locked_before_its_process_deadline(self):
        def locked(command, subcommand, payload, timeout=60):
            self.assertLess(payload["wait_ms"], timeout * 1000)
            return {"refused": "locked"}

        argv = ["run_ledger_cases.py", "--write", "fixture.ledger", "1", "1", "--", "kernel"]
        with patch.object(run_ledger_cases.sys, "argv", argv), \
                patch.object(run_ledger_cases, "ask", side_effect=locked), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(run_ledger_cases.writer(), run_ledger_cases.WRITER_MISMATCH)

    def test_torn_cuts_do_not_reuse_a_path_that_a_mutant_can_lock(self):
        paths = []

        def simulate(command, subcommand, payload):
            path = pathlib.Path(payload["ledger"])
            if path.name.startswith("torn"):
                if subcommand == "ledger-read":
                    return {"torn": True, "entries": [{}, {}]}
                paths.append(path)
                return {"refused": "locked"}
            return {}

        with patch.object(run_ledger_cases, "ask", side_effect=simulate):
            code, report = self.judge(self.kernel(), [FakeWriter(0), FakeWriter(0)])
        self.assertEqual((code, report["checks"], report["unfinished"]), (1, 110, 0))
        self.assertGreater(len(paths), 1)
        self.assertEqual(len(paths), len(set(paths)))

    def test_two_writers_require_object_bodies(self):
        wrong = {"torn": False, "entries": [{"body": [w, n]} for w in range(2) for n in range(20)]}
        code, summary = self.judge(self.kernel(json.dumps(wrong).encode()), [FakeWriter(0), FakeWriter(0)])
        self.assertEqual((code, summary["unfinished"]), (1, 0))
        self.assertIn("two kernels appending at once lose nothing", summary["rejected"])

    def judge_held_lock(self, answer):
        reference = json.loads((ROOT / "conformance" / "ledger" / "cases.json").read_text(encoding="utf-8"))["file"].encode("utf-8")
        output = io.StringIO()
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        held = pathlib.Path(fixture.name) / "held.ledger"
        lock = held.with_suffix(".ledger.lock")
        request = json.dumps({"ledger": str(held), "kind": "evidence", "body": {}, "wait_ms": 300}).encode("utf-8")
        answered = 0

        def run(command, **kwargs):
            nonlocal answered
            # All other requests, including the deliberately deep input, stay opaque.
            if command[-1] != "ledger-append" or kwargs["input"] != request:
                return subprocess.CompletedProcess(command, 0, b"{}", b"")
            answered += 1
            self.assertEqual(held.read_bytes(), reference)
            self.assertEqual(lock.read_text(encoding="ascii"), "held by the judge\n")
            reply = answer(held, lock)
            return subprocess.CompletedProcess(command, 0, json.dumps(reply).encode(), b"")

        with patch.object(run_ledger_cases.tempfile, "TemporaryDirectory", return_value=fixture):
            code, receipt = self.judge(run, [FakeWriter(0), FakeWriter(0)], output=output)
        self.assertEqual(answered, 1, "\n".join(output.getvalue().splitlines()[-3:-1]))
        return code, receipt, output.getvalue()

    def test_wrong_held_append_remains_a_named_rejection_when_it_removes_the_marker(self):
        def wrong(held, lock):
            held.write_bytes(held.read_bytes() + b"mock append\n")
            lock.unlink()
            return {"appended": "mock"}

        decode = json.loads
        deepest = b'{"body": ' + b'{"x": ' * 4999

        def bounded_decoder(data, *args, **kwargs):
            if isinstance(data, bytes) and data.startswith(deepest):
                raise RecursionError("mock decoder cannot read the 5,000-level request")
            return decode(data, *args, **kwargs)

        with patch.object(json, "loads", side_effect=bounded_decoder):
            code, receipt, log = self.judge_held_lock(wrong)
        name = "a held lock refuses an append"
        self.assertEqual((code, receipt["checks"], receipt["unfinished"], receipt["all_matched"]),
                         (1, 110, 0, False), "\n".join(log.splitlines()[-3:-1]))
        self.assertIn(f"MISMATCH {name}:", log)
        self.assertIn(name, receipt["rejected"])
        for location in ("new ledger", "existing ledger", "corrupt ledger", "held lock"):
            self.assertIn(f"a request to append with a body nested 5000 levels deep is refused, {location}",
                          receipt["rejected"])
        self.assertIn("two kernels appending at once lose nothing", log)

    def test_held_lock_requires_both_the_ledger_and_marker_to_be_intact(self):
        def unchanged(held, lock):
            return {"refused": "locked"}

        def removed_marker(held, lock):
            lock.unlink()
            return unchanged(held, lock)

        def changed_marker(held, lock):
            lock.write_bytes(b"changed")
            return unchanged(held, lock)

        def changed_ledger(held, lock):
            held.write_bytes(b"changed")
            return unchanged(held, lock)

        for answer in (unchanged, removed_marker, changed_marker, changed_ledger):
            with self.subTest(answer=answer.__name__):
                code, receipt, log = self.judge_held_lock(answer)
                self.assertEqual((code, receipt["unfinished"]), (1, 0), "\n".join(log.splitlines()[-3:-1]))
                self.assertEqual("a held lock refuses an append" in receipt["rejected"], answer is not unchanged)
                self.assertEqual("match    a held lock refuses an append" in log, answer is unchanged)

    def test_unrelated_held_lock_read_or_cleanup_errors_keep_the_judge_unfinished(self):
        denied = PermissionError(errno.EACCES, "mock marker access denied")
        disappeared = FileNotFoundError(errno.ENOENT, "mock marker disappeared after observation")

        for method, error in (("read_bytes", denied), ("unlink", denied), ("unlink", disappeared)):
            original = getattr(pathlib.Path, method)

            def fail_for_marker(path, *args, **kwargs):
                if path.name == "held.ledger.lock":
                    raise error
                return original(path, *args, **kwargs)

            with self.subTest(method=method, error=type(error).__name__), patch.object(pathlib.Path, method, fail_for_marker):
                code, receipt, log = self.judge_held_lock(lambda held, lock: {"refused": "locked"})
                self.assertUnfinished(code, receipt)
                self.assertIn(type(error).__name__, log)

    def test_a_writer_that_cannot_start_or_finish_is_reaped_and_unfinished(self):
        for writers in ([FakeWriter(None), OSError(errno.EAGAIN, "Resource temporarily unavailable")],
                        [FakeWriter(None), FakeWriter(0)], [FakeWriter(0), FakeWriter(2)],
                        [FakeWriter(-15), FakeWriter(0)], [FakeWriter(1), FakeWriter(0)]):
            running = [w for w in writers if isinstance(w, FakeWriter) and w.code is None]
            with self.subTest(writers=writers):
                self.assertUnfinished(*self.judge(self.kernel(), writers))
                self.assertTrue(all(w.killed and w.reaped for w in running))

    def test_a_failure_of_the_judge_itself_is_unfinished(self):
        with patch.object(pathlib.Path, "write_bytes", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            self.assertUnfinished(*self.judge(self.kernel()))
        real = tempfile.TemporaryDirectory.cleanup

        def cleanup(directory):
            real(directory)
            raise OSError(errno.EBUSY, "Device or resource busy")

        with patch.object(tempfile.TemporaryDirectory, "cleanup", cleanup):
            self.assertUnfinished(*self.judge(self.kernel(), [FakeWriter(0), FakeWriter(0)]))

    def test_a_writer_child_tells_a_wrong_answer_from_none(self):
        def write(run):
            argv = ["run_ledger_cases.py", "--write", "shared.ledger", "0", "2", "--", "kernel"]
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(run_ledger_cases.sys, "argv", argv), \
                    patch.object(run_ledger_cases.subprocess, "run", side_effect=run):
                return run_ledger_cases.writer()

        self.assertEqual(write(self.kernel(b'{"appended": "x"}')), 0)
        for stdout in (b'{"refused": "locked"}', b"not json"):
            self.assertEqual(write(self.kernel(stdout)), run_ledger_cases.WRITER_MISMATCH, stdout)
        for failure in (OSError(errno.ENOSPC, "No space left on device"), subprocess.TimeoutExpired("kernel", 60),
                        subprocess.CompletedProcess(["kernel"], -15, b"", b""), subprocess.CompletedProcess(["kernel"], 1, b"", b"")):
            self.assertEqual(write([failure]), 2, failure)


class InputJudgeTests(unittest.TestCase):
    """The strict-input judge counts a nonzero exit as a refusal only when the kernel returned on its own: a kernel
    that could not start, ran out of time or was ended by the operating system leaves the run unfinished (issue 41)."""

    control = "the input without a fault is answered"
    repeated_key = "a key repeated in one object is refused"

    @staticmethod
    def exited(code):
        return subprocess.CompletedProcess(["kernel", "scenario"], code, b"", b"")

    def judge(self, answers):
        answers = [self.exited(a) if isinstance(a, int) else a for a in answers]
        argv = ["run_input_cases.py", "--", "kernel"]
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(run_input_cases.sys, "argv", argv), \
                patch.object(run_input_cases.subprocess, "run", side_effect=answers) as run:
            code = run_input_cases.main()
        return code, json.loads(output.getvalue().splitlines()[-1]), run.call_args_list

    def test_ordinary_nonzero_refusals_complete_and_pass(self):
        for codes in ([0, 1, 2, 1, 2, 2], [0, 101, 1, 3, 255, 2], [0, 0xFFFFFFFF, 1, 1, 1, 1]):
            with self.subTest(codes=codes):
                code, summary, _ = self.judge(codes)
                self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["all_matched"]), (0, 0, [], True))
                self.assertEqual((summary["cases"], summary["matched"]), (6, 6))

    def test_an_accepted_fault_is_a_named_mismatch(self):
        code, summary, _ = self.judge([0, 0, 2, 2, 2, 2])
        self.assertEqual((code, summary["unfinished"], summary["all_matched"]), (1, 0, False))
        self.assertEqual(summary["rejected"], [self.repeated_key])
        self.assertEqual((summary["cases"], summary["matched"]), (6, 5))
        code, summary, _ = self.judge([1, 2, 2, 2, 2, 2])
        self.assertEqual((code, summary["unfinished"], summary["rejected"]), (1, 0, [self.control]))

    def test_a_kernel_ended_by_the_operating_system_is_unfinished_not_a_refusal(self):
        # -15: a POSIX signal. 0xC0000005, 0xC00000FD, 0xC0000409: an access violation, a stack overflow and a fail-fast
        # abort as Windows reports them, in the NTSTATUS error range.
        for ended in (-15, -9, 0xC0000005, 0xC00000FD, 0xC0000409):
            with self.subTest(ended=ended):
                code, summary, _ = self.judge([0, ended, 2, 2, 2, 2])
                self.assertEqual((code, summary["unfinished"], summary["all_matched"]), (2, 1, False))
                self.assertNotIn(self.repeated_key, summary["rejected"])
                self.assertEqual(summary["rejected"], [])

    def test_a_kernel_that_could_not_start_or_ran_out_of_time_is_unfinished(self):
        for failure in (OSError(errno.ENOSPC, "No space left on device"), FileNotFoundError(),
                        subprocess.TimeoutExpired("kernel", 60)):
            for at in (0, 1):
                answers = [0, 2, 2, 2, 2, 2]
                answers[at] = failure
                with self.subTest(failure=failure, at=at):
                    code, summary, _ = self.judge(answers)
                    self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["all_matched"]), (2, 1, [], False))

    def test_explicit_disk_full_diagnostic_is_unfinished(self):
        for code_at, message in ((0, b"No space left on device"), (1, b"ENOSPC: write")):
            with self.subTest(case=code_at):
                answers = [0, 2, 2, 2, 2, 2]
                answers[code_at] = subprocess.CompletedProcess(["kernel", "scenario"], 1, b"", message)
                code, summary, _ = self.judge(answers)
                self.assertEqual((code, summary["unfinished"], summary["rejected"]), (2, 1, []))

    def test_a_mismatch_then_an_unfinished_case_leaves_the_run_unfinished(self):
        code, summary, _ = self.judge([0, 0, -15, 2, 2, 2])
        self.assertEqual((code, summary["unfinished"], summary["all_matched"]), (2, 1, False))
        self.assertEqual(summary["rejected"], [self.repeated_key])

    def test_a_failure_of_the_judge_itself_is_unfinished(self):
        with patch.object(pathlib.Path, "read_text", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            code, summary, calls = self.judge([])
        self.assertEqual((code, summary["unfinished"], summary["all_matched"], calls), (2, 1, False, []))

    def test_the_same_inputs_are_sent(self):
        _, _, calls = self.judge([0, 1, 2, 1, 2, 2])
        self.assertEqual([call.args[0] for call in calls], [["kernel", "scenario"]] * 6)
        sent = [call.kwargs["input"] for call in calls]
        json.loads(sent[0].decode("utf-8"))
        self.assertTrue(sent[1].startswith(b'{"kind": "nothing", '))
        self.assertTrue(sent[5].endswith(b', "x": "\xff"}'))
        with self.assertRaises(UnicodeDecodeError):
            sent[5].decode("utf-8")


class KeyVectorJudgeTests(unittest.TestCase):
    """The core-key judge names a completed wrong answer, and never reports a key command that did not finish as one.
    A kernel refuses a preimage with exit 0 and `{"refused": ...}`, so any other exit is no answer (issue 41)."""

    @staticmethod
    def vectors():
        cases = []
        for name in ("core-key.json", "core-key-more.json"):
            data = json.loads((ROOT / "conformance" / "vectors" / name).read_text(encoding="utf-8"))
            cases += [(v["name"], {"core_key": v["core_key"]}) for v in data.get("accept", [])]
            cases += [(v["name"], {"refused": v["reason"]}) for v in data.get("reject", [])]
        return cases

    @staticmethod
    def answered(want, code=0):
        stdout = want if isinstance(want, bytes) else json.dumps(want).encode("utf-8")
        return subprocess.CompletedProcess(["kernel", "key"], code, stdout, b"")

    def right(self):
        return [self.answered(want) for _, want in self.vectors()]

    def judge(self, answers):
        argv = ["run_key_vectors.py", "--", "kernel", "key"]
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(run_key_vectors.sys, "argv", argv), \
                patch.object(run_key_vectors.subprocess, "run", side_effect=answers) as run:
            code = run_key_vectors.main()
        return code, json.loads(output.getvalue().splitlines()[-1]), run.call_args_list

    def test_every_right_answer_passes(self):
        total = len(self.vectors())
        code, summary, calls = self.judge(self.right())
        self.assertEqual((code, summary), (0, {"vectors": total, "matched": total, "all_matched": True,
                                               "unfinished": 0, "rejected": []}))
        self.assertEqual([call.args[0] for call in calls], [["kernel", "key"]] * total)

    def test_a_completed_wrong_answer_is_a_named_rejection(self):
        cases = self.vectors()
        for wrong in ({}, b"not json", b"", b"\xff", {"refused": "unknown-field"}):
            answers = self.right()
            answers[0] = self.answered(wrong)
            answers[-1] = self.answered({"core_key": "0" * 64})
            with self.subTest(wrong=wrong):
                code, summary, _ = self.judge(answers)
                self.assertEqual((code, summary["unfinished"], summary["all_matched"]), (1, 0, False))
                self.assertEqual(summary["rejected"], [cases[0][0], cases[-1][0]])
                self.assertEqual((summary["vectors"], summary["matched"]), (len(cases), len(cases) - 2))

    def test_a_key_command_that_did_not_finish_is_unfinished_not_a_mismatch(self):
        right = self.right()[0].stdout
        for failure in (FileNotFoundError(), OSError(errno.ENOSPC, "No space left on device"),
                        subprocess.TimeoutExpired("kernel", 30), self.answered(right, -15), self.answered(right, 1),
                        self.answered(b"", 101), self.answered(right, 0xC0000005)):
            for at in (0, -1):
                answers = self.right()
                answers[at] = failure
                with self.subTest(failure=failure, at=at):
                    code, summary, _ = self.judge(answers)
                    self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["all_matched"]), (2, 1, [], False))
                    self.assertEqual(summary["matched"], summary["vectors"] - 1)

    def test_every_key_command_timing_out_is_unfinished(self):
        # What a reviewer saw: every vector timed out, and the judge reported exit 1 with 0 matched.
        code, summary, _ = self.judge([subprocess.TimeoutExpired("kernel", 30)] * len(self.vectors()))
        self.assertEqual(code, 2)
        self.assertEqual((summary["unfinished"], summary["rejected"], summary["matched"]), (len(self.vectors()), [], 0))

    def test_a_mismatch_then_an_unfinished_answer_leaves_the_run_unfinished(self):
        answers = self.right()
        answers[0] = self.answered({})
        answers[1] = subprocess.TimeoutExpired("kernel", 30)
        code, summary, _ = self.judge(answers)
        self.assertEqual((code, summary["unfinished"], summary["all_matched"]), (2, 1, False))
        self.assertEqual(summary["rejected"], [self.vectors()[0][0]])

    def test_vectors_that_cannot_be_read_leave_the_run_unfinished(self):
        with patch.object(pathlib.Path, "read_text", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            code, summary, calls = self.judge([])
        self.assertEqual((code, summary["vectors"], summary["unfinished"], summary["all_matched"], calls), (2, 0, 1, False, []))


class CanonicalVectorJudgeTests(unittest.TestCase):
    """A named mismatch needs a completed, usable canonical answer."""

    @staticmethod
    def vectors():
        vectors = json.loads((ROOT / "conformance" / "vectors" / "canonical.json").read_text(encoding="utf-8"))
        accept = [(v["name"], json.dumps(v["value"], indent=1, ensure_ascii=True).encode("utf-8"),
                   {"canonical": v["canonical"], "sha256": v["sha256"]}) for v in vectors["accept"]]
        reject = [(v["name"], v["text"].encode("utf-8"), {"refused": v["reason"]}) for v in vectors["reject"]]
        return accept + reject

    @staticmethod
    def answered(payload, code=0, stderr=b""):
        stdout = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        return subprocess.CompletedProcess(["kernel", "canonical"], code, stdout, stderr)

    def right(self):
        return [self.answered(want) for _, _, want in self.vectors()]

    def judge(self, answers):
        argv = ["run_vectors.py", "--", "kernel", "canonical"]
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(run_vectors.sys, "argv", argv), \
                patch.object(run_vectors.subprocess, "run", side_effect=answers) as run:
            code = run_vectors.main()
        lines = output.getvalue().splitlines()
        return code, json.loads(lines[-1]), lines[:-1], run.call_args_list

    def test_disk_full_stdout_cannot_pass_as_an_expected_refusal(self):
        answers = self.right()
        answers[-1] = self.answered(self.vectors()[-1][2], stderr=b"No space left on device")
        code, summary, lines, _ = self.judge(answers)
        self.assertEqual(code, 2)
        self.assertEqual((summary["unfinished"], summary["rejected"]), (1, []))
        self.assertTrue(any(line.startswith("UNFINISHED " + self.vectors()[-1][0]) for line in lines))


    def test_all_existing_vectors_keep_input_bytes_and_exact_answers(self):
        code, summary, _, calls = self.judge(self.right())
        cases = self.vectors()
        self.assertEqual((code, summary), (0, {"vectors": len(cases), "matched": len(cases), "all_matched": True,
                                               "unfinished": 0, "rejected": []}))
        self.assertEqual([call.args[0] for call in calls], [["kernel", "canonical"]] * len(cases))
        self.assertEqual([call.kwargs["input"] for call in calls], [data for _, data, _ in cases])

    def test_valid_wrong_bytes_hash_or_refusal_are_named(self):
        cases = self.vectors()
        at = next(i for i, (name, _, _) in enumerate(cases) if name == "keys are sorted")
        want = cases[at][2]
        value = json.loads(want["canonical"])
        unsorted = json.dumps(dict(reversed(list(value.items()))), ensure_ascii=False, separators=(",", ":"))
        self.assertNotEqual(unsorted, want["canonical"])
        replies = [
            (at, {"canonical": unsorted, "sha256": hashlib.sha256(unsorted.encode("utf-8")).hexdigest()}),
            (at, dict(want, sha256="0" * 64)),
            (-1, {"refused": "wrong reason"}),
        ]
        for index, wrong in replies:
            with self.subTest(index=index, wrong=wrong):
                answers = self.right()
                answers[index] = self.answered(wrong)
                code, summary, lines, _ = self.judge(answers)
                self.assertEqual((code, summary["matched"], summary["unfinished"], summary["rejected"]),
                                 (1, len(cases) - 1, 0, [cases[index][0]]))
                self.assertTrue(any(line.startswith("MISMATCH " + cases[index][0]) for line in lines))

    def test_process_failures_and_unusable_output_are_unfinished(self):
        cases = self.vectors()
        for at in (0, -1):
            want = cases[at][2]
            failures = [
                FileNotFoundError("missing command"), OSError(errno.ENOSPC, "disk full"),
                subprocess.TimeoutExpired("kernel", 30), self.answered(want, -15), self.answered(want, 0xC0000005),
                self.answered(want, 1, b"failed"), self.answered(want, stderr=b"ENOSPC"),
                self.answered(b"not JSON"), self.answered(b""), self.answered(b"\xff"),
                self.answered(["not an answer"]), self.answered({}), self.answered({"canonical": "missing hash"}),
                self.answered(b'{"refused":"x","refused":"y"}'),
            ]
            for failed in failures:
                with self.subTest(at=at, failed=failed):
                    answers = self.right()
                    answers[at] = failed
                    code, summary, lines, _ = self.judge(answers)
                    self.assertEqual((code, summary["matched"], summary["unfinished"], summary["rejected"]),
                                     (2, len(cases) - 1, 1, []))
                    self.assertTrue(any(line.startswith("UNFINISHED " + cases[at][0]) for line in lines))

    def test_an_unfinished_case_takes_precedence_over_a_named_mismatch(self):
        answers = self.right()
        answers[0] = self.answered({"refused": "wrong"})
        answers[-1] = subprocess.TimeoutExpired("kernel", 30)
        code, summary, _, _ = self.judge(answers)
        self.assertEqual((code, summary["unfinished"], summary["rejected"]),
                         (2, 1, [self.vectors()[0][0]]))

    def test_empty_duplicate_and_unreadable_fixtures_launch_nothing(self):
        duplicate = {"name": "same name", "text": "wrong", "reason": "invalid-json"}
        replies = [
            json.dumps({"accept": [], "reject": []}),
            json.dumps({"accept": [], "reject": [duplicate, duplicate]}),
            "{",
            OSError(errno.ENOSPC, "No space left on device"),
        ]
        for reply in replies:
            with self.subTest(reply=reply), patch.object(pathlib.Path, "read_text", side_effect=[reply]):
                code, summary, _, calls = self.judge([])
                self.assertEqual((code, summary["vectors"], summary["matched"], summary["rejected"], calls),
                                 (2, 0, 0, [], []))
                self.assertFalse(summary["all_matched"])


class PathVectorJudgeTests(unittest.TestCase):
    """The path judge keeps incomplete executions separate from named wrong answers."""

    @staticmethod
    def vectors():
        vectors = json.loads((ROOT / "conformance" / "vectors" / "paths.json").read_text(encoding="utf-8"))
        cases = [(f"accept {p!a}", "one", {"hex": p.encode("utf-8").hex()}, {"accepted": True})
                 for p in vectors["accept"]]
        cases.extend((f"reject {v['path']!a}", "one",
                      {"hex": v["path"].encode("utf-8", errors="surrogatepass").hex()}, {"refused": v["reason"]})
                     for v in vectors["reject"])
        cases.extend((f"reject bytes {v['hex']}", "one", {"hex": v["hex"]}, {"refused": v["reason"]})
                     for v in vectors["reject_bytes"])
        cases.extend((f"collision case {v['name']!a}", "many", {"paths": v["paths"]},
                      {"collisions": [v["paths"]] if v["collide"] else []}) for v in vectors["collisions"])
        return cases

    @staticmethod
    def answered(want, code=0, stderr=b""):
        stdout = want if isinstance(want, bytes) else json.dumps(want).encode("utf-8")
        return subprocess.CompletedProcess(["kernel"], code, stdout, stderr)

    def right(self):
        return [self.answered(want) for _, _, _, want in self.vectors()]

    def judge(self, answers):
        argv = ["run_path_vectors.py", "--", "kernel", "one", "many"]
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(run_path_vectors.sys, "argv", argv), \
                patch.object(run_path_vectors.subprocess, "run", side_effect=answers) as run:
            code = run_path_vectors.main()
        lines = output.getvalue().splitlines()
        return code, json.loads(lines[-1]), lines[:-1], run.call_args_list

    def test_disk_full_stdout_cannot_pass_for_the_expected_pair(self):
        cases = self.vectors()
        index = next(i for i, case in enumerate(cases) if case[0] == "collision case 'plain case'")
        answers = self.right()
        answers[index] = self.answered(cases[index][3], stderr=b"No space left on device")
        code, summary, lines, _ = self.judge(answers)
        self.assertEqual(code, 2)
        self.assertEqual((summary["unfinished"], summary["rejected"]), (1, []))
        self.assertTrue(any(line.startswith("UNFINISHED " + cases[index][0]) for line in lines))


    def test_all_existing_vectors_keep_exact_payloads_and_both_pair_orders(self):
        cases = self.vectors()
        for reverse in (False, True):
            answers = [self.answered({"collisions": [want["collisions"][0][::-1]]})
                       if reverse and want.get("collisions") else self.answered(want) for _, _, _, want in cases]
            code, summary, _, calls = self.judge(answers)
            self.assertEqual((code, summary), (0, {"vectors": len(cases), "matched": len(cases), "all_matched": True,
                                                   "unfinished": 0, "rejected": []}))
            self.assertEqual([call.args[0] for call in calls], [["kernel", sub] for _, sub, _, _ in cases])
            self.assertEqual([call.kwargs["input"] for call in calls],
                             [json.dumps(payload).encode("utf-8") for _, _, payload, _ in cases])

    def test_completed_wrong_answers_keep_distinct_identifiers(self):
        cases = self.vectors()
        named = ("accept ", "reject '", "reject bytes ", "collision case ")
        indices = [next(i for i, case in enumerate(cases) if case[0].startswith(prefix)) for prefix in named]
        wrong = [{"refused": "wrong"}, {"accepted": True}, {"refused": "wrong"},
                 {"collisions": [["unrelated/1", "unrelated/2"]]}]
        answers = self.right()
        for index, reply in zip(indices, wrong, strict=True):
            answers[index] = self.answered(reply)
        code, summary, lines, _ = self.judge(answers)
        names = [cases[index][0] for index in indices]
        self.assertEqual((code, summary["matched"], summary["rejected"], summary["unfinished"]),
                         (1, len(cases) - len(indices), names, 0))
        for name in names:
            self.assertTrue(any(line.startswith(f"MISMATCH {name}: ") for line in lines))

    def test_failed_processes_and_unusable_answers_are_unfinished(self):
        cases = self.vectors()
        for index in (0, -1):
            want = cases[index][3]
            malformed = {"accepted": 1} if index == 0 else {"collisions": [["a", 1]]}
            failures = [FileNotFoundError("missing command"), OSError(errno.ENOSPC, "disk full"),
                        subprocess.TimeoutExpired("kernel", 30), self.answered(want, -15),
                        self.answered(want, 0xC0000005), self.answered(want, 1, b"failure"),
                        self.answered(want, stderr=b"ENOSPC"), self.answered(b"not JSON"),
                        self.answered(b"\xff"), self.answered([]), self.answered({}), self.answered(malformed)]
            for failed in failures:
                with self.subTest(case=cases[index][0], failed=failed):
                    answers = self.right()
                    answers[index] = failed
                    code, summary, lines, _ = self.judge(answers)
                    self.assertEqual((code, summary["matched"], summary["unfinished"], summary["rejected"]),
                                     (2, len(cases) - 1, 1, []))
                    self.assertTrue(any(line.startswith(f"UNFINISHED {cases[index][0]}: ") for line in lines))

    def test_unfinished_takes_precedence_but_retains_completed_names(self):
        answers = self.right()
        answers[0] = self.answered({"accepted": False})
        answers[-1] = subprocess.TimeoutExpired("kernel", 30)
        code, summary, _, _ = self.judge(answers)
        self.assertEqual((code, summary["unfinished"], summary["rejected"]),
                         (2, 1, [self.vectors()[0][0]]))

    def test_empty_duplicate_and_unreadable_fixtures_launch_nothing(self):
        empty = {"accept": [], "reject": [], "reject_bytes": [], "collisions": []}
        duplicate = {"name": "duplicate", "paths": ["a", "A"], "collide": True}
        for source in (json.dumps(empty), json.dumps(dict(empty, collisions=[duplicate, duplicate])),
                       json.dumps(dict(empty, accept=[1])), json.dumps(dict(empty, accept="path")),
                       "{", OSError(errno.ENOSPC, "No space left on device")):
            with self.subTest(source=source), patch.object(pathlib.Path, "read_text", side_effect=[source]):
                code, summary, _, calls = self.judge([])
                self.assertEqual((code, summary["vectors"], summary["matched"], summary["rejected"], calls),
                                 (2, 0, 0, [], []))
                self.assertFalse(summary["all_matched"])


class AttestJudgeTests(unittest.TestCase):
    """The attest judge names a completed wrong grade, and never reports a kernel, signer or fixture that did not finish
    as seven mismatches. A kernel grades the seven records in one `scenario` run that exits 0 (issue 41)."""

    names = ["signed now by the reference signer", "changed after signing", "the result changed after signing",
             "the target changed after signing", "signed without what was judged",
             "signed with a key policy does not list", "one fact left uncovered"]
    right = [{"level": "cross-make", "source": "attested"}] + [{"level": "helper", "source": "declared"}] * 6

    @staticmethod
    def answered(results, code=0):
        stdout = results if isinstance(results, bytes) else json.dumps({"results": results}).encode("utf-8")
        return subprocess.CompletedProcess(["kernel", "scenario"], code, stdout, b"")

    def judge(self, answers):
        argv = ["run_attest_check.py", "--", "kernel", "scenario"]
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(run_attest_check.sys, "argv", argv), \
                patch.object(run_attest_check.subprocess, "run", side_effect=answers) as run:
            code = run_attest_check.main()
        lines = output.getvalue().splitlines()
        return code, json.loads(lines[-1]), run.call_args_list, lines[:-1]

    def test_every_right_grade_passes(self):
        code, summary, calls, lines = self.judge([self.answered(self.right)])
        self.assertEqual((code, summary), (0, {"cases": 7, "matched": 7, "all_matched": True, "unfinished": 0, "rejected": []}))
        self.assertEqual([call.args[0] for call in calls], [["kernel", "scenario"]])
        sent = json.loads(calls[0].kwargs["input"].decode("utf-8"))
        self.assertEqual((sent["kind"], len(sent["steps"])), ("acts", 7))
        self.assertEqual([line.split(":")[0] for line in lines], [f"match    {name}" for name in self.names])

    def test_a_completed_wrong_grade_is_a_named_rejection(self):
        wrong = [dict(r) for r in self.right]
        wrong[1] = {"level": "cross-make", "source": "attested"}  # vouches for a record changed after signing
        wrong[6] = {"level": "helper", "source": "attested"}
        code, summary, _, lines = self.judge([self.answered(wrong)])
        self.assertEqual((code, summary), (1, {"cases": 7, "matched": 5, "all_matched": False, "unfinished": 0,
                                               "rejected": [self.names[1], self.names[6]]}))
        self.assertTrue(lines[1].startswith(f"MISMATCH {self.names[1]}:"))

    def test_a_malformed_per_case_answer_from_a_completed_kernel_is_a_named_rejection(self):
        short = self.right[:5]
        odd = list(self.right)
        odd[0], odd[3] = "cross-make", None
        for answer, rejected in ((self.answered(short), self.names[5:]), (self.answered(odd), [self.names[0], self.names[3]]),
                                 (self.answered(b"not json"), self.names), (self.answered(b""), self.names),
                                 (self.answered(b'{"results": 5}'), self.names), (self.answered(b"[]"), self.names)):
            with self.subTest(stdout=answer.stdout):
                code, summary, _, _ = self.judge([answer])
                self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["all_matched"]), (1, 0, rejected, False))
                self.assertEqual(summary["matched"], 7 - len(rejected))

    def test_a_kernel_that_did_not_finish_is_unfinished_not_seven_mismatches(self):
        right = self.answered(self.right).stdout
        for failure in (FileNotFoundError(), OSError(errno.ENOSPC, "No space left on device"),
                        subprocess.TimeoutExpired("kernel", 60), self.answered(right, -15), self.answered(right, -9),
                        self.answered(right, 1), self.answered(b"", 101), self.answered(right, 0xC0000005)):
            with self.subTest(failure=failure):
                code, summary, _, lines = self.judge([failure])
                self.assertEqual((code, summary.get("unfinished"), summary.get("rejected"), summary["all_matched"], summary["matched"]),
                                 (2, 7, [], False, 0))
                self.assertFalse(any(line.startswith("MISMATCH") for line in lines))
                self.assertTrue(lines[0].startswith("UNFINISHED"))

    def test_a_signer_or_fixture_that_could_not_finish_is_unfinished(self):
        with patch.object(pathlib.Path, "read_text", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            code, summary, calls, _ = self.judge([])
        self.assertEqual((code, summary, calls), (2, {"cases": 0, "matched": 0, "all_matched": False, "unfinished": 1, "rejected": []}, []))
        with patch.object(run_attest_check.attest, "sign", side_effect=ValueError("no key")):
            code, summary, calls, _ = self.judge([])
        self.assertEqual((code, summary["unfinished"], summary["rejected"], calls), (2, 1, [], []))
        # The kernel answered rightly, and the signer's own check of one record did not finish: that case is unfinished.
        real = run_attest_check.attest.verify
        with patch.object(run_attest_check.attest, "verify",
                          side_effect=lambda record, key: (_ for _ in ()).throw(MemoryError()) if record.get("result") == "refused" else real(record, key)):
            code, summary, _, _ = self.judge([self.answered(self.right)])
        self.assertEqual((code, summary), (2, {"cases": 7, "matched": 6, "all_matched": False, "unfinished": 1, "rejected": []}))

    def test_a_wrong_reference_verdict_is_unfinished_not_a_kernel_mismatch(self):
        # The signer checking its own known fixture and returning the other boolean is a failure of the judge: the kernel
        # graded rightly, so the case shows nothing about it. The same failure twice must not be a named catch.
        real = run_attest_check.attest.verify
        flip_refused = lambda record, key: (not real(record, key)) if record.get("result") == "refused" else real(record, key)
        with patch.object(run_attest_check.attest, "verify", side_effect=flip_refused):
            code, summary, _, lines = self.judge([self.answered(self.right)])
        self.assertEqual((code, summary), (2, {"cases": 7, "matched": 6, "all_matched": False, "unfinished": 1, "rejected": []}))
        self.assertTrue(lines[2].startswith(f"UNFINISHED {self.names[2]}:"))
        self.assertFalse(any(line.startswith("MISMATCH") for line in lines))
        with patch.object(run_attest_check.attest, "verify", side_effect=lambda record, key: not real(record, key)):
            code, summary, _, _ = self.judge([self.answered(self.right)])
        self.assertEqual((code, summary), (2, {"cases": 7, "matched": 0, "all_matched": False, "unfinished": 7, "rejected": []}))
        # A wrong grade on the same case as a wrong reference verdict is still unfinished; a wrong grade elsewhere is named.
        wrong = list(self.right)
        wrong[2] = wrong[6] = {"level": "cross-make", "source": "attested"}
        with patch.object(run_attest_check.attest, "verify", side_effect=flip_refused):
            code, summary, _, _ = self.judge([self.answered(wrong)])
        self.assertEqual((code, summary), (2, {"cases": 7, "matched": 5, "all_matched": False, "unfinished": 1,
                                               "rejected": [self.names[6]]}))

    def test_a_mismatch_with_an_unfinished_signer_check_leaves_the_run_unfinished(self):
        wrong = list(self.right)
        wrong[1] = {"level": "cross-make", "source": "attested"}
        real = run_attest_check.attest.verify
        with patch.object(run_attest_check.attest, "verify",
                          side_effect=lambda record, key: (_ for _ in ()).throw(OSError()) if record.get("result") == "refused" else real(record, key)):
            code, summary, _, _ = self.judge([self.answered(wrong)])
        self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["all_matched"]), (2, 1, [self.names[1]], False))


class HarnessJudgeTests(unittest.TestCase):
    """The harness judge names a completed wrong grade, and reports a kernel that did not finish, or a known-answer control
    or fixture grade that did not hold, as unfinished. The control is its own line, not one of the seven cases (issue 41)."""

    right = [{"level": "cross-make", "source": "attested"}, {"level": "tested", "source": "attested"},
             {"level": "apart", "source": "attested"}, {"level": "apart", "source": "attested"}] + [{"level": "helper", "source": "declared"}] * 3

    @staticmethod
    def cases(real_wrong=True, nods_wrong=False, result="agreed"):
        record = lambda rejected: {"result": result, "known_bad": {"rejected_wrong": rejected, "accepted_right": True}}  # noqa: E731
        made = [record(real_wrong)] + [{"result": "agreed"}] * 2 + [record(nods_wrong)] + [{"result": "agreed"}] * 3
        return {}, [(f"case {n}", r, "agreed", "", "") for n, r in enumerate(made)]

    def judge(self, answer, made=None):
        made = made or self.cases()
        names = [name for name, *_ in made[1]]
        made = (made[0], [(name, r, res, HarnessJudgeTests.right[n]["level"], HarnessJudgeTests.right[n]["source"])
                          for n, (name, r, res, _, _) in enumerate(made[1])])
        argv = ["run_harness_check.py", "--", "kernel", "scenario"]
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(run_harness_check.sys, "argv", argv), \
                patch.object(run_harness_check, "make_cases", return_value=made), \
                patch.object(run_harness_check.subprocess, "run", side_effect=[answer]):
            code = run_harness_check.main()
        lines = output.getvalue().splitlines()
        return code, json.loads(lines[-1]), lines[:-1], names

    @staticmethod
    def answered(results, code=0):
        return subprocess.CompletedProcess(["kernel"], code, json.dumps({"results": results}).encode("utf-8"), b"")

    def test_right_grades_pass_with_the_control_on_its_own_line(self):
        code, summary, lines, _ = self.judge(self.answered(self.right))
        self.assertEqual((code, summary), (0, {"cases": 8, "matched": 8, "all_matched": True, "unfinished": 0, "rejected": []}))
        self.assertTrue(lines[0].startswith(f"match    {run_harness_check.CONTROL}:"))

    def test_a_completed_wrong_grade_is_named(self):
        wrong = list(self.right)
        wrong[3] = {"level": "tested", "source": "attested"}  # trusts the checker that agrees with everything
        code, summary, _, names = self.judge(self.answered(wrong))
        self.assertEqual((code, summary["rejected"], summary["unfinished"], summary["matched"]), (1, [names[3]], 0, 7))

    def test_a_kernel_that_did_not_finish_is_unfinished(self):
        for failure in (FileNotFoundError(), OSError(errno.EPIPE, "Broken pipe"), OSError(errno.ENOSPC, "No space left"),
                        subprocess.TimeoutExpired("kernel", 60), self.answered(self.right, -15), self.answered(self.right, 1)):
            with self.subTest(failure=failure):
                code, summary, lines, _ = self.judge(failure)
                # the control was judged on the harness alone and held; the seven kernel cases showed nothing
                self.assertEqual((code, summary["cases"], summary["unfinished"], summary["rejected"], summary["matched"]), (2, 8, 7, [], 1))
                self.assertFalse(any(line.startswith("MISMATCH") for line in lines))

    def test_a_known_control_that_did_not_hold_is_unfinished_not_a_catch(self):
        # A real checker that crashed reads as `refused` on everything; one that agrees with everything but crashed on the
        # known-wrong case looks as if it refused it. Neither is the kernel's doing.
        # A real checker's failed known cases also leave its own record unfinished, so that case is not matched either.
        for made, unfinished, matched in ((self.cases(real_wrong=False), 2, 6), (self.cases(nods_wrong=True), 1, 7)):
            # every case is counted once: matched + rejected + unfinished == cases == 8
            code, summary, lines, _ = self.judge(self.answered(self.right), made)
            self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["matched"]), (2, unfinished, [], matched))
            self.assertTrue(lines[0].startswith("UNFINISHED"))

    def test_a_fixture_grade_that_did_not_hold_is_unfinished(self):
        code, summary, lines, _ = self.judge(self.answered(self.right), self.cases(result="refused"))
        self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["matched"]), (2, 2, [], 6))
        self.assertFalse(any(line.startswith("MISMATCH") for line in lines))

    def test_strict_harness_never_reads_an_unfinished_checker_as_a_refusal(self):
        # The ordinary harness CLI keeps reading anything but a final `agreed` as `refused`; the judge's strict records
        # raise instead, so a timed-out, failed or verdictless checker cannot pass for a known-wrong rejection.
        said = lambda code, out: subprocess.CompletedProcess(["checker"], code, out, b"")  # noqa: E731
        for failure in (subprocess.TimeoutExpired("checker", 600), FileNotFoundError(), OSError(errno.EPIPE, "Broken pipe"),
                        said(1, b"refused\n"), said(-9, b""), said(0, b"looks fine\n"), said(0, b"")):
            with self.subTest(failure=failure):
                with patch.object(harness.subprocess, "run", side_effect=[failure]):
                    self.assertEqual(harness.ask(["checker"], {"work": b"x"}, []), "refused")
                with patch.object(harness.subprocess, "run", side_effect=[failure]), self.assertRaises(harness.CheckerUnfinished):
                    harness.ask(["checker"], {"work": b"x"}, [], strict=True)
        for verdict in ("agreed", "refused"):
            with patch.object(harness.subprocess, "run", side_effect=[said(0, f"note\n{verdict}\n".encode())]):
                self.assertEqual(harness.ask(["checker"], {"work": b"x"}, [], strict=True), verdict)

    def test_records_that_could_not_be_made_are_unfinished(self):
        argv = ["run_harness_check.py", "--", "kernel"]
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(run_harness_check.sys, "argv", argv), \
                patch.object(run_harness_check, "make_cases", side_effect=OSError(errno.ENOSPC, "No space left")):
            code = run_harness_check.main()
        self.assertEqual((code, json.loads(output.getvalue().splitlines()[-1])["unfinished"]), (2, 1))


class ProviderJudgeTests(unittest.TestCase):
    """The session judge counts only an answer the host completed with exit 0 (issue 41). A host that could not start,
    ran out of time or exited other than 0, a fixture whose transcript or process ids could not be read, a process
    whose state could not be told, and a cleanup that did not take leave the case unfinished. A completed wrong answer,
    a wrong transcript, a completed answer over the deadline plus grace, and a fixture process confirmed still running
    are named mismatches. Every host, process probe and signal is a stand-in: no real process is started or probed."""

    spec = json.loads((ROOT / "conformance" / "provider" / "cases.json").read_text(encoding="utf-8"))
    PID = 4242

    def transcript(self, mode):
        limits = self.spec["limits"]
        echo = "h" + chr(0xE9) + "llo " + chr(0x2603) + " " + chr(1) + chr(0x1F) + " end"
        hello = {"type": "hello", "protocol": ["0.2"], "echo": echo,
                 "limits": {"max_line_bytes": limits["max_line_bytes"], "deadline_ms": limits["deadline_ms"]}}
        request = {"type": "request", "id": "1", "deadline_ms": limits["deadline_ms"], "capability": "decision.index",
                   "body": {"files": []}}
        return "".join(json.dumps(m) + "\n" for m in (hello, request, {"type": "shutdown"}))

    def host(self, override, clock):
        """A stand-in for the host: it records what the fixture would record and answers each case rightly with exit 0,
        unless `override` gives a mode another exit, answer, transcript, pid file, duration or exception."""
        cases = {case["mode"]: case for case in self.spec["cases"]}

        def run(command, **kwargs):
            mode = command[-1]
            case, change = cases[mode], (override or {}).get(mode, {})
            env = kwargs["env"]
            seen, pids = pathlib.Path(env["DODONA_TEST_SEEN"]), pathlib.Path(env["DODONA_TEST_PIDFILE"])
            pid_text = change.get("pids", f"{self.PID}\n")
            if pid_text == "directory":
                pids.mkdir()
            elif pid_text is not None:
                pids.write_text(pid_text, encoding="ascii")
            seen_text = change.get("transcript", self.transcript(mode))
            if seen_text is not None:
                seen.write_text(seen_text, encoding="utf-8")
            clock[0] += change.get("took", 0.1)
            if "raise" in change:
                raise change["raise"]
            answer = {"outcome": case["outcome"], "log_bytes": 0, "log_truncated": case.get("log_truncated", False)}
            if "reason" in case:
                answer["reason"] = case["reason"]
            answer = change.get("answer", answer)
            stdout = answer if isinstance(answer, bytes) else json.dumps(answer).encode("utf-8")
            return subprocess.CompletedProcess(command, change.get("code", 0), stdout, b"")
        return run

    # How the stand-in fixture process behaves after the host returned:
    #   gone         it has exited; no process has its id
    #   cooperative  it is still waiting: it acknowledges the probe, then the stop file, and exits
    #   late         still waiting, but it answers only the stop file
    #   silent       its id is present and nothing ever acknowledges (another process may hold the id)
    #   stubborn     it acknowledges the probe and never stops
    #   unknown      whether the id exists cannot be told, and nothing acknowledges
    def judge(self, override=None, fixture="gone", nonce=None):
        """Run the judge on stand-ins. Returns the exit status, the footer, the other lines, the host calls, and every
        destructive act attempted: a signal other than 0 through os.kill, or any command other than the host."""
        clock = [1000.0]
        envs: list[dict] = []
        destructive: list = []
        host = self.host(override, clock)
        state = {"gone": "gone", "unknown": "unknown"}.get(fixture, "present")

        def run(command, **kwargs):
            if command[:1] != ["host"]:
                destructive.append(command)
                raise OSError("no command but the host is started in these tests")
            envs.append(kwargs["env"])
            return host(command, **kwargs)

        def kill(pid, sig):
            if sig != 0:
                destructive.append(("kill", pid, sig))
            raise AssertionError("no process is probed in these tests")

        def note(env, kind):
            path = pathlib.Path(env["DODONA_TEST_ACK"]) / f"{kind}-{self.PID}"
            if path.parent.is_dir() and not path.exists():
                path.write_text(nonce or env["DODONA_TEST_NONCE"], encoding="ascii")

        def tick(seconds):  # the fixture's own polling, run whenever the judge waits
            clock[0] += seconds
            if not envs:
                return
            env = envs[-1]
            probed, stopped = (pathlib.Path(env[k]).exists() for k in ("DODONA_TEST_PROBE", "DODONA_TEST_STOP"))
            if probed and fixture in ("cooperative", "stubborn"):
                note(env, "alive")
            if probed and fixture == "dir-ack":  # something not a regular file where an acknowledgment belongs
                pathlib.Path(env["DODONA_TEST_ACK"], f"alive-{self.PID}").mkdir(exist_ok=True)
            if stopped and fixture == "after-stop":  # answers the probe only once the stop file exists
                note(env, "alive")
            if stopped and fixture in ("cooperative", "late", "after-stop"):
                note(env, "stopped")

        def look(pid, deadline):
            env = envs[-1]
            if fixture in ("cooperative", "late", "after-stop") and \
                    pathlib.Path(env["DODONA_TEST_ACK"], f"stopped-{pid}").exists():
                return "gone"
            return state

        argv = ["run_provider_cases.py", "--", "host"]
        made = tempfile.mkdtemp
        # `create=True`: the judge before issue 41 had no `observe`, so the first test fails there on its verdict alone.
        with tempfile.TemporaryDirectory() as base, contextlib.redirect_stdout(io.StringIO()) as output, \
                patch.object(run_provider_cases.sys, "argv", argv), \
                patch.object(run_provider_cases.subprocess, "run", side_effect=run) as ran, \
                patch.object(run_provider_cases.os, "kill", side_effect=kill), \
                patch.object(run_provider_cases.tempfile, "mkdtemp",
                             side_effect=lambda suffix=None, prefix=None, dir=None: made(suffix, prefix, base)), \
                patch.object(run_provider_cases.time, "sleep", side_effect=tick), \
                patch.object(run_provider_cases.time, "monotonic", side_effect=lambda: clock[0]), \
                patch.object(run_provider_cases, "alive", create=True, side_effect=lambda pid: False), \
                patch.object(run_provider_cases, "observe", create=True, side_effect=look) as looked:
            code = run_provider_cases.main()
        lines = output.getvalue().splitlines()
        self.looked = looked.call_args_list
        self.nonces = [env["DODONA_TEST_NONCE"] for env in envs]
        return code, json.loads(lines[-1]), lines[:-1], ran.call_args_list, destructive

    def total(self):
        return len(self.spec["cases"])

    def test_a_host_that_exits_nonzero_with_an_ok_answer_has_not_answered(self):
        # The red of issue 41: exit 1 with {"outcome": "ok"}, a healthy transcript and no process ids was a match.
        # The footer is read with .get, so the old judge fails here on its verdict, not on a missing key.
        code, summary, lines, _, _ = self.judge({"well-behaved": {"code": 1, "answer": {"outcome": "ok"}, "pids": None}})
        self.assertEqual((code, summary.get("unfinished"), summary.get("rejected"), summary.get("all_matched")), (2, 1, [], False))
        self.assertNotIn("match    well-behaved", lines)
        self.assertTrue(any(line.startswith("UNFINISHED well-behaved:") for line in lines))

    def test_the_exit_status_alone_leaves_the_case_unfinished(self):
        # The same, with the fixture's process id recorded and seen gone: only the exit status is wrong.
        for exit_code in (1, 2, -15, -9, 0xC0000005):
            with self.subTest(exit_code=exit_code):
                code, summary, lines, _, _ = self.judge({"well-behaved": {"code": exit_code, "answer": {"outcome": "ok"}}})
                self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["matched"]), (2, 1, [], self.total() - 1))
                self.assertNotIn("match    well-behaved", lines)

    def test_every_right_answer_with_exit_0_passes_each_mode_once(self):
        code, summary, lines, calls, destructive = self.judge()
        total = self.total()
        self.assertEqual((code, summary), (0, {"cases": total, "matched": total, "all_matched": True, "unfinished": 0, "rejected": []}))
        modes = [call.args[0][-1] for call in calls]
        self.assertEqual(modes, [case["mode"] for case in self.spec["cases"]])
        self.assertEqual(len(set(modes)), len(modes))
        self.assertEqual(destructive, [])
        # Intentional refusals a host answers with exit 0 are ordinary matches.
        for mode in ("exits-before-answering", "never-answers", "garbage", "nan-in-an-answer"):
            self.assertIn(f"match    {mode}", lines)

    def test_a_completed_wrong_named_answer_is_a_named_mismatch(self):
        for answer in ({"outcome": "error", "reason": "closed"}, {"outcome": "refused"}, {"outcome": "error", "reason": "deadline"}):
            with self.subTest(answer=answer):
                code, summary, lines, _, _ = self.judge({"well-behaved": {"answer": answer}})
                self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["all_matched"]), (1, 0, ["well-behaved"], False))
                self.assertTrue(any(line.startswith("MISMATCH well-behaved:") for line in lines))
        code, summary, _, _, _ = self.judge({"garbage": {"answer": {"outcome": "error", "reason": "deadline"}}})
        self.assertEqual((code, summary["rejected"]), (1, ["garbage"]))

    def test_exit_0_without_a_readable_json_object_naming_an_outcome_is_unfinished(self):
        for answer in (b"not json", b"", b"[]", b"\xff\xfe", b'{"outcome": NaN}', b'{"reason": "closed"}',
                       b'{"outcome": 1}', b'"ok"', b"{} {}"):
            with self.subTest(answer=answer):
                code, summary, lines, _, _ = self.judge({"well-behaved": {"answer": answer}})
                self.assertEqual((code, summary["unfinished"], summary["rejected"]), (2, 1, []))
                self.assertTrue(any(line.startswith("UNFINISHED well-behaved:") for line in lines))

    def test_each_curated_mode_is_its_own_control(self):
        # The curated modes are unchanged, each judged once; a wrong outcome for one mode alone is named as that mode only.
        modes = [case["mode"] for case in self.spec["cases"]]
        self.assertEqual((len(modes), len(set(modes))), (22, 22))
        for case in self.spec["cases"]:
            with self.subTest(mode=case["mode"]):
                flipped = {"outcome": "error", "reason": "closed"} if case["outcome"] == "ok" else {"outcome": "ok"}
                code, summary, _, _, destructive = self.judge({case["mode"]: {"answer": flipped}})
                self.assertEqual((code, summary["rejected"], summary["unfinished"], destructive), (1, [case["mode"]], 0, []))
                self.assertEqual(summary["matched"], len(modes) - 1)

    def test_a_wrong_transcript_from_a_fixture_that_started_is_a_named_mismatch(self):
        code, summary, _, _, _ = self.judge({"well-behaved": {"transcript": ""}})
        self.assertEqual((code, summary["unfinished"], summary["rejected"]), (1, 0, ["well-behaved"]))

    def test_a_completed_answer_over_the_deadline_plus_grace_is_a_named_mismatch(self):
        limits = self.spec["limits"]
        slow = (limits["deadline_ms"] + limits["grace_ms"]) / 1000 + 1
        code, summary, lines, _, _ = self.judge({"never-answers": {"took": slow}})
        self.assertEqual((code, summary["unfinished"], summary["rejected"]), (1, 0, ["never-answers"]))
        self.assertTrue(any(line.startswith("MISMATCH never-answers:") and "over the deadline plus grace" in line for line in lines))
        # Slow and exit 1 is no answer at all.
        code, summary, _, _, _ = self.judge({"never-answers": {"took": slow, "code": 1}})
        self.assertEqual((code, summary["unfinished"], summary["rejected"]), (2, 1, []))

    def test_a_host_that_could_not_start_or_ran_out_of_time_is_unfinished(self):
        for failure in (FileNotFoundError(), OSError(errno.ENOSPC, "No space left on device"),
                        subprocess.TimeoutExpired("host", 28)):
            with self.subTest(failure=failure):
                code, summary, lines, _, _ = self.judge({"late": {"raise": failure}})
                self.assertEqual((code, summary["unfinished"], summary["rejected"]), (2, 1, []))
                self.assertTrue(any(line.startswith("UNFINISHED late:") for line in lines))

    def test_a_fixture_that_could_not_be_observed_is_unfinished(self):
        broken = {"unparseable transcript": {"transcript": "{not json\n"},
                  "pid file not a number": {"pids": "abc\n"},
                  "pid that would signal a group": {"pids": "0\n"},
                  "negative pid": {"pids": "-1\n"},
                  "init": {"pids": "1\n"},
                  "no pid file": {"pids": None},
                  "empty pid file": {"pids": ""},
                  "unreadable pid file": {"pids": "directory"}}
        for name, change in broken.items():
            with self.subTest(name=name):
                code, summary, lines, _, destructive = self.judge({"wrong-id": change})
                self.assertEqual((code, summary["unfinished"], summary["rejected"]), (2, 1, []))
                self.assertEqual(destructive, [])
                # Evidence is kept, and the stop file was still created in `finally`.
                self.assertTrue(any(line.startswith("UNFINISHED wrong-id:") and "kept as evidence" in line for line in lines))
        # An invalid id leads to no process action at all, not even a look, and refuses the whole file.
        too_big = run_provider_cases.PID_MAX + 1
        for pids in ("0\n", "-1\n", "-4242\n", "1\n", "abc\n", f"{too_big}\n", "9" * 30 + "\n", "+4242\n", "4_242\n", "0x10\n", f"{self.PID}\n-5\n", f"{self.PID}\n{too_big}\n"):
            with self.subTest(pids=pids):
                code, summary, _, _, destructive = self.judge({"well-behaved": {"pids": pids}}, fixture="cooperative")
                self.assertEqual((destructive, summary["unfinished"] >= 1), ([], True))
                self.assertNotIn("well-behaved", summary["rejected"])
                self.assertTrue(all(call.args[0] == self.PID for call in self.looked))  # only the other cases' valid id
                self.assertTrue(self.looked)

    def test_pid_validation_is_strict_and_in_the_platforms_range(self):
        valid = run_provider_cases.valid_pid
        self.assertEqual(valid("4242"), 4242)
        self.assertEqual(valid(str(run_provider_cases.PID_MAX)), run_provider_cases.PID_MAX)
        for text in ("0", "1", "-1", "-4242", "+4242", " 4242", "4242 ", "4_242", "0x10", "٤٢", "",
                     str(run_provider_cases.PID_MAX + 1), "9" * 11, "9" * 400, str(os.getpid())):
            with self.subTest(text=text):
                self.assertIsNone(valid(text))
        self.assertEqual(run_provider_cases.PID_MAX, 0xFFFFFFFF if sys.platform == "win32" else 0x7FFFFFFF)
        # The observer refuses an unvalidated id itself, before any system call.
        with patch.object(run_provider_cases, "exists_posix") as posix, patch.object(run_provider_cases, "exists_windows") as win:
            for pid in (-5, 0, 1, run_provider_cases.PID_MAX + 1, 1 << 80):
                self.assertEqual(run_provider_cases.observe(pid, 0.0), "unknown")
            self.assertEqual((posix.call_args_list, win.call_args_list), ([], []))

    def test_an_id_written_twice_is_one_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "pids"
            path.write_text(f"{self.PID}\n{self.PID}\n4343\n", encoding="ascii")
            self.assertEqual(run_provider_cases.read_pids(path), [self.PID, 4343])
        code, summary, _, _, _ = self.judge({"well-behaved": {"pids": f"{self.PID}\n{self.PID}\n"}})
        self.assertEqual((code, summary["unfinished"]), (0, 0))

    def test_special_files_are_quarantined_not_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = pathlib.Path(tmp)
            real = folder / "real"
            real.write_bytes(b"4242\n")
            big = folder / "big"
            big.write_bytes(b"1" * (run_provider_cases.LIMITS["pids"] + 1))
            (folder / "dir").mkdir()
            kinds = ["dir", "big"]
            try:
                os.symlink(real, folder / "link")
                kinds.append("link")
            except (OSError, NotImplementedError):
                pass  # no symbolic links here
            if hasattr(os, "mkfifo"):
                os.mkfifo(folder / "fifo")  # never opened: a pipe would block a reader
                kinds.append("fifo")
            for kind in kinds:
                with self.subTest(kind=kind), self.assertRaises(run_provider_cases.Unobserved):
                    run_provider_cases.read_private(folder / kind, run_provider_cases.LIMITS["pids"])
            self.assertIsNone(run_provider_cases.read_private(folder / "absent", 10))
            self.assertEqual(run_provider_cases.read_private(real, 10), b"4242\n")
        # An acknowledgment that is not a regular file is not one.
        code, summary, lines, _, destructive = self.judge(fixture="dir-ack")
        self.assertEqual((code, summary["rejected"], destructive), (2, [], []))
        self.assertTrue(all("not a regular file" in line for line in lines))

    def test_each_case_has_its_own_nonce(self):
        self.judge()
        self.assertEqual(len(set(self.nonces)), self.total())
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{32}", nonce) for nonce in self.nonces))

    def test_an_acknowledgment_made_after_the_stop_is_not_survival_seen_before_it(self):
        code, summary, lines, _, destructive = self.judge(fixture="after-stop")
        self.assertEqual((code, summary["rejected"], summary["unfinished"], destructive), (2, [], self.total(), []))
        self.assertTrue(all("not before cleanup" in line for line in lines))

    def test_a_missing_transcript_is_unfinished_not_a_mismatch(self):
        # Every mode records hello first, and no case declares an absent transcript, so absence is no observation.
        for mode in ("well-behaved", "exits-before-answering", "never-answers"):
            with self.subTest(mode=mode):
                code, summary, lines, _, _ = self.judge({mode: {"transcript": None}})
                self.assertEqual((code, summary["unfinished"], summary["rejected"]), (2, 1, []))
                self.assertTrue(any(line.startswith(f"UNFINISHED {mode}:") and "missing" in line for line in lines))
        self.assertFalse(any(case.get("transcript") == "absent" for case in self.spec["cases"]))

    def test_a_survivor_that_acknowledges_before_cleanup_is_named_and_stopped_without_a_signal(self):
        code, summary, lines, _, destructive = self.judge(fixture="cooperative")
        self.assertEqual((code, summary["unfinished"], summary["matched"]), (1, 0, 0))
        self.assertEqual(summary["rejected"], [case["mode"] for case in self.spec["cases"]])
        self.assertTrue(lines[0].startswith("MISMATCH well-behaved:") and "still running" in lines[0])
        self.assertEqual(destructive, [])

    def test_a_survivor_shown_only_by_the_later_stop_acknowledgment_is_unfinished(self):
        code, summary, lines, _, destructive = self.judge(fixture="late")
        self.assertEqual((code, summary["unfinished"], summary["rejected"], destructive), (2, self.total(), [], []))
        self.assertTrue(all("not before cleanup" in line for line in lines))

    def test_an_acknowledgment_of_another_run_is_not_this_ones(self):
        code, summary, lines, _, destructive = self.judge(fixture="cooperative", nonce="0" * 32)
        self.assertEqual((code, summary["unfinished"], summary["rejected"], destructive), (2, self.total(), [], []))
        self.assertTrue(all("not this case's" in line for line in lines))

    def test_uncertainty_is_never_a_pass_and_never_a_signal(self):
        # An id that is present and never acknowledges (perhaps another program's now), one whose existence cannot be
        # told, and a survivor that ignores the stop file: each case is unfinished, kept, and nothing is signalled.
        for fixture, said in (("silent", "never acknowledged"), ("unknown", "never acknowledged"),
                              ("stubborn", "nothing was signalled")):
            with self.subTest(fixture=fixture):
                code, summary, lines, calls, destructive = self.judge(fixture=fixture)
                self.assertEqual((code, summary["unfinished"], summary["rejected"]), (2, self.total(), []))
                self.assertEqual((destructive, len(calls)), ([], self.total()))
                self.assertTrue(all(said in line and "kept as evidence" in line for line in lines))

    def test_every_wait_ends_by_one_deadline(self):
        # The stand-in clock moves only when the judge sleeps: a wait that ignored the deadline would never end.
        for fixture in ("silent", "stubborn", "unknown"):
            with self.subTest(fixture=fixture):
                self.judge(fixture=fixture)
                self.assertLessEqual(len(self.looked), self.total() * 2 * int(run_provider_cases.OBSERVE_SECONDS / run_provider_cases.POLL + 2))

    def test_the_stop_file_is_created_even_when_observation_fails(self):
        made = []
        real = run_provider_cases.create

        def create(path, text):
            made.append(path.name)
            return real(path, text)
        with patch.object(run_provider_cases, "read_transcript", side_effect=RuntimeError("observation broke")), \
                patch.object(run_provider_cases, "create", side_effect=create):
            with self.assertRaises(RuntimeError):
                self.judge()
        self.assertEqual(made, ["stop"])

    def test_marker_files_are_created_only_if_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "stop"
            self.assertIsNone(run_provider_cases.create(path, "n"))
            self.assertIsNotNone(run_provider_cases.create(path, "other"))
            self.assertEqual(path.read_text(encoding="ascii"), "n")

    def test_a_folder_that_cannot_be_removed_is_unfinished(self):
        real = run_provider_cases.shutil.rmtree

        def stuck(path, *args, **kwargs):  # removes the folder, so the test leaves nothing behind, and reports a failure
            real(path, *args, **kwargs)
            if "dodona-provider-case-" in str(path):  # the test's own folder is removed without complaint
                raise OSError(errno.EBUSY, "Device or resource busy")
        with patch.object(run_provider_cases.shutil, "rmtree", side_effect=stuck):
            code, summary, _, _, _ = self.judge()
        self.assertIs(run_provider_cases.shutil.rmtree, real)
        self.assertEqual((code, summary["unfinished"], summary["rejected"]), (2, self.total(), []))

    def test_a_mismatch_then_an_unfinished_case_leaves_the_run_unfinished(self):
        code, summary, _, _, _ = self.judge({"well-behaved": {"answer": {"outcome": "error", "reason": "closed"}},
                                             "garbage": {"code": 1}})
        self.assertEqual((code, summary["unfinished"], summary["rejected"], summary["all_matched"]), (2, 1, ["well-behaved"], False))
        self.assertEqual(summary["matched"], self.total() - 2)

    def test_cases_that_cannot_be_read_leave_the_run_unfinished(self):
        with patch.object(pathlib.Path, "read_text", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            code, summary, _, calls, _ = self.judge()
        self.assertEqual((code, summary, calls), (2, {"cases": 0, "matched": 0, "all_matched": False, "unfinished": 1, "rejected": []}, []))

    @staticmethod
    def ps(code, stdout=""):
        return unittest.mock.Mock(return_value=subprocess.CompletedProcess(["ps"], code, stdout, ""))

    def test_the_posix_existence_probe_only_asks(self):
        # Signal 0, then `ps -o stat=` for the one valid id; only a clearly reported Z is an exit.
        deadline = 2000.0
        cases = {
            "no such process": (ProcessLookupError(), None, "gone"),
            "the probe failed": (OSError(errno.EINVAL, "Invalid argument"), None, "unknown"),
            "running": (None, self.ps(0, "S\n"), "present"),
            "running, another user's": (PermissionError(), self.ps(0, "Ss+\n"), "present"),
            "zombie": (None, self.ps(0, "Z\n"), "gone"),
            "zombie with flags": (None, self.ps(0, "Z+\n"), "gone"),
            "ps found nothing": (None, self.ps(1, ""), "unknown"),
            "ps said nothing": (None, self.ps(0, "\n"), "unknown"),
            "ps said two things": (None, self.ps(0, "S Z\n"), "unknown"),
            "ps said something unexpected": (None, self.ps(0, "?\n"), "unknown"),
            "ps said a header": (None, self.ps(0, "STAT\nZ\n"), "unknown"),
            "ps is missing": (None, unittest.mock.Mock(side_effect=FileNotFoundError()), "unknown"),
            "ps timed out": (None, unittest.mock.Mock(side_effect=subprocess.TimeoutExpired("ps", 1)), "unknown"),
        }
        for name, (effect, ps, want) in cases.items():
            with self.subTest(name=name), patch.object(run_provider_cases.time, "monotonic", return_value=1999.5):
                kill = unittest.mock.Mock(side_effect=[effect])
                ps = ps or unittest.mock.Mock(side_effect=AssertionError("ps must not run"))
                self.assertEqual(run_provider_cases.exists_posix(self.PID, deadline, kill=kill, run=ps), want)
                self.assertEqual(kill.call_args_list, [unittest.mock.call(self.PID, 0)])  # signal 0 only, ever
                for call in ps.call_args_list:
                    self.assertEqual(call.args[0], ["ps", "-o", "stat=", "-p", str(self.PID)])
                    self.assertLessEqual(call.kwargs["timeout"], 0.5)  # what is left of the case's deadline
        # Past the deadline, `ps` is not started at all and the state is unknown.
        late = unittest.mock.Mock(side_effect=AssertionError("ps must not run"))
        with patch.object(run_provider_cases.time, "monotonic", return_value=2000.0):
            self.assertEqual(run_provider_cases.exists_posix(self.PID, deadline, kill=unittest.mock.Mock(), run=late), "unknown")
        self.assertEqual(late.call_args_list, [])

    def test_the_judge_has_no_way_to_signal_a_recorded_process(self):
        # Cleanup is the fixture's own: the stop file. No signalling helper and no command-line heuristic; `ps` asks
        # only for the state of one validated id.
        for name in ("end", "end_posix", "SIGKILL", "observe_posix", "FIXTURE_COMMANDS"):
            self.assertFalse(hasattr(run_provider_cases, name), name)
        source = (ROOT / "tools" / "run_provider_cases.py").read_text(encoding="utf-8")
        for word in ("SIGKILL", "SIGTERM", "taskkill", "TerminateProcess", "killpg", ".kill(", ".terminate(",
                     "command=", "-ww", "args="):
            self.assertNotIn(word, source)
        self.assertEqual(source.count('"ps"'), 1)
        self.assertIn('["ps", "-o", "stat=", "-p", str(pid)]', source)
        self.assertEqual(source.count("subprocess.run("), 1)  # the host; `ps` runs through the injected `run`
        fixture = (ROOT / "conformance" / "provider" / "misbehaving_provider.py").read_text(encoding="utf-8")
        self.assertNotIn("time.sleep(600)", fixture)
        for name in ("DODONA_TEST_STOP", "DODONA_TEST_PROBE", "DODONA_TEST_ACK", "DODONA_TEST_NONCE", '"x"'):
            self.assertIn(name, fixture)


class CheckHostJudgeTests(unittest.TestCase):
    """The host-check judge (tools/run_check_cases.py) judges only an answer the host completed with exit 0 (issue 41).
    A host that exited other than 0 after printing a valid refusal, could not start or ran out of time, printed no
    JSON object, or left records that cannot be read is unfinished, never a match or a mismatch. A completed wrong
    answer is a mismatch named in `rejected` by its label and content digest. Only the ten curated preflight refusals
    may leave no transcript and no process id. Every host is a stand-in: no process is started, probed or signalled.
    The stand-in also answers the judge before issue 41, which started the host through Popen and a pipe."""

    spec = json.loads((ROOT / "conformance" / "provider" / "check-cases.json").read_text(encoding="utf-8"))
    TRUSTED = ("bad-input", "unknown-file")

    def preflight(self):
        """The trusted preflight rows, from the curated expectation alone."""
        return [i for i, c in enumerate(self.spec["cases"])
                if c.get("outcome") == "refused" and c.get("reason") in self.TRUSTED and c.get("runs") == 0]

    @staticmethod
    def label(case):
        return f"{case['mode']} ({case['run']}) [{run_check_cases.case_id(case)}]"

    def judge(self, cases, override=None, platform=None):
        """Run the judge on `cases` with a stand-in host. `override` maps a case's index in `cases` to another exit
        code, standard output, transcript, run record or pid file (None removes the file), or an exception."""
        override = override or {}
        platform = platform or sys.platform
        order = [i for i, c in enumerate(cases) if platform not in c.get("not_on", [])]
        sent: list = []
        destructive: list = []
        self.pipes = []

        def behave(env, given):
            i = order[len(sent)]
            sent.append(given)
            case, change = cases[i], override.get(i, {})
            for name, key in (("transcript", "DODONA_TEST_SEEN"), ("runs", "DODONA_EXECUTOR_RECORD"),
                              ("pids", "DODONA_TEST_PIDFILE")):
                if name in change:
                    path = pathlib.Path(env[key])
                    if change[name] is None:
                        path.unlink()
                    else:
                        path.write_text(change[name], encoding="utf-8")
            if "raise" in change:
                raise change["raise"]
            right = {k: case[k] for k in ("outcome", "verdict", "reason") if k in case}
            return change.get("code", 0), change.get("stdout", json.dumps(right).encode("utf-8"))

        def run(command, **kwargs):
            if command != ["host"]:
                destructive.append(command)
                raise OSError("no command but the host is started in these tests")
            self.pipes.append(subprocess.PIPE in (kwargs.get("stdin"), kwargs.get("stdout")) or "input" in kwargs)
            given = kwargs["stdin"].read() if hasattr(kwargs.get("stdin"), "read") else kwargs.get("input")
            code, stdout = behave(kwargs["env"], given)
            if hasattr(kwargs.get("stdout"), "write"):
                kwargs["stdout"].write(stdout)
                stdout = None
            return subprocess.CompletedProcess(command, code, stdout, None)

        class Popen:  # how the judge before issue 41 started the host
            def __init__(self, command, **kwargs):
                if command != ["host"]:
                    destructive.append(command)
                    raise OSError("no command but the host is started in these tests")
                self.env, self.returncode = kwargs["env"], None

            def communicate(self, input=None, timeout=None):
                self.returncode, stdout = behave(self.env, input)
                return stdout, None

            def kill(self):
                destructive.append(("kill", "host"))

        def kill(pid, sig):
            if sig != 0:
                destructive.append(("kill", pid, sig))
            raise ProcessLookupError()

        made = tempfile.mkdtemp
        fake_sys = types.SimpleNamespace(platform=platform, argv=["run_check_cases.py", "--", "host"],
                                         executable=sys.executable, path=sys.path)
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as kit:
            pathlib.Path(kit, "check-cases.json").write_text(json.dumps({"cases": cases}), encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as output, \
                    patch.object(run_check_cases, "sys", fake_sys), \
                    patch.object(run_check_cases, "KIT", pathlib.Path(kit)), \
                    patch.object(run_check_cases.subprocess, "run", side_effect=run), \
                    patch.object(run_check_cases.subprocess, "Popen", Popen), \
                    patch.object(run_check_cases.os, "kill", side_effect=kill), \
                    patch.object(run_check_cases.tempfile, "mkdtemp",
                                 side_effect=lambda suffix=None, prefix=None, dir=None: made(suffix, prefix, base)), \
                    patch.object(run_check_cases.time, "sleep", side_effect=lambda seconds: None), \
                    patch.object(run_provider_cases, "observe", side_effect=lambda pid, deadline: "gone"):
                code = run_check_cases.main()
        lines = output.getvalue().splitlines()
        return code, json.loads(lines[-1]), lines[:-1], sent, destructive

    def only_preflight(self):
        return [self.spec["cases"][i] for i in self.preflight()]

    def test_the_census_is_the_curated_one(self):
        cases = self.spec["cases"]
        pre = self.preflight()
        self.assertEqual(len(cases), 132)
        self.assertEqual(sorted(cases[i]["reason"] for i in pre), ["bad-input"] * 8 + ["unknown-file"] * 2)
        self.assertEqual(sum("win32" in c.get("not_on", []) for c in cases), 3)
        # The judge's own preflight is read from the curated case alone, and names exactly these ten.
        self.assertEqual([i for i, c in enumerate(cases) if run_check_cases.preflight(c)], pre)
        self.assertFalse(run_check_cases.preflight(dict(cases[pre[0]], outcome="verdict")))
        self.assertFalse(run_check_cases.preflight(dict(cases[pre[0]], runs=1)))
        # Every case has its own stable identifier of its whole content, beside its readable label.
        ids = [run_check_cases.case_id(c) for c in cases]
        self.assertEqual(len(set(ids)), len(cases))
        self.assertEqual(ids, [run_check_cases.case_id(json.loads(json.dumps(c))) for c in cases])

    def test_valid_refusals_with_exit_0_match_and_the_report_is_typed(self):
        code, summary, lines, _, destructive = self.judge(self.only_preflight())
        self.assertEqual((code, summary), (0, {"cases": 10, "judged": 10, "skipped": 0, "matched": 10,
                                               "all_matched": True, "unfinished": 0, "rejected": []}))
        self.assertEqual(lines, [f"match    {self.label(c)}" for c in self.only_preflight()])
        self.assertEqual(destructive, [])

    def test_a_valid_refusal_with_a_nonzero_exit_is_unfinished(self):
        # The red of issue 41 here: a valid refusal printed by a host that exited 1 was a match.
        for exit_code in (1, 2, -9, 0xC0000005):
            with self.subTest(exit_code=exit_code):
                code, summary, lines, _, _ = self.judge(self.only_preflight(), {0: {"code": exit_code}})
                self.assertEqual((code, summary.get("unfinished"), summary.get("rejected"), summary.get("matched")),
                                 (2, 1, [], 9))
                self.assertTrue(lines[0].startswith("UNFINISHED "))

    def test_exit_0_without_a_json_object_naming_an_outcome_is_unfinished(self):
        for stdout in (b"not json", b"", b"[]", b"\xff\xfe", b'{"outcome": NaN}', b'{"reason": "bad-input"}',
                       b'{"outcome": 1}', b"{} {}", b"x" * (run_check_cases.ANSWER_LIMIT + 1)):
            with self.subTest(stdout=stdout[:20]):
                code, summary, lines, _, _ = self.judge(self.only_preflight(), {0: {"stdout": stdout}})
                self.assertEqual((code, summary.get("unfinished"), summary.get("rejected")), (2, 1, []))
                self.assertTrue(lines[0].startswith("UNFINISHED "))

    def test_a_completed_wrong_answer_is_a_named_mismatch(self):
        cases = self.only_preflight()
        for answer in ({"outcome": "refused", "reason": "closed"}, {"outcome": "verdict", "verdict": "passed"}):
            with self.subTest(answer=answer):
                code, summary, lines, _, _ = self.judge(cases, {0: {"stdout": json.dumps(answer).encode("utf-8")}})
                self.assertEqual((code, summary.get("unfinished"), summary.get("rejected"), summary.get("matched")),
                                 (1, 0, [self.label(cases[0])], 9))
                self.assertTrue(lines[0].startswith(f"MISMATCH {self.label(cases[0])}: "))

    def test_a_host_that_could_not_start_or_ran_out_of_time_is_unfinished(self):
        for failure in (FileNotFoundError(), OSError(errno.ENOSPC, "No space left on device"),
                        subprocess.TimeoutExpired("host", run_check_cases.HOST_SECONDS)):
            with self.subTest(failure=failure):
                code, summary, _, _, destructive = self.judge(self.only_preflight(), {0: {"raise": failure}})
                self.assertEqual((code, summary.get("unfinished"), summary.get("rejected")), (2, 1, []))
                self.assertEqual(destructive, [])

    def test_records_that_cannot_be_read_are_unfinished(self):
        cases = self.only_preflight()
        for name, change in {"malformed run record": {"runs": "{not json\n"},
                             "run record not objects": {"runs": "[1]\n"},
                             "run record removed": {"runs": None},
                             "malformed transcript": {"transcript": "{not json\n"},
                             "transcript removed": {"transcript": None},
                             "pid file not ids": {"pids": "abc\n"},
                             "pid file removed": {"pids": None}}.items():
            with self.subTest(name=name):
                code, summary, lines, _, _ = self.judge(cases, {0: change})
                self.assertEqual((code, summary.get("unfinished"), summary.get("rejected")), (2, 1, []))
                self.assertTrue(lines[0].startswith("UNFINISHED ") and "kept as evidence" in lines[0])

    def test_only_a_trusted_preflight_may_leave_no_checker_record(self):
        # A case the host must take to the provider, answered rightly but with no transcript and no process id:
        # the checker was never seen, so nothing about the host follows. The old judge called it a mismatch.
        others = [c for i, c in enumerate(self.spec["cases"]) if i not in self.preflight()][:3]
        code, summary, lines, _, _ = self.judge(others)
        self.assertEqual((code, summary.get("unfinished"), summary.get("rejected")), (2, 3, []))
        self.assertTrue(all(line.startswith("UNFINISHED ") for line in lines))
        # A preflight case whose answer is wrong is judged on its curated expectation, not on what was answered.
        wrong = json.dumps({"outcome": "verdict", "verdict": "passed"}).encode("utf-8")
        code, summary, _, _, _ = self.judge(self.only_preflight(), {0: {"stdout": wrong}})
        self.assertEqual((code, summary.get("unfinished")), (1, 0))

    def test_the_whole_census_on_each_platform(self):
        total = len(self.spec["cases"])
        for platform, skipped in (("linux", 0), ("darwin", 0), ("win32", 3)):
            with self.subTest(platform=platform):
                code, summary, lines, sent, destructive = self.judge(self.spec["cases"], platform=platform)
                judged = total - skipped
                self.assertEqual((summary.get("cases"), summary.get("judged"), summary.get("skipped")),
                                 (total, judged, skipped))
                self.assertEqual((len(sent), destructive), (judged, []))
                self.assertEqual(summary["matched"] + summary["unfinished"] + len(summary["rejected"]), judged)
                self.assertEqual((summary["matched"], summary["unfinished"], code), (10, judged - 10, 2))
                self.assertEqual(sum(line.startswith("skip     ") for line in lines), skipped)

    def test_the_exact_text_is_given_through_private_files_not_pipes(self):
        index = next(i for i, c in enumerate(self.spec["cases"]) if "input_text" in c)
        case = self.spec["cases"][index]
        _, _, _, sent, _ = self.judge([case])
        self.assertEqual((sent, self.pipes), ([case["input_text"].encode("utf-8")], [False]))

    def test_the_judge_has_no_way_to_signal_a_recorded_process(self):
        source = (ROOT / "tools" / "run_check_cases.py").read_text(encoding="utf-8")
        for word in ("os.kill", "SIGKILL", "SIGTERM", "taskkill", "tasklist", "TerminateProcess", "killpg", ".kill(",
                     ".terminate(", "Popen", "communicate", "PIPE"):
            self.assertNotIn(word, source)
        self.assertEqual(source.count("subprocess.run("), 1)  # the host, ended on timeout through its own handle
        self.assertFalse(hasattr(run_check_cases, "alive"))
        # The probe and stop are the provider judge's own, not a copy.
        self.assertIn("observing.watch_fixture(", source)
        self.assertNotIn("PROBE_SECONDS", source)
        for fixture in ("misbehaving_checker.py", "fake_executor.py"):
            text = (ROOT / "conformance" / "provider" / fixture).read_text(encoding="utf-8")
            self.assertIn("from misbehaving_provider import POLL", text)
            self.assertNotIn("time.sleep(6", text)  # the processes left behind wait cooperatively, not by a bare sleep
        # Every intentional wait of the checker answers the stop file; the executor's `slow` report delay is its own.
        checker = (ROOT / "conformance" / "provider" / "misbehaving_checker.py").read_text(encoding="utf-8")
        self.assertNotIn("time.sleep(", checker)


class PlantJsTests(unittest.TestCase):
    """Keep the standalone JavaScript runner tests registered in hosted CI."""

    command = "run: node --test kernel2/test-plant.js"

    def registered(self, workflow: str) -> bool:
        job = re.search(r"(?ms)^  checks:[ \t]*\n(.*?)(?=^  [\w-]+:[ \t]*$|\Z)", workflow)
        if job is None:
            return False
        steps = re.split(r"(?m)^      - ", job[1])[1:]
        for step in steps:
            if re.search(r"(?m)^\s*run: cargo build\b", step):
                break
            if self.command in [line.strip() for line in step.splitlines()]:
                return not re.search(r"(?m)^\s*(if|continue-on-error):", step)
        return False

    def test_plant_js_cases_run_on_the_hosted_matrix(self):
        self.assertTrue((ROOT / "kernel2" / "test-plant.js").is_file())
        workflow = (ROOT / ".github" / "workflows" / "checks.yml").read_text(encoding="utf-8")
        self.assertTrue(self.registered(workflow))
        for replacement in ("run: node --test kernel2/test.js",
                            "if: matrix.os == 'ubuntu-26.04'\n        " + self.command,
                            "continue-on-error: true\n        " + self.command):
            with self.subTest(replacement=replacement):
                self.assertFalse(self.registered(workflow.replace(self.command, replacement)))


class StatusJudgeTests(unittest.TestCase):
    """A project status mismatch requires three completed processes and a sound reference premise."""

    case = {"name": "an empty ledger has a report", "files": {}, "providers": {}, "ledgers": [], "policy": {}, "expect": {}}
    reference = {"judged": {"kind": "status", "name": "this-project", "self": {}, "policy": {},
                            "obligations": {}, "intents": {}, "steps": [{}]}, "coverage": {}, "ledger": {},
                 "not_served": [], "not_checkable": [], "policy_not_applied": [], "policy_source": "policy",
                 "project_doubts": []}
    report = {"obligations": {}, "intents": {}, "project": {"status": "nothing-required"}, "rejected": 0}
    right = dict(reference, report=report, project_status="nothing-required")

    @staticmethod
    def answered(payload, code=0, stderr=b""):
        return subprocess.CompletedProcess([], code, json.dumps(payload).encode("utf-8"), stderr)

    def exercise(self, answers, cases=None, variants=None):
        argv = ["run_status_cases.py", "--jobs", "1", "--kernel", "peer", "--", "kernel", "status"]
        if variants is not None:
            argv.insert(1, "--variants")
        cases = [self.case] if cases is None else cases
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(run_status_cases.sys, "argv", argv), \
                patch.object(run_status_cases, "CASES") as spec, patch.object(run_status_cases, "variants") as generated, \
                patch.object(run_status_cases.subprocess, "run", side_effect=answers):
            spec.read_text.return_value = json.dumps({"cases": cases, "site": {}})
            generated.return_value = variants
            code = run_status_cases.main()
        lines = output.getvalue().splitlines()
        return code, json.loads(lines[-1]), lines[:-1]

    def test_peer_report_from_failed_process_cannot_pass(self):
        code, summary, _ = self.exercise([
            self.answered(self.right), self.answered(self.reference),
            self.answered({"results": [self.report]}, 1, b"ENOSPC"),
        ])
        self.assertEqual(code, 2)
        self.assertEqual((summary["matched"], summary["unfinished"], summary["rejected"]), (0, 1, []))

    def replies(self):
        return [self.answered(self.right), self.answered(self.reference), self.answered({"results": [self.report]})]

    def test_launch_timeout_exit_and_invalid_json_are_unfinished_for_each_role(self):
        failures = [FileNotFoundError("missing command"), subprocess.TimeoutExpired("command", 120),
                    OSError(errno.ENOSPC, "No space left on device"), self.answered({}, -15),
                    self.answered({}, 0xC0000005), self.answered({}, 1, b"No space left on device"),
                    subprocess.CompletedProcess([], 0, b'{"x":1,"x":2}', b""), self.answered([])]
        for index, role in enumerate(("status command", "reference status", "independent scenario")):
            for failure in failures:
                with self.subTest(role=role, failure=failure):
                    answers = self.replies()
                    answers[index] = failure
                    code, summary, lines = self.exercise(answers)
                    self.assertEqual(code, 2)
                    self.assertEqual((summary["matched"], summary["unfinished"], summary["rejected"]), (0, 1, []))
                    self.assertIn(role, lines[0])

    def test_completed_wrong_status_is_named(self):
        answers = self.replies()
        answers[0] = self.answered(dict(self.right, judged={}, project_status="failed"))
        replies = iter(answers)

        def run(command, **kwargs):
            if command[-1] == "scenario":
                self.assertEqual(json.loads(kwargs["input"]), self.reference["judged"])
            return next(replies)

        code, summary, lines = self.exercise(run)
        self.assertEqual(code, 1)
        self.assertEqual(summary, {"cases": 1, "judged": 1, "skipped": 0, "matched": 0, "all_matched": False,
                                   "unfinished": 0, "rejected": [self.case["name"]]})
        self.assertIn("judged differs from the reference", lines[0])
        self.assertIn("project_status", lines[0])

    def test_expected_refusal_with_exit_zero_can_match(self):
        case = dict(self.case, expect={"refused": "provider-not-started"})
        expected = {"refused": "provider-not-started", "detail": "the fixture's provider is absent"}
        code, summary, _ = self.exercise([self.answered(expected)] * 2, cases=[case])
        self.assertEqual((code, summary["matched"], summary["unfinished"], summary["all_matched"]), (0, 1, 0, True))
        wrong = self.answered(dict(expected, refused="bad-manifest"))
        code, summary, _ = self.exercise([wrong, self.answered(expected)], cases=[case])
        self.assertEqual((code, summary["rejected"], summary["unfinished"]), (1, [case["name"]], 0))

    def test_incomplete_reference_or_scenario_and_wrong_premises_are_unfinished(self):
        for index, payload in [(1, {}), (1, dict(self.reference, coverage=[])),
                               (1, {"refused": "bad-input", "detail": "unexpected"}),
                               (2, {"results": []}), (2, {"results": [{}]})]:
            with self.subTest(role=index, payload=payload):
                answers = self.replies()
                answers[index] = self.answered(payload)
                code, summary, _ = self.exercise(answers)
                self.assertEqual((code, summary["rejected"], summary["unfinished"]), (2, [], 1))
        case = dict(self.case, expect={"status": {"project": "passed"}})
        code, summary, lines = self.exercise(self.replies(), cases=[case])
        self.assertEqual((code, summary["rejected"], summary["unfinished"]), (2, [], 1))
        self.assertIn("disagree with the fixture", lines[0])

    def test_variants_count_failed_references_and_use_completed_reference_refusals(self):
        cases = [dict(self.case, name="lost reference"), dict(self.case, name="expected refusal")]
        refused = self.answered({"refused": "bad-input", "detail": "variant input is invalid"})
        code, summary, lines = self.exercise([self.answered(self.right), OSError(errno.ENOSPC, "disk full"), refused, refused],
                                             variants=cases)
        self.assertEqual((code, summary), (2, {"cases": 2, "judged": 2, "skipped": 0, "matched": 1, "all_matched": False,
                                              "unfinished": 1, "rejected": []}))
        self.assertTrue(lines[0].startswith("UNFINISHED lost reference:"))
        self.assertEqual(lines[1], "match    expected refusal")

    def test_unfinished_takes_precedence_over_a_completed_rejection(self):
        cases = [dict(self.case, name="wrong status"), dict(self.case, name="timed out")]
        answers = self.replies()
        answers[0] = self.answered(dict(self.right, project_status="failed"))
        answers.append(subprocess.TimeoutExpired("status command", 120))
        code, summary, _ = self.exercise(answers, cases=cases)
        self.assertEqual((code, summary["matched"], summary["unfinished"], summary["rejected"]), (2, 0, 1, ["wrong status"]))

    def test_a_refused_preimage_read_cannot_supply_a_completed_report(self):
        case = dict(self.case, owner_ledger={"entries": [{"kind": "act", "body": {"target": "$baseline:i1"}}]})
        refused = self.answered({"refused": "bad-input", "detail": "no preimages"})
        code, summary, lines = self.exercise([refused, *self.replies()], cases=[case])
        self.assertEqual((code, summary["unfinished"], summary["rejected"]), (2, 1, []))
        self.assertIn("refused to read the fixture's preimages", lines[0])

    def test_link_capability_skip_differs_from_fixture_io_failure(self):
        cases = [dict(self.case, name="requires a link", links={"link": "target"}), self.case]
        with patch.object(run_status_cases.os, "symlink", side_effect=PermissionError(errno.EPERM, "links unavailable")):
            code, summary, _ = self.exercise(self.replies(), cases=cases)
        self.assertEqual((code, summary["judged"], summary["skipped"], summary["matched"], summary["unfinished"]), (0, 1, 1, 1, 0))
        with patch.object(run_status_cases.os, "symlink", side_effect=OSError(errno.ENOSPC, "disk full")):
            code, summary, _ = self.exercise(self.replies(), cases=cases)
        self.assertEqual((code, summary["judged"], summary["skipped"], summary["matched"], summary["unfinished"]), (2, 2, 0, 1, 1))


class RunJudgeTests(unittest.TestCase):
    """A project run mismatch requires completed commands and a sound reference premise."""

    case = StatusJudgeTests.case
    answered = staticmethod(StatusJudgeTests.answered)

    def exercise(self, answers, cases=None):
        argv = ["run_run_cases.py", "--jobs", "1", "--kernel", "peer", "--status", "kernel status", "--", "kernel", "run"]
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(run_run_cases.sys, "argv", argv), \
                patch.object(run_run_cases, "CASES") as spec, patch.object(run_status_cases.subprocess, "run", side_effect=answers):
            spec.read_text.return_value = json.dumps({"cases": [self.case] if cases is None else cases, "site": {}})
            code = run_run_cases.main()
        lines = output.getvalue().splitlines()
        return code, json.loads(lines[-1]), lines[:-1]

    def test_refusal_text_from_a_failed_command_is_unfinished(self):
        case = dict(self.case, expect={"refused": "bad-input"})
        refusal = {"refused": "bad-input", "detail": "fixture"}
        code, summary, lines = self.exercise([
            self.answered(refusal, 1, b"No space left on device"), self.answered(refusal),
        ], [case])
        self.assertEqual(code, 2)
        self.assertEqual((summary["matched"], summary["unfinished"], summary["rejected"]), (0, 1, []))
        self.assertIn("UNFINISHED " + case["name"], lines[0])


    @classmethod
    def report_answers(cls):
        report = StatusJudgeTests.right
        counts = dict.fromkeys(run_run_cases.COUNT_KEYS, 0)
        run = dict(report, counts=counts)
        return [cls.answered(payload) for payload in
                (run, report, run, run, report, run, {"results": [report["report"]]})]

    def test_complete_reports_and_expected_refusals_match(self):
        code, summary, _ = self.exercise(self.report_answers())
        self.assertEqual(code, 0)
        self.assertEqual(summary, {"cases": 1, "judged": 1, "skipped": 0, "matched": 1, "all_matched": True,
                                   "rejected": [], "unfinished": 0})
        refusal = self.answered({"refused": "bad-input", "detail": "fixture"})
        code, summary, _ = self.exercise([refusal, refusal], [dict(self.case, expect={"refused": "bad-input"})])
        self.assertEqual(code, 0)
        self.assertTrue(summary["all_matched"])

    def test_launch_timeout_exit_and_invalid_json_are_unfinished_for_each_role(self):
        failures = [FileNotFoundError("missing command"), subprocess.TimeoutExpired("command", 300),
                    OSError(errno.ENOSPC, "No space left on device"), self.answered({}, -15),
                    self.answered({}, 0xC0000005), self.answered({}, 1, b"No space left on device"),
                    subprocess.CompletedProcess([], 0, b'{"x":1,"x":2}', b""), self.answered([])]
        roles = ("run command", "run command's status command", "run command's second run",
                 "reference run", "reference run's status command", "reference run's second run", "independent scenario")
        for index, role in enumerate(roles):
            for failure in failures:
                with self.subTest(role=role, failure=failure):
                    answers = self.report_answers()
                    answers[index] = failure
                    code, summary, lines = self.exercise(answers)
                    self.assertEqual(code, 2)
                    self.assertEqual((summary["matched"], summary["unfinished"], summary["rejected"]), (0, 1, []))
                    self.assertIn(role, lines[0])

    def test_broken_reference_premises_are_unfinished(self):
        report = StatusJudgeTests.right
        cases = [
            (3, self.answered({"refused": "bad-input", "detail": "unexpected"})),
            (3, self.answered(dict(report, counts=dict.fromkeys(run_run_cases.COUNT_KEYS, 0), judged={}))),
            (3, self.answered(dict(report, counts=dict.fromkeys(run_run_cases.COUNT_KEYS, 0), project_status="failed"))),
            (6, self.answered({"results": []})),
        ]
        for index, failure in cases:
            with self.subTest(index=index, failure=failure):
                answers = self.report_answers()
                answers[index] = failure
                code, summary, lines = self.exercise(answers)
                self.assertEqual(code, 2)
                self.assertEqual((summary["matched"], summary["unfinished"], summary["rejected"]), (0, 1, []))
                self.assertIn("UNFINISHED " + self.case["name"], lines[0])

    def test_completed_wrong_run_and_wrong_second_count_are_named(self):
        report = StatusJudgeTests.right
        zero = dict.fromkeys(run_run_cases.COUNT_KEYS, 0)
        failures = [
            (0, self.answered(dict(report, counts=dict(zero, passed=1)))),
            (0, self.answered(dict(report, counts=zero, judged={}))),
            (2, self.answered(dict(report, counts=dict(zero, checked=False)))),
        ]
        for index, failure in failures:
            with self.subTest(index=index, failure=failure):
                answers = self.report_answers()
                answers[index] = failure
                code, summary, lines = self.exercise(answers)
                self.assertEqual(code, 1)
                self.assertEqual((summary["matched"], summary["unfinished"], summary["rejected"]), (0, 0, [self.case["name"]]))
                self.assertIn("MISMATCH " + self.case["name"], lines[0])

    def test_unfinished_takes_precedence_but_keeps_completed_names(self):
        rejected = dict(self.case, expect={"refused": "bad-input"})
        unfinished = dict(rejected, name="unfinished case")
        good = self.answered({"refused": "bad-input", "detail": "fixture"})
        wrong = self.answered({"refused": "bad-project", "detail": "wrong"})
        code, summary, _ = self.exercise([wrong, good, subprocess.TimeoutExpired("run", 300)], [rejected, unfinished])
        self.assertEqual(code, 2)
        self.assertEqual((summary["judged"], summary["unfinished"], summary["rejected"]), (2, 1, [rejected["name"]]))

    def test_platform_skip_never_counts_as_a_match(self):
        case = dict(self.case, name="unsupported link", links={"link": "file"})
        with patch.object(run_status_cases, "make_link", side_effect=run_status_cases.Skip("link unavailable")):
            code, summary, lines = self.exercise(self.report_answers(), [case, self.case])
        self.assertEqual(code, 0)
        self.assertEqual((summary["cases"], summary["judged"], summary["skipped"], summary["matched"]), (2, 1, 1, 1))
        self.assertIn("skipped  " + case["name"], lines[0])

    def test_no_judged_cases_or_ambiguous_names_cannot_match(self):
        for cases in ([], [self.case, self.case]):
            with self.subTest(cases=cases):
                code, summary, _ = self.exercise([], cases)
                self.assertEqual(code, 2)
                self.assertEqual((summary["judged"], summary["matched"], summary["all_matched"]), (0, 0, False))


class JudgeTests(unittest.TestCase):
    """The judge must never turn an unfinished or wrong run into a match."""

    hold = {"config": "a.cfg", "expect": "no-violation", "expect_exit": 0}
    viol = {"config": "b.cfg", "expect": "violation", "expect_exit": 12, "of": "Sound"}
    done = check_models.NO_ERROR + "\n10 states generated, 5 distinct states found, 0 states left on queue.\n"

    def test_complete_search_matches(self):
        self.assertTrue(check_models.judge(self.hold, 0, self.done)["match"])

    def test_exit_zero_without_completion_is_not_a_match(self):
        self.assertFalse(check_models.judge(self.hold, 0, "")["match"])

    def test_unfinished_search_is_not_a_match(self):
        out = "10 states generated, 5 distinct states found, 3 states left on queue.\n"
        self.assertFalse(check_models.judge(self.hold, 255, out)["match"])

    def test_did_not_run_is_not_a_match(self):
        self.assertFalse(check_models.judge(self.hold, None, "")["match"])
        self.assertFalse(check_models.judge(self.viol, None, "")["match"])

    def test_named_violation_matches(self):
        self.assertTrue(check_models.judge(self.viol, 12, "Error: Invariant Sound is violated.\n")["match"])

    def test_violation_in_the_initial_state_matches(self):
        out = "Error: Invariant Sound is violated by the initial state:\n"
        self.assertTrue(check_models.judge(self.viol, 12, out)["match"])

    def test_a_longer_property_name_is_not_a_match(self):
        self.assertFalse(check_models.judge(self.viol, 12, "Error: Invariant SoundX is violated.\n")["match"])
        self.assertFalse(check_models.judge(self.viol, 12, "Error: Invariant XSound is violated by the initial state:\n")["match"])

    def test_other_violation_is_not_a_match(self):
        self.assertFalse(check_models.judge(self.viol, 12, "Error: Invariant TypeOK is violated.\n")["match"])

    def test_executor_refusal_is_not_a_match(self):
        self.assertFalse(check_models.judge(self.hold, 75, "")["match"])
        self.assertFalse(check_models.judge(self.viol, 75, "")["match"])

    def test_temporal_violation(self):
        live = {"config": "c.cfg", "expect": "temporal-violation", "expect_exit": 13, "of": "P"}
        self.assertTrue(check_models.judge(live, 13, "Error: Temporal properties were violated.\n")["match"])
        self.assertFalse(check_models.judge(live, 0, self.done)["match"])
        self.assertFalse(check_models.judge(live, 12, "Error: Invariant Sound is violated.\n")["match"])
        self.assertFalse(check_models.judge(self.hold, 13, "Error: Temporal properties were violated.\n")["match"])

    def test_crash_is_not_the_expected_violation(self):
        self.assertFalse(check_models.judge(self.viol, 255, "java.io.IOException: File too large\n")["match"])

    def test_violation_where_none_expected(self):
        self.assertFalse(check_models.judge(self.hold, 12, "Error: Invariant Sound is violated.\n")["match"])

    def test_expected_violation_but_search_passed(self):
        self.assertFalse(check_models.judge(self.viol, 0, self.done)["match"])


def main() -> int:
    for check in [check_json_and_toml, check_links, check_line_endings, check_model_cases,
                  check_indexes] + GAP_CHECKS:
        check()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(JudgeTests)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ToolPinTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(KitAdequacyTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(LedgerJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(InputJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(KeyVectorJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(CanonicalVectorJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(PathVectorJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(AttestJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(HarnessJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ProviderJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(CheckHostJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(StatusJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(RunJudgeTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(PlantJsTests))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    for line in problems:
        print("PROBLEM", line)
    ok = not problems and result.wasSuccessful()
    print("repository checks:", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
