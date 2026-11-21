"""In-memory controls for the native status pair and its retained evidence.

    python .github/site/test_replay_retained_status.py
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
from pathlib import Path
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

        prior_run = dict(run, id=replay.PRIOR_RUN, head_branch="dodona-eight-3-retained-status",
                         event="workflow_dispatch", head_sha=replay.PRIOR_COMMIT, path=".github/workflows/checks.yml")
        prior_artifact = dict(artifact, id=replay.PRIOR_ID, name="issue-3-retained-status-receipt",
                              size_in_bytes=106_203, digest=f"sha256:{replay.PRIOR_ZIP_SHA256}",
                              workflow_run=dict(artifact["workflow_run"], id=replay.PRIOR_RUN,
                                                head_sha=replay.PRIOR_COMMIT, head_branch=prior_run["head_branch"]))
        replay.check_source(prior_run, prior_artifact, prior=True)
        with self.assertRaisesRegex(ValueError, "prior receipt run"):
            replay.check_source(dict(prior_run, head_sha=replay.SOURCE_COMMIT), prior_artifact, prior=True)
        with self.assertRaisesRegex(ValueError, "prior receipt artifact"):
            replay.check_source(prior_run, dict(prior_artifact, expired=True), prior=True)

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
        with patch.object(replay, "PRIOR_ZIP_SHA256", replay.digest(raw)), patch.object(replay, "PRIOR_MEMBERS", members):
            with self.assertRaisesRegex(ValueError, "prior receipt status.json digest"):
                replay.retained_members(raw, prior=True)

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
        replay.check_report(answer, "pin")
        replay.compare_output("native pair", answer, deepcopy(answer))
        altered = deepcopy(answer)
        altered["report"]["intents"]["0001"]["grade"] = False
        with self.assertRaisesRegex(ValueError, "native pair differs in report"):
            replay.compare_output("native pair", altered, answer)
        altered = deepcopy(answer)
        altered["judged"]["extra"] = 1
        with self.assertRaisesRegex(ValueError, "native pair differs in judged"):
            replay.compare_output("native pair", altered, answer)
        with self.assertRaisesRegex(ValueError, "policy source"):
            replay.check_report(dict(answer, policy_source="worktree"), "pin")
        with self.assertRaisesRegex(ValueError, "outer project status"):
            replay.check_report(dict(answer, project_status="passed"), "pin")
        del answer["judged"]["intents"]["0006"]
        with self.assertRaisesRegex(ValueError, "exact six intents"):
            replay.check_report(answer, "pin")

    def test_only_runner_local_paths_are_normalized(self):
        current = replay.status_input({"required": ["0001"]}, "policy")
        previous = deepcopy(current)
        other = Path.cwd() / "previous-run"
        previous["root"] = str(other)
        for binding in previous["site"]["providers"].values():
            binding["command"] = [str(other / "python"), "-B", str(other / binding["code"][0])]
        normalized = replay.request_without_runner_paths(current)
        self.assertTrue(replay.same(normalized, replay.request_without_runner_paths(previous)))
        foreign_ledger = dict(previous, ledgers=["different.ledger"])
        self.assertFalse(replay.same(normalized, replay.request_without_runner_paths(foreign_ledger)))
        previous["site"]["providers"]["dodona.tla"]["command"][1] = "-I"
        with self.assertRaisesRegex(ValueError, "different code or arguments"):
            replay.request_without_runner_paths(previous)

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

    def test_prior_summary_binds_the_report_and_the_independent_result(self):
        request = replay.status_input({"required": ["0001"]}, "pin")
        entry = {"kind": "evidence", "body": {"key": "old"}}
        payload = replay.encode(dict(entry, previous=None))
        ledger = b"dodona1 %d %s %s\n" % (len(payload), replay.digest(payload).encode(), payload)
        answer = dict.fromkeys(replay.OUT_KEYS)
        answer.update(
            judged={"intents": dict.fromkeys(replay.INTENTS), "steps": [
                {"do": {"append": entry}}, {"do": {"set_gate": {"intent": "", "criterion": "", "to": "hard"}}},
            ]},
            report={"project": {"status": "unknown"}, "intents": dict.fromkeys(replay.INTENTS)},
            ledger={"entries": 1, "torn": False}, policy_source="pin", project_status="unknown", project_doubts=[],
        )
        members = {"request.json": replay.encode(request), "native-status.json": replay.encode(answer),
                   "js-final-report.json": replay.encode({"results": [answer["report"]]}),
                   "complete.txt": b"native status replay completed and scenario report agreed\n"}
        summary = {"head": replay.PRIOR_COMMIT, "status_source": replay.PRIOR_STATUS_SOURCE,
                   "proof_run": str(replay.PRIOR_RUN), "proof_attempt": "1", "scenario_agrees": True,
                   "source": {"run": replay.SOURCE_RUN, "head": replay.SOURCE_COMMIT, "artifact": replay.ARTIFACT_ID,
                              "zip_sha256": replay.ZIP_SHA256, "member_sha256": replay.MEMBER_DIGESTS},
                   "policy": {"commit": replay.POLICY_COMMIT, "sha256": replay.POLICY_SHA256, "source": "pin"},
                   "sha256": {"request": replay.digest(members["request.json"]),
                              "native_status": replay.digest(members["native-status.json"]),
                              "scenario_input": replay.digest(replay.encode(answer["judged"])),
                              "scenario_result": replay.digest(members["js-final-report.json"])}}
        members["summary.json"] = replay.encode(summary)
        self.assertEqual(replay.comparison_answer(members, request, ledger), answer)
        members["js-final-report.json"] = b'{"results":[{}]}'
        with self.assertRaisesRegex(ValueError, "does not bind js-final-report.json"):
            replay.comparison_answer(members, request, ledger)
        summary["sha256"]["scenario_result"] = replay.digest(members["js-final-report.json"])
        members["summary.json"] = replay.encode(summary)
        with self.assertRaisesRegex(ValueError, "independent final report differs"):
            replay.comparison_answer(members, request, ledger)


if __name__ == "__main__":
    unittest.main()
