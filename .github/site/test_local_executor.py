"""Exercise this site's local executor with a real Node runtime and private project.

    python .github/site/test_local_executor.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from local_executor import child_environment

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
import host  # noqa: E402

IMPORT = "const test = require('node:test');\n"
TESTS = {
    "a": IMPORT + "test('passes', () => {});\n",
    "slow": IMPORT + "test('slow', async () => { await new Promise(r => setTimeout(r, 5000)); });\n",
}


class LocalExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = pathlib.Path(self.tmp.name) / "project"
        (self.project / "k").mkdir(parents=True)
        for name, test in TESTS.items():
            (self.project / f"k/{name}.test.js").write_bytes(test.encode("utf-8"))
        self.site = json.loads((HERE / "local-executor.json").read_text(encoding="utf-8"))
        self.node = [{"name": pin["name"], "digest": "sha256:" + host.floor_digest(pin)} for pin in self.site["pins"]]
        run = subprocess.check_output(["node", "-p", "process.platform + '/' + process.arch"], text=True, timeout=10)
        os_name, arch = run.strip().split("/")
        self.platform = {"os": {"darwin": "macos", "linux": "linux", "win32": "windows"}[os_name],
                         "arch": {"arm64": "aarch64", "x64": "x86_64"}[arch]}

    def run_of(self, test="a", identity=None, tool="node", wall=60000):
        path = f"k/{test}.test.js"
        if identity is None:
            identity = "sha256:" + hashlib.sha256(TESTS[test].encode("utf-8")).hexdigest()
        return {"program": {"tool": tool, "path": "bin/node"},
                "args": ["--test", "--test-reporter=tap", "--", path],
                "inputs": [{"path": path, "identity": identity}], "outputs": [],
                "limits": {"wall_ms": wall}, "platform": self.platform, "cwd": ".", "tools": self.node}

    def answer(self, *runs, site=None):
        batch = {"runs": [{"number": i + 1, "run_key": f"sha256:{i:064x}", "run": r} for i, r in enumerate(runs)]}
        done = subprocess.run([sys.executable, str(HERE / "local_executor.py"), str(site or HERE / "local-executor.json")],
                              cwd=self.project, input=json.dumps(batch).encode("utf-8"), capture_output=True, timeout=25)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stdout.count(b"\n"), 1)
        return [r["report"] for r in json.loads(done.stdout)["reports"]]

    def captured(self, report):
        return (self.project / report["captured_output"]["path"]).read_text(encoding="utf-8")

    def test_a_test_is_run_and_its_output_kept(self):
        report, = self.answer(self.run_of())
        self.assertEqual((report["end"], report.get("exit_status")), ("exited", 0), self.captured(report))
        self.assertIn("ok 1 - passes", self.captured(report))
        self.assertEqual(report["tools_ran"], self.node)
        self.assertEqual(report["platform"], self.platform)

    def test_a_different_platform_does_not_run(self):
        run = self.run_of()
        different_os = "macos" if self.platform["os"] != "macos" else "linux"
        different_arch = "aarch64" if self.platform["arch"] != "aarch64" else "x86_64"
        mismatches = [dict(self.platform, os=different_os), dict(self.platform, arch=different_arch),
                      dict(self.platform, libc="musl")]
        reports = self.answer(*(dict(run, platform=platform) for platform in mismatches))
        for report in reports:
            self.assertEqual(report["end"], "unavailable", report)
            self.assertEqual(self.captured(report), "")

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

    def test_a_node_below_the_floor_is_not_reported_as_the_one_asked_for(self):
        pin, = self.site["pins"]
        very_high_floor = dict(pin, floor="999.0.0")
        site = pathlib.Path(self.tmp.name) / "site.json"
        site.write_text(json.dumps(dict(self.site, pins=[very_high_floor])), encoding="utf-8")
        run = self.run_of()
        run["tools"] = [{"name": pin["name"], "digest": "sha256:" + host.floor_digest(very_high_floor)}]
        report, = self.answer(run, site=site)
        self.assertEqual(report["end"], "cancelled")
        self.assertNotEqual(report["tools_ran"], run["tools"])
        self.assertEqual(self.captured(report), "")

    def test_a_run_past_its_limit_ends_timed_out(self):
        report, = self.answer(self.run_of(test="slow", wall=1500))
        self.assertEqual(report["end"], "timed-out", self.captured(report))


class ChildEnvironment(unittest.TestCase):
    def test_windows_system_root_survives_the_allowlist(self):
        allowed = {"PATH": "fixture-path", "SYSTEMROOT": "fixture-root"}
        with patch.dict("os.environ", dict(allowed, NODE_OPTIONS="fixture-extra"), clear=True):
            self.assertEqual(child_environment(), allowed)


if __name__ == "__main__":
    unittest.main()
