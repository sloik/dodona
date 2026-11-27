"""Tests of the Node test runner's provider (decision 0035).

    python3 providers/node-test/test_provider.py

The enumeration is tested on texts; the verdicts on what Node's runner really prints for a sample test file written
to a temporary folder, run by the command the provider describes. A verdict is never `passed` unless exactly the
named test ran and passed. A different or additional result invalidates the test evidence.
"""
from __future__ import annotations

import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import provider  # noqa: E402

SAMPLE = r"""const test = require('node:test');
const assert = require('node:assert');
test('passes', () => {});
test('passes too', () => {});
test('also passes', () => {});
test('fails', () => { assert.equal(1, 2); });
test('has (parens) and a.dot', () => {});
test('it\'s quoted', () => {});
test('outer', async (t) => { await t.test('inner', () => {}); });
test('skipped', { skip: true }, () => {});
"""


class Enumerate(unittest.TestCase):
    def test_literal_names_are_tests(self):
        names, rejected = provider.tests_in(SAMPLE)
        self.assertEqual(names, ["passes", "passes too", "also passes", "fails", "has (parens) and a.dot", "it's quoted", "outer", "skipped"])
        self.assertEqual(rejected, [])

    def test_what_cannot_be_named_is_rejected_never_guessed(self):
        text = "test(name, () => {});\ntest(`t`, () => {});\ntest('a#b', () => {});\ntest('a\\nb', () => {});\n" \
               "test('twice', () => {});\ntest('twice', () => {});\ntest('', () => {});\n"
        names, rejected = provider.tests_in(text)
        self.assertEqual(names, [])  # a name used twice is checked under neither copy
        self.assertEqual([r["code"] for r in rejected],
                         ["name-not-literal", "name-not-literal", "name-unreadable", "name-not-literal", "name-twice", "name-unreadable"])

    def test_nested_and_indented_calls_are_not_top_level_tests(self):
        names, _ = provider.tests_in("describe('d', () => {\n  test('inside', () => {});\n});\n")
        self.assertEqual(names, [])

    def test_each_obligation_reads_every_file_of_its_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "k").mkdir()
            (root / "k" / "test.js").write_text("test('a', () => {});\n", encoding="utf-8")
            (root / "k" / "lib.js").write_text("module.exports = 1;\n", encoding="utf-8")
            (root / "k" / "lib.test.js").write_text("test('b', () => {});\n", encoding="utf-8")
            here = pathlib.Path.cwd()
            try:
                import os
                os.chdir(root)
                got = provider.enumerate_obligations({"files": [
                    {"path": "k/test.js"}, {"path": "k/lib.js"}, {"path": "k/lib.test.js"},
                    {"path": "k/\ue000.js"}, {"path": "k/\U00010000.js"},
                ]})
            finally:
                os.chdir(here)
        self.assertEqual([o["name"] for o in got["obligations"]], ["k/lib.test.js::b", "k/test.js::a"])
        self.assertEqual(got["obligations"][1]["inputs"], ["k/lib.js", "k/lib.test.js", "k/test.js", "k/\U00010000.js", "k/\ue000.js"])


    def test_multiple_top_level_declarations_refuse_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "multiple.test.js").write_text("test('a', () => {});\ntest('b', () => {});\n", encoding="utf-8")
            (root / "uncertain.test.js").write_text("test('ordinary', () => {});\ntest(other, () => {});\n", encoding="utf-8")
            (root / "reserved.test.js").write_text("test('reserved.test.js', () => {});\n", encoding="utf-8")
            here = pathlib.Path.cwd()
            try:
                import os
                os.chdir(root)
                result = provider.enumerate_obligations({"files": [
                    {"path": "multiple.test.js"}, {"path": "uncertain.test.js"}, {"path": "reserved.test.js"}]})
            finally:
                os.chdir(here)
        self.assertEqual(result["obligations"], [])
        self.assertEqual(sorted(item["code"] for item in result["rejected"]), ["multiple-tests", "name-is-file", "name-not-literal"])


class Verdicts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)

    def verdict(self, name: str, test: str, exit_status=None):
        test_path = self.root / "sample.test.js"
        test_path.write_text("const test = require('node:test');\nconst assert = require('node:assert');\n" + test,
                             encoding="utf-8")
        obligation = {"name": "sample.test.js::" + name, "config": {"file": "sample.test.js", "test": name}}
        run = provider.describe_run({"obligation": obligation, "inputs": [], "platform": {}, "tools": []})["next"]
        done = subprocess.run(["node", *run["args"]], cwd=self.root, capture_output=True, timeout=30)
        printed = self.root / "printed.txt"
        printed.write_bytes(done.stdout + done.stderr)
        report = {"captured_output": {"path": str(printed)}, "exit_status": done.returncode if exit_status is None else exit_status}
        return provider.interpret(obligation, report)["final"]

    def test_invocation_names_only_the_input_file_after_the_option_terminator(self):
        obligation = {"config": {"file": "nested/-sample.test.js", "test": "one / two ($)"}}
        run = provider.describe_run({"obligation": obligation, "inputs": [], "platform": {}, "tools": []})["next"]
        self.assertEqual(run["args"], ["--test", "--test-reporter=tap", "--", "nested/-sample.test.js"])

    def test_a_passing_test_passes(self):
        self.assertEqual(self.verdict("has (parens). / $", "test('has (parens). / $', () => {});")["verdict"], "passed")
        self.assertEqual(self.verdict("it's quoted", 'test("it\'s quoted", () => {});')["verdict"], "passed")

    def test_a_failing_test_fails(self):
        self.assertEqual(self.verdict("fails", "test('fails', () => assert.equal(1, 2));")["verdict"], "failed")

    def test_subtests_belong_to_their_test(self):
        test = "test('outer', async (t) => { await t.test('inner', () => {}); });"
        self.assertEqual(self.verdict("outer", test)["verdict"], "passed")

    def test_a_success_under_a_different_name_is_an_error(self):
        self.assertEqual(self.verdict("wanted", "test('other', () => {});")["verdict"], "error")

    def test_an_additional_top_level_result_is_an_error(self):
        test = "test('wanted', () => {});\n[0].forEach(() => test('other', () => {}));"
        self.assertEqual(self.verdict("wanted", test)["verdict"], "error")

    def test_file_level_output_cannot_pass_an_unregistered_test_of_the_same_name(self):
        comment = "/*\ntest('sample.test.js', () => {});\n*/\n"
        self.assertEqual(self.verdict("sample.test.js", comment)["verdict"], "error")

    def test_a_boolean_is_not_the_recorded_exit_status(self):
        valid = "test('passes', () => {});"
        self.assertEqual(self.verdict("passes", valid, exit_status=False)["verdict"], "error")

    def test_a_skipped_test_is_an_error(self):
        self.assertEqual(self.verdict("skipped", "test('skipped', { skip: true }, () => {});")["verdict"], "error")

    def test_a_result_and_an_exit_status_that_disagree_are_an_error(self):
        self.assertEqual(self.verdict("passes", "test('passes', () => {});", exit_status=1)["verdict"], "error")
        self.assertEqual(self.verdict("fails", "test('fails', () => assert.equal(1, 2));", exit_status=0)["verdict"], "error")


if __name__ == "__main__":
    unittest.main()
