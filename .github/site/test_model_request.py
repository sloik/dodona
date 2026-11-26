"""Test the policy and request handoff without starting any model checker.

    python .github/site/test_model_request.py
"""

import json
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

import model_request


class ModelRequest(unittest.TestCase):
    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.root, stderr=subprocess.PIPE).decode().strip()

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.git("init", "--quiet")
        self.policy_file = self.root / "policy.toml"
        self.policy_file.write_text('policy = "0.2"\n[required]\nintents = ["0001"]\n', encoding="utf-8")
        self.git("add", "policy.toml")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "-c", "commit.gpgSign=false", "commit", "--quiet", "-m", "protected policy")
        self.commit = self.git("rev-parse", "HEAD")
        origin = mock.patch.object(model_request, "ROOT", self.root)
        origin.start()
        self.addCleanup(origin.stop)

    def test_artifact_is_verified_against_the_commit_and_not_the_working_copy(self):
        original = model_request.policy_at(self.commit)
        self.policy_file.write_text('policy = "0.2"\n[required]\nintents = []\n', encoding="utf-8")
        self.assertEqual(model_request.policy_at(self.commit), original)
        path = self.root / "policy.json"
        path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(model_request.policy_from_artifact(self.commit, path), original)
        for field, change in (("commit", "0" * 40), ("identity", "sha256:" + "0" * 64),
                              ("policy", original["policy"] | {"required": []}),
                              ("policy", original["policy"] | {"min_hard_gates": True})):
            path.write_text(json.dumps(original | {field: change}), encoding="utf-8")
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "policy artifact"):
                model_request.policy_from_artifact(self.commit, path)

    def test_missing_or_different_checkout_is_refused(self):
        for other in ("HEAD", "0" * 40):
            with self.subTest(other=other), self.assertRaises(ValueError):
                model_request.policy_at(other)

    def test_native_run_and_status_share_policy_tools_and_ledger(self):
        policy = model_request.policy_at(self.commit)
        with mock.patch.object(model_request, "runner_identity", return_value="sha256:" + "1" * 64), \
                mock.patch.object(model_request, "site_settings", return_value={"native_batch_wait_floor_ms": 3_660_000}):
            run = model_request.request(policy, run=True)
            status = model_request.request(policy, run=False)
        self.assertEqual({k: v for k, v in run.items() if k in status}, status)
        self.assertEqual(set(run) - set(status), {"executor", "ledger", "transcript", "batch_wait_floor_ms"})
        self.assertIn(run["ledger"], status["ledgers"])
        self.assertIn(self.commit, status["policy_source"])
        self.assertIn(policy["identity"], status["policy_source"])
        self.assertEqual(run["batch_wait_floor_ms"], 3_660_000)
        self.assertEqual(set(status["site"]["providers"]), {"dodona.tla", "dodona.intent.markdown"})

    def test_dump_plan_never_schedules_obligations_and_checks_the_kept_dump(self):
        current = {}
        for name in ("kernel", "intent"):
            model = self.root / "spec" / name
            model.mkdir(parents=True)
            (model / "dump.cfg").write_text("fixture\n", encoding="utf-8")
            current[name] = model_request.host.dump_key(model)
        kept = self.root / "kept" / "dumps"
        (kept / "kernel").mkdir(parents=True)
        states = kept / "kernel" / "dump.states.dump"
        states.write_bytes(b"state dump fixture")
        (kept / "dumps.json").write_text(json.dumps({"kernel": current["kernel"], "intent": "old"}), encoding="utf-8")
        plan = model_request.dump_plan(kept)
        self.assertEqual(plan, {"run": [], "reuse": [], "dumps_run": ["intent"],
                                "dumps_reuse": ["kernel"], "dump_keys": current})
        states.unlink()
        self.assertEqual(model_request.dump_plan(kept)["dumps_run"], ["intent", "kernel"])


if __name__ == "__main__":
    unittest.main()
