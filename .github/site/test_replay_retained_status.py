"""In-memory controls for the issue 3 replay's evidence gates.

    python .github/site/test_replay_retained_status.py
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import unittest
from unittest.mock import patch
import zipfile

import replay_retained_status as replay


class RetainedProofTests(unittest.TestCase):
    def test_checkout_allows_only_the_proof_files(self):
        for changed in (b".github/site/replay_retained_status.py\0", b"kernel/src/main.rs\0"):
            with self.subTest(changed=changed), patch.object(
                replay, "command", side_effect=[b"head\n", changed, b"", b"tree\n"],
            ):
                if changed.startswith(b"kernel"):
                    with self.assertRaisesRegex(ValueError, "pinned status source"):
                        replay.checkout("head")
                else:
                    self.assertEqual(replay.checkout("head"), "tree")
        with patch.object(replay, "command", return_value=b"other head\n"):
            with self.assertRaisesRegex(ValueError, "dispatched commit"):
                replay.checkout("head")

    def test_source_must_be_completed_main_and_match_the_archive(self):
        repository = {"id": 17, "full_name": replay.REPOSITORY}
        run = {"id": replay.SOURCE_RUN, "status": "completed", "conclusion": "success", "head_branch": "main",
               "event": "push", "head_sha": replay.SOURCE_COMMIT, "path": ".github/workflows/models.yml",
               "head_repository": repository, "repository": repository}
        artifact = {"id": replay.ARTIFACT_ID, "name": "dodona-on-dodona", "expired": False, "size_in_bytes": 191_839,
                    "digest": f"sha256:{replay.ZIP_SHA256}", "workflow_run": {"id": replay.SOURCE_RUN,
                    "head_sha": replay.SOURCE_COMMIT, "head_branch": "main", "repository_id": 17,
                    "head_repository_id": 17}}
        replay.check_source(run, artifact)
        for bad_run, bad_artifact in ((dict(run, conclusion="cancelled"), artifact),
                                      (dict(run, head_branch="side"), artifact),
                                      (run, dict(artifact, digest="unrelated"))):
            with self.assertRaises(ValueError):
                replay.check_source(bad_run, bad_artifact)

    def test_archive_and_member_digests_are_independent_controls(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("dodona.ledger", b"ledger")
            archive.writestr("status.json", b"status")
        raw = buffer.getvalue()
        members = {"dodona.ledger": replay.digest(b"ledger"), "status.json": replay.digest(b"status")}
        with patch.object(replay, "ZIP_SHA256", replay.digest(raw)), patch.object(replay, "MEMBER_DIGESTS", members):
            self.assertEqual(replay.retained_members(raw), {"dodona.ledger": b"ledger", "status.json": b"status"})
            with self.assertRaisesRegex(ValueError, "archive digest"):
                replay.retained_members(raw + b"extra")
            members["status.json"] = replay.digest(b"other")
            with self.assertRaisesRegex(ValueError, "status.json digest"):
                replay.retained_members(raw)

    def test_changed_policy_is_refused(self):
        with patch.object(replay, "POLICY_SHA256", replay.digest(b"policy")):
            self.assertEqual(replay.policy_blob(b"policy"), b"policy")
            with self.assertRaisesRegex(ValueError, "policy digest"):
                replay.policy_blob(b"different policy")

    def test_report_checks_exact_ids_and_full_cross_kernel_agreement(self):
        report = {"project": {"status": "passed"}, "intents": {i: {"grade": 0} for i in replay.INTENTS}}
        answer = dict.fromkeys(replay.OUT_KEYS)
        answer.update(judged={"intents": dict.fromkeys(replay.INTENTS)}, report=report, policy_source="pin",
                      project_doubts=["a limitation"], project_status="unknown")
        replay.check_report(answer, "pin", {"results": [None, deepcopy(report)]})
        altered = deepcopy(report)
        altered["intents"]["0001"]["grade"] = False
        with self.assertRaisesRegex(ValueError, "differs from the second kernel"):
            replay.check_report(answer, "pin", {"results": [altered]})
        with self.assertRaisesRegex(ValueError, "policy source"):
            replay.check_report(dict(answer, policy_source="worktree"), "pin", {"results": [report]})
        with self.assertRaisesRegex(ValueError, "outer project status"):
            replay.check_report(dict(answer, project_status="passed"), "pin", {"results": [report]})
        del answer["judged"]["intents"]["0006"]
        with self.assertRaisesRegex(ValueError, "exact six intents"):
            replay.check_report(answer, "pin", {"results": [report]})

    def test_scenario_keeps_retained_evidence_without_rekeying(self):
        entry = {"kind": "evidence", "body": {"key": "old"}}
        payload = replay.encode(dict(entry, previous=None))
        raw = b"dodona1 %d %s %s\n" % (len(payload), hashlib.sha256(payload).hexdigest().encode(), payload)
        answer = {"ledger": {"entries": 1, "torn": False}, "judged": {"steps": [
            {"do": {"append": deepcopy(entry)}}, {"do": {"set_gate": {"intent": "", "criterion": "", "to": "hard"}}},
        ]}}
        replay.check_ledger(answer, raw)
        answer["judged"]["steps"][0]["do"]["append"]["body"]["key"] = "current"
        with self.assertRaisesRegex(ValueError, "exact retained entries"):
            replay.check_ledger(answer, raw)


if __name__ == "__main__":
    unittest.main()
