"""Checks of this repository that need no model checker and run on any platform.

Stage-0 helper (decision 0023): disposable, to be replaced by dodona itself.
Exit status is 0 only if every check passed.
"""
from __future__ import annotations

import contextlib
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
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_models  # noqa: E402
import pathcheck  # noqa: E402
import run_kit  # noqa: E402

problems: list[str] = []

SKIPPED_PARTS = {".git", "__pycache__", "target"}


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


def gap_every_tool_compiles() -> None:
    """A syntax error in the status command reached the branch because nothing ran that file."""
    for path in sorted(list((ROOT / "tools").glob("*.py")) + list((ROOT / "providers").rglob("*.py"))
                       + list((ROOT / "conformance").rglob("*.py")) + list((ROOT / ".github").rglob("*.py"))):
        try:
            compile(path.read_text(encoding="utf-8"), str(path), "exec")  # checks syntax, writes nothing
        except SyntaxError as err:
            problems.append(f"{path.relative_to(ROOT)} does not compile: line {err.lineno}: {err.msg}")


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


def gap_workflows_are_safe() -> None:
    """Self-hosted runners must never run code from a pull request; actions are pinned."""
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        for use in re.findall(r"uses: (\S+)", text):
            if not re.search(r"@[0-9a-f]{40}$", use):
                problems.append(f"{path.name}: action {use} is not pinned to a commit")
        if "self-hosted" in text:
            trigger = text.split("jobs:")[0]
            if "pull_request" in trigger:
                problems.append(f"{path.name}: runs on a self-hosted runner and is triggered by pull requests")
            if "github.ref == 'refs/heads/main'" not in text or "github.repository == 'sloik/dodona'" not in text:
                problems.append(f"{path.name}: self-hosted job is not restricted to this repository's main branch")
        if "permissions:" not in text:
            problems.append(f"{path.name}: no explicit permissions")


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


def gap_no_generated_files_are_tracked() -> None:
    """Compiled caches were once committed by mistake."""
    import shutil
    import subprocess
    if not shutil.which("git") or not (ROOT / ".git").exists():
        return
    listed = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines()
    for path in listed:
        if "__pycache__" in path or path.endswith(".pyc") or path.startswith("kernel/target/"):
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


GAP_CHECKS = [check_claims_match_runs, gap_readme_counts, gap_claims_name_real_properties,
              gap_every_property_has_a_defect, gap_decisions_are_well_formed,
              gap_vocabulary_is_the_same_everywhere, gap_nothing_private_or_unportable,
              gap_workflows_are_safe, gap_path_check_matches_its_vectors,
              gap_repository_paths_are_portable, gap_canonical_vectors_are_consistent,
              gap_every_modelled_case_has_a_scenario, gap_kit_judge_is_strict,
              gap_own_policy_fits_the_schema, gap_no_generated_files_are_tracked,
              gap_provider_cases_match_the_provider, gap_every_check_is_listed,
              gap_kit_shown_claims_are_exercised, gap_kit_judge_hides_the_answers, gap_generated_kit_files_are_current,
              gap_driver_refuses_outside_the_queue, gap_one_reader_of_checker_output,
              gap_an_unfinished_job_proves_nothing, gap_tool_tree_digest_matches_its_vectors,
              gap_every_tool_compiles]


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
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    for line in problems:
        print("PROBLEM", line)
    ok = not problems and result.wasSuccessful()
    print("repository checks:", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
