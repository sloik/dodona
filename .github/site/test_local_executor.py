"""Tests of this site's local executor (local_executor.py): it really runs Node, on a sample test in a temporary
project, and is judged on what it reports.

    python3 .github/site/test_local_executor.py

A run of a tool this site does not run here must end unavailable; a run whose input is not the file it names must
not run; a run past its wall limit must end timed-out; and the tools must be reported as asked only when the
machine's Node meets the pin.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import os
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
import host  # noqa: E402

TEST = "const test = require('node:test');\ntest('passes', () => {});\ntest('slow', async () => { await new Promise(r => setTimeout(r, 5000)); });\n"


@unittest.skipUnless(shutil.which("node"), "Node is not installed")
class LocalExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.project = pathlib.Path(self.tmp.name) / "project"
        (self.project / "k").mkdir(parents=True)
        (self.project / "k" / "a.test.js").write_text(TEST, encoding="utf-8")
        self.site = json.loads((HERE / "local-executor.json").read_text(encoding="utf-8"))
        self.node = [{"name": pin["name"], "digest": "sha256:" + host.floor_digest(pin)} for pin in self.site["pins"]]
        self.identity = "sha256:" + hashlib.sha256(TEST.encode("utf-8")).hexdigest()

    def tearDown(self):
        self.tmp.cleanup()

    def run_of(self, pattern="^passes$", identity=None, tool="node", wall=60000):
        return {"program": {"tool": tool, "path": "bin/node"},
                "args": ["--test", "--test-reporter=tap", f"--test-name-pattern={pattern}", "k/a.test.js"],
                "inputs": [{"path": "k/a.test.js", "identity": identity or self.identity}], "outputs": [],
                "limits": {"wall_ms": wall}, "platform": host.PLATFORM, "cwd": ".", "tools": self.node}

    def answer(self, *runs, site=None):
        batch = {"runs": [{"number": 1, "run_key": f"sha256:{i:064x}", "run": r} for i, r in enumerate(runs)]}
        done = subprocess.run([sys.executable, str(HERE / "local_executor.py"), str(site or HERE / "local-executor.json")],
                              cwd=self.project, input=json.dumps(batch).encode("utf-8"), capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.count(b"\n"), 1)
        return [r["report"] for r in json.loads(done.stdout)["reports"]]

    def test_a_test_is_run_and_its_output_kept(self):
        report, = self.answer(self.run_of())
        self.assertEqual((report["end"], report["exit_status"]), ("exited", 0))
        printed = (self.project / report["captured_output"]["path"]).read_text(encoding="utf-8")
        self.assertIn("ok 1 - passes", printed)
        self.assertEqual(report["tools_ran"], self.node)  # this machine's Node meets the pin

    def test_a_digest_other_than_the_site_pin_is_not_reported_as_run(self):
        run = self.run_of()
        run["tools"] = [{"name": "node", "digest": "sha256:" + "0" * 64}]
        report, = self.answer(run)
        self.assertEqual((report["end"], report["tools_ran"]), ("cancelled", self.node))

    def test_a_tool_this_site_does_not_run_here_is_unavailable(self):
        report, = self.answer(self.run_of(tool="java"))
        self.assertEqual(report["end"], "unavailable")

    def test_an_input_that_is_not_the_file_named_is_not_run(self):
        report, = self.answer(self.run_of(identity="sha256:" + "0" * 64))
        self.assertEqual(report["end"], "cancelled")

    @unittest.skipUnless(os.name == "posix", "the fake old Node is a shell script")
    def test_a_node_below_the_floor_is_not_reported_as_the_one_asked_for(self):
        old = pathlib.Path(self.tmp.name) / "old-node"
        old.write_text("#!/bin/sh\necho v20.0.0\n", encoding="utf-8")
        old.chmod(0o755)
        site = pathlib.Path(self.tmp.name) / "site.json"
        site.write_text(json.dumps(dict(self.site, programs={"node": str(old)})), encoding="utf-8")
        report, = self.answer(self.run_of(), site=site)
        self.assertNotEqual(report["tools_ran"], self.node)

    def test_a_run_past_its_limit_ends_timed_out(self):
        report, = self.answer(self.run_of(pattern="^slow$", wall=1500))
        self.assertEqual(report["end"], "timed-out")


if __name__ == "__main__":
    unittest.main()
