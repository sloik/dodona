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
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
import batch_driver  # noqa: E402
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
for i, c in enumerate(m["cases"]):
    if not (src / c["cwd"] / "a.tla").exists():
        sys.exit(3)  # the run's input was not sent
    timed_out = mode.startswith("timed-out") and i == 0 and c.get("wall_ms") == 1000
    (out / c["name"]).parent.mkdir(parents=True, exist_ok=True)
    (out / (c["name"] + ".txt")).write_text(" ".join(c["argv"]) + "\\n")
    (out / (c["name"] + ".exit")).write_text("timed-out" if timed_out else "0")
if mode not in {"no-marker", "timed-out-no-marker"}:
    (out / "complete.json").write_text(json.dumps({"cases": [c["name"] for c in m["cases"]]}))
'''


class KernelExecutor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.where = pathlib.Path(self.tmp.name)
        self.project = self.where / "project"
        (self.project / "spec" / "m").mkdir(parents=True)
        model_bytes = b"---- a\n"
        (self.project / "spec" / "m" / "a.tla").write_bytes(model_bytes)
        _, pinned = host.lock_tools()
        (self.where / "queue.py").write_text(FAKE_QUEUE.replace("PINNED_JAR", repr(pinned["tla2tools"]["sha256"])), encoding="utf-8")
        tools, _ = host.lock_tools()
        self.asked = [{"name": t["name"], "digest": t["digest"]} for t in tools]
        identity = "sha256:" + hashlib.sha256(model_bytes).hexdigest()
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

    def test_measured_tools_do_not_echo_requested_digests(self):
        run = self.batch["runs"][0]["run"]
        run["tools"] = [dict(tool, digest="sha256:" + "f" * 64) for tool in self.asked]
        report = self.answer("ok")["1"]
        self.assertEqual(report["tools_ran"], self.asked)

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

    def test_case_timeout_preserves_the_other_run(self):
        run = self.batch["runs"][0]["run"]
        self.batch["runs"].append({"number": 1, "run_key": "sha256:" + "3" * 64, "run": run})
        got = self.answer("timed-out")
        self.assertEqual(got["1"]["end"], "timed-out")
        self.assertNotIn("exit_status", got["1"])
        self.assertEqual((got["3"]["end"], got["3"]["exit_status"]), ("exited", 0))
        incomplete = self.answer("timed-out-no-marker")
        self.assertEqual({report["end"] for report in incomplete.values()}, {"cancelled"})


class BatchDriver(unittest.TestCase):
    def test_timeout_does_not_publish_partial_artifacts_or_stop_the_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            where = pathlib.Path(directory)
            out = where / "out"
            manifest = where / "manifest.json"
            cases = []
            for name in ("first", "next"):
                work = where / name
                work.mkdir()
                cases.append({"name": f"cases/{name}", "cwd": str(work), "argv": [name], "keep": ["states.dump"]})
            cases[0]["wall_ms"] = 1250
            manifest.write_text(json.dumps({"out": str(out), "cases": cases}), encoding="utf-8")

            def run(argv, *, cwd, capture_output, timeout=None):
                self.assertTrue(capture_output)
                pathlib.Path(cwd, "states.dump").write_text(argv[0], encoding="utf-8")
                if argv == ["first"] and timeout is not None:
                    raise subprocess.TimeoutExpired(argv, timeout, output=b"success before timeout", stderr=b"\n")
                return subprocess.CompletedProcess(argv, 0, stdout=b"finished", stderr=b"")

            with mock.patch.object(batch_driver, "inside_the_executor", return_value=True), \
                    mock.patch.object(batch_driver.sys, "argv", ["batch_driver.py", str(manifest)]), \
                    mock.patch.object(batch_driver.subprocess, "run", side_effect=run) as spawned:
                self.assertEqual(batch_driver.main(), 0)
            self.assertEqual(spawned.call_args_list[0].kwargs.get("timeout"), 1.25)
            self.assertIsNone(spawned.call_args_list[1].kwargs.get("timeout"))
            self.assertEqual((out / "cases/first.exit").read_text(encoding="ascii"), "timed-out")
            self.assertEqual((out / "cases/first.txt").read_bytes(), b"success before timeout\n")
            self.assertFalse((out / "cases/first.states.dump").exists())
            self.assertEqual((out / "cases/next.exit").read_text(encoding="ascii"), "0")
            self.assertEqual((out / "cases/next.states.dump").read_text(encoding="utf-8"), "next")
            self.assertEqual(json.loads((out / "complete.json").read_text()), {"cases": ["cases/first", "cases/next"]})


if __name__ == "__main__":
    unittest.main()
