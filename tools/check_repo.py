"""Checks of this repository that need no model checker and run on any platform.

Stage-0 helper (decision 0023): disposable, to be replaced by dodona itself.
Exit status is 0 only if every check passed.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_models  # noqa: E402

problems: list[str] = []


def check_json_and_toml() -> None:
    for path in sorted(ROOT.glob("**/*.json")):
        if ".git" in path.parts:
            continue
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
    for path in sorted(ROOT.glob("**/*.md")):
        if ".git" in path.parts:
            continue
        for target, _ in link.findall(path.read_text(encoding="utf-8")):
            if re.match(r"[a-z]+://", target):
                continue
            if not (path.parent / target).exists():
                problems.append(f"{path.relative_to(ROOT).as_posix()}: broken link to {target}")


def check_line_endings() -> None:
    for path in sorted(ROOT.glob("**/*")):
        if ".git" in path.parts or not path.is_file() or "conformance" in path.parts:
            continue
        if path.suffix in {".md", ".json", ".toml", ".tla", ".cfg", ".py", ".yml"}:
            data = path.read_bytes()
            if b"\r\n" in data:
                problems.append(f"{path.relative_to(ROOT).as_posix()}: has CRLF line endings")
            if data.startswith(b"\xef\xbb\xbf"):
                problems.append(f"{path.relative_to(ROOT).as_posix()}: starts with a byte-order mark")


def check_model_cases() -> None:
    for expected in sorted(ROOT.glob("spec/*/expected.json")):
        spec = json.loads(expected.read_text(encoding="utf-8"))
        listed = {c["config"] for c in spec["cases"]}
        present = {p.name for p in expected.parent.glob("*.cfg")}
        for name in sorted(listed - present):
            problems.append(f"{expected.parent.name}: {name} is listed but missing")
        for name in sorted(present - listed):
            problems.append(f"{expected.parent.name}: {name} exists but has no expected outcome")
        for case in spec["cases"]:
            if case["expect"] == "violation" and "of" not in case:
                problems.append(f"{expected.parent.name}: {case['config']} expects a violation of nothing")
            root = case.get("model", spec["model"])
            if not (expected.parent / root).exists():
                problems.append(f"{expected.parent.name}: root module {root} is missing")


def check_indexes() -> None:
    for folder in ("decisions", "intents"):
        index = (ROOT / folder / "README.md").read_text(encoding="utf-8")
        for path in sorted((ROOT / folder).glob("[0-9]*.md")):
            if f"({path.name})" not in index:
                problems.append(f"{folder}/README.md does not list {path.name}")


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

    def test_other_violation_is_not_a_match(self):
        self.assertFalse(check_models.judge(self.viol, 12, "Error: Invariant TypeOK is violated.\n")["match"])

    def test_crash_is_not_the_expected_violation(self):
        self.assertFalse(check_models.judge(self.viol, 255, "java.io.IOException: File too large\n")["match"])

    def test_violation_where_none_expected(self):
        self.assertFalse(check_models.judge(self.hold, 12, "Error: Invariant Sound is violated.\n")["match"])

    def test_expected_violation_but_search_passed(self):
        self.assertFalse(check_models.judge(self.viol, 0, self.done)["match"])


def main() -> int:
    for check in (check_json_and_toml, check_links, check_line_endings, check_model_cases, check_indexes):
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
