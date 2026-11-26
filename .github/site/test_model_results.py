"""Exercise what a native model run must prove before its ledger is kept.

    python .github/site/test_model_results.py
"""

import copy
import hashlib
import json
import pathlib
import tempfile
import unittest

import model_results
from model_results import canonical, host


class ModelResults(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        files = self.root / "spec" / "example"
        files.mkdir(parents=True)
        self.clean = {"config": "design.cfg", "expect": "no-violation", "expect_exit": 0}
        plant = {"config": "plant.cfg", "expect": "violation", "expect_exit": 12, "of": "Safe"}
        (files / "expected.json").write_text(json.dumps({
            "model": "Example.tla", "arguments": ["-config", "<config>", "Example.tla"],
            "cases": [self.clean, plant],
        }), encoding="utf-8")
        self.inputs = []
        for name in ("Example.tla", "design.cfg", "plant.cfg"):
            file = files / name
            file.write_bytes(name.encode())
            self.inputs.append({"path": file.relative_to(self.root).as_posix(), "identity": self.identity(file.read_bytes())})
        self.tools = [{k: tool[k] for k in ("name", "digest")} for tool in host.lock_tools()[0]
                      if tool["name"] in ("java", "tla2tools")]
        self.status = {"report": {"obligations": {name: {"status": "passed"} for name in ("example/design", "example/plant")}},
                       "not_checkable": [], "ledger": {"entries": 2, "torn": False}}
        self.run = {**copy.deepcopy(self.status),
                    "counts": dict.fromkeys(("failed", "error", "unavailable", "unsupported", "refused", "not_checkable"), 0)
                    | {"obligations": 2, "checked": 1, "passed": 1, "reused": 1}}
        self.start = {"op": "start", "obligation": {"name": "example/design", "binding": "kernel-models"},
                      "inputs": self.inputs}
        self.next = {"program": {"tool": "java", "path": "bin/java"}, "cwd": "spec/example",
                     "args": ["-cp", "${tool:tla2tools}/tla2tools.jar", "tlc2.TLC", "-config", "design.cfg", "Example.tla"],
                     "inputs": self.inputs, "platform": host.PLATFORM, "tools": self.tools}
        self.report = {"end": "exited", "exit_status": 0, "platform": host.PLATFORM, "tools_ran": self.tools}
        self.capture(b"Model checking completed. No error has been found.\n3 distinct states found, 0 states left on queue.\n")
        self.events = [self.message("provider", "request", "2", self.start),
                       self.message("kernel", "result", "2", {"next": self.next}),
                       self.message("provider", "request", "3", {"op": "run.result", "check": "2", "run": 1, "report": self.report})]

    @staticmethod
    def message(to, kind, identifier, body):
        return {"to": to, "message": {"type": kind, "id": identifier, "capability": "obligation.check", "body": body}}

    @staticmethod
    def identity(data):
        return "sha256:" + hashlib.sha256(data).hexdigest()

    def capture(self, content):
        key = canonical.identity({k: self.start[k] for k in ("obligation", "inputs")})
        run_key = host.run_key(key, 1, self.next)
        self.report["handle"] = "runs/r1-" + run_key.removeprefix("sha256:")[:16]
        rel = "out/kernel-runs/" + self.report["handle"].split("/")[1] + ".txt"
        self.report["captured_output"] = {"path": rel, "identity": self.identity(content)}
        output = self.root / rel
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        return output

    def verify(self):
        return model_results.verify(self.root, self.run, self.status, self.events)

    def test_fresh_and_reused(self):
        report = self.verify()
        self.assertEqual(report["summary"], {"cases": 1, "matched": 1, "reused": 1, "all_matched": True})
        self.assertEqual(report["cases"][0]["name"], "example/design")
        self.events.clear()
        self.run["counts"].update(checked=0, passed=0, reused=2)
        self.assertEqual(self.verify()["summary"], {"cases": 0, "matched": 0, "reused": 2, "all_matched": True})

    def test_inventory_cannot_drop_a_case(self):
        for view in (self.run, self.status):
            del view["report"]["obligations"]["example/plant"]
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.verify()

    def test_status_must_agree_and_ledger_must_be_whole(self):
        self.status["report"]["obligations"]["example/design"]["status"] = "failed"
        with self.assertRaisesRegex(ValueError, "status"):
            self.verify()
        self.status = {k: copy.deepcopy(v) for k, v in self.run.items() if k != "counts"}
        self.run["ledger"]["torn"] = self.status["ledger"]["torn"] = True
        with self.assertRaisesRegex(ValueError, "ledger"):
            self.verify()

    def test_every_started_case_needs_a_terminal_report(self):
        self.events.pop()
        with self.assertRaisesRegex(ValueError, "transcript"):
            self.verify()

    def test_a_timeout_cannot_be_credited_even_with_success_text(self):
        self.report["end"] = "timed-out"
        with self.assertRaisesRegex(ValueError, "finished"):
            self.verify()

    def test_raw_bytes_and_case_outcome_are_checked_independently(self):
        output = self.root / self.report["captured_output"]["path"]
        output.write_bytes(output.read_bytes() + b"extra output\n")
        with self.assertRaisesRegex(ValueError, "digest"):
            self.verify()
        self.capture(b"another result")
        with self.assertRaisesRegex(ValueError, "expected model outcome"):
            self.verify()

    def test_wrong_arguments_are_refused_even_with_matching_output_identity(self):
        self.next["args"][4] = "plant.cfg"
        self.capture(b"Model checking completed. No error has been found.\n3 distinct states found, 0 states left on queue.\n")
        with self.assertRaisesRegex(ValueError, "description"):
            self.verify()

    def test_changed_model_file_invalidates_the_raw_result(self):
        (self.root / "spec/example/Example.tla").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "protected model inputs"):
            self.verify()


if __name__ == "__main__":
    unittest.main()
