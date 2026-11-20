"""Tests of this site's batch executor for a kernel's run (kernel_executor.py), against a fake queue that runs nothing.

    python3 .github/site/test_kernel_executor.py

Each test sends one batch of two runs, the second naming an input by an identity the file does not have, and reads
what the executor answers: a run whose tools the job did not find as pinned must never come back reported as the
tools asked for, a job that did not end well must never come back `exited`, and a queue that cannot be reached must
make the executor fail rather than answer.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
import host  # noqa: E402

FAKE_QUEUE = '''
import json, pathlib, sys
src, dest, mode = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), sys.argv[3]
if mode == "down":
    sys.exit(2)
m = json.loads((src / "manifest.json").read_text())
out = dest / "out"
out.mkdir(parents=True)
pins = {"/site/java": "a" * 64, "/site/tla2tools.jar": PINNED_JAR}
if mode == "other-jar":
    pins["/site/tla2tools.jar"] = "b" * 64
(out / "measured.json").write_text(json.dumps({p: pins.get(p) for p in m["measure"]}))
(out / "versions.json").write_text(json.dumps({p: ("21.0.9" if mode == "old-java" else "21.0.15") for p in m["versions"]}))
for c in m["cases"]:
    if not (src / c["cwd"] / "a.tla").exists():
        sys.exit(3)  # the run's input was not sent
    (out / c["name"]).parent.mkdir(parents=True, exist_ok=True)
    (out / (c["name"] + ".txt")).write_text(" ".join(c["argv"]) + "\\n")
    (out / (c["name"] + ".exit")).write_text("0")
if mode != "no-marker":
    (out / "complete.json").write_text(json.dumps({"cases": [c["name"] for c in m["cases"]]}))
'''


class KernelExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.where = pathlib.Path(self.tmp.name)
        self.project = self.where / "project"
        (self.project / "spec" / "m").mkdir(parents=True)
        (self.project / "spec" / "m" / "a.tla").write_text("---- a\n", encoding="utf-8")
        _, pinned = host.lock_tools()
        (self.where / "queue.py").write_text(FAKE_QUEUE.replace("PINNED_JAR", repr(pinned["tla2tools"]["sha256"])), encoding="utf-8")
        tools, _ = host.lock_tools()
        self.asked = [{"name": t["name"], "digest": t["digest"]} for t in tools]
        identity = "sha256:" + hashlib.sha256(b"---- a\n").hexdigest()
        run = {"program": {"tool": "java", "path": "bin/java"}, "args": ["-cp", "${tool:tla2tools}/tla2tools.jar", "tlc2.TLC", "a.tla"],
               "inputs": [{"path": "spec/m/a.tla", "identity": identity}], "outputs": [], "limits": {"wall_ms": 1000},
               "platform": host.PLATFORM, "cwd": "spec/m", "tools": self.asked}
        changed = dict(run, inputs=[{"path": "spec/m/a.tla", "identity": "sha256:" + "0" * 64}])
        self.batch = {"runs": [{"number": 1, "run_key": "sha256:" + "1" * 64, "run": run},
                               {"number": 1, "run_key": "sha256:" + "2" * 64, "run": changed}]}

    def tearDown(self):
        self.tmp.cleanup()

    def answer(self, mode: str):
        site = self.where / "site.json"
        site.write_text(json.dumps({"batch_command": [sys.executable, str(self.where / "queue.py"), "{source}", "{dest}", mode],
                                    "executor_name": "test",
                                    "tool_files": {"java/bin/java": "/site/java", "tla2tools/tla2tools.jar": "/site/tla2tools.jar"}}), encoding="utf-8")
        done = subprocess.run([sys.executable, str(HERE / "kernel_executor.py"), str(site)], cwd=self.project,
                              input=json.dumps(self.batch).encode("utf-8"), capture_output=True)
        if done.returncode != 0:
            return None
        self.assertEqual(done.stdout.count(b"\n"), 1, "one line, and nothing else on standard output")
        return {r["run_key"][7:8]: r["report"] for r in json.loads(done.stdout)["reports"]}

    def test_a_good_job(self):
        got = self.answer("ok")
        self.assertEqual((got["1"]["end"], got["1"]["exit_status"], got["1"]["tools_ran"]), ("exited", 0, self.asked))
        printed = (self.project / got["1"]["captured_output"]["path"]).read_text(encoding="utf-8")
        self.assertIn("/site/tla2tools.jar", printed)  # the tool file mapped to this site's file
        self.assertEqual(got["2"]["end"], "cancelled")  # an input that is not the file named is never sent

    def test_a_queue_that_cannot_be_reached(self):
        self.assertIsNone(self.answer("down"))

    def test_another_jar(self):
        got = self.answer("other-jar")
        self.assertNotEqual(got["1"]["tools_ran"], self.asked)

    def test_java_below_the_floor(self):
        got = self.answer("old-java")
        self.assertNotEqual(got["1"]["tools_ran"], self.asked)

    def test_a_job_without_its_end_marker(self):
        got = self.answer("no-marker")
        self.assertEqual({r["end"] for r in got.values()}, {"cancelled"})


if __name__ == "__main__":
    unittest.main()
